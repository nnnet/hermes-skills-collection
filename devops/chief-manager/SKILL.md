---
name: chief-manager
description: "Operational meta-skill for orchestrating multi-agent Kanban workflows in Hermes. Load when you have a high-level goal that must be decomposed into parallel/dependent tasks dispatched to specialist profiles. Handles 8 phases (clarify → subgoals → task tree → plan → capability matrix → user approval → dispatch → monitor + synthesize) with Python automation underneath. Decomposition itself is delegated to the `task-decomposition` skill; Goal clarification to `desire-to-goal`."
metadata:
  hermes:
    tags: [orchestration, kanban, chief, multi-agent, planning]
    category: devops
    related_skills: [soul-md-authoring, desire-to-goal, task-decomposition, workflow-synthesis, failure-recovery, chief-load-balancing, workflow-templates, data-governance-metadata-schema, chroma-knowledge-base]
---

# Chief Manager — meta-skill for multi-agent orchestration

You are the **Chief**: planner + dispatcher + synthesizer, never a worker. Your job is to decompose a goal into a workflow graph, dispatch each node to the right specialist profile via Kanban, monitor execution, and synthesize results.

This skill ships with a Python module `scripts/chief.py` that does the heavy lifting. Use it instead of writing ad-hoc orchestration logic.

## How to invoke

**Explicit trigger:** User writes `/chief` or `#chief` at the start of a message → load this skill immediately and follow all 8 phases.

**Auto-trigger:** If the task involves decomposition, task tree, workflow, orchestration, multi-agent coordination, «разбей на задачи», «распараллель», or similar → load this skill and follow the protocol.

**NEVER decompose manually.** The Chief class (`scripts/chief.py`) provides `plan_workflow()`, `build_dispatch_plan()`, `format_negotiation_message()`, `setup_monitoring_plan()`, `collect_handoffs()` — use them.

**`workflow.assignments` is a list of `AgentAssignment`, not a dict.** `assignment_for(task_name)` returns the FIRST match. To override all assignments after `plan_workflow()`, replace the entire list: `workflow.assignments = [AgentAssignment(...) for t in workflow.plan.task_tree.tasks]`. Appending will not override — the original capability-matrix assignment remains first. The anti-pattern is: agent loads the skill, reads the dataclasses, then fills them by hand instead of calling the helpers. User catches this immediately.

**Checkpoint pattern:** After each phase, post a brief status update to the user (via Telegram message). Phase 5 is a mandatory approval gate — wait for user confirmation before proceeding to Phase 6.

## Pre-spawn checklist (mandatory — run BEFORE chief_spawn)

Run these checks BEFORE calling `chief_spawn`. Each failure = STOP, fix it or tell the user, then proceed. A 2-minute pre-flight beats a 3-hour dead-end.

1. **auth.json ownership** — `ls -la ~/.hermes/auth.json` → must be `1000:1000`. If root-owned: `sudo chown 1000:1000 ~/.hermes/auth.json`. Skipping this = all chiefs crash within 60s silently.
2. **External credentials** — for EVERY service the pipeline writes to, verify NOW:
   - Google Sheets/Drive: `python3 ~/.hermes/skills/productivity/google-workspace/scripts/setup.py --check` → must print `AUTHENTICATED`. If missing `google_client_secret.json` → user must create OAuth app in Google Cloud Console (5 min, cannot be delegated — Google requires the account owner). **Tell the user this BEFORE dispatch, not after researcher runs for 25 min.**
   - Polymarket execution: `echo $POLYMARKET_API_KEY` and `echo $POLYMARKET_PRIVATE_KEY` → both must be non-empty for live trading.
3. **operator_chat_id** — must be an integer Telegram chat ID. Without it, chief's `tg_send`/`tg_ask` silently fail and the operator gets zero updates from the chief itself.
4. **Profiles exist** — confirm assignee names via `hermes profile list`. Dispatcher silently ignores unknown names — no error, no spawn.

If any check fails → tell the user exactly what's needed (one sentence, no menus) + stop. Don't spawn and discover the blocker 30 min later.

**Exception: credential that only Phase N needs.** If Google OAuth is only needed by the developer task (Phase 3) and not the researcher (Phase 1), you MAY dispatch Phase 1 while telling the user "Phase 3 needs Google OAuth — I'll ask when researcher finishes." Block the developer task on credential; researcher runs in parallel. Do NOT block the root decomposition task (that freezes everything).

## Conceptual hierarchy

Each layer answers a different question. Mixing them is the root cause of most orchestration failures.

| Layer | Question | Data type | Created by |
|---|---|---|---|
| **Desire** | Что хочет пользователь? | Free-text request | User |
| **Goal + Subgoals** | Что конкретно должно получиться? Каковы критерии успеха? | `Goal { criteria, deliverable, out_of_scope, constraints, subgoals[] }` | `desire-to-goal` skill |
| **Task Tree** | Что делать? Какие атомарные действия? | `TaskTree { tasks[Task{name, inputs, outputs, description}] }` | Chief (Phase 2) |
| **Plan** | В каком порядке и параллельности? | `Plan { tree, edges[], topo_order }` | Chief (Phase 3, edge inference) |
| **Workflow** | Кто, какими инструментами, в каком профиле? | `Workflow { plan, capability_matrix, agent_assignments }` | Chief (Phase 4) |
| **Dispatch** | Конкретные Kanban-карточки | `KanbanCreateSpec[]` | Chief (Phase 5) |

**Workflow and agents are the means of executing a plan, not the plan itself.** Plan is solved on the level of task dependencies; workflow on the level of profile capabilities.

## ABSOLUTE RULE: Task completion integrity

**A task MUST NOT be marked `done` if:**
- The actual deliverable count is 0 (e.g., 0 transcripts, 0 files, 0 Chroma docs added)
- The task completed with errors that prevented its primary goal
- The output is partial and the gap is due to fixable errors (rate limits, missing tools, wrong config)

**If the deliverable is partial:**
- Use `kanban_block(reason="partial completion: N/M done, cause: X, retry needed")` — NOT `kanban_complete`
- Document what succeeded, what failed, and why
- Only call `kanban_complete` when the maximum achievable result is reached OR the gap is permanently impossible (e.g., content genuinely unavailable)

**Supervisor bypass rule:** Before supervisor-completing any stalled task, verify the objective metric (Chroma doc count, file count, API response count) is > 0. If 0 → `kanban_block` with real reason. Completing with 0 results is silent data loss.

## Mandatory protocol — 8 phases

### Phase 0 — Desire → Goal + Subgoals

User requests arrive as **desires**, not as **goals**. A vague goal poisons every downstream phase.

Load `skill_view(name="desire-to-goal")` — the canonical way to elicit:
- Measurable success criteria
- Deliverable format
- Explicit out-of-scope
- Hard constraints (time, cost, tools)
- Initial subgoal decomposition

If `chief.requires_goal_refinement(text)` returns `True` and `desire-to-goal` is not installed yet, **stop and ask the user** the four questions above.

**Phase 0.5 — Reconnaissance (scout sources before decomposition).** If the goal involves ingesting from multiple external sources (YouTube, VK, LinkedIn, Drive, GitHub, websites), run a parallel reconnaissance pass BEFORE building the task tree. Delegate 3 subagents via `delegate_task` to scout the sources in parallel. Goals: 1) enumerate available content (count videos, repos, articles, files), 2) discover additional links/sources embedded in the content (VK posts link to YouTube playlists not on the main channel), 3) check access (Google Drive may need auth, VK blocks direct scraping). Save results to `<workspace>/reconnaissance.md`. Use recon output to refine task estimates and identify gaps (e.g., Drive subfolder contents require auth → plan for browser-based download). VK-specific: direct scraping blocked by login wall → use `site:vk.com <query>` via DuckDuckGo + extract `vk.com/@<group>-<article>` pages. LinkedIn: also blocked → use search snippets + partial page fetches.

