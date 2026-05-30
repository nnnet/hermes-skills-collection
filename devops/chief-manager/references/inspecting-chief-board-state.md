# Inspecting Chief Board State (active + archived)

Recipes for a monitoring/observer agent (e.g. cron job) to check on a chief board it did not create. Especially relevant when polling a chief that may have been terminated, archived, or had its profiles disabled out-of-band between cron ticks.

## There is no `hermes chief` CLI subcommand — and no `hermes kanban chief` either

Neither `hermes chief status <id>` NOR `hermes kanban chief status <id>` exist.

`hermes kanban chief` fails with `invalid choice: 'chief'` because the valid kanban actions are:
`init, boards, create, list, ls, show, assign, reclaim, reassign, diagnostics, diag, link, unlink, claim, comment, complete, edit, block, unblock, archive, tail, dispatch, daemon, watch, stats, notify-subscribe, notify-list, notify-unsubscribe, log, runs, heartbeat, assignees, context, specify, decompose, gc`

The MCP tool `chief_status` exists in-process, but from a shell-only context (cron without that toolset) you must reach the data through `hermes kanban` or by reading the board directly off disk.

## Detecting chief "alive" from the board DB

A chief board contains exactly two kinds of tasks:
1. **The chief's own decomposition task** — `assignee = 'chief-manager'`, this is the initial goal task. When it reaches `status = 'done'`, the chief finished its Phase 6 dispatch and exited. This is NORMAL — `alive=false` does not mean the project is dead.
2. **The worker task(s)** — all other tasks in the board, dispatched by the chief in Phase 6.

```python
python3 - <<'PY'
import sqlite3
db = '/opt/data/kanban/boards/<slug>/kanban.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT id, status, assignee, title FROM tasks ORDER BY created_at")
tasks = cur.fetchall()
chief_task = next((t for t in tasks if t['assignee'] == 'chief-manager'), None)
worker_tasks = [t for t in tasks if t['assignee'] != 'chief-manager']
print("Chief alive:", chief_task and chief_task['status'] not in ('done', 'archived'))
print("Workers:", [(t['status'], t['assignee'], t['title'][:50]) for t in worker_tasks])
PY
```

## `--board` is a global flag — goes BEFORE the subcommand

Correct:

```bash
/opt/hermes/.venv/bin/hermes kanban --board <slug> list
/opt/hermes/.venv/bin/hermes kanban --board <slug> show t_xxxx
```

Wrong (silently fails with `unrecognized arguments`):

```bash
hermes kanban list --board <slug>     # WRONG — --board after subcommand
```

## Detecting an archived chief board

If `hermes kanban --board <slug> list` returns:

```
kanban: board '<slug>' does not exist. Create it with `hermes kanban boards create <slug>`.
```

…the board may simply not exist OR it may have been archived. Archived chiefs are moved to:

```
/opt/data/kanban/boards/_archived/<slug>-<unix_ts>/
├── board.json          # chief metadata (operator_chat_id, kind, lifetime, spawned_at)
├── kanban.db           # full task history at moment of archival
├── kanban.db-shm
├── kanban.db-wal
├── logs/
└── workspaces/
```

`<unix_ts>` is the archival time. Decode with `date -d @<ts>`.

When a chief is force-terminated, its profiles are typically renamed too:

```
/opt/data/profiles/<role>.broken.<unix_ts>
```

The `.broken.<ts>` suffix means the profile dir was sidelined and the worker can no longer be spawned. The numeric `<ts>` here is usually within ~30 s of the board archival timestamp — same termination event.

## Querying an archived kanban.db (no `sqlite3` CLI)

`sqlite3` CLI binary is NOT installed on the host. Use Python's stdlib instead:

