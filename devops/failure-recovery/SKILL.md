---
name: failure-recovery
description: "Hands-on recovery playbook for blocked/failed Kanban tasks. Covers all 8 failure types from chief-manager's failures.py with concrete fix commands, retry-vs-redesign decisions, compound/recurring failure handling, and verification that the fix worked. Load after you've classified a failure and need to actually fix it."
metadata:
  hermes:
    tags: [orchestration, recovery, kanban, failure, debugging, multi-agent]
    category: devops
    related_skills: [chief-manager, soul-md-authoring]
---

# Failure Recovery — hands-on playbook

You have a blocked or failed Kanban task. You've classified it (or need to). Now fix it.

## When to use

- A Kanban task is blocked and you need to recover it
- A task completed but artifacts don't exist (phantom completion)
- Same task failed 2+ times — recurring failure
- You're in Phase 7 of chief-manager and need concrete recovery steps
- The monitoring cron reported a blocked task

**Don't load this for:** prevention (use `soul-md-authoring`), classification only (use `failures.py`), monitoring setup (use `chief-manager` Phase 7 two-cron pattern).

## Recovery protocol — 6 steps

```
Step 1: DETECT   → read kanban_show, get block reason + events
Step 2: CLASSIFY → run failures.py classify_failure() or manual lookup
Step 3: DECIDE   → retry / fix-and-retry / redesign / escalate
Step 4: FIX      → execute the type-specific fix playbook
Step 5: VERIFY   → confirm the fix actually changed something
Step 6: RE-DISPATCH → kanban_unblock + optional reassign
```

## Step 1 — Detect

```python
import sys
sys.path.insert(0, '/opt/data/skills/devops/chief-manager/scripts')
from failures import classify_failure

# Get the task data
task = kanban_show(task_id="<task_id>")

# Classify
fc = classify_failure(task)
print(f"Type: {fc.type.value}, Confidence: {fc.confidence}")
print(f"Signals: {fc.signals}")
print(f"Action: {fc.action}")
```

Key fields to extract from `kanban_show`:
- `status` — blocked / running / done
- Comments — block reason, worker notes
- Events — claim/unclaim/heartbeat/complete attempts
- `summary` / `result` — what the worker reported
- `attempt_count` — how many times it's been retried

## Step 2 — Classify (if failures.py not available)

Manual lookup:

| Signal in comments/events | Type |
|---|---|
| Number in summary, no objective change | `hallucination` |
| "tool not found", "unknown tool", HTTP 401 | `missing_tool` |
| "skill not found", skill_view failed | `missing_skill` |
| "timed out", SIGTERM, "deadline exceeded" | `timeout` |
| "parent not done", "missing output from" | `dependency_unmet` |
| "please specify", "need clarification" | `ambiguous_spec` |
| "no capable agent", "out of scope" | `no_capable_agent` |
| `kind: protocol_violation` event, `exit_code: 0`, "worker exited cleanly without calling kanban_complete or kanban_block" | `protocol_violation` |
| None of the above | `unknown` |

## Step 3 — Decide: retry vs fix vs redesign vs escalate

```
                    ┌─ attempt_count == 1? ─→ RETRY (unblock, same profile)
                    │
BLOCKED ──→ Type? ──┼─ attempt_count == 2? ─→ FIX + RETRY (patch SOUL/config, unblock)
                    │
                    ├─ attempt_count >= 3? ─→ REDESIGN (different approach)
                    │
                    └─ no_capable_agent?   ─→ ESCALATE (ask user)
```

**Retry** — transient failure, likely race condition or temporary resource issue. Just unblock.
**Fix + retry** — real bug in profile setup. Patch SOUL.md / config.yaml / install tool, then unblock.
**Redesign** — fundamental mismatch. Decompose differently, reassign to different profile, or change approach.
**Escalate** — need user input (missing capability, ambiguous requirement, paywalled resource).

## Step 4 — Fix playbooks by failure type

### 4.1 — Hallucination

**Root cause:** SOUL.md lacks verification gate. Agent reported success without checking.

**Fix sequence:**
```bash
# 1. Identify what was hallucinated
kanban_show(task_id="<id>")  # read summary vs actual artifacts

# 2. Verify actual state
mcp_chroma_get_collection_count(collection_name="<target>")  # for Chroma tasks
# or: ls -la /path/to/expected/output  # for file tasks

# 3. Patch SOUL.md — add verification gate
# Read current SOUL:
cat /opt/data/profiles/<role>/SOUL.md
# Add Step N+1 Verification Gate (see soul-md-authoring skill)
```

