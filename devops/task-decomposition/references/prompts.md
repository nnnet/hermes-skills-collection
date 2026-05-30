# Decomposition Prompts

The canonical prompt is rendered by `build_decomposition_prompt(goal)` in `scripts/decomposer.py`. This file documents the prompt template, the retry-feedback contract, and self-mode vs subagent-mode differences.

## When to read this file

- You are about to decompose a goal and want to know the exact contract
- You're debugging a failed decomposition and need to see the feedback format
- You're authoring a similar skill and want to reuse the prompt shape

## Anatomy of the prompt

```
1. Role statement              "You are a task-decomposition specialist..."
2. Goal context                statement / success_criteria / constraints / out_of_scope
3. Subgoals enumeration        each with id and description
4. Hard rules                  7 numbered constraints
5. Output schema               JSON shape with field types
6. (optional) History          previous attempt summary
7. (optional) Suggestion       errors from validator to fix this attempt
8. Trigger phrase              "Produce the JSON now."
```

## Hard rules (from the prompt)

The 7 rules in the prompt template MUST be respected by the producer:

1. **Unique output names** across the whole graph
2. **Every input** must match another task's output OR be `"type": "external"`
3. **Slug-case** names: `[a-z0-9_]+`, ≤ 50 chars
4. **Description** 20-500 chars
5. **Parallelism** — siblings, not chains
6. **No implementation leakage** — no agent/profile/MCP/tool mentions
7. **No mega-tasks** — atomic operations only

## Output schema

```json
{
  "tasks": [
    {
      "name": "slug_name",
      "description": "What this task produces. Concrete, atomic.",
      "subgoal_id": "<one of declared subgoal ids>",
      "inputs": [
        {"name": "param", "type": "any|external", "description": "..."}
      ],
      "outputs": [
        {"name": "unique_name", "type": "any", "description": "..."}
      ],
      "priority": 0
    }
  ]
}
```

Optional fields per task: `reason` (one-line rationale), `max_runtime_seconds`.

## Retry feedback format

When the validator finds errors, the next decomposition attempt receives:

```
# Previous attempt
<one-line summary, e.g. "Previous attempt #1 produced 8 tasks">

# Required fixes for this attempt
Fix these issues:
- Duplicate output name 'market_data' produced by tasks: ['research_a', 'research_b']
- Task 'plan_construction': description chains 3+ operations. Split.
- Orphan task 'check_land_category' (no edges in or out)
```

The producer should:
1. Re-read the original goal
2. Address EACH listed error
3. Not regress on already-correct tasks (keep names stable when possible)

Retry budget: 2 by default. After 3 failed attempts the agent should `kanban_block(reason='decomposition errors: ...')`.

## Self-mode vs subagent-mode

| Aspect | Self-mode | Subagent-mode |
|---|---|---|
| Who calls `build_decomposition_prompt` | You (the orchestrator agent) | The `task-decomposer` profile worker |
| Where the LLM call happens | Your own context | A fresh Kanban-spawned context |
| Where outputs go | In-memory dict | `task_tree.json` + `plan.json` in workspace + `kanban_complete(metadata=...)` |
| Cost | One model context | Two contexts (orchestrator + worker) |
| Audit trail | Volatile | Persistent in Kanban DB |
| When to use | Quick goals (≤ 10 tasks), prototyping, no need for replay | Production runs, complex goals, when you want orchestrator/worker separation |

In **both** modes the prompt itself is identical — only the execution context differs.

## Producer-side anti-patterns (what the consumer should reject)

If you receive a decomposition with any of the following, send it back with the corresponding `suggestion`:

| Symptom | Suggestion |
|---|---|
| `description: "Get videos and transcribe them and tag them"` | "Split mega-task 'X' into 3 atomic tasks" |
| Two tasks output `data` | "Rename duplicate outputs: <list> with domain prefix" |
| `description: "Use yt-dlp to download"` | "Remove tool name 'yt-dlp' — describe WHAT, not HOW" |
| Single chain `A→B→C→D` for independent research | "Restructure: <X, Y, Z> should be parallel siblings, not sequential" |
| Task has no `subgoal_id` | "Every task must reference a declared subgoal_id" |

## Localization

If `goal.statement` is in Russian, the producer should keep descriptions in Russian (rule 4 in the prompt: "in the same language as the goal statement"). Slug names stay ASCII regardless of language — they are technical identifiers, not user-facing labels.