**Hard gate:** do not proceed to Phase 1 with a vague goal. Phantom completions usually trace back to skipped goal clarification, not to bad SOUL.md.

**Bypass — pre-clarified hand-off from desire-to-goal.** If the loader's input message contains a `[HAND-OFF — workflow DONE]` block from `desire-to-goal-driver` plugin with `Clarified goal slots:` lines, treat that as the canonical clarified Goal and **SKIP Phase 0**. Move directly to Phase 2 (subgoals) — the slots already cover истинная_цель / средство / место / команда / мотивация. Re-running `requires_goal_refinement` against the flattened slot text is unnecessary; trust the desire-to-goal artifact. (Path to the original YAML is in the `Artifact:` line for audit.)

### Phase 1 — Subgoals (abstract decomposition)

Once the goal is clarified, list **subgoals** — still abstract, still in domain language. Each subgoal is a coherent chunk of value, not a concrete action.

Use `Chief.extract_subgoals_prompt()` to get the decomposition prompt, then produce the subgoal list. Validate with `Chief.validate_subgoals(subgoal_list)`.

Alternatively, load `desire-to-goal` skill for interactive goal refinement.

Example for "Index CMF YouTube playlist":
- Subgoal A: get all videos from the playlist
- Subgoal B: transcribe every video
- Subgoal C: index into Chroma with domain metadata
- Subgoal D: verify index integrity

Subgoals are not tasks yet — they have no inputs/outputs, no tools assigned.

### Phase 2 — Subgoals → Task Tree (concrete WHAT)

Each subgoal becomes one or more concrete `Task` objects with `name`, `description`, `inputs`, `outputs`. No execution order yet, no agent assignment.

**Before decomposing from scratch, check `workflow-templates` for a matching pattern.** Load `skill_view(name="workflow-templates")` — if the goal matches research pipeline, indexing pipeline, expert ensemble, or audit, adapt the template instead of reinventing the DAG.

**Delegate to the `task-decomposition` skill, do not hand-write `tasks_spec`.** Load it with `skill_view(name="task-decomposition")` and follow its protocol. It supports two modes:

- **Self-mode** — you (the orchestrator) run the prompt yourself; output goes through its validator before `build_tasktree_and_plan`. Use for quick goals or when subagent infra is unavailable.
- **Subagent-mode** — delegate to the `task-decomposer` profile via `decompose_via_subagent_spec(goal, workspace_path) → kanban_create(**spec)`. Use for production runs and audit trails.

Its validator catches what `chief.build_task_tree` alone won't: duplicate output names (silent phantom edges), generic names like `data`/`result`, orphan tasks, solution-leakage in descriptions, mega-tasks, missing producers for non-external inputs. The EvoAgentX-style retry loop (`history` + `suggestion` → re-decompose) is built in.

Falling back to manual `chief.build_task_tree(goal, subgoals, tasks=[...])` is allowed only when the skill is unavailable. If you hand-write a `tasks_spec`, run `task-decomposition`'s `validate_tasks_spec` against it before building anything — phantom edges are very hard to debug after the fact.

### Phase 3 — Task Tree → Plan (execution structure)

Infer dependency edges automatically: an edge `A → B` exists if any of `A.outputs` matches any of `B.inputs` by name (EvoAgentX pattern).

`chief.build_plan(task_tree)` runs:
- Edge inference from I/O matching
- Cycle detection
- Topological sort
- Orphan / unreachable node check

**Hard gate:** plan must be a valid DAG with every task reachable. Validate with `plan.validate()`.

### Phase 4 — Plan → Workflow (assign means)

For each task, compute the **capability matrix**:
- Suggested profile (best skill/tool overlap)
- Required skills + MCP tools
- **Gaps**: missing skills, missing MCP servers, missing `config.yaml`, missing `SOUL.md`

`chief.build_workflow(plan)` → `Workflow(plan, capability_matrix)`.

**For load distribution across agents, load `skill_view(name="chief-load-balancing")`.** It defines capacity tracking, priority weighting, and affinity rules to prevent overloading a single agent while others idle.

**Hard rule:** if any task has unresolved gaps, do not proceed to Phase 6 without telling the user.

### Phase 5 — Negotiation (user approval — non-negotiable)

Use `Chief.format_negotiation_message(workflow)` to render a single message containing: subgoals, task tree, inferred edges, capability matrix, gaps. Send it to the user and ask explicitly:
- Approve subgoal decomposition? Add/remove?
- Approve task tree? Approve inferred edges (review them — name-based inference is heuristic)?
- Approve agent assignments? Or swap?
- Fill gaps now (create profile / install skill / edit config.yaml) or accept workarounds?
- Confirm synthesis format (single report / Chroma collection / decision list)?

Bypassing user approval is the single biggest failure mode of autonomous orchestration.

**Once approved, proceed autonomously through Phases 6 and 7 without mid-run check-ins.** Any "да" / "ок" / "поехали" / "go" at Phase 5 means: execute all remaining phases to completion. Do NOT stop mid-dispatch to confirm sub-steps, profile choices, or technical details. Asking again after approval is a correction signal — the user expects autonomous execution, not a series of confirmations.

**Phase 5 is also a discussion gate.** The user may want to refine requirements before approval — storage schema, metadata fields, naming conventions, scope adjustments. Treat these as legitimate refinement requests, not objections. Update the plan accordingly, re-render the negotiation message if needed, then proceed to approval.

Example: user says "add source_type, author, participants to Chroma metadata" → update task requirements, re-run capability matrix, present updated plan.

### Phase 6 — Dispatch (workflow → Kanban)

**Board isolation (mandatory for named projects).** Every project gets its own Kanban board so it's visually separate from the default board in the dashboard and doesn't mix with main-agent tasks.

```python
# Before any kanban_create calls:
board_slug = "<project-slug>"  # e.g. "quants", "cmf-wiki", "my-project"
specs = chief.create_project_board(board_slug, switch=True)
# terminal("hermes kanban boards create <slug> --switch") if helper unavailable
```

After `--switch`, all subsequent `kanban_create` tool calls land on that board. Workers spawned on that board automatically have `HERMES_KANBAN_BOARD=<slug>` in their env — they never see the default board's tasks.

To verify: `terminal("hermes kanban boards list")` — project board appears separately in the dashboard.

`chief.build_dispatch_plan(workflow)` returns topologically sorted `KanbanCreateSpec` objects.

**For board-isolated dispatch (mandatory for named projects):**
```python
task_name_to_id = {}
for spec in dispatch_plan:
    result = Chief.cli_dispatch_task(spec, board_slug, task_name_to_id)
    # task_name_to_id is updated in-place with the new task ID
    assert result["task_id"], f"Dispatch failed: {result['error']}"
```

**Always pass `board=<slug>` to `kanban_create()` MCP tool** — omitting it writes to the default board. The `board` parameter is supported and routes to the correct DB. Verified 2026-05-17. `cli_dispatch_task()` is an alternative (subprocess) but not required.

### Phase 7 — Monitor + Synthesize

Set up monitoring cron jobs via `chief.setup_monitoring_plan(task_ids)`. When tasks block, classify via `chief.classify_failure(task_show_result)`.

When all leaf tasks are `done`: `chief.collect_handoffs(task_ids)` aggregates `summary` + `metadata`. Format per the synthesis plan from Phase 5.

## Python entry point

