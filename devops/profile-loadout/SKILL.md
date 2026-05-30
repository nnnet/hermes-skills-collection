---
name: profile-loadout
description: "Plan and apply a complete loadout (model tier + toolsets + MCP servers + required_tools) for a Hermes subagent profile. Load when creating a new profile or deciding what model and tools a subagent should get. Avoids the 'all 119 tools to every profile' anti-pattern by computing a focused loadout from role + SOUL.md + tool count budget."
metadata:
  hermes:
    tags: [orchestration, profile, model-selection, tools-budget, chief-manager]
    category: devops
    related_skills: [chief-manager, soul-md-authoring]
---

# Profile Loadout — model + tools selector for subagents

When `chief-manager` creates a new subagent profile (or audits an existing one),
this skill computes a **loadout**: which model tier, which toolsets, which MCP
servers, which specific tools the profile should get.

## Why this exists

LLMs degrade with tool count. Giving every profile all 119+ tools is an
anti-pattern: noise in context, slow selection, wrong tools picked. Each profile
should get the **minimum loadout** for its role.

Plus: model tier is not "always Opus" or "always Haiku" — it depends on the
task. A scraper needs T3, a planner needs T2, a reviewer needs T1.

## Three layers of model sources (we use #3)

1. **Static catalogs** in `/opt/hermes/hermes_cli/models.py` (3769 lines of
   provider snapshots: OpenRouter, Vercel, Anthropic, OpenAI). What *could*
   exist.
2. **Live API discovery** via `/v1/models` endpoints. What's *available right
   now* in the registry.
3. **Configured models** in `/opt/data/config.yaml`. What's *actually ready
   to use* without further setup.

We use **only level 3** — spawning a subagent on a model the user hasn't
configured = 401 instantly. Level 1/2 are for "help the user add a new model",
not for loadout planning.

## Tier rubric

| Tier | Typical models | Use for | Tool cap |
|---|---|---|---|
| **T1** | claude-opus-*, gpt-5*, glm-5* | orchestrator, reviewer, critic, deep synthesis | ≤ 50 |
| **T2** | claude-sonnet-*, mimo-v2*, claude-haiku-4-7* | planner, decomposer, domain expert, analyst | ≤ 30 |
| **T3** | claude-haiku-4-5*, gpt-oss-20b*, mistral-7b* | indexer, scraper, formatter, fetcher, mechanical work | ≤ 15 |

**Tool cap is soft.** Above the cap → warning in `plan_loadout()` output.
Heuristic: if a profile needs > cap tools, either upgrade tier or split into
multiple profiles.

## Role rubric (Phase 2)

Coming in Piece 2 — `plan_loadout(role, soul_text)`. For now, see
`TIER_PATTERNS` and `discover_tools()` in `scripts/loadout.py`.

## Usage (current capabilities — Piece 1)

```python
import sys
sys.path.insert(0, '/opt/data/skills/devops/profile-loadout/scripts')
from loadout import discover_tools, classify_models

# What tools exist in this Hermes installation?
inv = discover_tools()
# → {"builtin": [...names], "mcp": {"server_name": [tool_names]}, "total": N}

# What models are configured?
tiers = classify_models()
# → {"tier1": ["claude-opus-4-7", ...],
#    "tier2": ["claude-sonnet-4-6", "mimo-v2.5-pro", ...],
#    "tier3": ["claude-haiku-4-5", "gpt-oss-20b"],
#    "unclassified": [...],
#    "default": "claude-opus-4-7",
#    "fallback_chain": ["claude-sonnet-4-6", "mimo-v2.5-pro", ...]}
```

## Files

- `scripts/loadout.py` — `discover_tools`, `classify_models` (Piece 1 — DONE).
  `plan_loadout` (Piece 2 — TODO). `apply_to_profile` (Piece 3 — TODO).
- `references/crash-diagnosis-missing-toolsets.md` — diagnosis recipe for the most common profile crash pattern (missing toolsets).

## Pitfalls

- **Naming: lowercase, hyphens, role-first.** Pattern: `<role>` or `<project>-<role>`. Examples: `youtube-indexer`, `cmf-chief`, `researcher-a`. Never: `agent1`, `worker`, `temp`. (Full naming conventions in `profile-design` skill.)
- **SOUL.md quality gate — use `soul-md-authoring` skill.** Before finalizing a profile's SOUL.md, apply the writing standard from `soul-md-authoring`: anti-patterns check (Don't/Never/Avoid), hallucination prevention (exact tool syntax, BLOCK triggers, verification gate), and toolset-tool mapping. A vague SOUL.md → fabricated completions. A SOUL.md referencing non-existent tools → silent crashes. The soul-md-authoring skill has the validation checklist and examples.
- **When to create vs extend — use `profile-design` skill.** If unsure whether to create a new profile or extend an existing one, load `profile-design` first. It has the decision tree, scope definition, and lifecycle management.
- **Missing toolsets cause silent crashes.** A profile with `toolsets: [hermes-cli, kanban]` but no `terminal` or `file` will crash within 60-120 seconds if its SOUL.md expects Python execution or file I/O. The crash looks like `exit_code=1` or `pid not alive` — no helpful error message. **Always verify the SOUL.md's required operations match the configured toolsets.** A SOUL.md that calls `execute_code`, `terminal`, or `read_file` needs `terminal` + `file` toolsets. One that calls `skill_view` needs `skills`. Checklist after writing SOUL.md: grep for every tool/function it references → confirm each maps to a toolset in config.yaml. (Lesson: task-decomposer crashed 6 times in a row because SOUL.md had Python import blocks but config.yaml had no `terminal` toolset.)
- **Tools registry comes from `hermes tools list --json`.** The container CLI
  is `/opt/hermes/.venv/bin/python -m hermes_cli ...` or just `hermes` if on
  PATH inside the container. Outside the container (host), use the host-side
  binary which has a different command set.
- **Model classification by regex over names.** Provider prefix may or may not
  be present (`anthropic/claude-opus-4-7` vs `claude-opus-4-7`). Match both.
- **Unclassified models** go to a separate bucket — don't silently assign them
  a tier. Surface them to the user so the rubric can be updated.
- **`auxiliary.*.model` entries** (compression, embedding) are NOT for agent
  loadout. They belong to a separate pool. `classify_models()` excludes them
  by default; pass `include_auxiliary=True` to see them.
