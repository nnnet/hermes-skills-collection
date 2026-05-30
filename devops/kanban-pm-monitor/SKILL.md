---
name: kanban-pm-monitor
description: Autonomous PM cron job that monitors a Kanban board, unblocks review-required tasks, escalates real blockers, and sends milestone notifications to the operator. Load when acting as an automated PM poller.
metadata:
  type: skill
---

## Trigger

You are a scheduled cron job acting as autonomous PM for a project board. No user is present. You must check board state, fix what you can, and report only when action is needed.

## Core loop (do all steps every run)

### Step 1 — List all tasks

Use the **native MCP tool** `kanban_list` with the board slug:

```
kanban_list(board="<board-slug>")
```

**CRITICAL PITFALL: Do NOT use the `hermes` CLI or `python cli.py kanban list`.**
- `hermes` is not in PATH in cron contexts → instant failure
- `python cli.py kanban list` spawns an agent subprocess → 60s timeout
- The native `mcp__oc__kanban_list` tool is always available and returns instantly

### Step 2 — Act on each non-done task

| Condition | Action |
|-----------|--------|
| `status=blocked` AND reason contains `review-required` | Call `kanban_unblock(task_id=...)` immediately — no approval needed |
| `status=blocked` AND `last_failure_error` matches `pid \d+ not alive` | Dispatcher detected dead worker PID. No SOUL fix needed — just reclaim + unblock: `hermes kanban reclaim <id> && kanban_unblock(task_id=<id>)`. This is the most common "worker was OOM-killed or evicted" pattern. |
| `status=blocked` AND reason does NOT contain `review-required` | Diagnose; fix infra issues yourself; create fix task assigned to `research-agent` for code issues |
| `consecutive_failures >= 3` AND assignee != `research-agent` | Create new task with same body + "previous assignee failed 3 times", assign to `research-agent` |
| `status=running` AND heartbeat > 90 min ago | Add comment asking for status; if still stale next run → unblock and re-queue |

### Step 3 — Phase completion check

```
Phase 1 done:  title contains 'Phase 1'  AND status='done'
Phase 2a done: title contains 'Phase 2a' AND status='done'
Phase 2b done: title contains 'Phase 2b' AND status='done'
Phase 3 done:  title contains 'Phase 3'  AND status='done'
Phase 4 done:  title contains 'Phase 4' or 'Deploy' AND status='done'
```

**CRITICAL PITFALL: `status=done` does NOT mean the work succeeded.**
Always check the task's run summary for caveats before reporting a milestone:
```python
# Use kanban_show(task_id=...) OR query task_runs directly
# Look for: NotImplementedError, blocker_note, partial completion, placeholder code
```
A task can be marked done by a worker that scaffolded files but left `raise NotImplementedError` stubs. Report the caveat to the operator alongside the milestone.

### Step 4 — Send operator messages only when needed

Send a message for:
- a) Blocker you cannot fix automatically (needs operator input or external resource)
- b) Phase 2a just completed → "Execution engine ready. Phase 3 (QA) starting."
- c) Phase 3 just completed → "QA passed. Ready for live deploy. Need Polymarket API key by June 3."
- d) Phase 4 just completed → "LIVE: system is trading. First P&L report in 24 hours." (BUT check run summary for blockers first)
- e) Task failed 3+ times and unfixable → escalate with diagnosis
- f) Past May 31 and Phase 2a not done → "ALERT: missed deadline. New estimate: [date]."
- g) Past June 3 and Phase 3 not done → "ALERT: missed deadline. New estimate: [date]."

**"Just completed" detection:** compare task `completed_at` timestamp against the timestamp of the last PM comment left on the board. If `completed_at > last_pm_comment_time` → new milestone.

**Silence = good news.** If all tasks are progressing normally, respond `[SILENT]`.

## Kanban DB schema reference (if direct sqlite access is ever needed)

```sql
-- Tasks table key columns
tasks: id, title, status, assignee, consecutive_failures,  -- NOT "attempt_count"
       last_failure_error, last_heartbeat_at, completed_at,
       result, created_at, started_at
       -- NOTE: no "blocked_reason" column, no "updated_at" column

-- Task runs key columns
task_runs: id, task_id, profile, status, outcome, summary,
           metadata, error, started_at, ended_at  -- NOT "completed_at"

-- Task comments key columns
task_comments: id, task_id, author, body, created_at

-- Task events key columns (USE THIS to find WHY a task is blocked)
task_events: id, task_id, run_id, kind, payload, created_at
-- kind values: created, claimed, spawned, crashed, gave_up, completed, blocked, unblocked
-- gave_up payload: {"failures": N, "effective_limit": N, "error": "...", "trigger_outcome": "crashed"}
-- crashed payload: {"pid": N, "exit_kind": "nonzero_exit", "exit_code": 1}
-- blocked payload: {"reason": "review-required: ..."} -- look here for review-required text
```

