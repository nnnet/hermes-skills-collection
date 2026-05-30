---
name: profile-design
description: "Decide when to create a new Hermes subagent profile vs extend an existing one. Naming conventions, scope definition, life cycle (create → use → retire/merge). Load when a new role emerges, a task has no matching profile, or you're tempted to overload an existing profile."
metadata:
  hermes:
    tags: [orchestration, profile, architecture, lifecycle]
    category: devops
    related_skills: [profile-loadout, soul-md-authoring, chief-manager, failure-recovery]
---

# Profile Design — when/why/how to create subagent profiles

When a new task arrives and no existing profile fits, or an existing profile is
getting overloaded, this skill decides: **create new** vs **extend existing** vs
**split**.

## When to load this skill

- A task has no matching profile → should I create one?
- An existing profile accumulates too many responsibilities → split?
- Naming a new profile → what convention?
- Retiring a profile that's no longer needed → merge or delete?

## Decision tree: new vs extend vs split

```
Task arrives with no matching profile
  │
  ├─ Does an existing profile handle 80%+ of similar tasks?
  │   ├─ YES → Extend existing (add capability, don't create new)
  │   └─ NO ↓
  │
  ├─ Is this a one-off task or recurring?
  │   ├─ ONE-OFF → Use inline delegation (delegate_task with context)
  │   │            Don't create a profile for throwaway work.
  │   └─ RECURRING ↓
  │
  ├─ Does the role need its own SOUL.md personality?
  │   ├─ NO → Add toolsets to existing profile via profile-loadout
  │   └─ YES ↓
  │
  └─ CREATE NEW PROFILE
      ├─ Name it (see naming conventions)
      ├─ Write SOUL.md (use soul-md-authoring skill)
      ├─ Compute loadout (use profile-loadout skill)
      └─ Deploy (copy config.yaml, test)
```

## When to SPLIT an existing profile

Split when:
- Profile has **> 30 tools** and performance degrades (wrong tool selection)
- Profile handles **2+ unrelated domains** (e.g., "scraper + reviewer")
- SOUL.md is **> 200 lines** — too much context, agent gets confused
- Profile has **conflicting behaviors** (e.g., "be conservative" AND "take risks")

Split pattern:
```
Old: cmf-worker (indexing + reviewing + formatting)
New: cmf-indexer (indexing only)
     cmf-reviewer (reviewing only)
     cmf-formatter (formatting only)
```

## Naming conventions

Pattern: `<role>` or `<project>-<role>`

**Good:**
- `youtube-indexer` — clear role
- `cmf-chief` — project + role
- `researcher-a` — role + variant
- `quant-finance-expert` — domain + role

**Bad:**
- `agent1`, `worker`, `temp` — meaningless
- `my-agent` — too generic
- `cmf-youtube-indexer-reviewer-formatter` — too many roles

Rules:
- Lowercase, hyphens only (no underscores, no spaces)
- Max 3 words
- Role describes WHAT it does, not HOW

## Scope definition

Before creating a profile, define its scope boundary:

1. **What it DOES** — list 3-5 concrete tasks
2. **What it does NOT do** — explicitly out of scope
3. **When to delegate** — what tasks should it hand off to other profiles
4. **Success criteria** — how to know it's working

Example scope for `youtube-indexer`:
- DOES: download transcripts, preprocess videos, index to Chroma
- DOES NOT: review quality, generate summaries, manage playlists
- DELEGATES: quality review → cmf-reviewer, playlist management → cmf-chief
- SUCCESS: 95%+ transcripts indexed without errors

## Life cycle

```
CREATE → DEPLOY → USE → MONITOR → RETIRE/MERGE
```

### CREATE
1. Decide (decision tree above)
2. Create profile dir: `/opt/data/profiles/<name>/`
3. Copy config.yaml: `cp /opt/data/config.yaml /opt/data/profiles/<name>/`
4. Write SOUL.md (use soul-md-authoring skill)
5. Compute loadout (use profile-loadout skill)

### DEPLOY
1. Test with a simple task
2. Verify all tools work (no missing toolsets)
3. Check model tier is correct (not too expensive for the role)

### USE
- Chief-manager assigns tasks to this profile
- Monitor for failures (failure-recovery skill)

### RETIRE/MERGE
When a profile is no longer needed:
1. Check if any cron jobs reference it
2. Check if any kanban tasks are assigned to it
3. Merge useful SOUL.md content into another profile if applicable
4. Delete profile dir (or archive)

## Anti-patterns

- **"One profile to rule them all"** — giving one profile all tools and all roles. Split.
- **"Profile per task"** — creating a new profile for every one-off task. Use inline delegation.
- **"Naming by technology"** — `python-agent`, `sql-worker`. Name by ROLE, not tech.
- **"No scope boundary"** — profile does everything poorly. Define what it does NOT do.
- **"Skip SOUL.md"** — profile with no SOUL.md behaves unpredictably. Always write one.
- **"Copy-paste SOUL.md"** — reusing another profile's SOUL.md without adapting. Each profile needs its own.

## Relationship to other skills

| Skill | What it does | When to load |
|---|---|---|
| `profile-design` | **this skill** — when/why to create a profile | New role emerges, no matching profile |
| `profile-loadout` | Model tier + toolsets selection | After deciding to create, compute the loadout |
| `soul-md-authoring` | SOUL.md writing standard | Writing the SOUL.md for a new profile |
| `chief-manager` | Orchestration protocol | Assigning tasks to profiles |
| `failure-recovery` | Recovery playbook | Profile fails, need to fix |

## Files

- This skill: `/opt/data/skills/devops/profile-design/SKILL.md`
- Related: `/opt/data/skills/devops/profile-loadout/SKILL.md`
- Related: `/opt/data/skills/devops/soul-md-authoring/SKILL.md`
