---
name: workflow-postmortem
description: "Analyze completed multi-agent workflows: extract reusable templates, log what worked/failed, track patterns over time. Load after a workflow completes to learn and improve future orchestration."
metadata:
  hermes:
    tags: [orchestration, postmortem, learning, templates, retrospective]
    category: devops
    related_skills: [chief-manager, workflow-templates, workflow-synthesis, failure-recovery]
---

# Workflow Postmortem — learning from completed workflows

After a multi-agent workflow completes (or fails), this skill extracts lessons,
identifies reusable patterns, and feeds improvements back into `workflow-templates`.

## When to load

- A kanban workflow (multi-task) just completed → analyze before closing
- A workflow failed mid-execution → postmortem after recovery
- Periodic review: look at recent completed workflows for patterns
- User asks "what did we learn from the last N workflows?"

## Protocol — 5 phases

### Phase 1 — Collect execution data

Gather raw data from the completed workflow:

```python
# For each task in the workflow:
for task_id in workflow_task_ids:
    show = kanban_show(task_id)
    # Extract:
    # - task title, body, assignee
    # - run summary (from kanban_complete)
    # - metadata (changed_files, tests_run, findings)
    # - comments (questions, blockers, clarifications)
    # - events (retries, blocks, unblocks, timeouts)
    # - wall time (created_at → completed_at)
```

Also collect:
- Number of retries per task
- Number of blocks (and reasons)
- Human interventions (manual unblocks, comment clarifications)
- Synthesis approach used (report / chroma / decision matrix / handoff)

### Phase 2 — Classify outcomes

For each task, classify:

| Outcome | Definition |
|---|---|
| `clean_success` | Completed first try, no blocks, no retries |
| `retry_success` | Completed after 1+ retries |
| `block_recovery` | Blocked, unblocked with human input, then completed |
| `partial_success` | Completed but output quality below expected |
| `failure` | Blocked permanently or timed out |

For the overall workflow:

| Outcome | Definition |
|---|---|
| `smooth` | All tasks clean_success, no human intervention needed |
| `bumpy` | Some retries/blocks but ultimately completed |
| `partial` | Some tasks completed, some failed |
| `failed` | Workflow could not complete |

### Phase 3 — Extract patterns

**Reusable template candidates:**

Ask: "Did this workflow's DAG structure match any existing template? Would a new template help future similar goals?"

- If the DAG matches an existing template → note the adaptation points used
- If the DAG is novel and the goal type is recurring → propose a new template
- If a template was used but needed heavy adaptation → update the template

**Anti-patterns discovered:**

- Tasks that took unusually long → check if they should be decomposed further
- Tasks that needed 3+ retries → check SOUL.md quality
- Blocks caused by ambiguous specs → check if goal clarification was sufficient
- Phantom completions → check if verification gates were missing

**Profile insights:**

- Profiles that performed well → note for reuse
- Profiles that struggled → note for SOUL.md improvement
- Missing capabilities → suggest new profiles or skill additions

### Phase 4 — Update templates and skills

Based on Phase 3 findings:

1. **New template candidate?** → Draft tasks_spec JSON, goal template, capability hints. Add to `workflow-templates` with `skill_manage(action='patch')`.

2. **Template improvement?** → Patch the existing template: add missing tasks, fix I/O contracts, update capability hints.

3. **Profile issue?** → Patch SOUL.md with `skill_manage` or note for `failure-recovery`.

4. **New anti-pattern?** → Add to the relevant skill's anti-patterns section.

5. **New pitfall?** → Add to the relevant skill's pitfalls section.

### Phase 5 — Log the postmortem

Write a structured postmortem record to the workspace:

```markdown
# Postmortem: {workflow_goal}

**Date:** {ISO date}
**Outcome:** smooth | bumpy | partial | failed
**Tasks:** {N} total, {clean} clean, {retry} retry, {block} blocked, {failed} failed
**Wall time:** {total_hours}h
**Human interventions:** {count}

## What worked
- {finding 1}
- {finding 2}

## What didn't work
- {finding 1}
- {finding 2}

## Template match
- Used template: {name} | None | Custom
- Adaptation notes: {what was changed}

## Reusable patterns extracted
- {pattern description + which template it feeds}

## Action items
- [ ] {improvement 1}
- [ ] {improvement 2}
```

Save to: `/opt/data/workspace/{project}/postmortems/{date}-{goal-slug}.md`

## Postmortem data model

```python
postmortem = {
    "goal": "str",
    "date": "ISO timestamp",
    "outcome": "smooth | bumpy | partial | failed",
    "tasks": [
        {
            "task_id": "str",
            "title": "str",
            "assignee": "profile-name",
            "outcome": "clean_success | retry_success | block_recovery | partial_success | failure",
            "retries": 0,
            "blocks": 0,
            "wall_time_seconds": 0,
            "human_interventions": 0,
            "notes": "str"
        }
    ],
    "synthesis_pattern": "report | chroma | decision_matrix | handoff | staged",
    "template_used": "str or null",
    "patterns_extracted": ["str"],
    "action_items": ["str"]
}
```

## Learning loop

```
Workflow completes
  │
  ├─ Run postmortem (Phases 1-3)
  │
  ├─ New template candidate?
  │   ├─ YES → Draft template → Add to workflow-templates
  │   └─ NO ↓
  │
  ├─ Template improvement needed?
  │   ├─ YES → Patch workflow-templates
  │   └─ NO ↓
  │
  ├─ Profile/SOUL.md issue?
  │   ├─ YES → Patch profile or note for failure-recovery
  │   └─ NO ↓
  │
  └─ Log postmortem → Done
```

## When to SKIP postmortem

- Single-task workflows (no orchestration to learn from)
- Trivially simple goals ("send an email", "search for X")
- Workflows that were just delegating to a single profile

## Anti-patterns

- **"Postmortem every task"** — overhead kills velocity. Only postmortem multi-task workflows.
- **"Blame the agent"** — postmortems find systemic issues (bad SOUL.md, missing tools, vague goals), not individual failures.
- **"Postmortem without action"** — if findings don't feed back into templates/profiles/skills, the postmortem was wasted effort.
- **"Perfect is the enemy of done"** — a 5-minute postmortem that extracts one useful pattern beats a 2-hour deep dive that nobody reads.

## Relationship to other skills

| Skill | What it does | When to load |
|---|---|---|
| `workflow-postmortem` | **this skill** — learn from completed workflows | After workflow completes |
| `workflow-templates` | Stores reusable patterns | Postmortem feeds new templates here |
| `chief-manager` | Orchestrator protocol | Postmortem analyzes chief's decisions |
| `workflow-synthesis` | Combines agent outputs | Postmortem evaluates synthesis quality |
| `failure-recovery` | Handles failures | Postmortem identifies failure root causes |

## Files

- This skill: `/opt/data/skills/devops/workflow-postmortem/SKILL.md`
- Postmortem logs: `/opt/data/workspace/{project}/postmortems/`
- Related: `/opt/data/skills/devops/workflow-templates/SKILL.md`
