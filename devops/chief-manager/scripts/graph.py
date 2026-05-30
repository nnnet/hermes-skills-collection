"""
Conceptual hierarchy for chief-manager:

    Desire → Goal+Subgoals → TaskTree → Plan → Workflow → Dispatch

This module defines the dataclasses for each layer above 'Dispatch'.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# ============================================================
# Layer 1 — Goal + Subgoals (output of desire-to-goal skill)
# ============================================================

@dataclass
class Subgoal:
    """Abstract chunk of value, no I/O yet."""
    id: str  # short slug
    description: str


@dataclass
class Goal:
    """A clarified goal. Comes out of the desire-to-goal skill."""
    statement: str  # one-line restatement
    success_criteria: list[str] = field(default_factory=list)
    deliverable_format: str = ""
    out_of_scope: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    subgoals: list[Subgoal] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Layer 2 — Task Tree (concrete WHAT)
# ============================================================

@dataclass
class TaskParam:
    """An input or output of a task."""
    name: str
    description: str = ""
    type: str = "any"

    def __hash__(self):
        return hash(self.name)


@dataclass
class Task:
    """Concrete unit of work. No agent assigned yet."""
    name: str
    description: str
    reason: str = ""
    inputs: list[TaskParam] = field(default_factory=list)
    outputs: list[TaskParam] = field(default_factory=list)
    subgoal_id: Optional[str] = None
    max_runtime_seconds: Optional[int] = None
    priority: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TaskTree:
    """Collection of tasks (no execution order yet)."""
    goal: Goal
    tasks: list[Task] = field(default_factory=list)

    def task_by_name(self, name: str) -> Optional[Task]:
        for t in self.tasks:
            if t.name == name:
                return t
        return None

    def validate(self) -> list[str]:
        errors = []
        names = [t.name for t in self.tasks]
        if len(names) != len(set(names)):
            dups = {n for n in names if names.count(n) > 1}
            errors.append(f"Duplicate task names: {sorted(dups)}")
        subgoal_ids = {sg.id for sg in self.goal.subgoals}
        for t in self.tasks:
            if not t.name:
                errors.append("Task with empty name")
                continue
            if not t.description:
                errors.append(f"Task {t.name!r} missing description")
            if t.subgoal_id and t.subgoal_id not in subgoal_ids:
                errors.append(f"Task {t.name!r} references unknown subgoal {t.subgoal_id!r}")
        return errors


# ============================================================
# Layer 3 — Plan (execution structure, DAG)
# ============================================================

@dataclass
class Edge:
    from_task: str
    to_task: str
    via_param: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Plan:
    """Task tree + inferred edges + topological order."""
    task_tree: TaskTree
    edges: list[Edge] = field(default_factory=list)
    topo_order: list[str] = field(default_factory=list)

    @classmethod
    def from_task_tree(cls, tree: TaskTree) -> "Plan":
        """Infer edges from I/O matching, then topo sort."""
        edges = cls._infer_edges(tree.tasks)
        plan = cls(task_tree=tree, edges=edges)
        plan.topo_order = plan._topological_sort()
        return plan

    @staticmethod
    def _infer_edges(tasks: list[Task]) -> list[Edge]:
        """If A.outputs and B.inputs share a name, edge A→B exists."""
        edges = []
        seen = set()
        for a in tasks:
            a_out_names = {p.name for p in a.outputs}
            for b in tasks:
                if a.name == b.name:
                    continue
                b_in_names = {p.name for p in b.inputs}
                for param in a_out_names & b_in_names:
                    key = (a.name, b.name, param)
                    if key not in seen:
                        edges.append(Edge(from_task=a.name, to_task=b.name, via_param=param))
                        seen.add(key)
        return edges

    def _topological_sort(self) -> list[str]:
        """Kahn's algorithm. Raises ValueError on cycle."""
        in_degree = {t.name: 0 for t in self.task_tree.tasks}
        adjacency = {t.name: [] for t in self.task_tree.tasks}
        for e in self.edges:
            if e.to_task in in_degree:
                in_degree[e.to_task] += 1
            if e.from_task in adjacency:
                adjacency[e.from_task].append(e.to_task)

        queue = sorted([n for n, d in in_degree.items() if d == 0])
        result = []
        while queue:
            queue.sort()  # deterministic
            node = queue.pop(0)
            result.append(node)
            for nb in adjacency[node]:
                in_degree[nb] -= 1
                if in_degree[nb] == 0:
                    queue.append(nb)
        if len(result) != len(self.task_tree.tasks):
            raise ValueError(
                f"Cycle detected — sorted {len(result)}/{len(self.task_tree.tasks)} tasks"
            )
        return result

    def validate(self) -> list[str]:
        errors = self.task_tree.validate()
        try:
            self._topological_sort()
        except ValueError as e:
            errors.append(str(e))
        # Orphan detection (only meaningful when multiple tasks exist)
        if len(self.task_tree.tasks) > 1:
            connected = set()
            for e in self.edges:
                connected.add(e.from_task)
                connected.add(e.to_task)
            orphans = [t.name for t in self.task_tree.tasks if t.name not in connected]
            if orphans:
                errors.append(f"Orphan tasks (no edges in or out): {orphans}")
        return errors

    def parents_of(self, task_name: str) -> list[str]:
        return [e.from_task for e in self.edges if e.to_task == task_name]

    def children_of(self, task_name: str) -> list[str]:
        return [e.to_task for e in self.edges if e.from_task == task_name]

    def render_tree(self) -> str:
        """ASCII tree grouped by subgoal."""
        lines = [f"Goal: {self.task_tree.goal.statement}"]
        if self.task_tree.goal.success_criteria:
            lines.append(f"  Success criteria:")
            for c in self.task_tree.goal.success_criteria:
                lines.append(f"    ✓ {c}")
        sg_map = {sg.id: sg.description for sg in self.task_tree.goal.subgoals}
        by_subgoal: dict[str, list[Task]] = {}
        for t in self.task_tree.tasks:
            by_subgoal.setdefault(t.subgoal_id or "_unassigned", []).append(t)
        for sg_id, ts in by_subgoal.items():
            desc = sg_map.get(sg_id, "(no subgoal)") if sg_id != "_unassigned" else "(unassigned)"
            lines.append(f"  Subgoal [{sg_id}]: {desc}")
            for t in sorted(ts, key=lambda x: self.topo_order.index(x.name) if x.name in self.topo_order else 999):
                deps = self.parents_of(t.name)
                dep_str = f"  ← {', '.join(deps)}" if deps else ""
                lines.append(f"    • {t.name}{dep_str}")
                lines.append(f"        {t.description[:80]}")
        return "\n".join(lines)


