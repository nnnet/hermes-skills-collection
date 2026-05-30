---
name: soul-md-authoring
description: Write SOUL.md role definitions that prevent agent hallucination — exact tool syntax, explicit block triggers, mandatory verification gates, and tool-availability preflight. Use when creating a new Hermes profile or fixing one whose agent reports fake success.
metadata:
  hermes:
    tags: [orchestration, soul-md, profile-authoring, agent-design, anti-hallucination]
    category: devops
    related_skills: [chief-manager, profile-loadout, profile-design]
---

# SOUL.md Authoring — Anti-Hallucination Patterns

Write SOUL.md role definitions that make agents behave predictably instead of fabricating success. Built from real failures observed in CMF-YNVRSTY (cmf-indexer reported "329 docs indexed" with zero Chroma writes).

## When to use

- Creating a new Hermes profile that performs concrete operations (Chroma writes, file generation, API calls, indexing)
- Fixing a profile whose agent reports fake success — claims N artifacts but verification shows zero
- Reviewing an existing SOUL.md before production deployment
- Diagnosing why a profile keeps blocking with vague reasons or never blocking at all

## Mental model (read before editing any SOUL.md)

SOUL.md is the **system prompt** the LLM agent reads at every turn — natural-language instructions, not Python code. The agent is capable but only as reliable as its instructions: vague prose produces fabricated completions; precise spec produces predictable behavior.

Don't confuse SOUL.md with entrypoint.py:
- **SOUL.md** = what the agent should do (read by the LLM at every turn)
- **entrypoint.py** = how the agent process is launched (Python harness executed by dispatcher)
- **config.yaml** = which model and which MCP tools are wired up (read at startup)

A SOUL.md that names a tool not present in config.yaml is a guaranteed fabrication setup — the agent will hallucinate the call.

## The Four Pillars (every SOUL.md must have all four)

### 1. Exact tool syntax
Name each tool call by its actual function name with all parameters spelled out. Never write "use the indexing tool" — write the literal call:
```
mcp_chroma_add_documents(
    collection_name="cmf-lectures",
    documents=[transcript_text],
    ids=[video_url],
    metadatas=[{...}]
)
```

### 2. Tool availability preflight
Before writing a SOUL.md that calls `tool_X`, verify `tool_X` is registered in the profile's config.yaml:
```bash
grep -A20 "mcp_servers:" /opt/data/profiles/<role>/config.yaml
hermes -p <role> tools list 2>/dev/null | grep <tool_name>
```
If the tool isn't there, either add the MCP server to config.yaml first, or pick a tool that is available.

### 3. Explicit block triggers
Every failure mode must have a named kanban_block reason in a lookup table. The agent never decides "what to do on error" — it consults the table.

### 4. Verification gate
The final step before `kanban_complete` must be an OBJECTIVE check: file exists, `count_after > count_before`, sha256 matches, HTTP 200. Subjective checks ("looks good to me") are forbidden and the agent will lie about them.

## Step-by-step writing process

### Step A — Define scope precisely (one sentence rule)
Write one sentence: "This agent does X for ONE input, then stops." If you can't fit it in one sentence, split it into two agents and let the orchestrator coordinate.

- ❌ "Indexes content and analyzes patterns and writes reports"
- ✅ "Indexes ONE YouTube video URL into Chroma collection cmf-lectures, then stops"

Batch loops belong at the orchestrator level (one kanban task per video), not inside one SOUL.

### Step B — Enumerate every external operation
List every tool call the agent will make. For each one capture:
- Exact tool name (MCP function or terminal command)
- Required parameters and where each value comes from (task body? previous step? hardcoded?)
- Expected return shape
- All failure modes (empty result, error code, timeout, malformed data)

### Step C — Preflight tool availability
For each tool in Step B, confirm it's in `config.yaml` or available as a system binary. If you find a missing MCP server, fix config.yaml first:
```bash
cp /opt/data/config.yaml /opt/data/profiles/<role>/config.yaml  # if profile has no config at all
```