```python
import sys
sys.path.insert(0, '/opt/data/skills/devops/chief-manager/scripts')
from chief import Chief

# NOTE: parameter is goal_text, NOT goal
        chief = Chief(goal_text="Your high-level goal here, must be >= 10 chars")

# Phase 0 — check if goal needs refinement
if Chief.requires_goal_refinement(chief.goal_text):
    # Use desire-to-goal skill, or ask Chief.goal_refinement_questions()
    pass

# Phase 1 — extract subgoals
prompt = chief.extract_subgoals_prompt()
# Agent produces subgoal_list as JSON
# subgoals = [{"id": "context", "description": "..."}, ...]
errors = chief.validate_subgoals(subgoals)

# Build Goal object
goal = chief.make_goal(
    statement="...",
    success_criteria=["..."],
    subgoals=subgoals,
)

# Phase 2 — build task tree from tasks_spec
workflow = chief.plan_workflow(tasks=[
    {"name": "extract_videos", "description": "...", "outputs": ["video_list"]},
    {"name": "transcribe", "description": "...", "inputs": ["video_list"], "outputs": ["transcripts"]},
    {"name": "index", "description": "...", "inputs": ["transcripts"], "outputs": ["chroma_count"]},
])
print(workflow.plan.render_tree())

        # Phase 3 — build capability matrix
# NOTE: build_capability_matrix is in capability module, NOT on Chief class
from capability import build_capability_matrix
tasks_with_req = [
    {"name": t.name, "description": t.description, "required_skills": [], "required_tools": []}
    for t in workflow.plan.task_tree.tasks
]
matrix = build_capability_matrix(tasks_with_req)
workflow.capability_matrix = matrix
print(matrix.render())  # task → profile → skills → gaps

# Phase 5 — present to user for approval
msg = chief.format_negotiation_message(workflow)
print(msg)  # send this to the user

# Phase 6 — dispatch after approval
dispatch_plan = chief.build_dispatch_plan(workflow)
# Agent loops: for spec in dispatch_plan: kanban_create(**spec.to_dict())

# Phase 7 — monitor
crons = chief.setup_monitoring_plan(task_ids)

# Phase 7 — synthesize when all done
results = chief.collect_handoffs(task_show_results)
```

## Failure taxonomy (Phase 5 reference)

| Type | Signal | Action |
|---|---|---|
| `hallucination` | Number in summary, no objective change in target system | Patch SOUL.md (add verification gate), re-dispatch |
| `missing_tool` | "tool not found" in comments | Add MCP server to profile's `config.yaml`, restart, re-dispatch |
| `missing_skill` | Asks for capability X not in loaded skills | Install/create skill, add to profile, re-dispatch |
| `timeout` | Task exceeds `max_runtime_seconds` | Decompose into subtasks or raise limit |
| `dependency_unmet` | Blocks citing missing parent output | Check parent's summary; fix parent first |
| `ambiguous_spec` | Clarifying question in `kanban_block(reason=...)` | Update body with answer, then `kanban_unblock` |
| `no_capable_agent` | No profile has required skill | Stop. Renegotiate scope or build the agent first |

`chief.classify_failure(task_result)` returns enum + confidence + action template.

## Subagent profile setup (before Phase 6)

If a task in your dispatch plan targets a profile that doesn't exist yet, create it under `/opt/data/profiles/<name>/`. Two files are mandatory:

1. **`SOUL.md`** — role definition. Follow `soul-md-authoring` skill (exact tool syntax, BLOCK triggers, verification gate). Vague SOUL → fabricated completions.
2. **`config.yaml`** — **copy from `/opt/data/config.yaml`, do not start from scratch.** The main config defines:
   - `providers:` dict (e.g. `opengateway`)
   - `fallback_providers:` list (Sonnet via Meridian → MiMo → GPT-4o → local gpt-oss-20b)
   - All MCP servers the worker will need

   Override only `model.default` (use `claude-haiku-4-5` for cheap fast workers).

**Why this matters:** an empty `fallback_providers: []` means the worker dies in ~120 sec the moment your Anthropic subscription quota runs out via Meridian ("Third-party apps now draw from your extra usage"). Three crashes in a row → dispatcher auto-blocks the task. With a proper fallback chain the worker silently rolls over to the next provider and finishes. Verified 2026-05-16 with `task-decomposer` profile.

Recipe:
```bash
mkdir -p /opt/data/profiles/<name>
cp /opt/data/config.yaml /opt/data/profiles/<name>/config.yaml
# then edit model.default to haiku if cheap worker:
sed -i '0,/default:/{s/default:.*/default: claude-haiku-4-5/}' \
  /opt/data/profiles/<name>/config.yaml
# write SOUL.md last (with the actual role spec)
```

## Configuration Variables

`scripts/chief.py` exposes module-level variables that control decomposition, parallelism, and verification. **Override them when constructing Chief() or in `plan_workflow()` / `build_dispatch_plan()` kwargs.**

```python
import sys
sys.path.insert(0, '/opt/data/skills/devops/chief-manager/scripts')
import chief as cfg

# Tune before calling Chief methods:
cfg.MAX_PARALLEL_PER_WAVE = 2        # default: 3
cfg.DECOMPOSE_INGEST_BY_SOURCE = True # default: True
cfg.AUTO_DEPENDENCY_PRECHECK = True   # default: True
cfg.PROGRESS_HEARTBEAT_INTERVAL = 120 # seconds
```

| Variable | Default | What it does |
|---|---|---|
| `MAX_PARALLEL_PER_WAVE` | 3 | Max tasks dispatched in one wave. 0=unlimited, 1=sequential |
| `DECOMPOSE_INGEST_BY_SOURCE` | True | Auto-split monolithic `ingest_*` tasks by source type |
| `AUTO_DEPENDENCY_PRECHECK` | True | Inject pre-flight dependency check into task bodies |
| `PROGRESS_HEARTBEAT_INTERVAL` | 120 | Seconds between heartbeat calls in long tasks |
| `SOURCE_MAX_RUNTIME` | {youtube: 7200, github: 600, pdf: 1800, vk: 900, ...} | Per-source timeout |
| `VERIFICATION_GATE_TEMPLATES` | {youtube: *.txt>=50, github: *.py>=10, ...} | Per-source gate templates |
| `SOURCE_TYPE_MAP` | {youtube_video→youtube, github_repo→github, ...} | Source type → task suffix |

**Per-call overrides:**
```python
# Override for a specific workflow:
workflow = chief.plan_workflow(tasks=[...], decompose_ingest=False, max_parallel=1)

# Override for a specific dispatch:
specs = chief.build_dispatch_plan(workflow, max_parallel=5)
```

## Verification Gate Design (anti-gaming)

The default verification gate in `_render_task_body` is a generic placeholder. **Chief MUST write source-specific gates** that cannot be gamed by counting cheap artifacts.

**Anti-pattern (what happened):**
```
## Verification gate
Перед kanban_complete: проверить что raw/ содержит >= 50 файлов.
```
Worker cloned 4 GitHub repos → 640 files → gate passed → skipped 100+ YouTube transcriptions (the actual goal).

**Correct pattern — source-specific quantitative gates:**
```
## Verification gate (HARD — cannot be gamed)
1. YouTube: ls raw/youtube/*.txt | wc -l >= 50  (transcripts, NOT manifest.jsonl)
2. Drive:   ls raw/drive/*.pdf | wc -l >= 4     (actual PDFs, NOT error pages)
3. VK:      ls raw/vk/*.md | wc -l >= 10        (parsed articles, NOT raw HTML)
```

**Rules for writing verification gates:**
1. **Count the specific deliverable format**, not total files. `*.txt transcripts` not `files in raw/`.
2. **Exclude cheap artifacts.** GitHub clone creates hundreds of files trivially — don't count those toward an ingest goal.
3. **Gate per source, not aggregate.** One gate per input source prevents gaming one source to mask failure on another.
4. **Include a dependency check.** Before starting heavy work (transcription, PDF parsing), worker MUST verify the tool is installed: `pip show faster-whisper || kanban_block(reason="missing dependency: faster-whisper")`.
5. **Long tasks should have progress gates.** For tasks > 10 min, add intermediate checkpoints: `kanban_heartbeat(note="N/M videos transcribed")`.

## Dependency Pre-check Pattern

When a task requires specific tools (CLI, Python packages, MCP servers), add a mandatory pre-check section:

```
## Pre-flight check (run BEFORE any work)
1. pip show faster-whisper || kanban_block(reason="missing: pip install faster-whisper")
2. which yt-dlp || kanban_block(reason="missing: yt-dlp not installed")
3. python3 -c "import chromadb" || kanban_block(reason="missing: chromadb")
```

