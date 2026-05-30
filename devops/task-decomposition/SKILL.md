---
name: task-decomposition
description: "Decompose a clarified Goal (with subgoals) into a parallel TaskTree + Plan (DAG with topo order). Pure WHAT layer — does NOT touch agents, profiles, MCP servers. Mirrors EvoAgentX's TaskPlanner stage. Use after desire-to-goal, before chief-manager capability matching. Two modes: self (you run prompts in your own context) and subagent (delegate to a task-decomposer profile via Kanban)."
metadata:
  hermes:
    tags: [decomposition, planning, dag, task-tree, plan, what-layer]
    category: devops
    related_skills: [chief-manager, desire-to-goal, workflow-templates]
---

# Task Decomposition

Convert a clarified `Goal` (output of `desire-to-goal`) into a `TaskTree` and a `Plan` (DAG with topological order). This skill answers **WHAT** to do and in **what order**, not **WHO** does it.

```
Layer:         desire → goal+subgoals → task tree → plan      → workflow → dispatch
Owner:         user     desire-to-goal   THIS SKILL  THIS SKILL  chief-mgr  chief-mgr
```

This skill returns objects compatible with `chief-manager/scripts/graph.py` (`Task`, `TaskTree`, `Plan`). It never invents agent assignments or capability matrices — that's the next layer.

## When to load

- After `desire-to-goal` produced a `goal.json` with non-empty `subgoals`
- Before `chief-manager` builds the capability matrix
- Standalone: when you need a validated DAG plan and don't care about agent assignment yet

**Before decomposing from scratch, check `workflow-templates` for a matching pattern.** If the goal matches research pipeline, indexing pipeline, expert ensemble, or audit, adapt the template instead of building the DAG from zero.

## Protocol — 5 phases inside this skill

```
Phase 1 — Decompose:  goal+subgoals → tasks_spec  (LLM call OR subagent)
Phase 2 — Validate:   tasks_spec → errors[]       (unique outputs, orphans, refs)
Phase 3 — Build:      tasks_spec → TaskTree + Plan (chief-manager graph)
Phase 4 — Retry:      if errors → re-decompose with `suggestion=...` (EvoAgentX-style)
Phase 5 — Repair:     fix broken task_tree.json inline (validate → patch → re-validate)
```

### Phase 5 — Repair an existing broken TaskTree

When a `task_tree.json` already exists but fails validation (e.g. from a previous session or a stale decomposition), **repair it in place** rather than re-decomposing from scratch. Re-decomposition loses the human/LLM intent captured in task names and descriptions; repair preserves it.

```python
# 1. Load existing task_tree + goal
# 2. Run validate_tasks_spec(tasks, goal) — get error list
# 3. Fix errors with targeted patches:
#    - Duplicate outputs → rename with domain prefix
#    - SubgoalIdMismatch → map old IDs to declared IDs
#    - OrphanRoot → add outputs as inputs to logically-related tasks
# 4. Re-validate until 0 errors
# 5. Rebuild edges + topo order (Kahn's algorithm or graph.py)
# 6. Overwrite task_tree.json, plan.json, plan.dot
```

See `references/repair-recipes.md` for worked examples of each fix type.

## Two execution modes

### Mode A — `self`: you decompose in your own LLM context

Use when the goal is simple, when you don't need persistence, or for testing.

```python
import sys
sys.path.insert(0, '/opt/data/skills/devops/task-decomposition/scripts')
from decomposer import build_decomposition_prompt, parse_decomposition_response, build_tasktree_and_plan
from validator import validate_tasks_spec

# Step 1: build a prompt for yourself
prompt = build_decomposition_prompt(goal_dict)
# (now YOU, the agent, produce tasks_spec_json following the prompt)

# Step 2: parse YOUR output back into Python objects
tasks_spec = parse_decomposition_response(tasks_spec_json)

# Step 3: validate before building
errors = validate_tasks_spec(tasks_spec, goal_dict)
if errors:
    # Re-prompt yourself with suggestion=errors
    ...

# Step 4: build TaskTree + Plan via chief-manager dataclasses
tree, plan = build_tasktree_and_plan(goal_dict, tasks_spec)
```

### Mode B — `subagent`: delegate to `task-decomposer` profile via Kanban

Use for non-trivial goals where you want a separate agent context and a Kanban audit trail.

```python
from decomposer import decompose_via_subagent_spec

# Returns a KanbanCreateSpec dict
spec = decompose_via_subagent_spec(goal_dict, workspace_path='/opt/data/workspace/<topic>/')
# Agent calls:
result = kanban_create(**spec)   # subagent runs, writes tasks_spec to metadata
# Then poll kanban_show(task_id=result['id']) until done
# Read tasks_spec from result['metadata']['tasks_spec']
# Continue with Phase 2-4 same as mode A
```

The `task-decomposer` profile lives at `/opt/data/profiles/task-decomposer/` and is just an executor of this skill in subagent form.

## Hard rules of decomposition

These must hold or the validator fails:

1. **Unique output parameter names across the whole graph.** If two tasks both emit `market_data`, edge inference will create phantom edges. Use specific names: `tourist_demand_data`, `rental_market_data`, `sale_market_data`.
2. **Every input must have a producing output OR be marked as `external`.** Otherwise the task is unreachable.
3. **Every task must belong to exactly one declared `subgoal_id`.**
4. **No task is an orphan** (out-degree 0 AND in-degree 0) unless it's a single-task plan.
5. **Names are slug-cased**: `[a-z0-9_]+`, ≤ 50 chars, unique.
6. **Description ≥ 20 chars and ≤ 500 chars.**
7. **DAG must be acyclic** (Kahn topo sort succeeds).

## Anti-patterns

| Pattern | Symptom | Fix |
|---|---|---|
| **SequentialDegeneration** | All tasks in one chain `A→B→C→D` with no parallelism | Re-decompose: independent research lines should be siblings, not a chain |
| **GenericOutputNames** | `data`, `result`, `output`, `info` appearing in outputs | Rename with domain prefix |
| **PhantomInput** | Input named in task but no other task produces it | Mark as `external` OR add a producer task |
| **SubgoalLeakage** | Task description mentions agents/profiles/tools | Move that detail to Phase 4 (capability matrix), keep WHAT pure |
| **MegaTask** | A single task encapsulates 3+ distinct operations | Split — atomic responsibilities only |
| **SubgoalIdMismatch** | Task's `subgoal_id` (e.g. `SG-A`) doesn't match any goal-declared subgoal (e.g. `context`) | Map old IDs → declared: `SG-A→sg_context`, `SG-B→sg_research`, `SG-C→sg_options`, `SG-D→sg_decision`, `SG-E→sg_plan`. Common when decomposer invents its own subgoal labels. |
| **DuplicateOutputs** | Two+ tasks emit the same output name (e.g. `market_data` × 3) | Rename with domain prefix: `tourist_demand_data`, `rental_market_data`, `sale_market_data`. Same for `option_economics` → `option_a_economics`..`option_e_economics`. |
| **OrphanRoot** | Task with no incoming OR outgoing edges (in multi-task plan) | Either remove or wire it into the graph via proper I/O. Technique: find tasks whose domain logically consumes the orphan's outputs, add those outputs as inputs. |

## Retry loop (EvoAgentX pattern)

```python
def decompose_with_retry(goal, max_retries=2):
    history, suggestion = "", ""
    for attempt in range(max_retries + 1):
        prompt = build_decomposition_prompt(goal, history=history, suggestion=suggestion)
        # agent produces response
        tasks_spec = parse_decomposition_response(response)
        errors = validate_tasks_spec(tasks_spec, goal)
        if not errors:
            return build_tasktree_and_plan(goal, tasks_spec)
        # Build feedback for next attempt
        history = f"Previous attempt #{attempt + 1} produced {len(tasks_spec)} tasks"
        suggestion = "Fix these issues:\n" + "\n".join(f"- {e}" for e in errors)
        time.sleep(2 ** attempt)  # exponential backoff
    raise ValueError(f"Decomposition failed after {max_retries + 1} attempts: {errors}")
```

## Output contract

Final return value of `build_tasktree_and_plan(goal, tasks_spec)`:

```python
(
    TaskTree(goal=..., tasks=[Task(...), ...]),   # from chief-manager.graph
    Plan(task_tree=..., edges=[Edge(...)], topo_order=[...])
)
```

Save to disk via `save_artifacts(workspace_path, tree, plan)` — creates `task_tree.json`, `plan.json`, and `plan.dot` (Graphviz visualization).

## Files

- `scripts/decomposer.py` — prompt builders, parsers, retry loop, builder
- `scripts/validator.py` — pre-build validation (unique outputs, orphans, naming)
- `references/prompts.md` — LLM prompt templates (self-mode + subagent-mode)
- `references/patterns.md` — common DAG patterns (research-pipeline, gather-compare-decide, parallel-experts)
- `references/examples.md` — 3 worked examples with full tasks_spec JSON

## Pitfalls

- **Don't enrich the prompt with agent info.** Goal+subgoals only. The whole point is decoupling.
- **Don't skip validation before building.** `Plan.from_task_tree()` will silently produce a broken graph if outputs aren't unique — it won't error, it'll just create phantom edges.
- **Don't try to use this skill on a vague goal.** First run `desire-to-goal` until confidence ≥ 0.7. Phantom decomposition = phantom completion downstream.
- **Don't merge Phase 4 (retry) with chief-manager's failure recovery.** This retry is for decomposition mistakes; chief-manager's `failures.py` is for execution failures.
- **Don't re-decompose when repair is cheaper.** If a task_tree.json exists and the task names/descriptions capture real intent, use Phase 5 (Repair) to fix validation errors inline. Re-decomposition throws away that intent.
- **Subgoal count may need expanding.** If the goal declares 4 subgoals but the DAG naturally groups into 6 parallelism clusters, expand the goal's subgoals to match. Subgoals should reflect DAG structure, not arbitrary categories. Update `goal_with_subgoals.json` before running the validator.
- **When renaming duplicate outputs, update ALL consumers.** A rename of `market_data` → `rental_market_data` requires updating every task that consumed `market_data` from that specific producer. Miss one → phantom input error or silent data mismatch.