Python path for direct access (last resort only, prefer native tools):
```python
import sqlite3
# NOTE: actual host path is ~/.hermes/kanban/boards/, NOT /opt/data/kanban/boards/
conn = sqlite3.connect('/home/hermes/.hermes/kanban/boards/<board-slug>/kanban.db')
conn.row_factory = sqlite3.Row
# Example: get last 3 comments on a task
rows = conn.execute(
    "SELECT * FROM task_comments WHERE task_id=? ORDER BY created_at DESC LIMIT 3",
    ('t_xxxxxxxx',)
).fetchall()
# Search all comments for a URL
rows = conn.execute(
    "SELECT task_id, body FROM task_comments WHERE body LIKE '%docs.google.com%'"
).fetchall()
```

**Note:** `sqlite3` CLI binary is often absent — use Python's built-in `sqlite3` module instead.

## When `chief_status` tool is unavailable (pure SQLite fallback)

In some cron worker contexts the `chief_status` MCP tool is not registered. Use the SQLite approach directly:

```python
import sqlite3, json, time

BOARD = "<example-chief-id>"  # replace with real chief_id, e.g. "chief-myproj-abcd12"
DB = f"/home/hermes/.hermes/kanban/boards/{BOARD}/kanban.db"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# 1. Discover all tasks
cur.execute("SELECT id, title, status, assignee, consecutive_failures, last_failure_error, created_at, completed_at, result FROM tasks ORDER BY id")
tasks = [dict(r) for r in cur.fetchall()]

# 2. Chief is DONE when the chief-manager task has status='done'
chief_task = next((t for t in tasks if t['assignee'] == 'chief-manager'), None)
chief_done = chief_task and chief_task['status'] == 'done'

# 3. Subtask counts
worker_tasks = [t for t in tasks if t['assignee'] != 'chief-manager']
done_count = sum(1 for t in worker_tasks if t['status'] == 'done')
open_count = sum(1 for t in worker_tasks if t['status'] not in ('done', 'archived'))

# 4. Stall detection — get last run end time
cur.execute("SELECT task_id, status, ended_at FROM task_runs ORDER BY ended_at DESC LIMIT 5")
runs = [dict(r) for r in cur.fetchall()]
last_run_end = max((r['ended_at'] for r in runs if r['ended_at']), default=0)
stalled = (time.time() - last_run_end) > 600  # >10 min

# 5. WHY is a task blocked? Check task_events (no blocked_reason column)
cur.execute("SELECT task_id, kind, payload, created_at FROM task_events WHERE kind IN ('gave_up','blocked') ORDER BY created_at DESC LIMIT 10")
block_events = [dict(r) for r in cur.fetchall()]
# gave_up = dispatcher exhausted retries (exit_code 1); blocked = review-required or manual block

# 6. Comments (for spreadsheet URL, last message)
cur.execute("SELECT task_id, author, body, created_at FROM task_comments ORDER BY created_at DESC LIMIT 5")
comments = [dict(r) for r in cur.fetchall()]
```

**Key determination logic:**
- `chief alive=true` → chief_task.status not in ('done','blocked','archived')
- `gave_up` event present → worker crashed beyond retry limit, not review-required
- Check `block_events[0]['payload']` for `"review-required"` string to trigger auto-unblock
- Runtime = `(chief_task['completed_at'] or time.time()) - chief_task['created_at']`

**Board discovery** (when board slug is unknown):
```bash
find /home/hermes/.hermes/kanban/boards -maxdepth 1 -name 'chief-*' -not -path '*/_archived/*'
```
Active boards are directly under `/home/hermes/.hermes/kanban/boards/` (not under `_archived/`).
Archived boards live at `/home/hermes/.hermes/kanban/boards/_archived/<slug>/kanban.db`.

See `references/kanban-sqlite-chief-fallback.md` for a complete worked example.

## Chief monitoring specifics

### `chief_status` last_comment is truncated

The `last_comment` field returned by `chief_status` is **NOT the full body** — it is a truncated summary like `{"author": "chief-manager", "len": 943}`. To get the full comment body, query `task_comments` directly against the chief's initial task id.

```python
import sys; sys.path.insert(0, '/opt/hermes')
from tools.chief_tools import _handle_chief_status, _import_kanban_db

# Get status
status = _handle_chief_status({'chief_id': 'chief-<slug>'})
import json; s = json.loads(status)
initial_task_id = s['initial_task']  # e.g. 't_173a5613'

# Get full last comment
db_mod = _import_kanban_db()
db_path = db_mod.kanban_db_path(s['chief_id'].replace('chief-', '', 1))
# Or directly:
import sqlite3
conn = sqlite3.connect(f'/opt/data/kanban/boards/{s["chief_id"]}/kanban.db')
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT * FROM task_comments WHERE task_id=? ORDER BY created_at DESC LIMIT 1",
    (initial_task_id,)
).fetchall()
```