**SOUL.md patch template** (add before the final kanban_complete):
```markdown
### Step N+1 (Final) — Verification Gate
<metric_after> = <verification_tool>(...)
If <metric_after> > <baseline_from_step_2>:
  kanban_complete(summary="...", metadata={"count_before": <baseline>, "count_after": <metric_after>})
Else:
  kanban_block(reason="verification_failed: stayed at <baseline>")
```

```bash
# 4. Unblock and re-dispatch
kanban_unblock(task_id="<id>")
# Worker respawns with patched SOUL.md automatically
```

**Verification that fix worked:**
```bash
# Wait for task to complete, then:
kanban_show(task_id="<id>")
# Check: summary contains concrete numbers that match metadata
# Check: actual artifact count matches claimed count
mcp_chroma_get_collection_count(collection_name="<target>")
```

### 4.2 — Missing tool

**Root cause:** Profile's config.yaml doesn't have the required MCP server, or tool not in toolset.

**Fix sequence:**
```bash
# 1. Identify the missing tool
kanban_show(task_id="<id>")  # read block reason, find tool name

# 2. Check what's in the profile config
grep -A20 "mcp_servers:" /opt/data/profiles/<role>/config.yaml
hermes -p <role> tools list 2>/dev/null | grep <tool_name>

# 3. Option A: tool exists in main config but not profile → copy it
# Compare main vs profile config
diff /opt/data/config.yaml /opt/data/profiles/<role>/config.yaml

# 3. Option B: MCP server missing from both → add it
# Edit config.yaml to add the MCP server under mcp_servers:
# Then copy to profile

# 4. Verify tool is available
hermes -p <role> tools list 2>/dev/null | grep <tool_name>

# 5. Restart Hermes if MCP server was added
cd /opt/hermes && make restart

# 6. Unblock
kanban_unblock(task_id="<id>")
```

**Verification that fix worked:**
```bash
# After restart, before unblocking:
hermes -p <role> tools list 2>/dev/null | grep <tool_name>
# Should show the tool. Then unblock and check task completes without tool errors.
```

### 4.3 — Missing skill

**Root cause:** SOUL.md references a skill that's not installed, or profile can't access it.

**Key signal:** Worker crashes (exit code 1) with `consecutive_failures > 0` and `last_failure_error = 'pid X exited with code 1'` — but NO comment is left on the task and the task status stays `blocked`. The actual error is ONLY in the per-task log file:

```bash
cat /opt/data/kanban/boards/<board-slug>/logs/<task_id>.log
# Example output:
# Error: Unknown skill(s): kanban-worker
# Error: Unknown skill(s): kanban-worker
```

**Profile-local skills dir** is the most common cause: `hermes -p <role> --skills <name>` resolves skills against `~/.hermes/profiles/<role>/skills/`, NOT the shared skills dir. Fix by copying manually:

```bash
cp -r ~/.hermes/skills/kanban-worker ~/.hermes/profiles/<role>/skills/
# Verify:
ls ~/.hermes/profiles/<role>/skills/
```

**Fix sequence:**
```bash
# 1. Identify the missing skill — check log file FIRST (not just block reason)
cat /opt/data/kanban/boards/<board-slug>/logs/<task_id>.log  # look for "Unknown skill(s):"
kanban_show(task_id="<id>")  # find skill name in block reason if present

# 2. Check if skill exists anywhere
hermes skills list 2>/dev/null | grep <skill_name>

# 3. Option A: skill exists but not loaded → add to SOUL.md
# Add skill_view(name='<skill_name>') to the workflow section

# 4. Option B: skill doesn't exist → create it
# Use skill_manage(action='create', name='<skill_name>', content='...')

# 5. Verify
hermes skills list 2>/dev/null | grep <skill_name>

# 6. Unblock
kanban_unblock(task_id="<id>")
```

### 4.4 — Timeout

**Root cause:** Task too big for max_runtime_seconds, or worker stuck in loop.

**Fix sequence:**
```bash
# 1. Check actual runtime
kanban_show(task_id="<id>")  # events show claim_time and timeout

# 2. Diagnose: was it stuck or legitimately long?
# If heartbeat events show progress → legitimately long → raise limit
# If no heartbeat after initial claim → stuck in loop → decompose

# 3a. Raise time limit (legitimate long task)
kanban_update(task_id="<id>", max_runtime_seconds=<new_limit>)
# Then unblock:
kanban_unblock(task_id="<id>")

# 3b. Decompose (stuck or too-big task)
# Create smaller subtasks:
kanban_create(
    title="<original_title> — part 1",
    assignee="<role>",
    body="<subset of original work>",
    parents=[<original_task_id>]  # if depends on prior work
)
# Mark original as superseded or leave blocked with note
```

