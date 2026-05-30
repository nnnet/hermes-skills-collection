# Action modes — when which one

The `ClarificationController` picks ONE action per iteration. This doc explains each, when it fires, what the agent should actually do, and what NOT to do.

## Quick decision tree

```
unresolved contradictions exist?  ─► ACKNOWLEDGE
confidence ≥ 0.7 AND stability ≥ 0.7?  ─► EXIT
confidence < 0.4?  ─► ASK
stability < 0.5?  ─► REFLECT
confidence < 0.65?  ─► HYPOTHESIZE
domain unfamiliar to LLM?  ─► RESEARCH
else  ─► ASK
```

The controller in `clarifier.py:select_next_action` implements this. RESEARCH is invoked by the agent's own judgment (the controller never picks RESEARCH by itself — it's a tool the agent reaches for).

---

## 1. ASK

**When**: low confidence, missing primitives.

**Goal**: extract NEW information from the user.

**Rules**:
- Maximum 3 questions per round
- All OPEN-ended (avoid yes/no, avoid multiple-choice unless legitimately enumerable)
- Questions phrased from the **active persona** (different persona ≠ different content, but DIFFERENT WORDING for the same question — that's the point)
- Pick questions by EVPI — the answer should change the plan

**Bad questions** (do NOT ask):
- "Is the deadline important?" — yes/no, useless
- "What format should the deliverable be in: a) PDF b) Markdown c) Slack message d) Notion?" — checklist; let user invent if not in list
- "Could you fill in this template?" — interrogation

**Good questions**:
- "Что должно произойти, чтобы ты сказал 'готово'?" (criteria)
- "Кто заметит результат, если он будет? А если не будет?" (stakeholders + value)
- "Что прямо сейчас НЕ работает в текущем процессе?" (context)

**Persona shapes wording**:
- `maieutic`: "Что для тебя самое важное в этой задаче?"
- `business`: "Какую бизнес-метрику это должно сдвинуть?"
- `psychologist`: "Что тебя на самом деле раздражает в текущей ситуации?"
- `journalist`: "Кто, что, когда — давай разложим по фактам?"

---

## 2. REFLECT

**When**: stability low (goal keeps changing), or anti-pattern `CriteriaWithoutGoal` / `MetricsWithoutGoal` fires.

**Goal**: confirm understanding, stabilize the formulation.

**Rules**:
- Paraphrase the current state in ONE sentence
- Ask: "Правильно понял? Что не так?"
- DO NOT introduce new primitives in REFLECT — that's HYPOTHESIZE's job
- DO NOT just echo back verbatim — the paraphrase must add structure or compress

**Bad reflect** (echo):
> "Ты сказал ты хочешь сайт. Правильно?"

**Good reflect** (compressed + structured):
> "Резюмирую: ты хочешь одностраничный сайт-визитку для своей консалтинговой
> практики, с формой обратной связи и базовой SEO, готовый к запуску за 3 недели.
> Что я упустил или понял неправильно?"

---

## 3. HYPOTHESIZE

**When**: stable but ambiguous — user keeps saying the same words but underlying intent might vary.

**Goal**: surface hidden interpretations.

**Rules**:
- Generate 2-3 interpretations that genuinely differ
- Each interpretation should imply different downstream tasks/agents
- Let user pick or say "ни одна не подходит, на самом деле ..."

**Example**:

User said: "Хочу больше клиентов"

Three hypotheses to surface:
1. "Хочешь повысить **конверсию** существующего трафика (UX, копирайтинг)"
2. "Хочешь **привлечь больше трафика** (SEO, реклама, PR)"
3. "Хочешь **удержать** текущих клиентов дольше (retention, продлевать продукт)"

Each leads to entirely different work. Without surfacing, the agent might pick #2 by default and waste effort.

**Bad hypothesize**: alternatives that differ only in surface words, not substance.

---

## 4. RESEARCH

**When**: there's `model uncertainty` — the LLM doesn't know enough about the domain to ask useful questions. The user shouldn't pay for that with their time.

**Goal**: reduce LLM's domain ignorance.

**Rules**:
- Use `web_search` / `web_extract` (or `web-search-service` skill)
- DO NOT bring research findings to user as questions ("did you know that ...?")
- Use findings to make the NEXT question more informed
- 1-2 minutes max per research detour

**Example**:

User said: "Хочу настроить мониторинг для нашего сервиса"

Before asking about specifics, search:
- "монiторинг продакшен Python сервисов основные инструменты"
- "Prometheus vs Datadog vs Grafana 2026 production"

Now the next ASK can be informed: "Я вижу три типа мониторинга — инфраструктурный, app-level, business-level. Какой у тебя в приоритете прямо сейчас?"

**Anti-pattern**: research что user знает. If user said "Datadog", don't research "what is Datadog" — research things ABOUT Datadog they may not know.

---

## 5. ACKNOWLEDGE

**When**: `contradiction_log.unresolved()` non-empty.

**Goal**: surface contradiction, get user's stance, then move on (with status).

**Rules**:
- Present the contradiction clearly: "Ты раньше сказал X, теперь Y. Кажется противоречием."
- Offer three stances:
  - **resolved**: pick one side (which?)
  - **acknowledged**: leave both, it's a real tension to manage
  - **open**: still unclear, keep clarifying
- Record the result via `resolve_contradiction(idx, status, comment)`

**Why acknowledged is valid**: real-world goals often contain genuine tensions ("be fast AND cheap", "support legacy AND modernize"). Forcing resolution prematurely destroys information.

**Example**:

> "Раньше ты сказал что бюджет 100к, но потом упомянул что хочешь нанять консультанта за 50к/мес — это противоречие. Варианты:
> - resolved: бюджет на самом деле X
> - acknowledged: оба True, надо распределить (тогда я учту в плане)
> - open: ещё думаешь — продолжаем уточнять"

---

## 6. EXIT

**When**: sufficiency reached OR soft cap + user confirms stop.

**Goal**: finalize and produce artifacts.

**Rules**:
- Last sanity check: run `detect_anti_patterns()` one more time
- If any severity ≥ 0.8 fires → DO NOT exit. Reset action to ASK or REFLECT.
- Otherwise: call `build_goal_for_chief_manager()` + `save_artifact(workspace_path)`
- Pass the resulting Goal to next phase (usually chief-manager Phase 1)

**What to tell the user on exit**:
> "Готово. Я зафиксировал цель в `goal.json`. Confidence=0.85, Stability=0.78,
> persona=`business`. Передаю в [следующий шаг]."

---

## Persona swapping mid-conversation

The `active_persona` is auto-detected from the raw desire BUT can switch mid-clarification if the conversation drifts into another domain. The agent should call `c.set_persona("new_persona_name")` when:
- The actual content moved into another domain (started with "сайт", evolved into "брендинг + SEO + контент")
- The user signals: "забудь про бизнес-метрики, мне просто понравиться"
- Anti-pattern `GoalDrift` fires — persona may have been wrong from start

Persona switching IS allowed. Switching twice in same session is a smell — usually means the goal is genuinely confused.

## Mode combinations

You can't pick two actions in one iteration. But the **instruction** for one action can mention insights from another mode:

> Action: ASK
> Instruction: "Сначала упомяни: я заметил противоречие X (ack), потом задай 2 открытых вопроса о Y и Z."

This is the agent's discretion. The controller picks the main action; the agent crafts the actual user-facing message.
