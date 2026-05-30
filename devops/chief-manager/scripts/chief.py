"""
Chief — main orchestrator class for chief-manager skill.

Pipeline (one method per layer):
    Desire → Goal+Subgoals → TaskTree → Plan → Workflow → DispatchPlan → Monitor → Synthesize

Phases that require external MCP tool calls (kanban_create, cronjob, kanban_show)
return structured spec objects. The calling agent dispatches them via its tools.

═══════════════════════════════════════════════════════════════
CONFIGURATION VARIABLES — override via Chief.__init__(**kwargs)
═══════════════════════════════════════════════════════════════

These control decomposition, parallelism, and verification behavior.
Set them when constructing Chief() or override per-workflow.

| Variable | Default | Purpose |
|---|---|---|
| MAX_PARALLEL_PER_WAVE | 3 | Max tasks dispatched in one wave simultaneously |
| DECOMPOSE_INGEST_BY_SOURCE | True | Auto-split monolithic ingest tasks by source type |
| SOURCE_MAX_RUNTIME | See map | Default max_runtime per source type |
| VERIFICATION_GATE_TEMPLATES | See dict | Per-source verification gate templates |
| PROGRESS_HEARTBEAT_INTERVAL | 120 | Seconds between kanban_heartbeat calls in long tasks |
| AUTO_DEPENDENCY_PRECHECK | True | Auto-inject dependency pre-check into task bodies |
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable, Any

from graph import (
    Goal, Subgoal, Task, TaskParam, TaskTree, Plan, Workflow,
    AgentAssignment, Edge, _compute_waves,
)
from capability import (
    Profile, CapabilityMatrix, discover_profiles, build_capability_matrix,
)
from failures import FailureClassification, classify_failure


# ════════════════════════════════════════════════════════════════
# CONFIGURATION — tune these per project/workflow
# ════════════════════════════════════════════════════════════════

MAX_PARALLEL_PER_WAVE: int = 3
"""Max tasks that can run simultaneously in one wave.
   Set to 1 for fully sequential, 0 for unlimited.
   Chief uses this in build_dispatch_plan() to split waves."""

DECOMPOSE_INGEST_BY_SOURCE: bool = True
"""If True, plan_workflow() auto-splits any task named 'ingest_*' 
   into per-source subtasks (ingest_youtube, ingest_github, etc).
   Each subtask gets its own verification gate and max_runtime.
   Set to False to keep monolithic ingest tasks."""

AUTO_DEPENDENCY_PRECHECK: bool = True
"""If True, _render_task_body() injects a pre-flight dependency 
   check section. Set to False for tasks that don't need tools."""

PROGRESS_HEARTBEAT_INTERVAL: int = 120
"""Seconds between kanban_heartbeat calls for long-running tasks.
   Workers should call heartbeat every N seconds to signal liveness."""

# Per-source max runtime defaults (seconds)
SOURCE_MAX_RUNTIME: dict[str, int] = {
    "youtube_video": 7200,    # 2h — transcription is slow (~37 sec/min)
    "github_repo": 600,       # 10 min — git clone is fast
    "pdf": 1800,              # 30 min — PDF extraction + OCR
    "vk_post": 900,           # 15 min — web scraping + parsing
    "linkedin": 600,          # 10 min — web scraping
    "website": 600,           # 10 min — web scraping
    "drive_doc": 1200,        # 20 min — download + parse
}

# Per-source verification gate templates
# {source_type: (glob_pattern, min_count, description)}
VERIFICATION_GATE_TEMPLATES: dict[str, tuple[str, int, str]] = {
    "youtube_video":  ("*.txt", 50, "YouTube transcripts"),
    "github_repo":    ("*.py",  10, "GitHub source files"),
    "pdf":            ("*.md",   3, "Extracted PDF content"),
    "vk_post":        ("*.md",   8, "VK articles"),
    "linkedin":       ("*.md",   2, "LinkedIn pages"),
    "website":        ("*.md",   3, "Website pages"),
    "drive_doc":      ("*.md",   3, "Drive documents"),
}

# Source types → canonical ingest task suffixes
SOURCE_TYPE_MAP: dict[str, str] = {
    "youtube_video": "youtube",
    "github_repo": "github",
    "pdf": "pdf",
    "vk_post": "vk",
    "linkedin": "linkedin",
    "website": "website",
    "drive_doc": "drive",
}