**Verification:** task completes within new time limit, or subtasks complete individually.

### 4.5 — Dependency unmet

**Root cause:** Parent task not done, or done but didn't produce expected output.

**Fix sequence:**
```bash
# 1. Check parent status
kanban_show(task_id="<parent_id>")

# 2a. If parent blocked → fix parent first (recurse into this playbook)
# 2b. If parent done but output insufficient → check parent's summary/metadata
kanban_show(task_id="<parent_id>")
# Verify: does parent's metadata contain the expected output field?

# 3. If parent completed with wrong output → create a correction task
kanban_create(
    title="fix: <parent_task> — missing <output>",
    assignee="<parent's assignee>",
    body="Previous run completed but didn't produce <expected_output>. "
         "Previous summary: <parent_summary>. "
         "Must produce: <what_child_needs>.",
    parents=[<parent_id>]
)

# 4. If parent just needs unblocking → unblock parent
kanban_unblock(task_id="<parent_id>")
# Child auto-promotes when parent reaches done
```

### 4.6 — Ambiguous spec

**Root cause:** Task body unclear. Worker asked a clarifying question.

**Fix sequence:**
```bash
# 1. Read the question
kanban_show(task_id="<id>")  # block reason contains the question

# 2. Answer it — update the task body
# Either edit via kanban_update or add a comment with the answer

# 3. Unblock
kanban_unblock(task_id="<id>")
```

### 4.7 — No capable agent

**Root cause:** No existing profile has the required skills/tools.

**Fix sequence — this is the only type that ALWAYS escalates:**
```
1. Report to user: "Task X requires capabilities no existing profile has:
   - Skills needed: <list>
   - Tools needed: <list>
   - Closest profile: <name> (has <what it has>, missing <what it lacks>)

   Options:
   A. Create new profile <suggested-name> with these capabilities
   B. Extend existing profile <closest> to add missing capabilities
   C. Redesign task to use available capabilities (may reduce scope)
   D. Cancel this task"
```

If user chooses A or B: use `soul-md-authoring` skill to build the profile, then reassign.

### 4.8 — Protocol violation

**Root cause:** Worker process exited cleanly (rc=0) without calling `kanban_complete` or `kanban_block`. The kernel emits a `protocol_violation` event when this happens — the worker burned through its iterations or reasoning loop and just *stopped* without signalling the kanban kernel either way. Most common causes:

- SOUL.md doesn't end with an explicit terminal step ("MUST call kanban_complete OR kanban_block")
- Agent ran out of iteration budget mid-reasoning and the runtime closed gracefully
- Agent hit a silent crash inside a tool call that returned without raising
- Profile model is too weak for the task complexity (Haiku on multi-step orchestration) and trailed off into empty output

**Signature in events (DB-level):**
```python
# Look for this sequence in task_events:
# kind='spawned' → ... → kind='protocol_violation' (payload.exit_code == 0) → kind='gave_up'
# The 'gave_up' event fires when consecutive_failures hits effective_limit.
```

**Fix sequence:**
```bash
# 1. Identify whether it's protocol_violation vs crash vs timeout
python3 -c "
import sqlite3, json
conn = sqlite3.connect('/opt/data/kanban.db')
cur = conn.cursor()
cur.execute(\"SELECT kind, payload FROM task_events WHERE task_id='<id>' ORDER BY created_at DESC LIMIT 10\")
for k, p in cur.fetchall():
    print(k, p)
"

# 2. Check whether worker actually did productive work (any comments, workspace files?)
ls -la /opt/data/kanban/workspaces/<task_id>/  # any artifacts?
# Query task_comments for any handoff/progress notes the worker left

# 3a. If worker did productive work but forgot to call kanban_complete:
#     Supervisor direct completion is appropriate (see "Supervisor direct completion" section).

# 3b. If worker did nothing productive (no artifacts, no comments):
#     Patch SOUL.md to add an explicit terminal step. Template:
```

**SOUL.md patch template — terminal-step enforcement:**
```markdown
## Step N (FINAL, MANDATORY) — Always signal kanban

You MUST end every run with one of:
  - kanban_complete(summary=..., metadata=...) — if the task succeeded
  - kanban_block(reason="...") — if you need human help or hit an impossible blocker

Do NOT just stop. An empty exit is treated as a protocol_violation by the dispatcher
and counts toward consecutive_failures. If you ran out of ideas, BLOCK with the reason.
```

