"""
Profile Loadout — model + tools selector for Hermes subagents.

Piece 1 (DONE):
    discover_tools(hermes_bin=None)        → tool inventory
    classify_models(config_path=None)      → models bucketed by tier

Piece 2 (TODO):
    plan_loadout(role, soul_text, ...)     → full loadout spec

Piece 3 (TODO):
    apply_to_profile(profile_dir, loadout) → write config.yaml + SOUL.md section

Run as CLI:
    python loadout.py tools
    python loadout.py models
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml


DEFAULT_CONFIG_PATH = "/opt/data/config.yaml"
DEFAULT_HERMES_BIN = "hermes"


# ============================================================
# Tier classification — regex patterns over model names
# ============================================================
# Order matters: first match wins. Patterns are case-insensitive.
# Match handles both 'provider/model' and bare 'model' forms.
TIER_PATTERNS: dict[str, list[str]] = {
    "tier1": [
        r"\bclaude[-/]?opus",
        r"\bgpt-?5(\.\d+)?(?!-mini|-nano)",   # gpt-5, gpt-5-pro — exclude mini/nano
        r"\bglm-?5",
        r"\bgrok-?4(\.\d+)?",
        r"\bdeepseek-?v?4",
        r"\bgemini-?3(\.\d+)?-pro",
        r"\bnemotron-?3-super",
    ],
    "tier2": [
        r"\bclaude[-/]?sonnet",
        r"\bclaude[-/]?haiku-?4[-.]?7",       # haiku 4.7 acts more like sonnet
        r"\bmimo[-/]?v?2",
        r"\bkimi-?k2",
        r"\bqwen3?(\.\d+)?[-_]?plus",
        r"\bqwen3?(\.\d+)?[-_]?35b",
        r"\bgpt-?5[-_]?mini",
        r"\bgpt-?4o?(?!-mini)",                # gpt-4o, gpt-4; exclude gpt-4o-mini → T3
        r"\bgemini-?3(\.\d+)?-flash",
        r"\bstep-?3",
        r"\bminimax-?m2",
        r"\bhy3",
    ],
    "tier3": [
        r"\bclaude[-/]?haiku-?4[-.]?5",
        r"\bclaude[-/]?haiku-?4[-.]?6",
        r"\bgpt-?5[-_]?nano",
        r"\bgpt-?oss-?20b",
        r"\bgpt-?oss-?7b",
        r"\bmistral-?7b",
        r"\bgemma-?\d",
        r"\bllama-?3",
    ],
}


def _classify_one(model_name: str) -> str:
    """Return tier1|tier2|tier3|unclassified for a model name."""
    if not model_name:
        return "unclassified"
    for tier, patterns in TIER_PATTERNS.items():
        for p in patterns:
            if re.search(p, model_name, re.IGNORECASE):
                return tier
    return "unclassified"


# ============================================================
# Tool discovery
# ============================================================

# ---- Static reference data ----
# Approximate tool counts per MCP server, captured from a live `hermes tools list`
# snapshot 2026-05-16. Used when we can only see the server list (config parse)
# and not the actual tool registrations. Update from a fresh CLI snapshot when
# servers are added/removed.
MCP_TOOL_COUNTS: dict[str, int] = {
    "brave_search": 2,
    "browsermcp": 14,
    "chroma": 17,
    "codebase-memory": 8,
    "db_alchemy": 6,
    "duckduckgo": 6,
    "everything": 18,
    "fetch": 3,
    "filesystem": 14,
    "gh_grep": 1,
    "git": 12,
    "github": 30,
    "huly": 12,
    "memory": 9,
    "plane": 20,
    "playwright": 23,
    "postgres": 8,
    "sequential_thinking": 1,
    "sqlite": 10,
    "time": 2,
    "youtube_transcript": 1,
}

# Built-in toolset categories declared in config.yaml `toolsets:`. Each
# expands into a fixed set of native Hermes tools (not MCP). Counts are
# approximate based on the 33-tool snapshot.
BUILTIN_TOOLSET_COUNTS: dict[str, int] = {
    "hermes-cli": 18,   # file/search/terminal/web/skill/memory etc
    "kanban": 7,        # kanban_show/create/complete/comment/heartbeat/block/unblock
    "moa": 2,           # delegate_task, execute_code
    "debugging": 2,     # process, others
    "image_gen": 1,
    "video": 1,
}


def discover_tools(config_path: Optional[str] = None) -> dict:
    """
    Parse the Hermes config.yaml and return a tool inventory.

    We read directly from config.yaml rather than calling `hermes tools list`
    because (a) the host hermes CLI is unreliable across container/venv
    installs, (b) parsing is faster and has no startup cost, (c) we only need
    server names + counts, not full tool schemas.

    Returns:
        {
            "toolsets": {"toolset_name": tool_count, ...},
            "mcp_servers": {"server_name": {"enabled": bool, "tool_count": N}, ...},
            "enabled_mcp_servers": ["server_name", ...],   # only enabled
            "configured_toolsets": ["toolset_name", ...],  # from top-level toolsets:
            "total_builtin": int,
            "total_mcp_enabled": int,
            "total_enabled": int,
            "error": None | str,
        }
    """
    path = config_path or DEFAULT_CONFIG_PATH
    empty = {
        "toolsets": {},
        "mcp_servers": {},
        "enabled_mcp_servers": [],
        "configured_toolsets": [],
        "total_builtin": 0,
        "total_mcp_enabled": 0,
        "total_enabled": 0,
        "error": None,
    }
    if not Path(path).exists():
        return {**empty, "error": f"config not found: {path}"}

    try:
        cfg = yaml.safe_load(Path(path).read_text())
    except Exception as e:
        return {**empty, "error": f"yaml parse error: {e}"}
    if not isinstance(cfg, dict):
        return {**empty, "error": "config root is not a mapping"}

    # MCP servers — read enabled flag, count from static table
    mcp_raw = cfg.get("mcp_servers") or {}
    mcp: dict[str, dict] = {}
    enabled_servers: list[str] = []
    if isinstance(mcp_raw, dict):
        for server, spec in mcp_raw.items():
            enabled = True if not isinstance(spec, dict) else bool(spec.get("enabled", True))
            count = MCP_TOOL_COUNTS.get(server, 0)
            mcp[server] = {"enabled": enabled, "tool_count": count}
            if enabled:
                enabled_servers.append(server)

    # Configured toolsets from top-level toolsets:
    cfg_toolsets = cfg.get("toolsets") or []
    if not isinstance(cfg_toolsets, list):
        cfg_toolsets = []

    # Toolset counts (filtered to those actually configured)
    toolsets = {t: BUILTIN_TOOLSET_COUNTS.get(t, 0) for t in cfg_toolsets}

    total_builtin = sum(toolsets.values())
    total_mcp_enabled = sum(mcp[s]["tool_count"] for s in enabled_servers)

    return {
        "toolsets": toolsets,
        "mcp_servers": mcp,
        "enabled_mcp_servers": sorted(enabled_servers),
        "configured_toolsets": sorted(cfg_toolsets),
        "total_builtin": total_builtin,
        "total_mcp_enabled": total_mcp_enabled,
        "total_enabled": total_builtin + total_mcp_enabled,
        "error": None,
    }


# ============================================================
# Model classification (config.yaml — level 3 only)
# ============================================================

def _extract_models_from_config(cfg: dict, include_auxiliary: bool = False) -> dict:
    """Walk the parsed config and return a categorised list of model strings."""
    out = {
        "default": None,
        "providers": {},          # provider_key → [model_names]
        "fallback_chain": [],     # in order
        "auxiliary": {},          # auxiliary_kind → model_name
    }

    # model.default
    m = (cfg.get("model") or {})
    if isinstance(m, dict):
        out["default"] = m.get("default")

    # providers.<key>.models + providers.<key>.default_model
    provs = cfg.get("providers") or {}
    if isinstance(provs, dict):
        for key, p in provs.items():
            if not isinstance(p, dict):
                continue
            names = set()
            for n in p.get("models") or []:
                if isinstance(n, str):
                    names.add(n)
            if isinstance(p.get("default_model"), str):
                names.add(p["default_model"])
            if names:
                out["providers"][key] = sorted(names)

    # fallback_providers
    fp = cfg.get("fallback_providers") or []
    if isinstance(fp, list):
        for entry in fp:
            if isinstance(entry, dict):
                name = entry.get("model")
                if isinstance(name, str):
                    out["fallback_chain"].append(name)

    # auxiliary.*.model
    if include_auxiliary:
        aux = cfg.get("auxiliary") or {}
        if isinstance(aux, dict):
            for kind, a in aux.items():
                if isinstance(a, dict) and isinstance(a.get("model"), str) and a["model"]:
                    out["auxiliary"][kind] = a["model"]

    return out


def classify_models(
    config_path: Optional[str] = None,
    include_auxiliary: bool = False,
) -> dict:
    """
    Parse the user's Hermes config.yaml and bucket every configured model
    into T1/T2/T3/unclassified.

    Args:
        config_path: Path to config.yaml. Defaults to /opt/data/config.yaml.
        include_auxiliary: Include auxiliary.*.model entries (compression,
            embedding). These are NOT for agent loadout; default off.

    Returns:
        {
            "default": "claude-opus-4-7",
            "default_tier": "tier1",
            "fallback_chain": ["claude-sonnet-4-6", ...],
            "tier1": [model, ...],
            "tier2": [model, ...],
            "tier3": [model, ...],
            "unclassified": [model, ...],
            "by_source": {
                "default": [...],
                "providers": {provider_key: [...]},
                "fallback_chain": [...],
                "auxiliary": {kind: model_name},
            },
            "error": None | str,
        }
    """
    empty = {
        "default": None,
        "default_tier": "unclassified",
        "fallback_chain": [],
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "unclassified": [],
        "by_source": {},
        "error": None,
    }
    path = config_path or DEFAULT_CONFIG_PATH
    if not Path(path).exists():
        return {**empty, "error": f"config not found: {path}"}

    try:
        cfg = yaml.safe_load(Path(path).read_text())
    except Exception as e:
        return {**empty, "error": f"yaml parse error: {e}"}

    if not isinstance(cfg, dict):
        return {**empty, "error": "config root is not a mapping"}

    sources = _extract_models_from_config(cfg, include_auxiliary=include_auxiliary)

    # Collect unique models, preserving source info
    all_models: set[str] = set()
    if sources["default"]:
        all_models.add(sources["default"])
    for names in sources["providers"].values():
        all_models.update(names)
    all_models.update(sources["fallback_chain"])
    if include_auxiliary:
        all_models.update(sources["auxiliary"].values())

    # Classify
    buckets = {"tier1": set(), "tier2": set(), "tier3": set(), "unclassified": set()}
    for m in all_models:
        buckets[_classify_one(m)].add(m)

    return {
        "default": sources["default"],
        "default_tier": _classify_one(sources["default"]),
        "fallback_chain": list(sources["fallback_chain"]),
        "tier1": sorted(buckets["tier1"]),
        "tier2": sorted(buckets["tier2"]),
        "tier3": sorted(buckets["tier3"]),
        "unclassified": sorted(buckets["unclassified"]),
        "by_source": sources,
        "error": None,
    }


# ============================================================
# Role rubric — role → recommended loadout
# ============================================================
# Each entry: {
#   tier: T1|T2|T3,
#   toolsets: [...],            # builtin toolsets ALWAYS needed
#   mcp_servers: [...],         # MCP servers ALWAYS needed
#   suggested_tools: [...],     # specific MCP tools (server:tool) likely needed
#                               # (not enforced; just shortlist for SOUL)
# }
# Match is by substring against role string (lowercase). First match wins.
ROLE_RUBRIC: dict[str, dict] = {
    # T1 — heavy reasoning
    "orchestrator": {
        "tier": "tier1",
        "toolsets": ["kanban", "hermes-cli"],
        "mcp_servers": ["sequential_thinking"],
        "suggested_tools": ["kanban_show", "kanban_create", "kanban_complete",
                            "kanban_block", "kanban_comment", "skill_view"],
    },
    "chief": {
        "tier": "tier1",
        "toolsets": ["kanban", "hermes-cli"],
        "mcp_servers": ["sequential_thinking"],
        "suggested_tools": ["kanban_show", "kanban_create", "kanban_complete",
                            "kanban_comment", "skill_view"],
    },
    "reviewer": {
        "tier": "tier1",
        "toolsets": ["kanban", "hermes-cli"],
        "mcp_servers": ["git"],
        "suggested_tools": ["kanban_show", "kanban_comment", "kanban_complete",
                            "read_file", "search_files", "git_diff"],
    },
    "critic": {
        "tier": "tier1",
        "toolsets": ["kanban", "hermes-cli"],
        "mcp_servers": ["sequential_thinking"],
        "suggested_tools": ["kanban_show", "kanban_comment", "skill_view"],
    },
    # T2 — standard agent work
    "planner": {
        "tier": "tier2",
        "toolsets": ["kanban", "hermes-cli"],
        "mcp_servers": ["sequential_thinking"],
        "suggested_tools": ["kanban_show", "kanban_complete", "kanban_block",
                            "execute_code", "skill_view"],
    },
    "decomposer": {
        "tier": "tier2",
        "toolsets": ["kanban", "hermes-cli"],
        "mcp_servers": ["filesystem", "sequential_thinking"],
        "suggested_tools": ["kanban_show", "kanban_complete", "kanban_block",
                            "execute_code", "skill_view", "write_file"],
    },
    "analyst": {
        "tier": "tier2",
        "toolsets": ["kanban", "hermes-cli"],
        "mcp_servers": ["chroma", "sqlite"],
        "suggested_tools": ["kanban_show", "kanban_complete", "execute_code",
                            "read_file", "search_files"],
    },
    "expert": {
        "tier": "tier2",
        "toolsets": ["kanban", "hermes-cli"],
        "mcp_servers": ["chroma", "fetch"],
        "suggested_tools": ["kanban_show", "kanban_complete", "kanban_comment",
                            "web_search", "web_extract", "execute_code"],
    },
    "synthesizer": {
        "tier": "tier2",
        "toolsets": ["kanban", "hermes-cli"],
        "mcp_servers": ["chroma"],
        "suggested_tools": ["kanban_show", "kanban_complete", "kanban_comment",
                            "read_file", "write_file"],
    },
    # T3 — cheap mechanical
    "indexer": {
        "tier": "tier3",
        "toolsets": ["kanban"],
        "mcp_servers": ["chroma", "filesystem"],
        "suggested_tools": ["kanban_show", "kanban_complete", "kanban_block",
                            "chroma_add_documents", "chroma_get_collection_count"],
    },
    "scraper": {
        "tier": "tier3",
        "toolsets": ["kanban"],
        "mcp_servers": ["fetch", "duckduckgo", "playwright"],
        "suggested_tools": ["kanban_show", "kanban_complete", "kanban_block",
                            "web_extract", "fetch", "write_file"],
    },
    "fetcher": {
        "tier": "tier3",
        "toolsets": ["kanban"],
        "mcp_servers": ["fetch"],
        "suggested_tools": ["kanban_show", "kanban_complete", "fetch", "web_extract"],
    },
    "formatter": {
        "tier": "tier3",
        "toolsets": ["kanban"],
        "mcp_servers": ["filesystem"],
        "suggested_tools": ["kanban_show", "kanban_complete", "read_file", "write_file"],
    },
    "transcriber": {
        "tier": "tier3",
        "toolsets": ["kanban"],
        "mcp_servers": ["youtube_transcript"],
        "suggested_tools": ["kanban_show", "kanban_complete", "youtube_transcript_get_transcript"],
    },
}


def _match_role(role: str) -> Optional[str]:
    """Find the rubric key whose name is a substring of `role` (case-insens).
    Returns the rubric key, not the full dict. First/longest match wins."""
    if not role:
        return None
    lo = role.lower()
    # Prefer longer keys so "task-decomposer" matches "decomposer" not "expert"
    for key in sorted(ROLE_RUBRIC.keys(), key=len, reverse=True):
        if key in lo:
            return key
    return None


def _extract_soul_section(soul_text: str, header: str) -> Optional[str]:
    """Pull a markdown section by '## <header>' until next '## ' or EOF."""
    if not soul_text:
        return None
    pat = rf"##\s+{re.escape(header)}\s*\n(.*?)(?=\n##\s|\Z)"
    m = re.search(pat, soul_text, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else None


def _parse_soul_tier_override(soul_text: str) -> Optional[str]:
    """Return 'tier1'|'tier2'|'tier3' if SOUL declares '## Model requirement'."""
    sec = _extract_soul_section(soul_text, "Model requirement")
    if not sec:
        return None
    s = sec.lower()
    for t in ("tier1", "tier2", "tier3"):
        if t in s.replace(" ", "").replace("-", ""):
            return t
    # Allow direct model name overrides — caller decides what to do
    return None


def _parse_soul_required_tools(soul_text: str) -> list[str]:
    """Parse '## Required tools' section, return flat list of tool names.
    Accepts bullet lines like '- kanban: kanban_show, kanban_complete'
    or '- skill_view' (one tool per bullet)."""
    sec = _extract_soul_section(soul_text, "Required tools")
    if not sec:
        return []
    tools: list[str] = []
    for line in sec.splitlines():
        line = line.strip().lstrip("-*").strip()
        if not line:
            continue
        # Drop 'category:' prefix if present
        if ":" in line:
            line = line.split(":", 1)[1]
        for t in line.split(","):
            t = t.strip()
            if t and not t.startswith("#"):
                tools.append(t)
    return tools


# Tier → soft tool count cap
TIER_TOOL_CAP: dict[str, int] = {"tier1": 50, "tier2": 30, "tier3": 15}


def _pick_model_for_tier(
    tier: str,
    available: dict,
    prefer_default: bool = True,
) -> Optional[str]:
    """Pick the best model for a tier from classify_models() output.
    Falls back to the next tier down if requested tier is empty."""
    candidates = available.get(tier) or []
    if prefer_default and available.get("default") in candidates:
        return available["default"]
    if candidates:
        return candidates[0]
    # Fallback: tier1 → tier2 → tier3
    order = {"tier1": ["tier2", "tier3"], "tier2": ["tier3", "tier1"], "tier3": ["tier2", "tier1"]}
    for fb in order.get(tier, []):
        c = available.get(fb) or []
        if c:
            return c[0]
    return available.get("default")


def plan_loadout(
    role: str,
    soul_text: str = "",
    config_path: Optional[str] = None,
    extra_mcp_servers: Optional[list[str]] = None,
    extra_toolsets: Optional[list[str]] = None,
) -> dict:
    """
    Compute a full loadout spec for a subagent profile.

    Resolution order:
      1. SOUL.md `## Model requirement: tier2` → forced tier
      2. SOUL.md `## Required tools` whitelist → forced tools (overrides rubric)
      3. ROLE_RUBRIC lookup by role substring → default tier + toolsets + servers
      4. Extra additions from caller args

    Args:
        role: role name (e.g. "task-decomposer", "cmf-chief", "youtube-indexer")
        soul_text: full SOUL.md contents (optional). If provided, mined for
            ## Model requirement and ## Required tools sections.
        config_path: path to config.yaml. Defaults to /opt/data/config.yaml.
        extra_mcp_servers: append these MCP servers to the rubric's defaults.
        extra_toolsets: append these toolsets to the rubric's defaults.

    Returns:
        {
            "role": str,
            "matched_rubric": str | None,   # which rubric key matched
            "tier": "tier1"|"tier2"|"tier3",
            "tier_source": "soul"|"rubric"|"default",
            "model": str,                   # chosen model id
            "model_source": "available_default"|"available_other"|"fallback",
            "toolsets": [str, ...],
            "mcp_servers": [str, ...],
            "suggested_tools": [str, ...],  # full whitelist (rubric + extras)
            "expected_tool_count": int,
            "tool_cap": int,
            "over_budget": bool,
            "reasoning": [str, ...],        # one bullet per decision
            "warnings": [str, ...],
            "error": None | str,
        }
    """
    reasoning: list[str] = []
    warnings: list[str] = []

    tools_inv = discover_tools(config_path)
    models = classify_models(config_path)

    if tools_inv["error"]:
        warnings.append(f"discover_tools error: {tools_inv['error']}")
    if models["error"]:
        return {
            "error": f"classify_models error: {models['error']}",
            "role": role, "matched_rubric": None, "tier": None, "tier_source": None,
            "model": None, "model_source": None, "toolsets": [], "mcp_servers": [],
            "suggested_tools": [], "expected_tool_count": 0, "tool_cap": 0,
            "over_budget": False, "reasoning": reasoning, "warnings": warnings,
        }

    # 1. Match rubric by role
    matched = _match_role(role)
    if matched:
        rubric = ROLE_RUBRIC[matched]
        reasoning.append(f"Role '{role}' matched rubric '{matched}'")
    else:
        rubric = {
            "tier": "tier2",
            "toolsets": ["kanban", "hermes-cli"],
            "mcp_servers": [],
            "suggested_tools": ["kanban_show", "kanban_complete", "kanban_block"],
        }
        warnings.append(f"Role '{role}' not in rubric; using T2 default")
        reasoning.append("No rubric match → default T2 with kanban+hermes-cli")

    # 2. Tier resolution: SOUL > rubric > default
    soul_tier = _parse_soul_tier_override(soul_text) if soul_text else None
    if soul_tier:
        tier = soul_tier
        tier_source = "soul"
        reasoning.append(f"Tier {tier} forced by SOUL.md '## Model requirement'")
    else:
        tier = rubric["tier"]
        tier_source = "rubric" if matched else "default"
        reasoning.append(f"Tier {tier} from {'rubric' if matched else 'default'}")

    # 3. Tools: SOUL whitelist > rubric suggested
    soul_tools = _parse_soul_required_tools(soul_text) if soul_text else []
    if soul_tools:
        tools = soul_tools
        reasoning.append(f"Tools forced by SOUL.md '## Required tools' ({len(tools)} listed)")
    else:
        tools = list(rubric.get("suggested_tools", []))
        reasoning.append(f"Tools from rubric ({len(tools)} suggested)")

    # 4. Toolsets and MCP servers: rubric + extras
    toolsets = sorted(set(rubric.get("toolsets", [])) | set(extra_toolsets or []))
    mcp_servers = sorted(set(rubric.get("mcp_servers", [])) | set(extra_mcp_servers or []))
    if extra_toolsets:
        reasoning.append(f"Added toolsets: {extra_toolsets}")
    if extra_mcp_servers:
        reasoning.append(f"Added MCP servers: {extra_mcp_servers}")

    # 5. Verify MCP servers are actually enabled in main config
    for s in mcp_servers:
        info = tools_inv.get("mcp_servers", {}).get(s)
        if info is None:
            warnings.append(f"MCP server '{s}' not in config.yaml — will be missing at runtime")
        elif not info.get("enabled", True):
            warnings.append(f"MCP server '{s}' is disabled in config.yaml — enable before dispatch")

    # 6. Pick model
    model = _pick_model_for_tier(tier, models, prefer_default=True)
    if model is None:
        model_source = "fallback"
        warnings.append(f"No model for {tier} in config — caller must add one")
    elif model == models.get("default"):
        model_source = "available_default"
    elif model in (models.get(tier) or []):
        model_source = "available_other"
    else:
        model_source = "fallback"
        warnings.append(f"No {tier} model configured; using fallback from another tier")
    reasoning.append(f"Model '{model}' chosen ({model_source})")

    # 7. Budget check
    tool_count = sum(BUILTIN_TOOLSET_COUNTS.get(t, 0) for t in toolsets) \
               + sum(MCP_TOOL_COUNTS.get(s, 0) for s in mcp_servers)
    cap = TIER_TOOL_CAP.get(tier, 30)
    over = tool_count > cap
    if over:
        warnings.append(
            f"Tool budget exceeded: {tool_count} > {tier} cap of {cap}. "
            f"Consider upgrading tier or trimming MCP servers."
        )
    reasoning.append(f"Tool count: {tool_count} / cap {cap}")

    return {
        "role": role,
        "matched_rubric": matched,
        "tier": tier,
        "tier_source": tier_source,
        "model": model,
        "model_source": model_source,
        "toolsets": toolsets,
        "mcp_servers": mcp_servers,
        "suggested_tools": tools,
        "expected_tool_count": tool_count,
        "tool_cap": cap,
        "over_budget": over,
        "reasoning": reasoning,
        "warnings": warnings,
        "error": None,
    }


# ============================================================
# CLI
# ============================================================

def _cli():
    if len(sys.argv) < 2:
        print("usage: loadout.py {tools|models|both} [--full]")
        sys.exit(2)
    cmd = sys.argv[1]
    full = "--full" in sys.argv
    if cmd in ("tools", "both"):
        t = discover_tools()
        if full:
            print(json.dumps(t, ensure_ascii=False, indent=2))
        else:
            if t["error"]:
                print(f"[tools] ERROR: {t['error']}")
            else:
                print(f"[tools] total_enabled={t['total_enabled']} "
                      f"(builtin={t['total_builtin']}, mcp_enabled={t['total_mcp_enabled']})")
                print(f"  toolsets configured: {t['configured_toolsets']}")
                print(f"  MCP servers enabled: {len(t['enabled_mcp_servers'])} of {len(t['mcp_servers'])}")
                for s, info in sorted(t["mcp_servers"].items()):
                    flag = "ON " if info["enabled"] else "off"
                    print(f"    [{flag}] {s}: {info['tool_count']} tools")
    if cmd in ("models", "both"):
        m = classify_models(include_auxiliary="--auxiliary" in sys.argv)
        if full:
            print(json.dumps(m, ensure_ascii=False, indent=2))
        else:
            if m["error"]:
                print(f"[models] ERROR: {m['error']}")
            else:
                print(f"[models] default={m['default']} ({m['default_tier']})")
                for tier in ("tier1", "tier2", "tier3", "unclassified"):
                    print(f"  {tier}: {m[tier]}")


if __name__ == "__main__":
    _cli()