VAGUE_GOAL_MARKERS = [
    "something", "somehow", "maybe", "kind of", "or so",
    "improve", "optimize", "fix", "clean up", "make better",
    "что-нибудь", "как-то", "может быть", "наверное",
    "улучшить", "оптимизировать", "почистить", "сделать лучше",
]

MEASURABILITY_MARKERS = [
    "count", "by", "until", "format", "deliverable", "criteria",
    "к ", "до ", "формат", "критерии", "%", "число", "сколько",
    "deadline", "deliver", "must contain", "should have",
    "into", "with", "for each", "per ", "all ", "each ",
    "в ", "на ", "по ", "кажд", "все ",
]


@dataclass
class KanbanCreateSpec:
    """Args for kanban_create. parents holds task NAMES; resolve to IDs before dispatch."""
    title: str
    assignee: str
    body: str
    parents: list[str] = field(default_factory=list)
    priority: int = 0
    max_runtime_seconds: Optional[int] = None
    skills: list[str] = field(default_factory=list)
    workspace_kind: str = "scratch"
    workspace_path: Optional[str] = None
    idempotency_key: Optional[str] = None
    _task_name: str = ""

    def to_dict(self, drop_optional_empty: bool = True) -> dict:
        d = asdict(self)
        d.pop("_task_name", None)
        if drop_optional_empty:
            if d.get("max_runtime_seconds") is None:
                d.pop("max_runtime_seconds", None)
            if not d.get("idempotency_key"):
                d.pop("idempotency_key", None)
            if not d.get("parents"):
                d.pop("parents", None)
            if not d.get("skills"):
                d.pop("skills", None)
            if not d.get("workspace_path"):
                d.pop("workspace_path", None)
        return d


@dataclass
class CronSpec:
    """Args for cronjob(action='create', ...)."""
    name: str
    schedule: str
    prompt: str
    deliver: str = "origin"

    def to_dict(self) -> dict:
        return {"action": "create", **asdict(self)}


# ============================================================
# Chief — main orchestrator
# ============================================================

