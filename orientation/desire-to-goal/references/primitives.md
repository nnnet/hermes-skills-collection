# 8 Primitives — clarification ontology

The clarification skill works with a minimal set of 8 primitives. Each one
answers a different question. Missing any of them past iteration 2 should
trigger a corresponding `ASK` or `REFLECT` action.

## Taxonomy

| # | Primitive | Question | Type | Required for `OperationalGoal` |
|---|---|---|---|---|
| 1 | **Хотелка** | Что хочет user в его словах? | string | yes (always) |
| 2 | **Субъект** | Кто исполняет? Какие ресурсы и ограничения? | dict | yes |
| 3 | **Контекст** | В какой среде? Какие внешние ограничения? | dict | yes |
| 4 | **Цель** | Что конкретно должно получиться? | string | yes |
| 5 | **КритерийУспеха** | Как поймём что готово? | list[str] | yes |
| 6 | **Метрика** | Чем измеряем? | list[str] | yes |
| 7 | **Ограничения** | Что нельзя? Когда дедлайн? | list[str] | recommended |
| 8 | **Гипотеза** | На каких допущениях стоит цель? | list[str] | recommended |

## Dependencies (DAG)

```
Хотелка (root, always)
  ├── Субъект (independent root)
  └── Контекст (independent root)
        ├── Ограничения  (from Контекст)
        └── ...
  └── Цель (depends on Хотелка)
        ├── КритерийУспеха (depends on Цель)
        ├── Метрика        (depends on Цель)
        └── Гипотеза       (depends on Цель + Контекст)
```

**Rule of inference:**
- Цель без Хотелки — bogus (CriteriaWithoutGoal anti-pattern)
- КритерийУспеха без Цели — нельзя (CriteriaWithoutGoal)
- Метрика без Цели — нельзя (MetricsWithoutGoal)
- Гипотеза без Контекста — слабая (HypothesisWithoutContext)

## What each primitive contains

### 1. Хотелка (raw desire)

The original user request, verbatim. **Never rewrite or "improve"** — it's a forensic artifact. Used for:
- Goal-drift detection (compare final goal vs raw desire by Jaccard)
- Persona auto-detection (keyword scan)
- Audit trail

### 2. Субъект (subject)

Who is doing the work, and what they bring to the table:

```python
subject = {
    "role": "founder" | "data_scientist" | ...,
    "skill_level": "beginner" | "intermediate" | "expert",
    "available_resources": ["compute", "team", "budget"],
    "constraints_self": ["only weekends", "no JS expertise"],
    "motivation": "why they care",
}
```

Most clarification skips this — and produces goals that look right but can't be executed by the actual person.

### 3. Контекст (context)

The environment around the goal:

```python
context = {
    "domain": "fintech" | "education" | ...,
    "stakeholders": ["users", "compliance team", "investors"],
    "time_horizon": "1 week" | "Q4 2026" | "long-term",
    "external_constraints": ["GDPR", "fixed budget", "legacy stack"],
    "current_state": "what exists today",
}
```

### 4. Цель (goal statement)

ONE sentence stating what should exist when the goal is achieved.

Good: "Onboarding flow with 80% completion rate by end of Q1"
Bad: "Improve onboarding"

If you can't write it in one sentence, the goal isn't ready.

### 5. КритерийУспеха (success criteria)

3-7 binary observable conditions. Each one is verifiable by inspection — no judgment.

Good criteria:
- "User reaches dashboard within 2 minutes of signup"
- "Funnel has <30% drop-off at each step"
- "No errors in Sentry from onboarding code path for 1 week"

Bad criteria:
- "Users are happy"  (not observable)
- "It's a good UX"   (judgment-based)
- "Improved"         (vague)

### 6. Метрика (metrics)

The measurement protocol for each criterion. Usually:
- Source (Mixpanel, Datadog, manual count)
- Frequency (daily, post-launch, one-shot)
- Threshold (>80%, <30%, exactly 1)

Often missed: criteria stated as if measurable, but no instrument exists to measure them.

### 7. Ограничения (constraints)

Hard and soft limits:
- **Hard**: deadline, budget cap, regulatory requirement, "cannot use X tool"
- **Soft**: preferences, "prefer X but Y acceptable", aesthetic concerns

Should also include **out-of-scope** items (what NOT to do, prefixed with "не" / "exclude" / "out of scope").

### 8. Гипотеза (hypotheses)

Explicit assumptions on which the goal stands. Format:

> "I assume X → Y → goal achieved"
> e.g. "I assume that lowering signup steps from 7 to 3 will reduce drop-off"

The point: **make assumptions visible** so they can be challenged. Hidden assumptions are the leading cause of goals that look good but fail in execution.

## Minimal sets (only one used in v1)

We use **one** minimal set: `OperationalGoal`. A goal is operational when primitives 1-6 are filled with non-empty values, and at least one of {Ограничения, Гипотеза} is filled.

(In the original ontology user provided there were 5 levels — АбсолютныйМинимум through МасштабируемаяСистема. We compressed to one level because over-leveling slows down clarification without changing outcomes.)

## When to leave a primitive empty

Sometimes a primitive genuinely doesn't apply:
- **Ограничения** can be empty for a personal-curiosity goal
- **Гипотеза** can be empty for a small well-understood task
- **Стейкхолдеры** (inside Контекст) can be {"self": true} for solo work

Empty primitive ≠ unfilled — distinguish in the state. Use a sentinel like `{"_intentionally_empty": True}` if needed.

## How the controller uses primitives

`estimate_confidence()` counts filled primitives / 8.
`detect_anti_patterns()` looks for dependency violations (e.g. criteria without goal).
The agent uses this taxonomy to know **which primitive to ask about** when action=ASK.