```bash
# 4. If task burned 2 attempts on protocol_violation specifically → consider model upgrade
grep "default:" /opt/data/profiles/<role>/config.yaml
# Haiku on complex orchestration → upgrade to Sonnet
sed -i 's/claude-haiku-4-5/claude-sonnet-4-6/' /opt/data/profiles/<role>/config.yaml

# 5. Reclaim and unblock (DO NOT just unblock — the dispatcher already gave_up,
#    so consecutive_failures is at the limit; reclaim resets it)
hermes kanban reclaim <task_id>
hermes kanban unblock <task_id>
```

**Verification that fix worked:**
```bash
# After patch + reclaim + unblock, watch the next run:
# - Should see kind='completed' or kind='blocked' (with sensible reason) in events
# - NOT kind='protocol_violation' again
```

**Pitfall:** Resist the urge to just `kanban_unblock` after a `gave_up` event. The dispatcher already gave up because consecutive_failures hit the limit — re-running with the same buggy SOUL produces another `protocol_violation` and another gave_up. You need EITHER `kanban_reclaim` (resets failure counter) OR a patched SOUL/upgraded model. Ideally both.

### 4.9 — Unknown

**Root cause:** Failure pattern not in the taxonomy.

**Fix sequence:**
```bash
# 1. Manual inspection — read everything
kanban_show(task_id="<id>")
# Read all comments, events, summary, metadata

# 2. Check worker's conversation (if available)
# Look for: tool call errors, unexpected responses, infinite loops

# 3. If pattern is new → extend failures.py
# Add regex pattern to _PATTERNS dict
# Add action template to _ACTION_TEMPLATES

# 4. Apply closest-match fix from above playbooks

# 5. Document in kanban_comment
kanban_comment(task_id="<id>",
    body="Unknown failure pattern. Signals: <what you found>. "
         "Applied: <what you did>. "
         "Consider adding to failures.py: <regex suggestion>")
```

## Step 5 — Verify the fix

**Every recovery must end with verification.** Don't just unblock and hope.

```python
# After fix applied and task unblocked:

# Option A: wait for task to complete (passive)
kanban_show(task_id="<id>")  # check status

# Option B: verify the actual fix changed something (active)
# For config fixes:
hermes -p <role> tools list 2>/dev/null | grep <tool_name>

# For SOUL.md fixes:
grep -c "Verification Gate" /opt/data/profiles/<role>/SOUL.md

# For tool installs:
hermes -p <role> tools list 2>/dev/null | wc -l  # count before/after

# For dependency fixes:
kanban_show(task_id="<parent_id>")  # confirm parent now done
```

## Step 6 — Re-dispatch

```bash
# Standard unblock (worker respawns automatically)
kanban_unblock(task_id="<id>")

# If worker profile changed (new model, new SOUL, different profile):
hermes kanban reclaim <task_id>   # abort current claim
hermes kanban reassign <task_id> <new_profile> --reclaim

# If task needs fresh start (clean slate):
hermes kanban reclaim <task_id>
kanban_unblock(task_id="<id>")
```

## Recurring failures (same task failed 3+ times)

Three strikes → stop retrying. Diagnose the systemic issue.

```
Strike 1 → retry (maybe transient)
Strike 2 → fix + retry (patch SOUL/config/skill)
Strike 3 → STOP. Diagnose:
  - Is the profile fundamentally wrong for this task? → reassign
  - Is the task spec impossible? → renegotiate with user
  - Is the model too weak? → upgrade model (Haiku → Sonnet)
  - Is there a missing dependency nobody installed? → install + verify
```

**Model upgrade pattern:**
```bash
# Check current model
grep "default:" /opt/data/profiles/<role>/config.yaml

# Upgrade from Haiku to Sonnet
sed -i 's/default: claude-haiku-4-5/default: claude-sonnet-4-6/' \
  /opt/data/profiles/<role>/config.yaml

# Reclaim and retry
hermes kanban reclaim <task_id>
kanban_unblock(task_id="<id>")
```

## Compound failures

Sometimes a task has MULTIPLE failure types. Priority order for fixing:

1. `missing_tool` / `missing_skill` — fix first (infra prerequisite)
2. `dependency_unmet` — fix parent chain
3. `ambiguous_spec` — get clarification
4. `hallucination` — patch SOUL
5. `timeout` — decompose or raise limit
6. `no_capable_agent` — escalate
7. `unknown` — manual diagnosis