### Step D — Write the Workflow section (numbered, ordered)
Standard ordering:
- **Step 0** — Dependency check (auto-install if needed)
- **Step 1** — Read task via `kanban_show()`, extract required fields, block if missing
- **Step 2** — Capture baseline metrics (count_before, file existence, etc.)
- **Step 3..N** — Do the work, one tool call per step
- **Step N+1** — Verification gate (final step, decides complete vs block)

Each step template:
```markdown
### Step N — <imperative verb describing intent>
Call `<exact_tool_name>` with:
- <param1>: <where it comes from>
- <param2>: <value or rule>

If <failure condition> → kanban_block(reason="<exact_reason>")
Otherwise capture <return_value> as <variable_name> for later steps.
```

### Step E — Write the Block Triggers reference table
Compile every failure mode from Step B into one lookup table at the bottom of the SOUL. Each row pairs a condition with the EXACT `kanban_block` reason string:

```markdown
## Block Triggers

| Trigger condition | kanban_block reason |
|---|---|
| body missing required field | "missing_input: <field_name>" |
| upstream API returned 4xx/5xx | "upstream_failed: <api>: <code>" |
| empty/null response | "empty_response: <tool>: <input>" |
| verification mismatch | "verification_failed: <expected> vs <actual>" |
| dependency install failed | "dependency_install_failed: <pkg>" |
```

The agent should never invent reasons — only pick from this table.

### Step F — Write the Verification Gate (the most important step)
This is the FINAL workflow step. It must produce a boolean check on an objective metric:

```markdown
### Step N+1 (Final) — Verification Gate

Call <verification_tool> to get <objective_metric_after>.
Compare to <baseline_captured_in_step_2>.

If <metric_after> > <baseline>:
  kanban_complete(
    summary="<concrete numbers from actual measurements, no estimates>",
    metadata={
      "count_before": <baseline>,
      "count_after": <metric_after>,
      "<other_captured_values>": ...
    }
  )

Else:
  kanban_block(reason="verification_failed: <metric> stayed at <baseline>")
```

The agent runs this RIGHT BEFORE complete — not after. If the gate fails, the task blocks instead of completing with fake numbers.

### Step G — Add Constraints section
List explicit boundaries:
- Allowed model (e.g., "claude-haiku-4-5 only — don't burn Opus on indexing")
- Allowed workspace paths (e.g., "only /opt/data/workspace/<project>/")
- Forbidden actions ("never invent numbers", "never write to /opt/data/profiles/", "never call delegate_task")

### Step H — Test before production
Before assigning real work:
```bash
# 1. Dry-run with a known good input
hermes kanban create --assignee=<role> --title="smoke test" --body="<minimal valid input>"
hermes kanban tail <task_id>

# 2. Inject a failure case (empty body, bad URL)
# Verify the agent blocks with the EXACT reason from your Block Triggers table

# 3. Verify the gate fires
# Run a no-op input; confirm the agent blocks rather than fake-completing
```

## Anti-patterns (do not do)

| Anti-pattern | Why it fails | Fix |
|---|---|---|
| "Use the appropriate tool to..." | Agent picks wrong tool or invents one | Name the exact tool with full parameter list |
| "Index the videos" (plural, vague) | Agent reports "indexed all" without doing it | One agent = one input; loop at orchestrator level |
| No baseline captured | Can't verify "after > before" later | Step 2 always captures baseline |
| Verification AFTER kanban_complete | Too late; task already marked done | Verification gate IS the final step, before complete |
| "If something goes wrong, handle it" | Agent invents arbitrary handling | Enumerate every failure mode in Block Triggers table |
| Mixing prose and Python in one step | Agent confused what's code vs instruction | Either pseudocode style OR full Python in code fence — not mixed |
| SOUL references tool not in config.yaml | Tool unavailable, agent fabricates output | Preflight check before writing SOUL |
| "Estimate" or "approximately" anywhere | Agent treats it as license to hallucinate | Forbid these words in Constraints section |
| Single SOUL handles multiple unrelated tasks | Agent picks wrong path or fakes the others | Split into separate profiles |
| Verification compares wrong metrics | Gate passes when it shouldn't | Pick a metric that ONLY changes when work succeeds |
| SOUL.md copies commands/params/endpoints from an existing skill (yt-dlp flags, API URLs, cookie patterns, Chroma calls) | When the skill is patched, SOUL stays stale → agent silently follows the wrong procedure with no error | SOUL.md must tell the agent to `skill_view(name='<skill-name>')` at startup and follow its protocol; never copy-paste logic inline |

