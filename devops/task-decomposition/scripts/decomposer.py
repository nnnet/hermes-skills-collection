"""
Task Decomposition — turn a clarified Goal into a validated TaskTree + Plan (DAG).

This module is the WHAT-layer. It does NOT know about agents, profiles, or MCP servers.
Output objects are compatible with chief-manager/scripts/graph.py.

Pipeline:
    Goal (with subgoals)
        → build_decomposition_prompt()                 # LLM input
        → (agent produces tasks_spec JSON)
        → parse_decomposition_response()               # JSON → list[dict]
        → validate_tasks_spec()                        # hard rules
        → build_tasktree_and_plan()                    # → TaskTree + Plan
        → save_artifacts()                             # task_tree.json + plan.json + plan.dot
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Import chief-manager graph dataclasses (re-exported for caller convenience)
_CHIEF_MANAGER_SCRIPTS = "/opt/data/skills/devops/chief-manager/scripts"
if _CHIEF_MANAGER_SCRIPTS not in sys.path:
    sys.path.insert(0, _CHIEF_MANAGER_SCRIPTS)

from graph import (  # noqa: E402
    Goal, Subgoal, Task, TaskParam, TaskTree, Plan, Edge,
)


# ============================================================
# Phase 1 — Prompt builder (for self-mode)
# ============================================================

DECOMPOSITION_PROMPT_TEMPLATE = """\
You are a task-decomposition specialist. Decompose the goal below into a DAG of
concrete tasks with explicit inputs/outputs. Output VALID JSON only — no prose,
no markdown fence, no commentary.

# Goal
{goal_statement}

# Success criteria
{success_criteria}

# Constraints
{constraints}

# Out of scope
{out_of_scope}

# Subgoals (each task MUST belong to one)
{subgoals_block}

# Hard rules
1. Output parameter names MUST be unique across ALL tasks. If two tasks would
   produce the same kind of data, give them distinct names with a domain prefix
   (e.g. `tourist_demand_data`, `rental_market_data` — never both `market_data`).
2. Every task input must either match an output of another task (case-sensitive)
   OR be flagged as `"type": "external"` for inputs that come from outside the graph.
3. Each task name is slug-cased: lowercase, digits, underscores only, ≤ 50 chars.
4. Each task description is 20–500 chars, plain text, in the same language as
   the goal statement.
5. Aim for PARALLELISM: independent research/data-gathering tasks should be
   siblings (no edges between them), not a chain.
6. DO NOT mention agents, profiles, MCP servers, tool names, or implementation
   details. Stay at the WHAT level.
7. DO NOT create mega-tasks. If a task description contains "and" linking 3+
   distinct operations, split it.

# Required output shape

```json
{{
  "tasks": [
    {{
      "name": "slug_name",
      "description": "What this task produces. Concrete, atomic.",
      "subgoal_id": "<one of the subgoal ids above>",
      "inputs": [
        {{"name": "param_name", "type": "any|external", "description": "..."}}
      ],
      "outputs": [
        {{"name": "unique_output_name", "type": "any", "description": "..."}}
      ],
      "priority": 0
    }}
  ]
}}
```

{history_block}{suggestion_block}