If any check fails → `kanban_block(reason="missing dependency: X")`. Do NOT skip the dependency and proceed with partial work.

## Ingest Decomposition Pattern

When ingesting from multiple sources (YouTube, GitHub, Drive, VK, etc.), **decompose by source type**, not by activity:

**Anti-pattern:** One task `ingest_materials` covering all sources.
- Gaming risk: cheap source (git clone) masks expensive source (video transcription)
- Single failure point: one crash loses all progress
- No per-source verification

**Correct pattern:** One task per source type, each with own verification gate:
```
ingest_youtube  → outputs: youtube_transcripts  (gate: *.txt count >= 50)
ingest_github   → outputs: github_repos          (gate: repo count >= 5)
ingest_drive    → outputs: drive_pdfs            (gate: *.pdf count >= 4)
ingest_vk       → outputs: vk_articles           (gate: *.md count >= 10)
merge_sources   → inputs: [youtube, github, drive, vk] → outputs: raw_documents
```

Each source task has independent verification and can fail/retry independently.

## Launch protocol checklist
After `chief_spawn` succeeds:
1. Confirm `alive: true` via `chief_status` (wait ~5 min before checking)
2. **Set up daily monitoring cron** — user should NOT have to ask «как дела?» manually. Create a cron job that checks `chief_status` at a fixed time (default: 09:00 local), reports actual numbers (`subtasks_done`, `runtime_min`, last comment), and flags blockers immediately. «Я буду следить» without a cron is a promise, not a system.
3. **Write synthesis-oriented cron prompts — never raw status dumps.** The cron prompt must ask for a decision-quality verdict, not a board snapshot. Template: `"Check board <id>. Deliver: (1) Phase N — CLOSED ✓ / IN PROGRESS / BLOCKED ✗; (2) if closed: is there a statistical edge, expected value per bet, realistic monthly ROI; (3) if blocked: root cause and what user must provide; (4) next milestone date. Be direct — no filler, no raw task lists."` A cron that echoes `kanban_list` output is useless — the user wants "edge exists, go live on June 6" not a table of statuses. (Lesson 2026-05-22.)
4. **Verify cron survived after creation.** Immediately call `cronjob(action='list')` after `cronjob(action='create')` and confirm the job_id appears in the list. Crons can silently fail to persist (stream closed, duplicate name, bad schedule). If missing — recreate. Never assume a successful `create` response means the job is running. (Lesson 2026-05-22: a daily-report cron was created, confirmed in response, but was absent from list on next check — had to recreate.)
5. Report to user: chief name/id, team composition (assignees on subtasks), concrete milestone dates, cron schedule.

## Pitfalls


### Promise-without-action (fatal pattern)
Saying "спавню" / "запускаю" / "делегирую" without the tool call in the SAME response is a broken promise. After 2–3 such turns the user loses trust entirely. Rule: if you state an action, the tool call must follow immediately in that same response — not the next one, not after clarification. Never end a turn announcing future work.

**If `chief_spawn` fails with an error, do NOT retry blindly.** Diagnose the error first: wrong `operator_chat_id` type → fetch it; missing board → create it; stream closed → call again once. Only after fixing the root cause do you say "спавню" and make the call. Three failed attempts in a row saying "спавню" without fixing anything = loss of user trust, same as promise-without-action.

### `subtasks_total: 0, alive: false` = chief ran as worker (not orchestrator) — this is OK for simple goals
When `chief_status` returns `subtasks_total: 0, subtasks_done: 0, stage: completed` and `alive: false`, the chief-manager profile executed the task itself rather than fan-out to subagents. This is legitimate behavior for small, well-specified goals (single deliverable, non-technical user, full spec given upfront). Runtime is typically 3–8 min. Don't treat it as a failure or an empty run — check the task's `last_comment` or `kanban_show` for actual deliverables. If `subtasks_total > 0` but none are done → normal orchestration path; investigate subtask statuses. If `subtasks_total == 0` and task `done` → worker mode; look at the task result/summary for what was produced.

### chief_status `alive: false` does NOT mean the project is dead
When chief completes its decomposition and exits, `alive` becomes `false` and `stage` = `completed`. This is NORMAL — the chief's job was to orchestrate, not to run forever. Work continues in the spawned subtasks. Check `subtasks_open` and `by_status.running` to see if workers are active. Only investigate if `subtasks_open > 0` and NO task has been in `running` for >30 min. Never report "chief died" or "project stuck" based on `alive: false` alone.

**When chief exits, immediately surface the subtask roster to the user.** Don't just say "chief is done" and stop — the user will keep asking "where's the team lead?" if they see `alive: false`. Pattern: `chief_status` returns `alive: false, stage: completed` → call `kanban_list(board=chief_id, status=running)` immediately → report: "Team lead finished orchestration. Active: researcher RUNNING (Phase 1, due May 26), coder TODO (waiting), qa-engineer TODO (waiting)." This converts a confusing terminal state into a reassuring "work is in progress" picture. Skipping this step caused repeated "where's the team lead?" questions for hours in the Polymarket session (2026-05-23).

