# Kanban SQLite Direct Access — Fallback for CLI Failures in Cron/Autonomous Context

## When to use this

Use direct SQLite instead of the `hermes kanban` CLI when:
- Running in a cron job or `execute_code` context where shell sessions don't persist
- `hermes kanban unblock <id>` returns "cannot unblock (not blocked?)" despite DB showing `status='blocked'`
- `hermes kanban archive <id>` returns "cannot archive" (cannot archive a blocked task directly)
- Board switch via `hermes kanban boards switch <slug>` didn't survive to the next terminal() call

## DB location — host vs container

**Inside Hermes container** (worker/MCP/kanban context):
```
/opt/data/kanban/boards/<board-slug>/kanban.db
```

**From the host** (cron jobs when Docker daemon is unreachable, or host-side scripts):
```
/home/hermes/.hermes/kanban/boards/<board-slug>/kanban.db
```

List all active boards (host, Python):
```python
import os
base = "/home/hermes/.hermes/kanban/boards"
boards = [d for d in os.listdir(base) if d != "_archived"]
```

List all boards (container, bash):
```bash
find /opt/data/kanban/boards -name 'kanban.db' 2>/dev/null
```

## Verified table schemas (2026-05-23)

### `tasks`
Key columns: `id TEXT`, `title TEXT`, `status TEXT`, `assignee TEXT`,
`consecutive_failures INTEGER`, `last_failure_error TEXT`,
`completed_at INTEGER` (unix timestamp), `started_at INTEGER`,
`created_at INTEGER`, `workspace_kind TEXT`, `workspace_path TEXT`,
`priority INTEGER`, `worker_pid TEXT`, `last_heartbeat_at INTEGER`

Status values: `triage`, `todo`, `ready`, `running`, `blocked`, `done`, `archived`

### `task_events`
Columns: `id INTEGER PK`, `task_id TEXT`, `run_id INTEGER`, `kind TEXT`, `payload TEXT`, `created_at INTEGER`
**Note:** Column is `kind`, NOT `event_type` — inserting with `event_type` raises OperationalError.

### `task_comments`
Columns: `id INTEGER PK`, `task_id TEXT`, `author TEXT`, `body TEXT`, `created_at INTEGER`

### `task_links`
Columns: `parent_id TEXT`, `child_id TEXT` (dependency edges)

### `task_runs`
Columns: `id INTEGER PK`, `task_id TEXT`, `profile TEXT`, `outcome TEXT`, `elapsed_sec REAL`, `summary TEXT`, `created_at INTEGER`

## Common operations via Python

```python
import sqlite3, time, json

db = "/opt/data/kanban/boards/<board-slug>/kanban.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()
now = int(time.time())

# Read all non-done tasks
cur.execute("SELECT id, title, status, assignee, consecutive_failures, last_failure_error, last_heartbeat_at FROM tasks WHERE status != 'done'")
for row in cur.fetchall():
    print(dict(row))

# Mark a superseded blocked task as done (cleanup)
cur.execute("UPDATE tasks SET status='done', completed_at=? WHERE id=?", (now, task_id))

# Add a comment
cur.execute(
    "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?, ?, ?, ?)",
    (task_id, "chief-pm-cron", "Reason for update.", now)
)

con.commit()
con.close()
```

## Board switch persistence in non-interactive contexts

`hermes kanban boards switch <slug>` writes to a config file. It persists within a
single bash script but NOT across separate `execute_code` / `terminal()` calls from Python.

**Pattern that works:** combine switch + commands in ONE bash script:
```bash
#!/bin/bash
hermes kanban boards switch chief-my-board
hermes kanban list  # picks up the switched board
hermes kanban show t_abc123
```

**Pattern that does NOT work:**
```python
terminal("hermes kanban boards switch my-board")  # call 1
terminal("hermes kanban list")  # call 2 — sees the DEFAULT board, not my-board
```

**Reliable alternative:** bypass CLI entirely and query SQLite directly.

## Why `hermes kanban unblock` fails silently

The CLI may return "cannot unblock (not blocked?)" even when `SELECT status FROM tasks WHERE id='<id>'`
returns `blocked`. Observed on 2026-05-23 in a cron context — cause unknown (possible stale board
switch state or concurrency lock). Workaround: direct SQL UPDATE as shown above.

## Detecting superseded tasks

A blocked task is "superseded" when:
- `status = 'blocked'`, `consecutive_failures >= 2`
- Another task with nearly identical title + `[reassigned]` suffix exists and is `done`

Pattern for cleanup:
```python
cur.execute("""
    SELECT id, title FROM tasks
    WHERE status='blocked' AND consecutive_failures >= 2
""")
blocked = cur.fetchall()
cur.execute("SELECT title FROM tasks WHERE status='done'")
done_titles = {r['title'] for r in cur.fetchall()}

for t in blocked:
    reassigned_title = t['title'] + ' [reassigned]'
    if any(reassigned_title in dt or dt.endswith('[reassigned]') for dt in done_titles):
        # superseded — safe to mark done
        ...
```
