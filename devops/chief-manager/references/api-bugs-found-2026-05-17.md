# chief-manager API bugs found during live test (2026-05-17)

## Bug 1: `chief.build_capability_matrix` does not exist

**Error:** `AttributeError: 'Chief' object has no attribute 'build_capability_matrix'`

**Root cause:** SKILL.md (before fix) showed it as a Chief method. It's actually in `capability.py`.

**Correct usage:**
```python
from capability import build_capability_matrix

tasks_with_req = [
    {
        "name": t.name,
        "description": t.description,
        "required_skills": ["skill-name"],   # explicit, not inferred
        "required_tools": ["terminal"],       # explicit
    }
    for t in workflow.plan.task_tree.tasks
]
matrix = build_capability_matrix(tasks_with_req)
workflow.capability_matrix = matrix  # attach to workflow manually
```

---

## Bug 2: `workflow.assignments` is first-match — append silently fails

**Error:** After `plan_workflow`, assignments contain auto-detected profiles. Appending new AgentAssignment objects puts them at the END, but `assignment_for()` returns the FIRST match. Result: your manual override is silently ignored.

**Wrong pattern:**
```python
workflow.assignments.append(AgentAssignment(task_name="enrich_metadata", profile="youtube-indexer"))
# Does nothing — auto-assigned profile is already first in list
```

**Correct pattern:**
```python
from graph import AgentAssignment
workflow.assignments = [
    AgentAssignment(task_name=t.name, profile="youtube-indexer")
    for t in workflow.plan.task_tree.tasks
]
```

---

## Bug 3: `plan_workflow` silently overwrites external `make_goal` calls

**Root cause:** Inside `plan_workflow` (line 280):
```python
goal = self.make_goal(statement=self.goal_text)  # overwrites self.goal
```
Any `chief.make_goal(subgoals=[...])` call BEFORE `plan_workflow` is discarded.

**Consequence:** If you set `subgoal_id` in task specs, validation fails with:
```
ValueError: Task 'X' references unknown subgoal 'Y'
```
Because the internal `make_goal` creates a goal with NO subgoals.

**Workaround:** Do NOT use `subgoal_id` in tasks when calling `plan_workflow`. All tasks fall into `_unassigned` subgoal bucket — this is fine for dispatch.

---

## Bug 4: `DECOMPOSE_INGEST_BY_SOURCE=True` breaks already-per-source tasks

When providing individual `ingest_youtube`, `ingest_github`, etc., the auto-splitter still fires because their descriptions contain source keywords. It creates phantom subtasks `ingest_drive_drive`, `ingest_drive_pdf`, etc.

**Fix:**
```python
import chief as cfg
cfg.DECOMPOSE_INGEST_BY_SOURCE = False
```
Set BEFORE calling `Chief()` or `plan_workflow()`.

---

## False positive: `terminal` in missing_mcp gaps

Capability scanner checks `terminal` against `config.yaml mcp.servers`. But `terminal` is a built-in Hermes tool, not an MCP server. This gap is always a false positive — safe to ignore.

---

## ~~Bug 6~~ ОПРОВЕРГНУТ (2026-05-17): `kanban_create` MCP с `board=<slug>` работает корректно

Тест: `kanban_create(title=..., board="quants")` → `t_ff39921a` попала в `/opt/data/kanban/boards/quants/kanban.db`. Задачи первоначального теста попали на дефолтную доску из-за **отсутствия параметра `board`**, а не из-за бага.

---

## Bug 6 (historical): `kanban_create` MCP tool ignores board switch — always writes to legacy default

**Symptom:** Tasks appear on default board despite `hermes kanban boards create quants --switch`.
User sees quants board empty, default board has all tasks.

**Root cause:** The MCP `kanban_create` tool is backed by the **gateway process** (`hermes gateway run`).
The gateway opens `/opt/data/kanban.db` at startup and never changes its connection.
CLI `hermes kanban boards create quants --switch` only updates a session-local state for
the CLI binary — the gateway process is unaffected.

**Wrong pattern (does NOT write to quants):**
```python
# After hermes kanban boards create quants --switch ...
kanban_create(title="task", assignee="profile", ...)  # ← still goes to /opt/data/kanban.db
```

**Correct pattern — use `cli_dispatch_task()`:**
```python
board_slug = "quants"
result = Chief.create_project_board(board_slug)
verify = Chief.verify_board_active(board_slug)
assert verify["ok"], f"Board not ready: {verify['error']}"

task_name_to_id = {}
for spec in dispatch_plan:
    r = Chief.cli_dispatch_task(spec, board_slug, task_name_to_id)
    assert r["task_id"], f"Dispatch failed: {r['error']}"
    print(f"Created {r['task_id']} on {board_slug}")
```

This runs `HERMES_KANBAN_BOARD=quants /opt/hermes/.venv/bin/hermes kanban create ...`
as a subprocess — it writes directly to `/opt/data/kanban/boards/quants/kanban.db`.

**Impact of this bug on current run (2026-05-17):**
All 8 quants tasks created on `/opt/data/kanban.db`. youtube-indexer and vk-indexer were
already running when discovered — interrupting would lose progress. Pipeline completes on
default board. Fix applied to chief.py; next run will be board-isolated.

---

## Working smoke-test script (Phases 1–6, no dispatch)

```python
import sys
sys.path.insert(0, '/opt/data/skills/devops/chief-manager/scripts')
import chief as cfg
cfg.DECOMPOSE_INGEST_BY_SOURCE = False  # MUST be before Chief()

from chief import Chief
from graph import AgentAssignment
from capability import build_capability_matrix

chief = Chief(goal_text="Your goal text here, at least 10 chars")

# Phase 2 — task tree (do NOT call make_goal first)
workflow = chief.plan_workflow(tasks=[
    {"name": "task_a", "description": "...", "inputs": [], "outputs": ["output_a"]},
    {"name": "task_b", "description": "...", "inputs": ["output_a"], "outputs": ["output_b"]},
])

# Phase 3 — validate
assert not workflow.plan.validate(), "DAG invalid"

# Phase 4 — capability matrix
tasks_with_req = [
    {"name": t.name, "description": t.description, "required_skills": [], "required_tools": []}
    for t in workflow.plan.task_tree.tasks
]
matrix = build_capability_matrix(tasks_with_req)
workflow.capability_matrix = matrix

# Override assignments (REPLACE, not append)
workflow.assignments = [
    AgentAssignment(task_name=t.name, profile="youtube-indexer")
    for t in workflow.plan.task_tree.tasks
]

# Phase 5 — negotiation message
print(chief.format_negotiation_message(workflow))

# Phase 6 — dispatch specs (call kanban_create on each)
specs = chief.build_dispatch_plan(workflow)
for spec in specs:
    print(f"[{spec.assignee}] {spec.title} parents={spec.parents}")
    # kanban_create(**spec.to_dict())  # uncomment to actually dispatch
```