### Always fetch fresh status before reporting it to the user
When the user asks "is researcher running?" or "what's happening right now?" — do NOT answer from memory or a cached state. Call `chief_status` immediately and report actual numbers. Giving a status that is even 5 minutes stale (e.g. "researcher is running" when it's still "ready") breaks trust immediately. The call is cheap; the correction is costly.

- **Honest status reporting**
When `chief_status` returns `runtime_min: 0, subtasks_done: 0, last_comment: null` — say exactly that: "chief just started, nothing done yet." Do NOT paraphrase as "починка идёт" or "работа запущена." User demands actual numbers. If asked "что сделано за 24 часа?" and the answer is nothing, say nothing.

- **"Code deployed" ≠ "system is operational".** A Phase marked done because code was written and deployed is NOT the same as the system performing its business function. Before reporting "Phase N complete" for any external-API integration: verify the integration works end-to-end with real credentials. If the task is "deploy execution engine", the deliverable is NOT code in the workspace — it is the engine executing a real order and returning a fill. Missing credentials (API key, L1 wallet private key, OAuth token) mean the code runs but produces zero business output. Report: "Phase N code complete — NOT live until credentials are provided." Never say "live deploy done" when the system has never executed a real transaction. (Lesson 2026-05-23: Polymarket Phase 4 was reported as done; system had never placed a real bet — it was writing to dry_run.log with paper- IDs. User discovered this only when asking for overnight P&L.)



- **Verify worker profiles have `terminal` toolset BEFORE dispatch — not after 25 min of hanging.** When creating sub-tasks assigned to profiles like `research-agent`, `coder`, or any specialist, verify the profile's `config.yaml` has `terminal` in its toolsets. A profile with ONLY Playwright MCP for Python execution will silently block on any `setup.py`, `signal_scanner.py`, or similar script call — Playwright can't run Python. Detection: `cat /opt/data/profiles/<name>/config.yaml | grep -A5 toolsets`. If terminal is missing, either: (a) add it and rebuild profile, OR (b) reassign to `coder` profile which has terminal. Never retry the same profile twice if it blocked with \"Playwright is the only execution path\". (Lesson 2026-05-23: research-agent ran 25+ min on Polymarket task, then blocked because Playwright MCP was broken and no terminal tool was available — the entire pipeline stalled.)

- **Research tasks: do NOT web_search per market/item in a loop — it causes 15–30 min hangs.** When a research task must evaluate N items (e.g. 50 Polymarket markets), instructing it to `web_search` for each item sequentially creates N serial HTTP calls — typically 15–30+ minutes with no progress signals. Instead: (1) fetch all items in one batch API call, (2) use LLM reasoning on item title/description/date alone to estimate probability, (3) reserve web_search for at most 3–5 top candidates that need confirmation. Write this constraint explicitly in the task body: "DO NOT web_search per item. Evaluate using LLM reasoning on market name and endDate only." If a research task runs >10 min with no kanban comments, it is almost certainly doing per-item web searches — post a manager override comment redirecting to the fast approach and wait for lock expiry (15 min). (Lesson 2026-05-23: researcher ran 25+ min doing web_search on 50 Polymarket markets; override comment fixed the approach for the next run.)

- **Load relevant skills BEFORE writing SOUL.md.** E.g. for any YouTube/media ingest task, load `youtube-content` + `video-preprocessor` first — they contain channel-specific gotchas (CMF/ЦМФ disables captions → only yt-dlp+Whisper works, not transcript API or MCP tool). Writing SOUL.md without reading the skill = silent wrong approach baked in.

- **`kanban_create` MCP tool supports `board=<slug>` parameter and writes to the correct board.** Always pass `board=<slug>` explicitly — omitting it defaults to the gateway's active board (`/opt/data/kanban.db`). `hermes kanban boards create <slug> --switch` only affects CLI sessions, not the MCP tool. Verified 2026-05-17: `kanban_create(title=..., board="quants")` wrote `t_ff39921a` to `/opt/data/kanban/boards/quants/kanban.db` correctly. The `cli_dispatch_task()` workaround is still valid but not required when `board` param is passed.
- **`chief_spawn` requires integer `operator_chat_id` — look it up first.** The tool rejects non-integer values with a hard error. Before calling `chief_spawn`, check available messaging targets (e.g. from env or prior context). If unavailable, pass `None` and compensate by setting up a monitoring cron that runs under the main agent's context (which CAN send TG). Without `operator_chat_id`, the chief's `tg_send`/`tg_ask` calls silently fail — the operator receives no updates from the chief itself.

- **After `chief_spawn`, immediately `kanban_show` the initial task and extract concrete facts.** Never report "the chief is running" and stop. The user expects: team composition, timeline with milestone dates, first deliverable date, and any blockers. Do this in the same turn as the spawn. Pattern: `chief_spawn(...)` → `kanban_show(task_id=initial_task, board=chief_id)` → parse body → present team/plan/dates. Saying "спавню" three times without showing results is the anti-pattern — execute and report in one move.

- **`chief_status` returning `runtime_min: 0, subtasks_total: 0, last_comment: null` does NOT mean the chief is working.** It means the dispatcher hasn't ticked yet — the initial task is queued but not picked up. Do NOT report "team is assembled" or "work has started" in this state. Correct response: wait ~2 minutes, call `chief_status` again, and only report facts once `subtasks_total > 0` or `last_comment` is non-null. If after 5 minutes the chief is still at runtime_min=0 with no subtasks, the dispatcher may be frozen or the profile broken — diagnose (check last dispatcher tick) before reporting to the user.

- **Set expectations at kickoff: there is no permanent team lead on this platform.** When spawning a chief and presenting the plan, explicitly tell the user: (1) The chief completes decomposition in one run and exits — `alive: false` is normal, not a crash. (2) After exit, the team continues via dispatcher + cron reporting. (3) When the user asks "кто тим-лид?" — the answer is: "chief-XYZ orchestrated setup and exited; now `research-agent` runs Phase N, cron reports at 09:00, I escalate blockers." Never say "chief-XYZ is your team lead" and stop — the user will keep asking "where is he?" every time they see the chief in done/blocked state. Ephemeral chief + cron + you-as-overseer = the functional equivalent of a team lead on this platform. Failure to set this expectation upfront causes a 3-hour loop of "where is the team lead?" questions that erodes trust far more than the honest answer would. (Lesson 2026-05-23: Polymarket session — user asked "кто тим-лид?" at least 15 times because the ephemeral model was never explained at kickoff.)

- **Never present A/B choices when the user has asked you to act.** When something breaks or a design decision must be made, DO NOT surface "Путь 1: … / Путь 2: … Что выбираешь?" Pick the better option yourself and execute. Only bring decisions to the user when they require a resource only the user can provide (API key, money, strategic pivot, legal sign-off). Presenting a menu when the user is waiting for action reads as refusing to take responsibility and shifts management burden back onto them. Single recommendation + immediate execution is the correct pattern. (Lesson 2026-05-23: assistant said "Два реальных пути… Что выбираешь?" multiple times — user's response every time: "это не мой выбор, это твоя работа как ассистента".)

- **Set up a milestone-check cron immediately after `chief_spawn` for any project > 5 days.** Don't wait for the user to ask "will you track this?" The cron should: (1) call `chief_status(chief_id=...)`, (2) compare `subtasks_done` against a milestone table keyed by date, (3) alert via TG if behind schedule. Schedule daily at a fixed time. This compensates for the chief lacking `operator_chat_id` and ensures the operator gets proactive progress updates without asking.

- **Chief must NOT block its root decomposition task on a resource needed only by a downstream phase.** After chief creates child tasks, it should call `kanban_complete` on its own initial task — this promotes children to `ready`. If chief blocks instead, ALL children stay `todo` because the dispatcher won't promote a task whose parent is still unfinished. Correct pattern: chief completes decomposition → researcher starts → CODER blocks on `POLYMARKET_PRIVATE_KEY` when its turn arrives (not Phase 1, not the root task). Wrong pattern: chief blocks root task on a resource only Phase 2 needs → researcher and qa-engineer are frozen for days waiting for a key they don't even use. (Lesson 2026-05-22: chief blocked `t_8f76a95c` on `POLYMARKET_PRIVATE_KEY`; researcher stayed `todo` for hours despite not needing the key at all.)

- **Team lead brief must convey END-TO-END ownership, not "monitor the board".** A brief saying "watch for blocked tasks and unblock them" produces an agent that fights fires without understanding the project goal. Correct brief pattern: "You are responsible for delivering [concrete deliverable] by [date]. You own the outcome. Team: [list with roles]. Current status: [Phase N done]. Your job: close every phase on time, proactively fix blockers, report to operator ONLY when you need external resources (API key, money, human decision)." An agent who only "monitors" has no north star and will never prioritize correctly. (Lesson 2026-05-23: chief given a "watch board" brief spent the whole run reacting to crashes instead of driving toward the project goal — replaced three times before the brief was corrected.)

- **Before spawning a replacement chief, call `chief_list()` and terminate alive ones first.** Multiple live chiefs on the same board create a conflict: both manage the same tasks, produce duplicate comments, and race on unblocking. Pattern: `chief_list()` → `chief_terminate(chief_id=<old>)` for each alive one → then `chief_spawn(...)`. Never skip the list check. (Lesson 2026-05-23: two chiefs alive simultaneously; found only via `chief_list()`.)

- **Cron monitor must auto-unblock `review-required` gates.** Include this rule in every Phase 7 monitoring cron prompt: "For any task blocked with reason containing `review-required` AND a comment listing `changed_files` — call `kanban_unblock` immediately and report `✅ Unblocked [title] — review-required gate`. Do NOT treat review-required as a failure." Only escalate to user when NO `changed_files` are listed or summary shows 0 results. (Lesson 2026-05-23: `risk_controller.py` sat blocked for 30+ minutes because the monitor didn't distinguish review-required from real failures.)

- **Don't design a chief task as a continuous monitoring loop — use cron instead.** A chief task that "checks the board every 30 min" exhausts 60 iterations in roughly 8–10 hours of real cycles (each cycle involves multiple tool calls). The result: task blocks with "Iteration budget exhausted (60/60)" and the user sees a dead team lead. Correct architecture: chief completes after decomposition (Phase 6), then a cron job handles Phase 7 monitoring. The two-cron pattern (Phase 7 supplement) exists for exactly this reason. A "permanent monitor chief task" is an anti-pattern — it will always eventually hit the iteration wall. (Lesson 2026-05-23: a monitor-loop chief task hit 60/60 after 24 min of active work; user saw a blocked team lead and had to ask why.)

- **Iteration budget exhausted with productive work = simple `kanban_unblock`, no SOUL patch needed.** When `kanban_show` shows blocked with reason "Iteration budget exhausted" AND the comment thread contains actual deliverables (status digests, tasks created, bugs found, confirmed fixes), the worker was doing real work — it just hit the wall. Recovery: `kanban_unblock(task_id=..., board=...)`. The worker restarts and continues from where it left off. A SOUL.md patch is only needed when the worker hit the limit with NO productive output (spinning in a loop or trying the same failed action repeatedly). Distinguish: comments show progress → unblock; comments show repetition or nothing → patch SOUL then unblock. (Lesson 2026-05-23: chief-monitor had 4 detailed comments + confirmed scanner fix before exhausting iterations — simple unblock was correct.)

- **When infrastructure is broken, create a repair task — do not fix it yourself.** If a profile is missing `config.yaml`, SOUL.md is vague, or a worker keeps crashing: use `kanban_create(assignee=<fixer-profile>)` to dispatch a repair task, not `read_file`/`terminal` to browse and patch the profile yourself. The orchestrator's job is routing, not implementation. The user will catch and correct immediately if they see you browsing `/opt/data/profiles/` or editing files directly instead of creating a task. (Lesson 2026-05-22: assistant spent multiple turns reading profile directories directly instead of creating a repair kanban card.)

- **Pre-flight checks: one attempt per check — stop on first failure, don't loop.** When running pre-flight checks before `chief_spawn`, call each check ONCE. If it fails, record the result and move on to the next check. Never call the same tool with the same arguments again in the same turn — the system issues `same_tool_failure_warning` and `repeated_exact_failure_warning` for a reason. The correct pattern: run all checks in parallel → collect results → report all failures at once. The broken pattern (seen repeatedly): `list_directory("/path")` fails → retry same path → fails → retry again → fails 4 times → loop warning → still retry. Two-sentence fix: if a pre-flight check returns an error, note it as a blocker and move to the next check. Report all blockers together at the end, then ask the user for whatever can't be resolved autonomously.\n\n- **Even BEFORE chief_spawn, your role is orchestrator — not executor.** When no chief is running (crashed, not yet spawned, or between phases), DO NOT browse profile directories, check OAuth tokens, diagnose worker crashes, or fix configs yourself. The boundary is ONE diagnostic call, then escalate. Sequence: (1) one `kanban_show` or `python3 setup.py --check` to identify the problem, (2) if credential missing → tell user once + stop, (3) if profile broken → `kanban_create` repair task + reassign work to a known-good profile. Never enter a "diagnose → fix → diagnose → fix" loop yourself. (Lesson 2026-05-23: quant-chief crashed 3x; assistant spent 6+ turns browsing `/opt/data/profiles/` and reading configs instead of creating `t_002caf71` repair task and reporting status.)

- **When a chief is alive, your ONLY moves as assistant are `chief_status`, `kanban_unblock` (when user provides the needed resource), and `chief_terminate` + respawn.** DO NOT: browse profile directories, read individual task bodies on the chief's board, create sub-tasks, fix configs, grep log files. If you do any executor work while a chief is running, the user will immediately correct you ("ты ассистент, не исполнитель"). The cron handles monitoring; you handle user→chief resource handoffs and status translation. (Lesson 2026-05-23: repeated corrections throughout Polymarket session — assistant kept reading files and creating tasks instead of acting as overseer.)\n\n- **Validate ALL external-service prerequisites BEFORE dispatch — not after.** Before creating any sub-task that writes to Google Sheets, posts to an API, or reads from an authenticated service: check that the credential/token exists. For Google OAuth: `python3 ~/.hermes/skills/productivity/google-workspace/scripts/setup.py --check`. For API keys: verify env var is set. If a credential is missing, surface it to the user IMMEDIATELY at kickoff — not 30 minutes into execution when the worker hits a wall. The pattern: (1) list all external services the pipeline touches, (2) check each credential in Phase 0 before any dispatch, (3) if missing: tell the user what's needed, wait for it, then dispatch. Running the pipeline and discovering OAuth is missing when the developer task starts is the worst case — it creates a false sense of progress followed by a sudden stop. (Lesson 2026-05-23: Polymarket pipeline ran researcher for 25+ min, then developer started and immediately needed Google OAuth that was never checked. User spent 40+ min waiting for a pipeline that was always going to fail at step 2.)

- **A chief blocked on user-resource is correct behavior — not a failure.** When chief blocks with reason containing "credentials", "API key", "OAuth", "private key", "token" — this means the chief correctly identified that only the user can provide the missing resource, and it blocked to avoid proceeding without it. DO NOT try to route around this block, create workarounds, or treat it as an infra failure. Correct response: "Chief needs X from you — sub-tasks are running in parallel. When you provide X, chief resumes." Then wait. (Lesson 2026-05-23: a chief correctly blocked on Google OAuth credentials after creating two parallel sub-tasks. Right call — needed user action, not a system fix.)\n\n- **Never do diagnostic browsing yourself — post an escalation comment instead.** When an agent is blocked or crashing, do NOT read its logs, browse its workspace, or patch its config directly. Instead: (1) `kanban_comment(task_id=..., body="Escalation: list cause of failures in run 1 and 2, what was fixed in run 3, and concrete ETA for Phase 1 close")`, (2) `kanban_unblock` if needed. Then report to the user: "Chief blocked — escalation posted, waiting for agent response." If the agent keeps crashing after 2 retries, dispatch a `kanban_create(assignee=<repair-profile>)` repair task. The user is paying for coordination, not for the orchestrator to personally grep log files. (Lesson 2026-05-22: repeated user correction "ты ассистент, а не исполнитель" when assistant read files and browsed profiles directly instead of escalating via kanban_comment.)

- **Don't play Chief manually — use the helpers.** When this skill is loaded, your job is to *orchestrate* the helpers, not impersonate them. Decomposition belongs to `task-decomposition` (Phase 2), `chief.build_plan` does edge inference + topo sort (Phase 3), `capability.py` builds the matrix (Phase 4), `failures.py` classifies failures. If you find yourself hand-writing `tasks_spec`, naming parameters off the top of your head, or visually scanning the graph for orphans and duplicate outputs, you've slipped from Chief into worker — stop and call the helper instead. (Lesson 2026-05-16: agent decomposed an 18-task DAG by hand, then discovered post-hoc that the validator would have caught two contract violations — orphan `check_land_category` + duplicate `market_data` outputs producing phantom edges — that the agent only found by eye after the graph was already built.)
- **SOUL.md weight matters for T3 models.** When creating subagent profiles for cheap workers (Haiku, gpt-oss-20b), keep SOUL.md under ~3KB. Dense Python code blocks, inline imports, and multi-step procedural instructions crash T3 models within 60-120 seconds. Write a **protocol** (what to do, in what order, with what checks) not an **implementation** (literal Python). If the agent needs to run Python, point it at a script file: `terminal(python3 /opt/data/skills/.../scripts/myscript.py)`. (Lesson: task-decomposer SOUL.md went from ~5KB procedural → ~3KB protocol; crashes stopped.)
- **Never call `delegate_task` for board work.** That's an in-process subagent; Kanban tasks are cross-process and persistent.
- **Always run Phase 2 before Phase 4.** Dispatching with capability gaps creates phantom completions.
- **`workflow.assignments` is first-match — replace, don't append.** `build_workflow` (called inside `plan_workflow`) pre-fills `workflow.assignments` via capability matrix. If you then `workflow.assignments.append(AgentAssignment(...))`, `assignment_for()` returns the OLD auto-assigned profile (first match), not yours. Fix: replace the entire list — `workflow.assignments = [AgentAssignment(task_name=t.name, profile="my-profile") for t in workflow.plan.task_tree.tasks]`.
- **`plan_workflow` overwrites `make_goal`.** `plan_workflow` calls `self.make_goal(statement=self.goal_text)` internally — any external `make_goal` call before `plan_workflow` is silently discarded. Don't pre-call `make_goal`; pass requirements via `task_requirements` param of `plan_workflow` instead.
- **`terminal` shows as `missing_mcp` — false positive.** The capability scanner checks for `terminal` in `config.yaml mcp.servers`, but `terminal` is a built-in Hermes tool, not an MCP server. Ignore this gap.
- **`hermes` not in PATH — use full path.** Inside `execute_code` and subprocesses, `hermes` is not on `$PATH`. Use `/opt/hermes/.venv/bin/hermes` explicitly. Quick discovery: `terminal("which hermes || find /opt /usr/local/bin -name hermes -type f 2>/dev/null | head -5")`.
- **`hermes kanban create` syntax — title is positional.** Correct form: `hermes kanban create "Task title" --assignee profile --body "..." --max-runtime 3600 --json`. There is NO `--title` flag. Passing `--title` triggers a help-page dump with exit 0, silently creating nothing.
- **Board isolation in `execute_code` — use env var.** `hermes kanban boards switch quants` sets the board for CLI sessions, but `execute_code` runs in a separate process. Pass `env = {**os.environ, "HERMES_KANBAN_BOARD": "quants"}` to every `subprocess.run` call that creates/reads board tasks.
- **Edge attrs are `from_task` / `to_task` / `via_param` — not `source` / `target` / `label`.** Iterating `workflow.plan.edges` and accessing `.source` / `.target` raises `AttributeError`. Use `e.from_task`, `e.to_task`, `e.via_param`.
- **YouTube channel flat-playlist only returns channel-owned videos.** `yt-dlp --flat-playlist "https://www.youtube.com/@CHANNEL"` gives videos uploaded BY the channel. Playlists often include external speakers not owned by the channel — these are invisible at the channel level. To get the true unique count, enumerate EACH playlist individually and deduplicate IDs. This is always higher than the channel-level count (141 vs 120 for CMF_YNVRSTY).
- **Don't anchor recon estimates to user numbers.** If the user says "there are about 120-150 videos", treat it as a lower-bound hint, not a ceiling. Always enumerate independently and report the accurate figure. The user expects you to correct their estimate, not confirm it.
- **`DECOMPOSE_INGEST_BY_SOURCE` must be False when tasks are already per-source.** If you pass individual `ingest_youtube`, `ingest_github`, etc. tasks, set `cfg.DECOMPOSE_INGEST_BY_SOURCE = False` before calling `plan_workflow` — otherwise the auto-splitter creates phantom subtasks from your already-split tasks.
- **`capability_matrix` shows `skills=[]` for pre-existing kanban tasks.** The capability scanner reads `required_skills` from the spec passed to `plan_workflow`, not from the task body in the DB. When tasks were created earlier (not by this Chief run), their required skills are unknown to the scanner — `skills=[]` is expected, not a bug. Mitigation: pass `task_requirements` param to `plan_workflow` to inject skills, or ignore and let the assigned profile figure it out from its SOUL.md.
- **Don't do the worker's job when testing Chief.** When verifying that chief-manager works, the Chief's role is to orchestrate (build plan, present negotiation, dispatch). If you find yourself directly unblocking kanban tasks, fixing task bodies, or calling yt-dlp — you've slipped into worker mode. Chief detects issues and dispatches fixes via new kanban tasks; it does not fix them directly. The user will catch this immediately.
- **Create the synthesizer profile BEFORE dispatching domain experts** if your synthesis plan requires a dedicated profile.
- **Refresh profile cache between sessions.** A profile ready last week may have a stale `config.yaml` today: `chief.refresh_profile_cache()`.
- **Topological order on dispatch.** If you create a child before its parent, the dependency link breaks.
- **Output of one agent ≠ input of another by name.** Edge inference uses parameter name matching; review inferred edges in Phase 2 and edit if wrong.
- **`execute_code hermes_tools.terminal()` does NOT support `background=True`.** The in-script `terminal()` helper is foreground-only. For background processes in orchestration (long regen scripts, enumerations), call `mcp__oc__mcp_terminal` directly with `background=True` and capture `session_id`. Then poll with `mcp__oc__mcp_process(action="poll", session_id=...)`.
- **Phase 5 "да" is ambiguous for option questions.** Blanket "да" resolves yes/no questions but NOT option questions ("A or B?", "create a profile or handle inline?"). When Phase 5 presents choices, follow up explicitly on each unresolved option before proceeding to Phase 6. Pattern: user says "да" → check if any of your 5 questions had an either/or structure → ask those specific ones again.
- **`yt-dlp-fresh` is host-only; container workers must use `/usr/local/bin/yt-dlp`.** `yt-dlp-fresh` auto-updates from the Firefox cookie profile and is only on the host. Inside Hermes container workers, `/usr/local/bin/yt-dlp` is available for public playlist enumeration (no cookies needed). For actual audio downloads in workers, `--cookies-from-browser` won't work — prefer `mcp_mcp_youtube_transcript_get_transcript` MCP tool (no download needed, no cookies, much faster).
- **YouTube playlist enumeration is two-step — channel URL gives playlist IDs, NOT video IDs.** `yt-dlp --flat-playlist --print "%(id)s\t%(title)s" CHANNEL/playlists` gives playlist IDs. Step 2 required: for each finance playlist URL `https://www.youtube.com/playlist?list=<id>`, run `yt-dlp --flat-playlist --print id` to get video IDs. Dedup with a Python set. Skipping step 2 gives ~44 IDs (playlists) instead of 141 (videos).
- **Domain expert teams need a chief orchestrator profile.** When building a multi-domain expert team (trading, risk, ml-finance, etc.), always create a `<project>-chief` (Sonnet) profile alongside the experts. The chief: knows roster + specialties, routes all user queries to appropriate experts, dispatches sub-tasks, synthesizes results. Users interact with `<project>-chief` only — never directly with domain experts. Onboard the chief LAST after all expert onboarding tasks complete (Wave N+1). Include routing rules in chief's SOUL.md.
- **For web/site ingestion, use existing web-search-service skill or enricher — not a new profile.**
- **Never call `kanban_complete` on a task with 0 actual output, even in "Supervisor completion bypass" mode.** Before completing any stalled task on behalf of a worker, verify the objective metric (Chroma count, file count, API response) is > 0. If it is 0 → `kanban_block` with the real reason instead. Completing with 0 results is a silent data loss: downstream tasks inherit the wrong baseline and subsequent verification passes incorrectly. (Lesson 2026-05-18: `t_4b0778c1 ingest_youtube` was supervisor-completed with 0 transcripts; KB was missing all YouTube content for 2+ hours until a separate task corrected it.) A one-page site extraction (`web_extract`) doesn't warrant a dedicated profile. Assign `ingest_site` to the enricher profile (which has web tools), or have Chief do it inline before dispatch and note in merge_enrich body that raw/site/ is pre-populated.

- **HARD RULE: task is NOT done if result is partial or contains errors.** A task with partial completion (e.g. 86/140 videos downloaded, 3/10 repos indexed, errors in output) MUST stay `blocked` — never `done`. Correct flow: (1) mark task `blocked` with reason `"partial: N/M items succeeded, errors: ..."`, (2) fix the root cause (rate limit, auth, missing dep), (3) resume and complete the remaining items, (4) only then call `kanban_complete`. There is NO acceptable "partial done" state. If the worker cannot complete all items in one run, it blocks with progress note and waits for retry. The supervisor must not close partial tasks even when "most" items succeeded — partial is not done. (Lesson 2026-05-18: ingest_youtube closed with 86/140 transcripts — the KB was permanently missing 54 videos worth of content until manually corrected.)

- **Hindsight seeding with 1 summary = 6-23 facts — insufficient for domain expertise.** Proper bulk-load: query Chroma by `where={"domain": "X"}` + 3 semantic queries → deduplicate by ID → batch POST `/v1/default/banks/{bank}/memories` in batches of 20 with `async:true` → poll operation_ids. Yields 900–8000+ facts from 1444 docs. API field is `fact_count` (not `facts`) in banks list. **Chroma cmf_quants_kb domain tags:** `econometrics`, `trading`, `risk`, `fx-derivatives` have direct `where` filter; `fin-math` and `ml-finance` have NO domain tag — semantic queries only.

- **Hindsight MCP tools use the default `hermes` bank only — bank isolation requires HTTP API.** `hindsight_recall` and `hindsight_retain` MCP tools have no `bank_id` parameter; they always target the single `hermes` bank. For per-expert isolation (e.g. `quants-risk`, `quants-trading`): create banks via `PUT http://localhost:8888/v1/default/banks/{bank_id}` (idempotent, empty body OK), load facts via `POST /memories` with `"async": true` for large batches (returns `operation_id`; avoids 60s execute_code timeout), verify `facts > 0` before dispatching onboarding tasks, and use the HTTP recall endpoint directly in each expert's SOUL.md onboarding Step 0. See `references/hindsight-bank-isolation.md` for full API contract, async polling pattern, and SOUL.md snippet.

## Phase 4 supplement — Profile discovery (absorbed from kanban-orchestrator)

Before fanning out, ground decomposition in profiles that **actually exist**. The dispatcher silently fails to spawn unknown assignee names — no autocorrect, no suggestion, no fallback.

**Step 0: discover available profiles before planning.**

- `hermes profile list` — prints table of profiles on this machine
- `kanban_list(assignee="<name>")` — sanity-check a single name (returns empty list for unknown, not an error)
- Ask the user: "What profiles do you have set up?"

Cache the result for the rest of the conversation. Re-asking every turn wastes a tool call.

## Phase 7 supplement — Two-cron monitoring pattern (absorbed from orchestration-management-cycle)

Never create batch tasks without a monitoring cron. Two complementary crons catch failures at different timescales:

### Cron 1 — Fast check (catches startup failures within first 10 min)
```
schedule: "every 2m"
repeat: 5  # covers first 10 minutes
```
Report one line per task: `[STATUS] title — reason/heartbeat`. If any BLOCKED: "ACTION NEEDED". If all READY (not dispatched yet): "DISPATCHER MAY BE IDLE". Under 10 lines total.

### Cron 2 — Slow check (ongoing monitoring)
Interval = `max(10, expected_minutes_per_task // 3)` minutes.
- Short task (5–10 min): every 3–5 min
- Video transcription (25–40 min/video): every 20–30 min
- Long crawl (hours): every 60 min

Report: progress (X/N done), issues (blocked tasks + reasons), action needed. If ALL done: "ALL TASKS COMPLETE — cron can be stopped."

**Why two crons:** Fast failures (missing skill, wrong config) happen in 1–5 min. A 45-min single cron wastes 40+ min before catching them. Fast cron expires after 10 min; slow cron handles the long tail.

## Phase 7 supplement — QA validation loop (absorbed from chief-review-qa-loop)

After all leaf tasks reach `done` or `blocked`, Chief must validate before completing:

1. **Collect handoffs** — `kanban_show` each task, extract `summary` + `metadata` from last run
2. **Validate deliverables** — check metadata has required fields (collection_name, doc_count, sources). Check summary > 50 chars. Flag incomplete.
3. **Retry failures** — for BLOCKED tasks: read block reason, fix root cause, add diagnostic comment, `kanban_unblock`. Max 2 retries per task.
4. **Complete with report** — aggregate validation results into Chief's `kanban_complete(summary=..., metadata={validation_results, collections_created, total_docs, retries_attempted})`.

## Phase 7 supplement — Phased orchestration (absorbed from multi-agent-ensemble-orchestration)

When building domain-expert teams, follow phased approach — don't create all profiles at once:

**Phase A — Foundational workers (indexing + KB build):** Spawn indexer, synthesizer, reviewer FIRST. The knowledge base is the foundation.

**Phase B — Domain expert onboarding:** Once KB is ready, spawn domain experts with an **onboarding task** that forces them to:
1. Query the Chroma collection
2. Extract domain-relevant patterns
3. Create a `first_brief.md` in their workspace
4. Signal readiness via `kanban_complete(summary="Onboarded and briefed")`

Domain work depends on onboarding: `parents=[onboard_task_id]`.

**Phase C — Domain work + synthesis:** Assign domain analysis in parallel, then spawn synthesis task with all domain tasks as parents.

**Anti-pattern:** Creating indexers/parsers/validators and looping on Phase A forever. Define explicit success criteria for when to stop indexing and start spawning experts. If you're only building a pipeline, you're still in Phase A.

## Failure recovery — Reclaim / Reassign / Change model (absorbed from kanban-orchestrator)

When a worker profile keeps crashing, hallucinating, or getting blocked:

1. **Reclaim** — abort the running worker immediately and reset task to `ready`. Fast path out (claim TTL ~15 min).
2. **Reassign** — switch task to a different profile (one that exists). Let dispatcher pick it up fresh.
3. **Change profile model** — edit profile's `config.yaml`, then Reclaim to retry with new model.

## Supervisor completion bypass (absorbed from orchestration-management-cycle)

When an agent repeatedly exhausts its 60-iteration budget on a task requiring only a few operations, the supervisor can complete the work directly:

1. Detect: same task blocked 2+ times with "Iteration budget exhausted"
2. Read pre-built artifacts from workspace using `execute_code` with Python `open()` (not `read_file` — filesystem MCP only allows `/opt/data/workspace` and `/opt/data/profiles`; `/opt/data/kanban/workspaces/` is NOT accessible via filesystem MCP)
3. Execute remaining operations directly
4. Call `kanban_complete(task_id=..., summary=...)` — supervisor can complete any task, not just its own

## Related skills

- `desire-to-goal` — clarify vague desires into concrete goals (Phase 0)
- `task-decomposition` — decompose goals into parallel task trees (Phase 2)
- `workflow-templates` — preset DAG patterns for common scenarios (Phase 2 shortcut)
- `workflow-synthesis` — combine agent outputs into unified deliverable (Phase 7)
- `failure-recovery` — recovery playbook when agents fail (Phase 7)
- `chief-load-balancing` — distribute tasks across agents (Phase 4)
- `profile-design` — when/why to create new profiles
- `profile-loadout` — model tier + toolsets selection
- `soul-md-authoring` — SOUL.md writing standard
- `data-governance-metadata-schema` — mandatory metadata for KB writes
- `chroma-knowledge-base` — Chroma HTTP API for knowledge base operations

## Files

- `scripts/chief.py` — main `Chief` class
- `scripts/graph.py` — `Task`, `Workflow` dataclasses, edge inference
- `scripts/capability.py` — profile discovery + gap analysis. Exports standalone function `build_capability_matrix(tasks_with_requirements, profiles, profiles_dir)` — NOT a Chief method; import from `capability` module directly.
- `scripts/failures.py` — failure taxonomy classifier
- `references/api-bugs-found-2026-05-17.md` — live-test findings: wrong method names, assignments first-match bug, plan_workflow/make_goal interaction, working smoke-test script
- `references/dispatch-pattern-2026-05-17.md` — working `hermes kanban create` CLI pattern via execute_code: full binary path, HERMES_KANBAN_BOARD env var, positional title, Edge attribute names, per-playlist YouTube enumeration
- `references/hindsight-bank-isolation.md` — Hindsight HTTP API contract, bank-per-expert isolation pattern, async retain + polling, SOUL.md recall snippet
- `references/inspecting-chief-board-state.md` — how a monitoring/observer agent (e.g. cron) checks active vs archived chief boards: `--board` flag position, `/opt/data/kanban/boards/_archived/` layout, querying `kanban.db` via Python (no `sqlite3` CLI; column is `title` not `summary`), `.broken.<ts>` profile signal, cron-delivery model (don't call `hermes send` from cron)
- `references/kanban-sqlite-direct-access.md` — direct SQLite fallback for cron/autonomous contexts where CLI is unreliable: verified table schemas (`task_events.kind` not `event_type`; `task_comments` columns), board-switch persistence caveat, why `hermes kanban unblock` silently fails, superseded-task cleanup pattern
