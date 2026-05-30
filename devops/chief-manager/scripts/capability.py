"""
Profile discovery and gap analysis.

A Hermes profile at /opt/data/profiles/<name>/ must have:
- SOUL.md (role + skills/tools referenced)
- config.yaml (MCP servers, model, etc.)

This module reads both, then matches against task requirements to compute Gaps.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None


PROFILES_DIR = "/opt/data/profiles"


@dataclass
class Profile:
    name: str
    profile_dir: str
    soul_md_path: Optional[str] = None
    config_yaml_path: Optional[str] = None
    skills_referenced: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    tools_mentioned: list[str] = field(default_factory=list)
    soul_text: str = ""

    def is_ready(self) -> bool:
        return bool(self.soul_md_path and self.config_yaml_path)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("soul_text", None)
        return d


@dataclass
class Gap:
    profile: str
    type: str  # missing_soul | missing_config | missing_skill | missing_mcp | no_capable_agent
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CapabilityRow:
    task_name: str
    suggested_profile: Optional[str]
    alternatives: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)

    def has_gaps(self) -> bool:
        return bool(self.gaps)

    def to_dict(self) -> dict:
        return {
            "task_name": self.task_name,
            "suggested_profile": self.suggested_profile,
            "alternatives": self.alternatives,
            "required_skills": self.required_skills,
            "required_tools": self.required_tools,
            "gaps": [g.to_dict() for g in self.gaps],
        }


@dataclass
class CapabilityMatrix:
    rows: list[CapabilityRow] = field(default_factory=list)

    def has_gaps(self) -> bool:
        return any(r.has_gaps() for r in self.rows)

    def gaps_by_profile(self) -> dict[str, list[Gap]]:
        out: dict[str, list[Gap]] = {}
        for row in self.rows:
            for gap in row.gaps:
                out.setdefault(gap.profile, []).append(gap)
        return out

    def render(self) -> str:
        lines = [
            "| Task | Profile | Alternatives | Skills | Tools | Gaps |",
            "|---|---|---|---|---|---|",
        ]
        for r in self.rows:
            gaps_str = "; ".join(f"`{g.type}` {g.detail}" for g in r.gaps) or "—"
            lines.append(
                f"| {r.task_name} | {r.suggested_profile or '⚠️ none'} "
                f"| {','.join(r.alternatives) or '—'} "
                f"| {','.join(r.required_skills) or '—'} "
                f"| {','.join(r.required_tools) or '—'} "
                f"| {gaps_str} |"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"rows": [r.to_dict() for r in self.rows]}


# ============================================================
# SOUL.md / config.yaml parsing
# ============================================================

_SKILL_REF_RE = re.compile(r"""skill_view\s*\(\s*name\s*=\s*['"]([\w\-]+)['"]""")
_SKILL_ANGLE_RE = re.compile(r"""<skill[^>]*name=['"]([\w\-]+)['"]""")
_MCP_TOOL_RE = re.compile(r"""(?:mcp[_-]|MCP:\s*)([a-z][a-z0-9_]+)""", re.IGNORECASE)
_TOOL_CALL_RE = re.compile(r"""(?:^|\s)([a-z][a-z0-9_]{3,})\s*\(""", re.MULTILINE)


def parse_soul_md(path: str) -> tuple[list[str], list[str], str]:
    """Returns (skills_referenced, tools_mentioned, full_text)."""
    if not path or not os.path.exists(path):
        return [], [], ""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    skills = sorted(set(_SKILL_REF_RE.findall(text)) | set(_SKILL_ANGLE_RE.findall(text)))
    tools = sorted(set(m for m in _TOOL_CALL_RE.findall(text) if len(m) > 3))
    return skills, tools, text


def parse_config_yaml(path: str) -> list[str]:
    """Returns list of MCP server names from config.yaml."""
    if not path or not os.path.exists(path) or yaml is None:
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return []
    mcp = cfg.get("mcp", {})
    if not isinstance(mcp, dict):
        return []
    servers = mcp.get("servers", {})
    if isinstance(servers, dict):
        return sorted(servers.keys())
    if isinstance(servers, list):
        names = []
        for s in servers:
            if isinstance(s, dict) and "name" in s:
                names.append(s["name"])
            elif isinstance(s, str):
                names.append(s)
        return sorted(names)
    return []


# ============================================================
# Discovery & matching
# ============================================================

def discover_profiles(profiles_dir: str = PROFILES_DIR) -> list[Profile]:
    """Walk profiles_dir, read SOUL.md + config.yaml for each."""
    profiles = []
    if not os.path.isdir(profiles_dir):
        return profiles
    for entry in sorted(os.listdir(profiles_dir)):
        pdir = os.path.join(profiles_dir, entry)
        if not os.path.isdir(pdir):
            continue
        soul_path = os.path.join(pdir, "SOUL.md")
        config_path = os.path.join(pdir, "config.yaml")
        soul_path = soul_path if os.path.exists(soul_path) else None
        config_path = config_path if os.path.exists(config_path) else None
        skills, tools, text = parse_soul_md(soul_path) if soul_path else ([], [], "")
        mcp_servers = parse_config_yaml(config_path)
        profiles.append(Profile(
            name=entry,
            profile_dir=pdir,
            soul_md_path=soul_path,
            config_yaml_path=config_path,
            skills_referenced=skills,
            mcp_servers=mcp_servers,
            tools_mentioned=tools,
            soul_text=text,
        ))
    return profiles


_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "with", "for", "in", "on", "at", "by",
    "is", "are", "was", "were", "be", "been", "this", "that", "it", "its",
    "и", "в", "на", "по", "из", "для", "с", "что", "как", "к",
}


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-zА-Яа-я0-9_]+", text.lower())) - _STOPWORDS