Example: task blocked because (a) missing tool AND (b) parent not done.
→ Fix the tool first, then unblock parent, then unblock this task.

## Partial completions

When a task completed (status=done) but artifacts are incomplete:

```python
# 1. Detect: compare claimed vs actual
task = kanban_show(task_id="<id>")
claimed = task.get("summary", "")  # "indexed 50 videos"
actual_count = mcp_chroma_get_collection_count("target_collection")

# 2. Calculate what's missing
# 3. Create a RESUME task (don't re-run the whole thing)
kanban_create(
    title="resume: <original_title> — <N> remaining",
    assignee="<same_role>",
    body=f"Previous run completed {actual_count}/{expected}. "
         f"Previous summary: {claimed}. "
         f"Resume from where it stopped. "
         f"Baseline: {actual_count} (do NOT re-process existing).",
)
```

## Supervisor direct completion (bypassing stuck workers)

When a worker exhausts its iteration budget on a task that needs only a few operations:

```python
# 1. Read worker's artifacts from workspace
import json
with open("/opt/data/kanban/workspaces/<task_id>/some_artifact.json") as f:
    data = json.load(f)

# 2. Execute remaining operations directly
# (Chroma API, file writes, etc.)

# 3. Complete the task
kanban_complete(
    task_id="<task_id>",
    summary="Completed by supervisor after worker exhaustion. <what was done>.",
    metadata={"completed_by": "supervisor", "reason": "iteration_budget_exhausted"}
)
```

**When to use:** Worker blocked 2+ times with "Iteration budget exhausted" AND the remaining work is mechanical (few tool calls, no reasoning needed).
**When NOT to use:** The task needs domain expertise, creative decisions, or multi-step reasoning.

## Recovery decision matrix

| Type | Attempts | Action | Fix time |
|---|---|---|---|
| `hallucination` | 1 | Patch SOUL + unblock | ~5 min |
| `hallucination` | 2+ | Redesign verification gate | ~15 min |
| `missing_tool` | any | Add tool + restart + unblock | ~5 min |
| `missing_skill` | any | Create skill + unblock | ~15-30 min |
| `timeout` | 1 | Raise limit + unblock | ~2 min |
| `timeout` | 2+ | Decompose task | ~15 min |
| `dependency_unmet` | any | Fix parent chain first | varies |
| `ambiguous_spec` | any | Answer + unblock | ~2 min |
| `no_capable_agent` | any | ESCALATE to user | N/A |
| `protocol_violation` | 1 | Patch SOUL terminal step + reclaim + unblock | ~5 min |
| `protocol_violation` | 2+ | Patch SOUL + upgrade model + reclaim | ~10 min |
| `unknown` | 1 | Manual diag + closest fix | ~10 min |
| `unknown` | 2+ | Escalate + extend taxonomy | ~20 min |

## Special case — `review-required` is NOT a failure

**Signal:** `kanban_block(reason="review-required: ...")` + comment containing `changed_files` JSON.

This is the Aegis attestation gate firing correctly — the worker completed the task and is waiting for sign-off. **Do not classify, do not patch SOUL, do not escalate.** Just unblock:

```python
kanban_unblock(task_id="<id>", board="<board>")
```

Auto-unblock is correct when:
- Block reason contains "review-required"
- Comment thread has a JSON block with `changed_files`
- Summary describes actual work done