# ============================================================
# Layer 4 — Workflow (Plan + agent assignments — means)
# ============================================================

@dataclass
class AgentAssignment:
    task_name: str
    profile: str
    required_skills: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Workflow:
    """Plan + agent assignments. The means of executing a plan."""
    plan: Plan
    assignments: list[AgentAssignment] = field(default_factory=list)
    capability_matrix: Optional[object] = None  # avoid circular import

    def assignment_for(self, task_name: str) -> Optional[AgentAssignment]:
        for a in self.assignments:
            if a.task_name == task_name:
                return a
        return None


# ============================================================
# Parallelism analysis
# ============================================================

def _compute_waves(plan: Plan) -> list[list[str]]:
    """Group tasks into execution waves by dependency depth.

    Wave 0 = tasks with no incoming edges (no parents).
    Wave 1 = tasks whose parents are all in wave 0.
    And so on.

    Returns: list of waves, each wave is a list of task names that can run in parallel.
    """
    if not plan.topo_order:
        return []

    parent_map: dict[str, set[str]] = {t: set() for t in plan.topo_order}
    for e in plan.edges:
        if e.to_task in parent_map:
            parent_map[e.to_task].add(e.from_task)

    assigned: dict[str, int] = {}  # task_name → wave index
    waves: list[list[str]] = []

    for task in plan.topo_order:
        parents = parent_map[task]
        if not parents:
            wave_idx = 0
        else:
            parent_waves = [assigned[p] for p in parents if p in assigned]
            if not parent_waves:
                wave_idx = 0
            else:
                wave_idx = max(parent_waves) + 1
        assigned[task] = wave_idx
        while len(waves) <= wave_idx:
            waves.append([])
        waves[wave_idx].append(task)

    return waves