```python
python3 - <<'PY'
import sqlite3, json
db = '/opt/data/kanban/boards/_archived/<slug>-<ts>/kanban.db'
conn = sqlite3.connect(db)
cur = conn.cursor()

# Final status of every task in the archived chief
cur.execute("""
    SELECT id, status, assignee, substr(title,1,80), substr(last_failure_error,1,120)
    FROM tasks ORDER BY created_at;
""")
for r in cur.fetchall():
    print(r)

# Structured result blobs (researchers often dump JSON here)
cur.execute("SELECT id, result FROM tasks WHERE result IS NOT NULL;")
for tid, raw in cur.fetchall():
    try:
        print(tid, json.dumps(json.loads(raw), indent=2, ensure_ascii=False))
    except Exception:
        print(tid, raw[:200])
PY
```

### `tasks` schema gotcha

The column is `title`, NOT `summary`. Writing `SELECT summary FROM tasks` raises `OperationalError: no such column: summary`. Other notable columns: `body`, `assignee`, `status`, `result` (free-form, often JSON), `last_failure_error`, `worker_pid`, `consecutive_failures`, `last_heartbeat_at`.

## Interpreting common terminal states

| Signal | Meaning |
|---|---|
| `status='blocked'` + `last_failure_error='pid <N> not alive'` | Worker process died (OOM, crash, signal). Task is parked. |
| `status='blocked'` + reason starts with `review-required:` | Worker handed off to Aegis attestation; not a real failure. |
| `status='completed'` (yes — not `done`) | Worker called `kanban_complete`. Used interchangeably with `done` in older boards. |
| `status='done'` | Normal terminal state via dispatcher. |
| Board archived AND profiles renamed `.broken.*` simultaneously | External termination event (operator ran `chief_terminate` or equivalent). Not a transient failure. |

## Named board exists but has zero tasks — check sibling boards

A chief spawn can create multiple boards with similar name prefixes. The board you were given (e.g. `chief-b2b-growth-agent-55a290`) may be an empty artifact from a parallel spawn, while actual execution runs in a differently-named board (e.g. `chief-b2b-autonomous-agent-126338`).

**Detection (host context):**
```python
import sqlite3, os

base = "/home/hermes/.hermes/kanban/boards"
for board in os.listdir(base):
    if board == "_archived":
        continue
    db = os.path.join(base, board, "kanban.db")
    if not os.path.isfile(db):
        continue
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    if count > 0:
        print(f"{board}: {count} tasks")
```

**Also verify an active worker exists:**
```bash
ps aux | grep 'chief' | grep -v grep
# Expected output includes the task ID and board context
```

**Reporting rule:** if the named board is empty but a sibling board has active tasks, report on the sibling board. Don't say "chief has no work" based on the named board alone.

## Monitoring-cron decision logic

When a cron's job is to poll a chief and report:

1. Try `hermes kanban --board <slug> list` first.
2. If "board does not exist", look in `/opt/data/kanban/boards/_archived/` for `<slug>-<ts>` directories — most recent timestamp wins.
3. If found archived → the chief is **gone**. Read final state from the archived `kanban.db`, report final task statuses, and recommend the cron itself be removed. Do NOT try to resurrect it — that's an operator decision.
4. If profiles also moved to `.broken.*` with timestamp near the board's archival ts → external termination, not a salvageable crash.

This pattern (board archived + profiles broken) is the difference between "system is currently sick, please retry" (transient, recover) and "system is gone, stop polling" (final, recommend cron removal).

## Cron-job delivery model — do NOT call `hermes send` yourself

When running as a scheduled cron job, the system AUTO-DELIVERS your final response to the configured destination. Do not invoke `hermes send telegram --chat <id>` from inside the cron — it duplicates the message and can be blocked by the Tirith security scanner if your text contains emoji variation selectors (`tirith:variation_selector` MEDIUM, asks for approval that never comes in a cron context).

Right pattern: produce the report as your final assistant text. The cron framework picks it up and sends it.

Wrong pattern:

```bash
hermes send telegram --chat 507735107 --text "..."
```

## Why this matters for chief-manager

A live Chief's Phase 7 monitoring crons assume the board still exists and the worker profiles are still healthy. They don't normally consider "the operator killed the chief between ticks." Without this reference, the monitoring agent gets stuck on `board does not exist` and either retries forever or reports a confusing error. The right behavior is: detect the archival, summarize the final state from the archived DB, and recommend cron removal.