## Diagnosis table (symptom → root cause → fix)

| Symptom | Likely cause | Fix |
|---|---|---|
| Agent reports success but artifacts don't exist | No verification gate or wrong metric | Add count_before/count_after comparison |
| Agent blocks with vague "something failed" | Block Triggers table missing | Add explicit table; every failure has a named reason |
| Agent crashes with HTTP 401 on first run | Profile missing config.yaml | `cp /opt/data/config.yaml /opt/data/profiles/<role>/config.yaml` |
| Agent says it used tool X but X doesn't exist | SOUL references tool not in config | Add MCP server to config.yaml OR pick available tool |
| Agent crashes 60-120 sec after start, exit_code=1 | SOUL.md references tools not in profile's toolsets | Grep SOUL for tool calls → verify each maps to a configured toolset (terminal, file, skills, etc.) |
| Agent dies with "protocol violation" | Missing or broken entrypoint.py | Add entrypoint that calls kanban_show then exits via complete/block |
| Agent loops forever on same task | No iteration budget or no clear exit condition | Set `agent.max_turns` in config.yaml; add explicit Step N+1 exit |
| Verification gate never fires | Step N+1 written after kanban_complete | Reorder — gate must precede complete |
| Numbers in summary don't match metadata | Agent invented summary, used real metadata | Compute summary from metadata values, not from "feeling" |

## Constraints to copy into every SOUL.md

```markdown
## Constraints

- Model: <specific anthropic model, never "the default">
- Workspace: only /opt/data/workspace/<project>/
- Tool availability: do NOT call tools outside this SOUL's documented list
- Numbers: NEVER estimate, approximate, or round. Read them from tool returns or kanban_block.
- Completion: NEVER call kanban_complete without first passing the Verification Gate.
- Forbidden words in output: "approximately", "roughly", "should be", "I think", "successfully" (without proof).
```

## SOUL.md skeleton (copy-paste starting point)

```markdown
---
name: <role-name>
description: <one sentence — what this agent does for ONE input>
---

# <Role> SOUL

## Role
<2-3 sentences — single concrete responsibility. ONE input → ONE output.>

## Constraints
- Model: <specific Anthropic model, e.g., claude-haiku-4-5>
- Workspace: only /opt/data/workspace/<project>/
- NEVER invent numbers. If unsure → kanban_block.
- Forbidden words: "approximately", "should be", "I think".

## Workflow

### Step 0 — Dependency check
[auto-install Python deps if needed; kanban_block on install failure]

### Step 1 — Read task
kanban_show() → extract <required_field> from body.
If <required_field> missing → kanban_block(reason="missing_input: <required_field>")

### Step 2 — Capture baseline
<baseline_var> = <tool_to_read_current_state>(...)
Store this value; needed for Step N+1.

### Step 3..N — Do the work
Call <exact_tool_name>(<param>=<value>, ...)
If <failure_condition> → kanban_block(reason="<reason_from_table>")
Capture <return> as <var> for next step.

### Step N+1 (Final) — Verification Gate
<metric_after> = <same_tool_as_baseline>(...)

If <metric_after> > <baseline_var>:
  kanban_complete(
    summary=f"<concrete numbers from real measurements>",
    metadata={"count_before": <baseline_var>, "count_after": <metric_after>, ...}
  )
Else:
  kanban_block(reason="verification_failed: stayed at {baseline_var}")

## Block Triggers

| Condition | reason |
|---|---|
| body missing required field | "missing_input: <field>" |
| tool returned empty/error | "<tool>_failed: <details>" |
| verification metric unchanged | "verification_failed: stayed at <baseline>" |
| dependency missing | "dependency_install_failed: <package>" |
```

