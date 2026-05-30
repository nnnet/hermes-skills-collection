---
name: desire-to-goal-v2
description: |
  Prototype v2 (2026-05-25). Python-orchestrator-driven version of
  desire-to-goal cycle. The bot calls `clarify_engine.py` ONCE per
  turn, receives a focused per-phase mini-prompt, and uses it as its
  TG reply. State persists in `~/.hermes/clarify_state/<session>.json`.

  Why: SKILL.md v1 grew to 435 lines, bot ignored sections (4/16 cases
  skipped FINAL TURN PROTOCOL in batch-011-p0). v2 moves logic to
  python: 6-state machine (pytransitions) + 5 phase prompts (~70 lines
  each, focused). LLM still does the language generation, but the
  "what should I say next" decision is deterministic.

  This file is the prototype skill body — short, just a runbook to
  call the engine. The heavy lifting is in
  `scripts/clarify_engine.py`.
when_to_load: |
  Load this skill INSTEAD of orientation/desire-to-goal/SKILL.md when
  Hermes-main receives a vague desire that needs clarification.
  Trigger same as v1: build/help/automate requests with unclear scope.
---

# desire-to-goal — v2 (orchestrator)

## Workflow

On every clarification turn, the bot does ONE thing:

```bash
python3 ~/.hermes/skills/orientation/desire-to-goal/scripts/clarify_engine.py \
    --session "$CHAT_SESSION_ID" \
    --user "$LATEST_USER_MESSAGE" \
    [--prev-bot "$YOUR_PREVIOUS_REPLY_IF_ANY"]
```

The engine returns a JSON object:

```json
{
    "phase": "DECOMPOSE|ASK|REFLECT|LOCK|DONE",
    "iteration": 2,
    "state_summary": {...},
    "mini_prompt": "<markdown — use this AS YOUR REPLY>",
    "instructions_for_bot": "<one-liner about what to do>"
}
```

## How to use the response

1. **Take `mini_prompt` verbatim** as the body of your TG reply.
   - You MAY tweak phrasing for personality/tone (kawaii markers, etc.)
   - You MUST NOT add new slot content the engine didn't include
   - You MUST keep the lock-phrase «Истинная цель определена» literal
     when phase=LOCK

2. **Follow `instructions_for_bot`** — most important is the LOCK
   phase: write the lock-block, then PAUSE (no tool calls in the
   same turn unless user already explicitly pushed for action).

3. **Don't loop more than 5 iterations** — engine's force-exit at
   iteration=5 + max_filled=0 means user is unwilling to clarify;
   advisory-EXIT with current state.

## What the engine does for you

- **Slot extraction** from your previous reply (no need to re-parse)
- **Non-answer detection** (user said «начинай» = not an answer to «зачем»)
- **Means-as-goal detection** (warns if истинная_цель looks like proxy)
- **Motivation tracking** (knows if «зачем» was asked / answered)
- **User-push detection** («начинай с defaults» → fast-track to LOCK)
- **Phase routing** (DECOMPOSE → ASK → REFLECT → LOCK → DONE)
- **State persistence** (next turn picks up where you left off)

## Anti-patterns prevented by engine (you don't need to remember)

| Anti-pattern | How engine handles |
|---|---|
| Going straight to config-questions | Forces DECOMPOSE first |
| Interpreting non-answer as answer | Re-asks motivation on next ASK |
| Skipping FINAL TURN PROTOCOL | LOCK prompt mandates lock-phrase |
| Means-as-goal lock-in | Detector flags via state_summary |
| Forgetting to ask «зачем» | Forced into DECOMPOSE template |

## Anti-patterns NOT prevented (still your job)

- Brand-listing in clarification questions (engine warns in prompt)
- Filling slots from training (engine warns; you must self-check)
- Single-track strategy lock-in (research ≥3 alternatives before lock)

## Inspection / debug

Status without advancing:
```bash
python3 .../clarify_engine.py --session $SESS --status
```

Reset state (e.g. user changed topic):
```bash
python3 .../clarify_engine.py --session $SESS --reset
```

## Edge cases

- **Engine errors** → fall back to v1 SKILL.md (the markdown one)
- **pytransitions not installed** → engine exits 2 with install hint
- **State file corrupted** → delete it, engine creates fresh on next call

## Architecture notes for future maintainers

- 3-slot model matches `infra/hermes/test/clarification/models/simple-3-slot.yaml`
- Detectors reuse logic from `infra/hermes/test/clarification/lib/clarity.py`
- State machine has 6 states + 5 transitions — see scripts/clarify_engine.py:ClarifyMachine
- Adding new phases: add to `states`, `transitions`, write `prompt_<phase>(...)`, route in `decide()`

## Migration plan (v1 → v2)

1. Phase 0 (now): v2 lives alongside v1 as alt-skill. Manual swap via
   `--skill desire-to-goal-v2` for testing.
2. Phase 1: Run quick-smoke 6 cases on v2; if PASS rate > v1 → keep iterating.
3. Phase 2: Full 16-case batch on v2; if ≥5 PASS → propose making it default.
4. Phase 3: Move clarify_engine.py + this SKILL to a Hermes plugin
   (`plugins/cyclic-controllers/desire-to-goal/`) for cleaner shipping.
5. Phase 4: Generalize to other cyclic skills (risk-assessment,
   negotiation, discovery) sharing the same engine core.
