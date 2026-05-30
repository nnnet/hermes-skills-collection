"""
Validator for tasks_spec — runs BEFORE build_tasktree_and_plan.

Returns a list of human-readable error strings. Empty list = pass.

Why pre-validate instead of relying on TaskTree.validate() / Plan.validate():
- Plan.from_task_tree() will silently create phantom edges when two tasks
  share an output name. The graph builder doesn't error; the graph is wrong.
- Subgoal references need to be checked against the goal's declared subgoals.
- Naming conventions and anti-patterns (mega-tasks, solution leakage, generic
  output names) are domain rules the graph builder doesn't enforce.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

SLUG_RE = re.compile(r"^[a-z0-9_]+$")
NAME_MAX = 50
DESC_MIN = 20
DESC_MAX = 500

GENERIC_OUTPUT_NAMES = {
    "data", "result", "output", "info", "value", "item", "content", "text",
    "response", "payload", "thing", "stuff",
}

# Words that suggest a task description is leaking implementation details
SOLUTION_LEAKAGE_PATTERNS = [
    r"\bagent\b", r"\bsubagent\b", r"\bprofile\b",
    r"\bMCP\b", r"\bkanban\b", r"\bcron\b",
    r"\bclaude\b", r"\bgpt\b", r"\bllm\b",
    r"\bdocker\b", r"\bcurl\b", r"\bplaywright\b",
]
SOLUTION_LEAKAGE_RE = re.compile("|".join(SOLUTION_LEAKAGE_PATTERNS), re.IGNORECASE)

# Mega-task heuristic: count distinct verbs joined by "и"/"and"
MEGA_TASK_CONNECTORS = [r"\sи\s", r"\sand\s", r",\sзатем\s", r",\sthen\s"]
MEGA_TASK_RE = re.compile("|".join(MEGA_TASK_CONNECTORS), re.IGNORECASE)


def validate_tasks_spec(
    tasks_spec: list[dict],
    goal: dict,
) -> list[str]:
    """Run all checks. Returns sorted unique error strings."""
    errors: list[str] = []
    if not isinstance(tasks_spec, list) or not tasks_spec:
        return ["tasks_spec is empty or not a list"]

    errors += _check_task_shape(tasks_spec)
    errors += _check_unique_names(tasks_spec)
    errors += _check_naming_convention(tasks_spec)
    errors += _check_descriptions(tasks_spec)
    errors += _check_subgoal_refs(tasks_spec, goal)
    errors += _check_unique_output_names(tasks_spec)
    errors += _check_generic_outputs(tasks_spec)
    errors += _check_inputs_have_producers(tasks_spec)
    errors += _check_orphans(tasks_spec)
    errors += _check_solution_leakage(tasks_spec)
    errors += _check_mega_tasks(tasks_spec)

    seen = set()
    deduped = []
    for e in errors:
        if e not in seen:
            seen.add(e)
            deduped.append(e)
    return deduped


# ============================================================
# Individual checks
# ============================================================

def _check_task_shape(specs: list[dict]) -> list[str]:
    errs = []
    for i, t in enumerate(specs):
        if not isinstance(t, dict):
            errs.append(f"Task #{i}: not a dict (got {type(t).__name__})")
            continue
        if "name" not in t or not isinstance(t.get("name"), str):
            errs.append(f"Task #{i}: missing or non-string 'name'")
        if "description" not in t or not isinstance(t.get("description"), str):
            errs.append(f"Task #{i}: missing or non-string 'description'")
        for fld in ("inputs", "outputs"):
            if fld in t and not isinstance(t[fld], list):
                name = t.get("name", f"#{i}")
                errs.append(f"Task '{name}': '{fld}' must be a list")
    return errs


def _check_unique_names(specs: list[dict]) -> list[str]:
    names = [s.get("name") for s in specs if isinstance(s.get("name"), str)]
    dupes = [n for n, c in Counter(names).items() if c > 1]
    return [f"Duplicate task name: '{n}'" for n in sorted(dupes)]


def _check_naming_convention(specs: list[dict]) -> list[str]:
    errs = []
    for s in specs:
        name = s.get("name", "")
        if not isinstance(name, str):
            continue
        if not name:
            continue
        if len(name) > NAME_MAX:
            errs.append(f"Task '{name}': name longer than {NAME_MAX} chars")
        if not SLUG_RE.match(name):
            errs.append(
                f"Task '{name}': name must be lowercase [a-z0-9_]+ (slug-case)"
            )
    return errs


def _check_descriptions(specs: list[dict]) -> list[str]:
    errs = []
    for s in specs:
        name = s.get("name", "(unnamed)")
        desc = s.get("description", "")
        if not isinstance(desc, str):
            continue
        if len(desc) < DESC_MIN:
            errs.append(
                f"Task '{name}': description too short ({len(desc)} chars, min {DESC_MIN})"
            )
        if len(desc) > DESC_MAX:
            errs.append(
                f"Task '{name}': description too long ({len(desc)} chars, max {DESC_MAX})"
            )
    return errs


def _check_subgoal_refs(specs: list[dict], goal: dict) -> list[str]:
    declared = {sg["id"] for sg in (goal.get("subgoals") or []) if isinstance(sg, dict) and "id" in sg}
    # If the goal has zero subgoals, allow tasks to reference 'main' (synthesized fallback)
    if not declared:
        declared = {"main"}

    errs = []
    for s in specs:
        name = s.get("name", "(unnamed)")
        sg_id = s.get("subgoal_id")
        if sg_id is None or sg_id == "":
            errs.append(f"Task '{name}': missing subgoal_id (must reference one of {sorted(declared)})")
            continue
        if sg_id not in declared:
            errs.append(
                f"Task '{name}': subgoal_id '{sg_id}' not in declared subgoals {sorted(declared)}"
            )
    return errs


def _check_unique_output_names(specs: list[dict]) -> list[str]:
    """The single most important check — duplicate outputs break edge inference."""
    pairs: list[tuple[str, str]] = []
    for s in specs:
        for out in s.get("outputs", []):
            name = out.get("name") if isinstance(out, dict) else (out if isinstance(out, str) else None)
            if not name:
                continue
            pairs.append((name, s.get("name", "(unnamed)")))

    by_output: dict[str, list[str]] = {}
    for out_name, task_name in pairs:
        by_output.setdefault(out_name, []).append(task_name)

    return [
        f"Duplicate output name '{out}' produced by tasks: {sorted(set(producers))}. "
        f"Each output MUST have a unique name (e.g. prefix with domain: "
        f"'tourist_demand_data' vs 'rental_market_data')."
        for out, producers in by_output.items()
        if len(producers) > 1
    ]


def _check_generic_outputs(specs: list[dict]) -> list[str]:
    errs = []
    for s in specs:
        name = s.get("name", "(unnamed)")
        for out in s.get("outputs", []):
            out_name = out.get("name") if isinstance(out, dict) else out
            if isinstance(out_name, str) and out_name.lower() in GENERIC_OUTPUT_NAMES:
                errs.append(
                    f"Task '{name}': generic output name '{out_name}' — "
                    f"prefix with domain to avoid edge collisions"
                )
    return errs


def _check_inputs_have_producers(specs: list[dict]) -> list[str]:
    """Every non-external input must match some other task's output by name."""
    all_outputs: set[str] = set()
    for s in specs:
        for out in s.get("outputs", []):
            if isinstance(out, dict) and "name" in out:
                all_outputs.add(out["name"])
            elif isinstance(out, str):
                all_outputs.add(out)

    errs = []
    for s in specs:
        name = s.get("name", "(unnamed)")
        for inp in s.get("inputs", []):
            if isinstance(inp, dict):
                if inp.get("type") == "external":
                    continue
                in_name = inp.get("name")
            elif isinstance(inp, str):
                in_name = inp
            else:
                continue
            if not in_name:
                continue
            if in_name not in all_outputs:
                errs.append(
                    f"Task '{name}': input '{in_name}' has no producer task. "
                    f"Either add a task that outputs '{in_name}', or mark this input "
                    f"as {{\"type\": \"external\"}}."
                )
    return errs