def suggest_profile_for_task(
    task_description: str,
    profiles: list[Profile],
    required_skills: Optional[list[str]] = None,
    required_tools: Optional[list[str]] = None,
) -> tuple[Optional[Profile], list[Profile]]:
    """
    Heuristic match. Score = 2*skill_match + 2*tool_match + keyword_match.
    Returns (best, alternatives_top3).
    """
    required_skills = required_skills or []
    required_tools = required_tools or []
    keywords = _tokenize(task_description)
    scores: list[tuple[float, Profile]] = []
    for p in profiles:
        if not p.is_ready():
            continue
        if required_skills:
            skill_match = len(set(p.skills_referenced) & set(required_skills)) / len(required_skills)
        else:
            skill_match = 0.0
        if required_tools:
            tool_match = len(set(p.mcp_servers) & set(required_tools)) / len(required_tools)
        else:
            tool_match = 0.0
        if keywords:
            keyword_match = len(_tokenize(p.soul_text) & keywords) / len(keywords)
        else:
            keyword_match = 0.0
        score = 2.0 * skill_match + 2.0 * tool_match + keyword_match
        if score > 0:
            scores.append((score, p))
    scores.sort(key=lambda x: -x[0])
    if not scores:
        return None, []
    best = scores[0][1]
    alts = [p for _, p in scores[1:4]]
    return best, alts


def find_gaps(
    profile: Optional[Profile],
    required_skills: list[str],
    required_tools: list[str],
) -> list[Gap]:
    gaps = []
    if profile is None:
        gaps.append(Gap("?", "no_capable_agent", "No profile matches task requirements"))
        return gaps
    if not profile.soul_md_path:
        gaps.append(Gap(profile.name, "missing_soul", f"{profile.profile_dir}/SOUL.md absent"))
    if not profile.config_yaml_path:
        gaps.append(Gap(profile.name, "missing_config", f"{profile.profile_dir}/config.yaml absent"))
    for skill in required_skills:
        if skill not in profile.skills_referenced:
            gaps.append(Gap(profile.name, "missing_skill",
                            f"SOUL.md doesn't load skill_view(name={skill!r})"))
    for tool in required_tools:
        if tool not in profile.mcp_servers:
            gaps.append(Gap(profile.name, "missing_mcp",
                            f"config.yaml mcp.servers missing {tool!r}"))
    return gaps


def build_capability_matrix(
    tasks_with_requirements: list[dict],
    profiles: Optional[list[Profile]] = None,
    profiles_dir: str = PROFILES_DIR,
) -> CapabilityMatrix:
    """
    tasks_with_requirements is a list of dicts:
        {"name": str, "description": str, "required_skills": [...], "required_tools": [...]}
    """
    if profiles is None:
        profiles = discover_profiles(profiles_dir)
    rows = []
    for spec in tasks_with_requirements:
        best, alts = suggest_profile_for_task(
            spec.get("description", ""),
            profiles,
            spec.get("required_skills", []),
            spec.get("required_tools", []),
        )
        gaps = find_gaps(best, spec.get("required_skills", []), spec.get("required_tools", []))
        rows.append(CapabilityRow(
            task_name=spec["name"],
            suggested_profile=best.name if best else None,
            alternatives=[a.name for a in alts],
            required_skills=spec.get("required_skills", []),
            required_tools=spec.get("required_tools", []),
            gaps=gaps,
        ))
    return CapabilityMatrix(rows=rows)
