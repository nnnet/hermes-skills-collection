"""
Failure taxonomy classifier for blocked Kanban tasks.

Given a kanban_show result for a blocked task, classify into one of 8 types
and recommend a corrective action.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class FailureType(str, Enum):
    HALLUCINATION = "hallucination"
    MISSING_TOOL = "missing_tool"
    MISSING_SKILL = "missing_skill"
    TIMEOUT = "timeout"
    DEPENDENCY_UNMET = "dependency_unmet"
    AMBIGUOUS_SPEC = "ambiguous_spec"
    NO_CAPABLE_AGENT = "no_capable_agent"
    UNKNOWN = "unknown"


@dataclass
class FailureClassification:
    type: FailureType
    confidence: float  # 0..1
    signals: list[str] = field(default_factory=list)
    action: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "confidence": round(self.confidence, 2),
            "signals": self.signals,
            "action": self.action,
        }


# Regex patterns. (?i) on join via flags=IGNORECASE below.
_PATTERNS: dict[FailureType, list[str]] = {
    FailureType.MISSING_TOOL: [
        r"tool not found",
        r"unknown tool",
        r"mcp server[^.]{0,40}not[^.]{0,20}connect",
        r"no such tool",
        r"command not found",
        r"toolset .+ not (registered|available)",
        r"401 unauthorized",  # often config.yaml missing API key
    ],
    FailureType.MISSING_SKILL: [
        r"skill[^.]{0,30}not[^.]{0,10}found",
        r"no skill named",
        r"skill_view\([^)]*\)[^.]*failed",
        r"skill .+ does not exist",
    ],
    FailureType.TIMEOUT: [
        r"\btimed[\s_-]?out\b",
        r"max_runtime_seconds[^.]{0,30}exceeded",
        r"sigterm",
        r"killed[^.]{0,20}timeout",
        r"deadline exceeded",
        r"iteration budget exhausted",
        r"\b60/60\b",
        r"could not complete within the allowed iterations",
    ],
    FailureType.AMBIGUOUS_SPEC: [
        r"please (specify|confirm|provide|clarify)",
        r"which (one|of|version|option)",
        r"unclear (whether|if|what|how)",
        r"need clarification",
        r"could you (specify|clarify|tell)",
    ],
    FailureType.DEPENDENCY_UNMET: [
        r"parent[^.]{0,30}not[^.]{0,10}done",
        r"missing[^.]{0,30}output from",
        r"depends on[^.]{0,30}unavailable",
        r"no input data",
        r"upstream task[^.]{0,30}failed",
    ],
    FailureType.HALLUCINATION: [
        r"(indexed|processed|created|saved)\s+\d+",
    ],
    FailureType.NO_CAPABLE_AGENT: [
        r"no capable agent",
        r"cannot (do|execute|complete) this task",
        r"out of scope for this profile",
        r"this profile lacks",
    ],
}


_ACTION_TEMPLATES: dict[FailureType, str] = {
    FailureType.HALLUCINATION: (
        "Patch SOUL.md to add a verification gate (e.g., count_after > count_before "
        "before kanban_complete). Re-dispatch. See skill: soul-md-authoring."
    ),
    FailureType.MISSING_TOOL: (
        "Edit profile config.yaml to add the required MCP server, restart Hermes "
        "(make restart from /opt/hermes). Then kanban_unblock + re-dispatch."
    ),
    FailureType.MISSING_SKILL: (
        "Install or create the missing skill via skill_manage(action='create',...). "
        "Add skill_view(name='...') to profile's SOUL.md. Re-dispatch."
    ),
    FailureType.TIMEOUT: (
        "Either decompose the task into smaller subtasks or raise "
        "max_runtime_seconds. Long-running ML training should use background terminals."
    ),
    FailureType.DEPENDENCY_UNMET: (
        "Read parent task's kanban_show. If parent done but output insufficient, "
        "fix parent's SOUL.md first. Otherwise unblock parent before this one."
    ),
    FailureType.AMBIGUOUS_SPEC: (
        "Read clarifying question in kanban_block(reason=...). Update task body with "
        "answer, then kanban_unblock."
    ),
    FailureType.NO_CAPABLE_AGENT: (
        "Stop. Either renegotiate task scope with user, or build the missing agent "
        "profile (SOUL.md + config.yaml + required MCP servers) before re-dispatch."
    ),
    FailureType.UNKNOWN: (
        "Inspect kanban_show comments and events manually. If this is a recurring "
        "class, extend failures._PATTERNS with the new signal."
    ),
}


def _verification_present(text: str) -> bool:
    """Heuristic: does the text mention an objective verification step?"""
    markers = [
        r"verif", r"chroma\.count", r"count_after", r"len\(", r"assert",
        r"check\s+(?:that|if|whether)",
    ]
    return any(re.search(m, text, flags=re.IGNORECASE) for m in markers)


def classify_failure(task_show_result: dict) -> FailureClassification:
    """
    task_show_result is the dict returned by kanban_show(task_id).
    Expected (best-effort) keys: title, body, comments[], events[], status.
    """
    parts = []
    parts.append(task_show_result.get("body", ""))
    parts.append(task_show_result.get("title", ""))
    parts.append(task_show_result.get("summary", "") or task_show_result.get("result", ""))
    for c in task_show_result.get("comments", []):
        if isinstance(c, dict):
            parts.append(c.get("body", ""))
        else:
            parts.append(str(c))
    for e in task_show_result.get("events", []):
        if isinstance(e, dict):
            payload = e.get("payload", {}) or {}
            parts.append(e.get("message", "") or e.get("type", "") or payload.get("reason", ""))
        else:
            parts.append(str(e))
    for run in task_show_result.get("runs", []):
        if isinstance(run, dict):
            parts.append(run.get("summary", "") or "")
            parts.append(run.get("outcome", "") or "")
    haystack = "\n".join(p for p in parts if p)

    scores: dict[FailureType, list[str]] = {ft: [] for ft in FailureType}
    for ftype, patterns in _PATTERNS.items():
        for pat in patterns:
            for m in re.finditer(pat, haystack, flags=re.IGNORECASE):
                scores[ftype].append(m.group(0).strip())

    # Hallucination heuristic: count claim AND no verification language
    if scores[FailureType.HALLUCINATION] and _verification_present(haystack):
        scores[FailureType.HALLUCINATION] = []  # false positive — verification IS present

    best_type = max(scores, key=lambda k: len(scores[k]))
    signals = list(dict.fromkeys(scores[best_type]))  # dedupe, preserve order
    if not signals:
        return FailureClassification(
            type=FailureType.UNKNOWN,
            confidence=0.0,
            signals=[],
            action=_ACTION_TEMPLATES[FailureType.UNKNOWN],
        )

    confidence = min(1.0, 0.3 + 0.2 * len(signals))
    return FailureClassification(
        type=best_type,
        confidence=confidence,
        signals=signals[:5],
        action=_ACTION_TEMPLATES[best_type],
    )


def all_failure_types() -> list[str]:
    return [ft.value for ft in FailureType]