def _check_orphans(specs: list[dict]) -> list[str]:
    """Multi-task plans: every task must connect to the graph via at least one edge."""
    if len(specs) <= 1:
        return []

    # Build name → outputs and name → inputs (non-external)
    outputs_by_task: dict[str, set[str]] = {}
    inputs_by_task: dict[str, set[str]] = {}
    for s in specs:
        name = s.get("name")
        if not name:
            continue
        outputs_by_task[name] = {
            (o.get("name") if isinstance(o, dict) else o)
            for o in s.get("outputs", [])
            if (isinstance(o, dict) and o.get("name")) or isinstance(o, str)
        }
        inputs_by_task[name] = {
            (i.get("name") if isinstance(i, dict) else i)
            for i in s.get("inputs", [])
            if (isinstance(i, dict) and i.get("type") != "external" and i.get("name"))
            or isinstance(i, str)
        }

    # All outputs → which tasks consume them
    all_out_names = set().union(*outputs_by_task.values()) if outputs_by_task else set()
    all_in_names = set().union(*inputs_by_task.values()) if inputs_by_task else set()

    orphans = []
    for name in outputs_by_task:
        is_source = bool(outputs_by_task[name] & all_in_names)
        is_sink = bool(inputs_by_task[name] & all_out_names)
        if not is_source and not is_sink:
            orphans.append(name)

    return (
        [
            f"Orphan task '{n}' (no edges in or out). Either remove it, "
            f"or wire it into the graph by adjusting inputs/outputs."
            for n in sorted(orphans)
        ]
    )


def _check_solution_leakage(specs: list[dict]) -> list[str]:
    errs = []
    for s in specs:
        name = s.get("name", "(unnamed)")
        desc = s.get("description", "")
        if isinstance(desc, str):
            m = SOLUTION_LEAKAGE_RE.search(desc)
            if m:
                errs.append(
                    f"Task '{name}': description mentions implementation detail "
                    f"'{m.group(0)}'. Decomposition is WHAT-layer — move agent/tool/profile "
                    f"references to Phase 4 (capability matrix)."
                )
    return errs


def _check_mega_tasks(specs: list[dict]) -> list[str]:
    errs = []
    for s in specs:
        name = s.get("name", "(unnamed)")
        desc = s.get("description", "")
        if not isinstance(desc, str):
            continue
        connectors = MEGA_TASK_RE.findall(desc)
        # 2+ connectors = 3+ operations chained
        if len(connectors) >= 2:
            errs.append(
                f"Task '{name}': description chains {len(connectors) + 1}+ operations. "
                f"Split into atomic tasks."
            )
    return errs


__all__ = [
    "validate_tasks_spec",
]