### `alive=false` + `initial_status=done` ≠ all subtasks complete

When a chief reports `alive=false` and `initial_task` status is `done`, this means only the **planning/decomposition task** completed — the chief board has stopped dispatching. Subtasks (researcher, developer, QA) can still be open, running, or blocked. Always cross-check `subtasks_done` vs `subtasks_total` before reporting full completion to the user.

### Chief tools import path

```python
# Correct import (from /opt/hermes working directory):
from tools.chief_tools import _handle_chief_status
result = _handle_chief_status({'chief_id': 'chief-<slug>'})  # returns JSON string

# Wrong — module does not exist:
# from agent.tools.chief_tools import chief_status
```

## Diagnosing crash-blocked tasks (no comment left by worker)

When a task is `blocked` with `consecutive_failures > 0` but **zero comments** on the task, the worker crashed before it could call `kanban_block`. The block reason and error are NOT in `task_runs.error` (which only says `"pid X exited with code 1"`). Check the per-task log file:

```python
import os
log_path = f"/home/hermes/.hermes/kanban/boards/{BOARD}/logs/{task_id}.log"
if os.path.exists(log_path):
    with open(log_path) as f:
        print(f.read())
# Common patterns:
# "Error: Unknown skill(s): kanban-worker"  → profile-local skills dir missing the skill
# "ModuleNotFoundError: ..."                → missing Python package in profile env
# "Error: Unknown tool ..."                 → tool not in profile's toolset/config
```

**Profile-local skills fix** (for `Unknown skill(s): <name>`):
```bash
cp -r ~/.hermes/skills/<skill-name> ~/.hermes/profiles/<role>/skills/
```
Skills resolve against the profile-local `skills/` dir, not the shared one. This crash leaves no comment on the task — the log file is the only evidence.

## Pitfalls

- **Live board empty ≠ chief never ran**: A board directory can exist under `boards/<slug>/` with zero tasks/comments/events if the chief was archived mid-run and then re-spawned fresh. When `SELECT COUNT(*) FROM tasks` returns 0 on the live board, check the most recent archived snapshot: `find /home/hermes/.hermes/kanban/boards/_archived -maxdepth 1 -name '<slug>-*' | sort | tail -1`. That archived DB has the actual run history.

- **chief_id ≠ board slug**: The chief_id you're given (e.g. `chief-b2b-growth-agent-55a290`) is a prefix, NOT the full board directory name. The actual board slug has a Unix timestamp suffix: `chief-b2b-growth-agent-55a290-1779875387`. Always discover the board via grep:
  ```bash
  # Check active boards first
  ls /home/hermes/.hermes/kanban/boards/ | grep "chief-b2b-growth-agent-55a290"
  # Then archived
  ls /home/hermes/.hermes/kanban/boards/_archived/ | grep "chief-b2b-growth-agent-55a290"
  ```
  If the chief appears only under `_archived/`, it is `alive=false`. When multiple timestamped boards match, use the highest timestamp (most recent run). Empty boards under the active path are stale stubs — the real data is in the newest archived snapshot.

- **Never use `hermes` CLI in cron** — not in PATH (binary is at `/opt/hermes/.venv/bin/hermes`); even when invoked by full path, `--board <slug>` only works for `list` — `unblock` and `boards switch` return "board does not exist". Use SQLite fallback for any write operation.
- **`hermes kanban --board <slug> unblock` silently fails** — same `--board` flag accepted by `list` is rejected by `unblock`/`switch` with "board does not exist". Always use the Python sqlite3 unblock pattern (see failure-recovery pitfall 11).
- **Never run `cli.py kanban list`** — spawns agent subprocess, times out in 60s
- **`attempt_count` does not exist** — the column is `consecutive_failures`
- **`task_runs.completed_at` does not exist** — use `ended_at`
- **`status=done` with 0 failures can still be a partial/stub deployment** — always read `task_runs.summary` and `task_runs.metadata` for blockers before reporting live success
- **Check for prior PM notifications** before sending milestone alerts — query `task_comments` filtered by `author='chief-pm-cron'` to avoid duplicate reports

## References

- `references/kanban-sqlite-chief-fallback.md` — complete SQLite fallback pattern when `chief_status` MCP tool is unavailable (cron worker context); includes DB path discovery, schema, event kinds, and stall detection code.
- `references/kanban-sqlite-schema.md` — full column list for tasks/task_runs/task_events tables with gotchas (no `blocked_reason`, no `updated_at`).

- `references/phase4-notimplementederror-pattern.md` — Polymarket EIP-712 signing blocker pattern