Produce the JSON now."""


def build_decomposition_prompt(
    goal: dict,
    history: str = "",
    suggestion: str = "",
) -> str:
    """Render the decomposition prompt from a Goal dict.

    `goal` accepts both raw dicts (from desire-to-goal goal.json) and Goal.to_dict()
    output. Required keys: statement, success_criteria, constraints, out_of_scope, subgoals.
    """
    subgoals = goal.get("subgoals") or []
    if not subgoals:
        # Synthesize a single catch-all subgoal so tasks have something to reference
        subgoals = [{"id": "main", "description": goal.get("statement", "")}]

    subgoals_block = "\n".join(
        f"- id: `{sg['id']}` — {sg.get('description', '')}"
        for sg in subgoals
    )

    criteria = goal.get("success_criteria") or []
    criteria_block = "\n".join(f"- {c}" for c in criteria) or "- (none specified)"

    constraints = goal.get("constraints") or []
    constraints_block = "\n".join(f"- {c}" for c in constraints) or "- (none specified)"

    oos = goal.get("out_of_scope") or []
    oos_block = "\n".join(f"- {c}" for c in oos) or "- (none specified)"

    history_block = f"\n# Previous attempt\n{history}\n" if history else ""
    suggestion_block = (
        f"\n# Required fixes for this attempt\n{suggestion}\n" if suggestion else ""
    )

    return DECOMPOSITION_PROMPT_TEMPLATE.format(
        goal_statement=goal.get("statement", "(no statement)"),
        success_criteria=criteria_block,
        constraints=constraints_block,
        out_of_scope=oos_block,
        subgoals_block=subgoals_block,
        history_block=history_block,
        suggestion_block=suggestion_block,
    )


# ============================================================
# Phase 1b — Response parser
# ============================================================

def parse_decomposition_response(text: str) -> list[dict]:
    """Extract tasks_spec list from a model response.

    Tolerates: bare JSON, ```json fences, leading/trailing prose, BOM.
    Returns: list of task dicts. Raises ValueError with a precise diagnosis
    if parsing fails — call sites should catch and feed to the retry loop.
    """
    if not text or not text.strip():
        raise ValueError("Empty decomposition response")

    cleaned = text.strip().lstrip("\ufeff")

    # Strip ```json ... ``` fences (greedy match the last closing fence)
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()

    # If still surrounded by prose, find the first { and matching last }
    if not cleaned.startswith("{"):
        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first == -1 or last == -1 or last < first:
            raise ValueError(f"No JSON object in response (first 200 chars): {cleaned[:200]!r}")
        cleaned = cleaned[first : last + 1]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON decode failed at {e.lineno}:{e.colno} — {e.msg}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Top-level JSON must be object, got {type(data).__name__}")

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("Response missing 'tasks' array")
    if not tasks:
        raise ValueError("Response contains zero tasks — decomposition is empty")

    # Light schema check (deeper validation in validator.py)
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            raise ValueError(f"Task #{i} is not an object")
        for required in ("name", "description"):
            if required not in t:
                raise ValueError(f"Task #{i} missing required field {required!r}")

    return tasks


# ============================================================
# Phase 3 — Builder (tasks_spec → TaskTree + Plan)
# ============================================================

def _coerce_goal(goal: dict) -> Goal:
    """Convert a Goal dict (from desire-to-goal) into chief-manager Goal dataclass."""
    subgoals = [
        Subgoal(id=sg["id"], description=sg.get("description", ""))
        for sg in (goal.get("subgoals") or [])
    ]
    return Goal(
        statement=goal.get("statement", ""),
        success_criteria=list(goal.get("success_criteria") or []),
        deliverable_format=goal.get("deliverable_format", ""),
        out_of_scope=list(goal.get("out_of_scope") or []),
        constraints=list(goal.get("constraints") or []),
        subgoals=subgoals,
    )


def _coerce_params(params: list, kind: str) -> list[TaskParam]:
    """Convert input/output dicts into TaskParam objects."""
    result = []
    for p in params or []:
        if isinstance(p, str):
            result.append(TaskParam(name=p))
        elif isinstance(p, dict):
            if "name" not in p:
                raise ValueError(f"{kind} param missing 'name': {p!r}")
            result.append(TaskParam(
                name=p["name"],
                description=p.get("description", ""),
                type=p.get("type", "any"),
            ))
        else:
            raise ValueError(f"{kind} param must be str or dict, got {type(p).__name__}")
    return result


def build_tasktree_and_plan(
    goal: dict,
    tasks_spec: list[dict],
) -> tuple[TaskTree, Plan]:
    """Build TaskTree + Plan from a goal dict and validated tasks_spec.

    Caller must run validate_tasks_spec() FIRST. This function will raise on
    invalid input (e.g. cycles) but doesn't re-run business validation.
    """
    goal_obj = _coerce_goal(goal)

    tasks: list[Task] = []
    for spec in tasks_spec:
        # Skip "external" inputs entirely from Task.inputs — they don't participate
        # in edge inference. We keep them in the spec for documentation but not
        # as TaskParam, otherwise Plan would think there's a phantom producer.
        raw_inputs = spec.get("inputs", [])
        non_external = [p for p in raw_inputs if not (isinstance(p, dict) and p.get("type") == "external")]

        tasks.append(Task(
            name=spec["name"],
            description=spec["description"],
            reason=spec.get("reason", ""),
            inputs=_coerce_params(non_external, "input"),
            outputs=_coerce_params(spec.get("outputs", []), "output"),
            subgoal_id=spec.get("subgoal_id"),
            max_runtime_seconds=spec.get("max_runtime_seconds"),
            priority=spec.get("priority", 0),
        ))

    tree = TaskTree(goal=goal_obj, tasks=tasks)
    tree_errors = tree.validate()
    if tree_errors:
        raise ValueError(f"TaskTree validation failed: {tree_errors}")

    plan = Plan.from_task_tree(tree)
    plan_errors = plan.validate()
    if plan_errors:
        # Orphan errors are caller-policy: raise with details, let them decide
        raise ValueError(f"Plan validation failed: {plan_errors}")

    return tree, plan


# ============================================================
# Phase 4 — Save artifacts
# ============================================================

def save_artifacts(
    workspace_path: str,
    tree: TaskTree,
    plan: Plan,
) -> dict[str, str]:
    """Save task_tree.json, plan.json, and plan.dot to workspace.

    Returns: dict[kind, path].
    """
    p = Path(workspace_path)
    p.mkdir(parents=True, exist_ok=True)

    tree_path = p / "task_tree.json"
    plan_path = p / "plan.json"
    dot_path = p / "plan.dot"

    tree_dict = {
        "goal": tree.goal.to_dict(),
        "tasks": [t.to_dict() for t in tree.tasks],
    }
    with open(tree_path, "w", encoding="utf-8") as f:
        json.dump(tree_dict, f, ensure_ascii=False, indent=2)

    plan_dict = {
        "goal_statement": plan.task_tree.goal.statement,
        "task_count": len(plan.task_tree.tasks),
        "edge_count": len(plan.edges),
        "topo_order": list(plan.topo_order),
        "edges": [e.to_dict() for e in plan.edges],
        "waves": _compute_waves(plan),
    }
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan_dict, f, ensure_ascii=False, indent=2)

    with open(dot_path, "w", encoding="utf-8") as f:
        f.write(render_dot(plan))

    return {
        "task_tree": str(tree_path),
        "plan": str(plan_path),
        "dot": str(dot_path),
    }


def _compute_waves(plan: Plan) -> list[list[str]]:
    """Group topo-sorted tasks by parallel-execution wave."""
    levels: dict[str, int] = {}
    for name in plan.topo_order:
        parents = plan.parents_of(name)
        levels[name] = 1 + max((levels[p] for p in parents), default=-1)

    waves: dict[int, list[str]] = {}
    for name, lvl in levels.items():
        waves.setdefault(lvl, []).append(name)
    return [sorted(waves[lvl]) for lvl in sorted(waves)]


def render_dot(plan: Plan) -> str:
    """Produce Graphviz .dot representation for visualization."""
    lines = ["digraph plan {", "  rankdir=TB;", "  node [shape=box, style=rounded];"]
    for t in plan.task_tree.tasks:
        label = t.name.replace('"', r'\"')
        lines.append(f'  "{t.name}" [label="{label}"];')
    for e in plan.edges:
        elabel = e.via_param.replace('"', r'\"')
        lines.append(f'  "{e.from_task}" -> "{e.to_task}" [label="{elabel}"];')
    lines.append("}")
    return "\n".join(lines)


# ============================================================
# Mode B — Subagent dispatch helper
# ============================================================

def decompose_via_subagent_spec(
    goal: dict,
    workspace_path: str,
    priority: int = 5,
    max_runtime_seconds: int = 1800,
) -> dict:
    """Build a KanbanCreateSpec dict for delegating decomposition to task-decomposer.

    Returns a dict ready to pass into kanban_create(**spec). The agent calls
    kanban_create itself — this function never touches MCP tools.
    """
    body = _render_subagent_body(goal, workspace_path)
    statement_short = (goal.get("statement") or "")[:60].rsplit(" ", 1)[0]
    return {
        "title": f"Decompose: {statement_short}",
        "assignee": "task-decomposer",
        "body": body,
        "priority": priority,
        "max_runtime_seconds": max_runtime_seconds,
        "skills": ["task-decomposition"],
        "workspace_kind": "dir",
        "workspace_path": workspace_path,
        "idempotency_key": f"decompose-{abs(hash(goal.get('statement', ''))) % 10**12}",
    }


def _render_subagent_body(goal: dict, workspace_path: str) -> str:
    return f"""# Decomposition task

## Goal
{goal.get('statement', '')}

## Success criteria
{chr(10).join('- ' + c for c in (goal.get('success_criteria') or []))}

## Constraints
{chr(10).join('- ' + c for c in (goal.get('constraints') or []))}

## Subgoals
{chr(10).join('- id `' + sg['id'] + '`: ' + sg.get('description', '') for sg in (goal.get('subgoals') or []))}

## Instructions for you (task-decomposer)

1. Load skill `skill_view(name="task-decomposition")`.
2. Read the goal at `{workspace_path}/goal.json` for full context.
3. Call `build_decomposition_prompt(goal)` and produce the JSON yourself.
4. Call `validate_tasks_spec(tasks_spec, goal)`. If errors:
   - Re-decompose with the errors as `suggestion`.
   - Retry up to 2 times. If still failing → `kanban_block(reason='decomposition errors: ...')`.
5. Call `build_tasktree_and_plan(goal, tasks_spec)` and `save_artifacts(workspace_path, tree, plan)`.
6. `kanban_complete(summary=..., metadata={{"tasks_spec": [...], "task_count": N, "edge_count": M, "wave_count": K, "artifacts": {{...}}}})`

## Hard rules (recap)
- Unique output parameter names across ALL tasks
- No mention of agents, profiles, or MCP servers in task descriptions
- Aim for MAX parallelism — siblings, not chains
- Each input either matches another task's output or is `"type": "external"`
"""


# ============================================================
# Retry loop (EvoAgentX pattern)
# ============================================================

def execute_with_retry(
    operation_name: str,
    operation,
    retries_left: int = 1,
    backoff_base: float = 2.0,
    **kwargs,
) -> tuple[Any, int]:
    """Generic retry wrapper with exponential backoff.

    Returns: (result, attempts_consumed).
    Raises ValueError after `retries_left + 1` failed attempts.
    """
    last_err: Optional[Exception] = None
    for attempt in range(retries_left + 1):
        try:
            return operation(**kwargs), attempt
        except Exception as e:
            last_err = e
            if attempt == retries_left:
                break
            sleep_time = backoff_base ** attempt
            time.sleep(min(sleep_time, 30.0))
    raise ValueError(
        f"{operation_name} failed after {retries_left + 1} attempts. Last error: {last_err}"
    )


__all__ = [
    "build_decomposition_prompt",
    "parse_decomposition_response",
    "build_tasktree_and_plan",
    "save_artifacts",
    "render_dot",
    "decompose_via_subagent_spec",
    "execute_with_retry",
]