Escalate to user (don't auto-unblock) when: block reason says "review-required" but NO `changed_files` listed, or summary shows 0 results / errors. That's a hallucination masquerading as a review gate.

**Cron monitors must include this rule** or they'll leave completed work sitting blocked while agents downstream wait. (Lesson 2026-05-23.)

## Special case — stable-profile fallback (recurring crash, 3+ times)

When a specialized profile crashes 3+ times and config fixes don't hold, stop fighting the profile and reassign to your setup's known-stable profile.

**Pattern:**
```python
# Create replacement task for the stable profile
kanban_create(
    title="<original_title> [reassigned to <stable_profile>]",
    assignee="<stable_profile>",  # e.g. research-agent
    body=(
        "Previous task <id> assigned to <broken_profile> crashed N times. "
        "Reassigned here. Full spec follows:\n\n<original_body>"
    ),
    parents=[<same_parents>],
    board="<board>",
)
# Leave original blocked — it's evidence of the failure, not noise
```

**Compensate for missing SOUL expertise:** The stable profile lacks domain-specific SOUL.md. Put API details, expected file structure, and examples directly in the task body — don't rely on SOUL knowledge the profile doesn't have.

**When to use:** 3+ crashes, same root cause (e.g. empty `fallback_providers`), config fix applied but crashes persist. Stop at 3 — further debugging of the broken profile is wasted time. (Lesson 2026-05-23: `trading-expert` and `risk-expert` crashed repeatedly; both reassigned to `research-agent` with explicit specs — both completed successfully.)

## Pitfalls

1. **Unblocking without fixing** — `kanban_unblock` without addressing root cause just creates another failed attempt. Always fix THEN unblock.
2. **Fixing prevention instead of recovery** — if the task is blocked NOW, fix the immediate issue first. Update soul-md-authoring patterns for NEXT time.
3. **Not verifying the fix** — "I edited config.yaml" ≠ "the tool is now available". Always verify.
4. **Escalating too early** — try fix+retry before escalating. Only `no_capable_agent` and strike-3 need escalation.
5. **Not escalating when needed** — strike-3 recurring failures and `no_capable_agent` MUST go to user. Don't redesign without approval.
6. **Forgetting to check dependent tasks** — when you fix a parent, check if blocked children can now proceed.
7. **Re-running completed work** — for partial completions, create a RESUME task, don't re-dispatch the original.
8. **Ignoring the iteration budget** — if a worker hits 60 iterations, the SOUL is probably too procedural. Simplify it.
9. **Restarting Hermes unnecessarily** — only restart when MCP servers changed. Config.yaml model changes take effect on next worker spawn without restart.
10. **Not logging recovery actions** — always `kanban_comment` what you fixed so the next attempt has context.
11. **`hermes kanban unblock` returns "cannot unblock (not blocked?)" despite DB showing `blocked`** — observed in cron/non-interactive contexts. Also: `hermes kanban --board <slug> unblock` returns "board does not exist" even though `hermes kanban --board <slug> list` works fine — the `--board` flag is only honoured by `list`, not by `unblock` or `boards switch`. Workaround for both: update the per-board SQLite directly with Python (sqlite3 CLI is usually absent):
    ```python
    import sqlite3
    db = "/opt/data/kanban/boards/<board-slug>/kanban.db"
    con = sqlite3.connect(db)
    con.execute("UPDATE tasks SET status='ready', consecutive_failures=0, last_failure_error=NULL WHERE id='<task-id>'")
    con.commit()
    ```
    Use `status='ready'` (not `'done'`) to re-queue the task for a fresh dispatch attempt.
12. **`task_events` column is `kind`, not `event_type`** — inserting with `event_type` raises `OperationalError: table task_events has no column named event_type`. Use `(task_id, run_id, kind, payload, created_at)`. For comments, use `task_comments (task_id, author, body, created_at)`.
13. **Board switch doesn't persist across separate `terminal()` / `execute_code` calls** — `hermes kanban boards switch <slug>` writes to a config file that only lives for the current shell. Combine all board-scoped commands in a single bash script, or bypass CLI and query SQLite directly.

## Quick reference — recovery commands

```bash
# Read task state
kanban_show(task_id="<id>")

# Classify failure
python3 -c "
import sys; sys.path.insert(0, '/opt/data/skills/devops/chief-manager/scripts')
from failures import classify_failure
fc = classify_failure(kanban_show(task_id='<id>'))
print(fc.type.value, fc.confidence, fc.action)
"

# Unblock (same profile, fresh attempt)
kanban_unblock(task_id="<id>")

# Reclaim + reassign (different profile)
hermes kanban reclaim <task_id>
hermes kanban reassign <task_id> <new_profile> --reclaim

# Check profile tools
hermes -p <role> tools list 2>/dev/null

# Check profile model
grep "default:" /opt/data/profiles/<role>/config.yaml

# Verify Chroma count
mcp_chroma_get_collection_count(collection_name="<name>")

# Comment on recovery
kanban_comment(task_id="<id>", body="Recovery: <what was fixed>")
```

## Related skills

- `workflow-synthesis` — combine agent outputs after all tasks complete
- `chief-manager` — orchestration protocol, dispatch, monitoring
- `profile-design` — create new profiles when capability gap is diagnosed
- `profile-loadout` — fix toolsets/model when profile misconfigured

## Files

- `scripts/failures.py` — in chief-manager: classification engine
- `scripts/capability.py` — in chief-manager: profile discovery
- This skill: `/opt/data/skills/devops/failure-recovery/SKILL.md`