class Chief:
    """
    Stateless per call; constructed per goal.

    Typical agent loop:
        chief = Chief("Your goal")
        if Chief.requires_goal_refinement(chief.goal_text):
            # load desire-to-goal skill, ask user

        # After clarification:
        goal = chief.make_goal(statement="...", success_criteria=[...], subgoals=[...])
        tree = chief.build_task_tree(goal, tasks_spec=[...])
        plan = chief.build_plan(tree)
        wf = chief.build_workflow(plan, task_requirements={...})

        # Present to user; on approval:
        specs = chief.build_dispatch_plan(wf)
        # Agent loops over specs, calls kanban_create, builds task_name_to_id map.

        crons = chief.setup_monitoring_plan(list_of_ids)
        # Agent calls cronjob() for each.

        # On completion:
        synth = chief.collect_handoffs(map_of_id_to_kanban_show)
    """

    def __init__(self, goal_text: str, profiles_dir: str = "/opt/data/profiles"):
        if not goal_text or len(goal_text.strip()) < 10:
            raise ValueError("Goal text must be >= 10 chars (this is a desire, not a noun).")
        self.goal_text = goal_text.strip()
        self.profiles_dir = profiles_dir
        self._profiles_cache: Optional[list[Profile]] = None

    # ----- Phase 0: vagueness check -----

    @staticmethod
    def requires_goal_refinement(text: str) -> bool:
        """True if the text looks like a desire, not a measurable goal."""
        if not text or len(text.split()) < 5:
            return True
        lower = text.lower()
        if any(marker in lower for marker in VAGUE_GOAL_MARKERS):
            return True
        if not any(m in lower for m in MEASURABILITY_MARKERS):
            return True
        return False

    @staticmethod
    def goal_refinement_questions() -> list[str]:
        """Fallback questions when desire-to-goal skill is not installed."""
        return [
            "Что конкретно должно получиться? Опишите измеримый результат.",
            "В каком формате нужен deliverable (отчёт, коллекция, список, артефакт)?",
            "Что ЯВНО вне области (out of scope)?",
            "Какие жёсткие ограничения — по времени, бюджету, инструментам?",
            "Какие подцели вы видите (3-7 крупных блоков)?",
        ]

    # ----- Construction helpers -----

    @staticmethod
    def make_goal(
        statement: str,
        success_criteria: Optional[list[str]] = None,
        deliverable_format: str = "",
        out_of_scope: Optional[list[str]] = None,
        constraints: Optional[list[str]] = None,
        subgoals: Optional[list[dict]] = None,
    ) -> Goal:
        """Convenience factory. Subgoals as list of {id, description}."""
        sg_objs = [Subgoal(**s) if isinstance(s, dict) else s for s in (subgoals or [])]
        return Goal(
            statement=statement,
            success_criteria=success_criteria or [],
            deliverable_format=deliverable_format,
            out_of_scope=out_of_scope or [],
            constraints=constraints or [],
            subgoals=sg_objs,
        )

    # ----- Profile cache -----

    def profiles(self) -> list[Profile]:
        if self._profiles_cache is None:
            self._profiles_cache = discover_profiles(self.profiles_dir)
        return self._profiles_cache

    def refresh_profile_cache(self) -> None:
        self._profiles_cache = None

    # ----- Project board isolation -----

    HERMES_BIN: str = "/opt/hermes/.venv/bin/hermes"

    @staticmethod
    def create_project_board(slug: str, switch: bool = True,
                              hermes_bin: str = "/opt/hermes/.venv/bin/hermes") -> dict:
        """Create a dedicated Kanban board for this project and verify it exists.

        IMPORTANT: This only creates the board metadata and DB file.
        The MCP `kanban_create` tool writes to the GATEWAY's active board (legacy
        /opt/data/kanban.db), NOT to this board. Use `cli_dispatch_task()` for
        board-isolated task creation.

        Call BEFORE Phase 6 dispatch. After creation, always call
        `verify_board_active(slug)` to confirm the DB exists before dispatching.

        Returns {"slug", "db_path", "db_exists", "stdout", "stderr", "returncode"}.
        """
        import subprocess, os
        cmd = [hermes_bin, "kanban", "boards", "create", slug]
        if switch:
            cmd.append("--switch")
        result = subprocess.run(cmd, capture_output=True, text=True)
        db_path = f"/opt/data/kanban/boards/{slug}/kanban.db"
        return {
            "slug": slug,
            "db_path": db_path,
            "db_exists": os.path.exists(db_path),
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }

    @staticmethod
    def verify_board_active(slug: str) -> dict:
        """Verify project board DB exists and is writable. Call after create_project_board().

        Returns {"ok": bool, "db_path": str, "task_count": int, "error": str|None}.
        """
        import sqlite3, os
        db_path = f"/opt/data/kanban/boards/{slug}/kanban.db"
        if not os.path.exists(db_path):
            return {"ok": False, "db_path": db_path, "task_count": -1,
                    "error": f"Board DB not found: {db_path}"}
        try:
            conn = sqlite3.connect(db_path)
            # Ensure schema exists (boards/quants/kanban.db may be empty before first task)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tasks "
                "(id TEXT PRIMARY KEY, title TEXT, status TEXT, assignee TEXT, "
                " body TEXT, created_at INTEGER)"
            )
            count = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status NOT IN ('archived')"
            ).fetchone()[0]
            conn.close()
            return {"ok": True, "db_path": db_path, "task_count": count, "error": None}
        except Exception as e:
            return {"ok": False, "db_path": db_path, "task_count": -1, "error": str(e)}

    @staticmethod
    def cli_dispatch_task(spec: "KanbanCreateSpec", board_slug: str,
                          task_name_to_id: dict,
                          hermes_bin: str = "/opt/hermes/.venv/bin/hermes") -> dict:
        """Create a single Kanban task on a specific board via CLI (not MCP tool).

        Use this instead of kanban_create() MCP tool when board isolation is required.
        The MCP tool always writes to the gateway's active board (legacy /opt/data/kanban.db).
        This method uses HERMES_KANBAN_BOARD=<slug> env to target the correct DB directly.

        Args:
            spec: KanbanCreateSpec to dispatch
            board_slug: target board slug (e.g. "quants")
            task_name_to_id: dict mapping task names to real kanban IDs (updated in-place)
            hermes_bin: path to hermes CLI binary

        Returns {"task_id": str, "title": str, "returncode": int, "error": str|None}.
        """
        import subprocess, json as _json, os
        env = {**os.environ, "HERMES_KANBAN_BOARD": board_slug}
        cmd = [hermes_bin, "kanban", "create", spec.title,
               "--assignee", spec.assignee,
               "--body", spec.body,
               "--json"]
        # Resolve parent names → IDs
        resolved_parents = [task_name_to_id[p] for p in spec.parents
                            if p in task_name_to_id]
        for pid in resolved_parents:
            cmd += ["--parent", pid]
        if spec.priority:
            cmd += ["--priority", str(spec.priority)]
        if spec.max_runtime_seconds:
            cmd += ["--max-runtime", str(spec.max_runtime_seconds)]
        if spec.idempotency_key:
            cmd += ["--idempotency-key", spec.idempotency_key]

        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        task_id = None
        error = None
        if result.returncode == 0:
            try:
                data = _json.loads(result.stdout)
                task_id = data.get("id") or data.get("task_id")
                if task_id and spec._task_name:
                    task_name_to_id[spec._task_name] = task_id
            except Exception as e:
                error = f"JSON parse error: {e} — stdout: {result.stdout[:200]}"
        else:
            error = result.stderr.strip() or result.stdout.strip()
        return {
            "task_id": task_id,
            "title": spec.title,
            "board": board_slug,
            "returncode": result.returncode,
            "error": error,
        }

    # ----- Phase 2+3+4: plan_workflow with auto-decomposition -----

    def plan_workflow(
        self,
        tasks: list[dict],
        task_requirements: Optional[dict[str, dict]] = None,
        decompose_ingest: Optional[bool] = None,
        max_parallel: Optional[int] = None,
    ) -> Workflow:
        """End-to-end: tasks_spec → TaskTree → Plan → Workflow.

        Args:
            tasks: list of task dicts with keys: name, description, inputs, outputs,
                   subgoal_id, max_runtime_seconds, priority, reason
            task_requirements: optional {task_name: {"required_skills": [...], "required_tools": [...]}}
            decompose_ingest: override DECOMPOSE_INGEST_BY_SOURCE (None = use global)
            max_parallel: override MAX_PARALLEL_PER_WAVE (None = use global)
        """
        do_decompose = decompose_ingest if decompose_ingest is not None else DECOMPOSE_INGEST_BY_SOURCE
        self._effective_max_parallel = max_parallel if max_parallel is not None else MAX_PARALLEL_PER_WAVE

        # Auto-decompose ingest tasks by source type
        if do_decompose:
            tasks = self._decompose_ingest_tasks(tasks)

        goal = self.make_goal(statement=self.goal_text)
        tree = self.build_task_tree(goal, tasks)
        plan = self.build_plan(tree)
        return self.build_workflow(plan, task_requirements)

    # ----- Ingest decomposition -----

    @staticmethod
    def _decompose_ingest_tasks(tasks: list[dict]) -> list[dict]:
        """Split monolithic ingest tasks into per-source subtasks.

        Looks for tasks whose name starts with 'ingest' and whose description
        mentions multiple source types. Replaces with per-source tasks + a
        merge task.

        Each subtask gets:
        - Source-specific output name (e.g., youtube_transcripts)
        - Source-specific verification gate (from VERIFICATION_GATE_TEMPLATES)
        - Source-specific max_runtime (from SOURCE_MAX_RUNTIME)
        """
        result = []
        for task in tasks:
            name = task.get("name", "")
            if not name.startswith("ingest"):
                result.append(task)
                continue

            # Detect which source types are mentioned in description
            desc = task.get("description", "").lower()
            detected_sources = []
            for source_type, suffix in SOURCE_TYPE_MAP.items():
                # Match keywords: "youtube", "github", "pdf", "vk", "linkedin", "website", "drive"
                keywords = [suffix, source_type.replace("_", " ")]
                if any(kw in desc for kw in keywords):
                    detected_sources.append(source_type)

            # If fewer than 2 sources detected, keep as-is
            if len(detected_sources) < 2:
                result.append(task)
                continue

            # Split into per-source tasks
            source_outputs = []
            for source_type in detected_sources:
                suffix = SOURCE_TYPE_MAP.get(source_type, source_type)
                subtask_name = f"{name}_{suffix}"
                output_name = f"{suffix}_documents"
                source_outputs.append(output_name)

                # Get verification gate template
                gate_glob, gate_count, gate_desc = VERIFICATION_GATE_TEMPLATES.get(
                    source_type, ("*", 1, source_type)
                )
                max_rt = SOURCE_MAX_RUNTIME.get(source_type, 1800)

                subtask = {
                    "name": subtask_name,
                    "description": (
                        f"{task.get('description', '')}\n\n"
                        f"Source type: {source_type}\n"
                        f"Verification: count {gate_glob} in raw/{suffix}/ >= {gate_count} ({gate_desc})"
                    ),
                    "outputs": [output_name],
                    "max_runtime_seconds": max_rt,
                    "priority": task.get("priority", 5),
                }
                # Inherit inputs from parent task
                if "inputs" in task:
                    subtask["inputs"] = task["inputs"]

                result.append(subtask)

            # Create merge task that consumes all source outputs
            merge_task = {
                "name": name,  # keep original name for the merge
                "description": (
                    f"Merge all source-specific outputs into unified raw_documents. "
                    f"Verify all sources processed: {', '.join(source_outputs)}"
                ),
                "inputs": source_outputs,
                "outputs": task.get("outputs", ["raw_documents"]),
                "priority": task.get("priority", 5) - 1,  # slightly lower priority
            }
            result.append(merge_task)

        return result

    # ----- Dispatch plan with parallelism control -----

    def build_dispatch_plan(
        self,
        workflow: Workflow,
        idempotency_namespace: Optional[str] = None,
        max_parallel: Optional[int] = None,
    ) -> list[KanbanCreateSpec]:
        """
        Returns KanbanCreateSpec objects in topological order.
        `parents` field uses task NAMES — call resolve_parents() to swap in real IDs
        after each kanban_create returns.

        Args:
            max_parallel: override MAX_PARALLEL_PER_WAVE. 
                         0 = unlimited, 1 = fully sequential, N = max N per wave.
        """
        effective_parallel = max_parallel if max_parallel is not None else getattr(self, '_effective_max_parallel', MAX_PARALLEL_PER_WAVE)

        plan = workflow.plan
        specs: list[KanbanCreateSpec] = []
        waves = _compute_waves(plan)

        for wave_idx, wave_tasks in enumerate(waves):
            # Apply parallelism limit: split wave into chunks if needed
            if effective_parallel > 0 and len(wave_tasks) > effective_parallel:
                chunks = [wave_tasks[i:i+effective_parallel] 
                         for i in range(0, len(wave_tasks), effective_parallel)]
            else:
                chunks = [wave_tasks]

            for chunk_idx, chunk in enumerate(chunks):
                for task_name in chunk:
                    t = plan.task_tree.task_by_name(task_name)
                    if t is None:
                        continue
                    assignment = workflow.assignment_for(task_name)
                    body = self._render_task_body(t, plan.task_tree.goal, assignment)
                    spec = KanbanCreateSpec(
                        title=t.name,
                        assignee=assignment.profile if assignment else "?",
                        body=body,
                        parents=plan.parents_of(task_name),
                        priority=t.priority,
                        max_runtime_seconds=t.max_runtime_seconds,
                        skills=assignment.required_skills if assignment else [],
                        idempotency_key=(
                            f"{idempotency_namespace}:{task_name}" if idempotency_namespace else None
                        ),
                        _task_name=task_name,
                    )
                    # Tag with wave/chunk for downstream analysis
                    spec._wave = wave_idx
                    spec._chunk = chunk_idx
                    specs.append(spec)

        return specs

    # ----- Phase 1: Subgoal extraction -----

    def extract_subgoals_prompt(self) -> str:
        """Return a prompt the agent can use to decompose the goal into subgoals.

        The agent calls this, then produces the subgoal list itself (Mode A),
        or delegates to desire-to-goal skill (Mode B).
        """
        return (
            f"Given the goal:\n\n\"\"\"{self.goal_text}\"\"\"\n\n"
            "Break it into 3-7 abstract subgoals. Each subgoal:\n"
            "- Is a coherent chunk of VALUE (not an action)\n"
            "- Has a short slug id (lowercase, hyphens)\n"
            "- Has a 1-2 sentence description\n"
            "- Does NOT mention agents, tools, or execution details\n\n"
            "Output JSON array:\n"
            '[{"id": "slug", "description": "..."}]\n\n'
            "If the goal is too vague (< 5 words, no measurable criteria), "
            "return {\"needs_clarification\": true, \"questions\": [...]} instead."
        )

    def validate_subgoals(self, subgoals: list[dict]) -> list[str]:
        """Check subgoal list before building a Goal object."""
        errors = []
        if not subgoals:
            errors.append("Empty subgoal list")
            return errors
        ids = [s.get("id", "") for s in subgoals]
        if len(ids) != len(set(ids)):
            errors.append(f"Duplicate subgoal ids: {[i for i in ids if ids.count(i) > 1]}")
        for s in subgoals:
            if not s.get("id"):
                errors.append("Subgoal with empty id")
            if not s.get("description"):
                errors.append(f"Subgoal {s.get('id', '?')!r} missing description")
            elif len(s["description"]) < 10:
                errors.append(f"Subgoal {s['id']!r} description too short (< 10 chars)")
        return errors

    # ----- Phase 2: TaskTree -----

    def build_task_tree(self, goal: Goal, tasks_spec: list[dict]) -> TaskTree:
        """
        tasks_spec items:
            {"name": str,
             "description": str,
             "subgoal_id": str (optional),
             "inputs": ["param_name", ...] | [{name, description, type}, ...],
             "outputs": [...],
             "max_runtime_seconds": int (optional),
             "priority": int (optional),
             "reason": str (optional)}
        """
        def _params(items):
            out = []
            for p in items:
                if isinstance(p, str):
                    out.append(TaskParam(name=p))
                elif isinstance(p, dict):
                    out.append(TaskParam(**p))
                else:
                    out.append(p)
            return out

        tasks = []
        for spec in tasks_spec:
            tasks.append(Task(
                name=spec["name"],
                description=spec.get("description", ""),
                reason=spec.get("reason", ""),
                inputs=_params(spec.get("inputs", [])),
                outputs=_params(spec.get("outputs", [])),
                subgoal_id=spec.get("subgoal_id"),
                max_runtime_seconds=spec.get("max_runtime_seconds"),
                priority=spec.get("priority", 0),
            ))
        tree = TaskTree(goal=goal, tasks=tasks)
        errors = tree.validate()
        if errors:
            raise ValueError("Task tree validation failed:\n  - " + "\n  - ".join(errors))
        return tree

    # ----- Phase 3: Plan -----

    def build_plan(self, tree: TaskTree) -> Plan:
        plan = Plan.from_task_tree(tree)
        errors = plan.validate()
        if errors:
            raise ValueError("Plan validation failed:\n  - " + "\n  - ".join(errors))
        return plan

    # ----- Phase 4: Workflow (Plan + capability matrix → means) -----

    def build_workflow(
        self,
        plan: Plan,
        task_requirements: Optional[dict[str, dict]] = None,
    ) -> Workflow:
        """
        task_requirements: {task_name: {"required_skills": [...], "required_tools": [...]}}
        """
        task_requirements = task_requirements or {}
        tasks_with_req = []
        for t in plan.task_tree.tasks:
            req = task_requirements.get(t.name, {})
            tasks_with_req.append({
                "name": t.name,
                "description": t.description,
                "required_skills": req.get("required_skills", []),
                "required_tools": req.get("required_tools", []),
            })
        matrix = build_capability_matrix(
            tasks_with_req,
            profiles=self.profiles(),
            profiles_dir=self.profiles_dir,
        )
        assignments = []
        for row in matrix.rows:
            assignments.append(AgentAssignment(
                task_name=row.task_name,
                profile=row.suggested_profile or "?",
                required_skills=row.required_skills,
                required_tools=row.required_tools,
                notes="; ".join(f"alt:{a}" for a in row.alternatives),
            ))
        return Workflow(plan=plan, assignments=assignments, capability_matrix=matrix)

    # ----- Phase 5: Negotiation (user approval) -----

    def format_negotiation_message(self, workflow: Workflow) -> str:
        """Render a single message for the user to approve/deny/swap assignments.

        Shows: subgoals, task tree, edges, capability matrix, gaps.
        The agent sends this to the user, collects feedback, then proceeds to Phase 6.
        """
        plan = workflow.plan
        goal = plan.task_tree.goal
        lines = [
            "## 📋 Orchestration plan — approval needed",
            "",
            f"**Goal:** {goal.statement}",
            "",
        ]

        # Subgoals
        if goal.subgoals:
            lines.append("### Subgoals")
            for sg in goal.subgoals:
                lines.append(f"- `{sg.id}`: {sg.description}")
            lines.append("")

        # Task tree
        lines.append("### Task tree")
        lines.append(plan.render_tree())
        lines.append("")

        # Edges
        if plan.edges:
            lines.append("### Dependencies (edges)")
            for e in plan.edges:
                lines.append(f"- `{e.from_task}` → `{e.to_task}` (via `{e.via_param}`)")
            lines.append("")

        # Parallelism
        from graph import _compute_waves
        try:
            waves = _compute_waves(plan)
            lines.append(f"### Parallelism: {len(waves)} waves")
            for i, wave in enumerate(waves):
                lines.append(f"  Wave {i+1}: {', '.join(wave)}")
            lines.append("")
        except Exception:
            pass

        # Capability matrix
        if workflow.capability_matrix:
            lines.append("### Capability matrix")
            lines.append(workflow.capability_matrix.render())
            lines.append("")
            if workflow.capability_matrix.has_gaps():
                lines.append("⚠️ **Gaps detected** — see last column. Resolve before dispatch.")

        # Questions
        lines.extend([
            "",
            "**Please confirm:**",
            "1. Subgoals OK? Add/remove?",
            "2. Task tree OK? Edges correct?",
            "3. Agent assignments OK? Swap any?",
            "4. Gaps — fill now or accept workarounds?",
        ])
        return "\n".join(lines)

    @staticmethod
    def _render_task_body(t: Task, goal: Goal, assignment: Optional[AgentAssignment]) -> str:
        lines = [
            f"# Task: {t.name}",
            "",
            f"## Description",
            t.description,
            "",
        ]
        if t.reason:
            lines += [f"## Reason", t.reason, ""]
        if t.inputs:
            lines += ["## Inputs"]
            for p in t.inputs:
                lines.append(f"- `{p.name}` ({p.type}): {p.description or '—'}")
            lines.append("")
        if t.outputs:
            lines += ["## Outputs"]
            for p in t.outputs:
                lines.append(f"- `{p.name}` ({p.type}): {p.description or '—'}")
            lines.append("")
        if goal.success_criteria:
            lines += ["## Goal success criteria (the whole goal, for context)"]
            for c in goal.success_criteria:
                lines.append(f"- {c}")
            lines.append("")
        if assignment:
            if assignment.required_skills:
                lines += ["## Required skills"]
                for s in assignment.required_skills:
                    lines.append(f"- `{s}`")
                lines.append("")
            if assignment.required_tools:
                lines += ["## Required tools (MCP)"]
                for tt in assignment.required_tools:
                    lines.append(f"- `{tt}`")
                lines.append("")
        if goal.constraints:
            lines += ["## Constraints", *[f"- {c}" for c in goal.constraints], ""]
        if goal.out_of_scope:
            lines += ["## Out of scope", *[f"- {c}" for c in goal.out_of_scope], ""]

        # Dependency pre-check (if AUTO_DEPENDENCY_PRECHECK enabled)
        if AUTO_DEPENDENCY_PRECHECK:
            lines += [
                "## Pre-flight dependency check",
                "Before starting work, verify all required tools are installed.",
                "If any check fails → `kanban_block(reason=\"missing dependency: <tool>\")`.",
                "Do NOT skip the dependency and proceed with partial work.",
                "",
            ]

        # Source-specific verification gate (detect from task name/description)
        gate_rendered = False
        task_name_lower = t.name.lower()
        task_desc_lower = t.description.lower()
        for source_type, (glob_pat, min_count, desc) in VERIFICATION_GATE_TEMPLATES.items():
            suffix = SOURCE_TYPE_MAP.get(source_type, source_type)
            # Only apply source-specific gate to ingest_ tasks — other tasks (merge, enrich,
            # index, verify) mention source names in their descriptions and would false-match.
            if task_name_lower.startswith("ingest_") and (suffix in task_name_lower or source_type.replace("_", " ") in task_desc_lower):
                lines += [
                    f"## Verification gate (source-specific — cannot be gamed)",
                    f"Count: `ls raw/{suffix}/{glob_pat} 2>/dev/null | wc -l` must be >= {min_count}",
                    f"This counts {desc} specifically, NOT total files in raw/.",
                    f"If count < {min_count} → `kanban_block(reason=\"{desc} insufficient: got N, need >= {min_count}\")`",
                    "",
                    f"## Heartbeat",
                    f"Call `kanban_heartbeat(note=\"N/{min_count} {desc} processed\")` every "
                    f"{PROGRESS_HEARTBEAT_INTERVAL} seconds during long operations.",
                    "",
                ]
                gate_rendered = True
                break

        if not gate_rendered:
            lines += [
                "## Verification gate",
                "Verify DELIVERABLES, not total file counts. Count the specific output",
                "format (e.g., *.txt transcripts, *.pdf documents), not aggregate files.",
                "If you cannot verify objectively → kanban_block(reason=...).",
                "Do NOT complete the task based on partial success.",
                "",
            ]

        return "\n".join(lines)

    @staticmethod
    def resolve_parents(
        specs: list[KanbanCreateSpec],
        task_name_to_id: dict[str, str],
    ) -> list[dict]:
        """
        Convert specs to kanban_create kwargs, replacing task names in parents with IDs.
        Call incrementally: after each kanban_create returns, update task_name_to_id then
        call resolve_parents on the remaining specs.
        """
        out = []
        for s in specs:
            d = s.to_dict()
            if "parents" in d:
                resolved = [task_name_to_id[p] for p in d["parents"] if p in task_name_to_id]
                if resolved:
                    d["parents"] = resolved
                else:
                    d.pop("parents", None)
            out.append({"_task_name": s._task_name, "kwargs": d})
        return out

    # ----- Phase 7: Monitor -----

    def setup_monitoring_plan(
        self,
        task_ids: list[str],
        poll_every: str = "every 10m",
        escalate_after: str = "every 1h",
        deliver: str = "origin",
    ) -> list[CronSpec]:
        if not task_ids:
            return []
        ids_str = ", ".join(task_ids)
        ts = int(time.time())
        return [
            CronSpec(
                name=f"chief-monitor-{ts}",
                schedule=poll_every,
                deliver=deliver,
                prompt=(
                    "You are the chief-manager monitor cron. "
                    f"Call kanban_show on each task id in [{ids_str}] and report status. "
                    "If any are blocked, load chief-manager skill, run "
                    "Chief().classify_failure(task_show_result) and recommend action. "
                    "If all are done, summarize handoffs via Chief().collect_handoffs(...)."
                ),
            ),
            CronSpec(
                name=f"chief-escalate-{ts}",
                schedule=escalate_after,
                deliver=deliver,
                prompt=(
                    "You are the chief-manager escalation cron. "
                    f"Check tasks [{ids_str}]. If any have been status=blocked for >1h, "
                    "escalate to the user with classification + recommended action."
                ),
            ),
        ]

    # ----- Failure classification proxy -----

    def classify_failure(self, task_show_result: dict) -> FailureClassification:
        return classify_failure(task_show_result)

    # ----- Phase 7: Synthesis -----

    def collect_handoffs(self, task_show_results: dict[str, dict]) -> dict:
        """
        Input: {task_id: kanban_show_result_dict}
        Output: {"all_done", "summaries", "metadata", "issues", "synthesis_input"}
        """
        summaries = {}
        metadata = {}
        issues = []
        for tid, show in task_show_results.items():
            inner = show.get("task", show)  # kanban_show may wrap in {"task": {...}}
            status = inner.get("status")
            if status != "done":
                issues.append(f"{tid}: status={status}")
                continue
            summaries[tid] = inner.get("summary") or inner.get("result", "")
            metadata[tid] = inner.get("metadata", {}) or {}
        synthesis_input = {
            "summaries": summaries,
            "metadata": metadata,
            "n_tasks": len(task_show_results),
            "n_done": len(summaries),
        }
        return {
            "all_done": len(issues) == 0,
            "summaries": summaries,
            "metadata": metadata,
            "issues": issues,
            "synthesis_input": synthesis_input,
        }

    # ----- Internal: retry wrapper (EvoAgentX pattern) -----

    @staticmethod
    def execute_with_retry(name: str, op: Callable, retries: int = 1, **kwargs) -> Any:
        """Exponential backoff wrapper for heavy operations."""
        attempts = 0
        while attempts <= retries:
            try:
                return op(**kwargs)
            except Exception as e:
                if attempts == retries:
                    raise ValueError(f"{name} failed after {attempts + 1} attempts: {e}") from e
                time.sleep(2 ** attempts)
                attempts += 1

    # ----- Diagnostic dump -----

    def dump_state(self, workflow: Optional[Workflow] = None) -> dict:
        """Return a JSON-serializable snapshot for debugging."""
        out = {
            "goal_text": self.goal_text,
            "profiles_dir": self.profiles_dir,
            "profiles_known": [p.name for p in self.profiles()],
        }
        if workflow:
            out["plan"] = {
                "topo_order": workflow.plan.topo_order,
                "edges": [e.to_dict() for e in workflow.plan.edges],
                "n_tasks": len(workflow.plan.task_tree.tasks),
            }
            out["assignments"] = [
                {"task": a.task_name, "profile": a.profile,
                 "skills": a.required_skills, "tools": a.required_tools}
                for a in workflow.assignments
            ]
            if workflow.capability_matrix:
                out["has_gaps"] = workflow.capability_matrix.has_gaps()
        return out


__all__ = [
    "Chief",
    "KanbanCreateSpec",
    "CronSpec",
]