## Pitfalls observed in production

0. **Overly procedural SOUL.md crashes T3 models.** A SOUL.md with multi-line Python code blocks, `sys.path.insert`, import statements, and inline function calls will work on Sonnet/Opus but crash Haiku or weaker models within 60-120 seconds. The agent tries to parse the code as instructions, fails to produce valid tool calls, and the gateway kills it. **Rule: SOUL.md describes the PROTOCOL (what to do, in what order, with what checks), not the IMPLEMENTATION (literal Python code).** If the agent needs to run Python, point it at a script file in `scripts/` and tell it to `terminal(python3 /opt/data/skills/.../scripts/myscript.py)`. Don't inline the code in the SOUL. (Lesson: task-decomposer SOUL.md was ~5KB of dense Python; simplified to ~3KB protocol → no more crashes.)

1. **CMF-indexer "329 docs" incident** — SOUL said "index videos" without naming the tool. Agent invented the number; Chroma count was unchanged. Root cause: no Verification Gate. Fix applied: added Step N+1 with `chroma_get_collection_count` comparison.

2. **Profile-without-config silent failure** — agent crashed with HTTP 401 on every first call because no config.yaml existed in profile dir. Dispatcher kept retrying. Fix applied: pre-deployment check that config.yaml exists with valid provider.

3. **Vague block reasons accumulating** — agents blocked with reasons like "error happened" making the queue impossible to triage. Fix applied: mandatory Block Triggers table; agent only picks from documented reasons.

4. **Verification AFTER complete** — verification is now the final workflow step, gates the complete call (see `chief-manager` Phase 7 supplement).

5. **SOUL.md must reference existing skills via `skill_view()`, never duplicate their logic inline.** If an existing skill covers what the agent needs — yt-dlp flags, Whisper API, Chroma endpoints, cookie patterns, web search — the SOUL.md must tell the agent: `Load skill_view(name='<skill-name>') at startup and follow its protocol for <X>.` Never copy-paste commands, endpoints, or parameters from a skill into SOUL.md. **Why:** when the skill is patched, the SOUL.md copy stays stale and the agent silently follows the wrong procedure — no error, just wrong output or 0 results. (Lesson 2026-05-18: youtube-indexer SOUL.md had hardcoded yt-dlp flags copied from an earlier conversation; the canonical `--cookies-from-browser firefox:/opt/firefox-profile` flag was in `video-preprocessor` skill. The SOUL's copy omitted it → 0 downloads until SOUL was rewritten to call `skill_view('video-preprocessor')`.)\n\n6. **Hindsight recall in SOUL.md must use HTTP API, not MCP tool, when using isolated banks.** The MCP tool `hindsight_recall` has no `bank_id` parameter — it always queries the default `hermes` bank. If the expert's knowledge lives in an isolated bank (e.g. `quants-risk`), the onboarding step MUST use the REST endpoint directly:\n   ```python\n   r = requests.post(\n       "http://localhost:8888/v1/default/banks/<BANK_ID>/memories/recall",\n       json={"query": "domain knowledge"}, timeout=20)\n   for m in r.json().get("memories", []): print(m.get("content", ""))\n   ```\n   Add this as `### Step 0 — Recall domain knowledge` in every domain expert's SOUL.md `## Onboarding Protocol`. See `chief-manager/references/hindsight-bank-isolation.md` for the full API contract and async loading pattern.\n\n## Related skills

- **profile-design** — when/why to create a new profile vs extend existing (naming, scope, lifecycle)
- **profile-loadout** — model tier + toolsets selection for profiles
- **chief-manager** — orchestration meta-skill with decomposition, dispatch, monitoring, and phased team formation

## Reference files

- `references/toolset-tool-mapping.md` — which toolsets provide which tools; verification checklist for SOUL.md authors
