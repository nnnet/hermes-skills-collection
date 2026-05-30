# Worked Examples — Desire to Goal

## Example 1: "Сделай мне сайт"

**Desire:** "Сделай мне сайт"
**Decomposition:**
- True goal: новые клиенты / публичное присутствие (метрика неизвестна)
- Means: сайт — один из вариантов
- Place: веб

**Key clarification question:** зачем сайт — портфолио, продажи, блог? (меняет всю архитектуру)

---

## Example 2: "Дашборд по моим финансам"

**Desire:** "Дашборд по моим финансам"
**Decomposition:**
- True goal: контроль над финансами (какой именно — расходы, инвестиции, сбережения?)
- Means: дашборд — один из вариантов (возможен чат-бот, таблица, уведомления)
- Place: домохозяйство / личные финансы

**Key clarification question:** какие данные уже есть (CSV, банк API, ручной ввод)?

---

## Example 3: "Бот, торгующий крипту прибыльно" ← CRYPTO BOT

**Desire:** "Бот, торгующий крипту прибыльно"

**Decomposition (correct form):**
> — **Истинная цель**: заработать на крипте. Неясно: *сколько* и *зачем* — развлечение/игра, пассивный доход, или реально заменить часть дохода? Горизонт?
> — **Средство**: бот (автоматический). Один из вариантов.
> — **Место/контекст**: крипторынок. Биржа, размер депозита, риск-аппетит — пока неизвестны.

**Key clarification question (ONE):** реальные деньги или paper trading?
- Это не config-вопрос — это архитектурный. Real money требует API-ключей, другой риск-менеджмент, другую стратегию тестирования.

**What NOT to ask first (MeansAsGoalAntiPattern):**
- ❌ "Какую биржу использовать?"
- ❌ "EMA или RSI?"
- ❌ "Какой стек — Python или JS?"

These are config questions about the *means*, not goal questions. They anchor the user before the goal is clear.

**Critical pitfall — "continuation that isn't":**
If the user *already has* a paper-trading bot with signals and comes back saying "make it profitable" — this is NOT a continuation request. It is a NEW desire. The existing bot is context, not a commitment to the means. Treat "profitable" as the desired outcome and clarify it fresh. Don't assume:
- "profitable" means "keep EMA+RSI but tune params"
- The user wants to stay on paper trading
- The existing strategy is the right foundation

Apply full desire-to-goal decomposition even when there's prior work.

**Exit criteria for this class:**
- Confirmed: real vs paper (changes architecture completely)
- Confirmed: risk tolerance / bankroll order of magnitude (changes position sizing)
- Confirmed: time horizon (scalping vs swing vs hold changes strategy class)
- Can proceed without knowing: exact exchange, specific indicator params (resolved in build phase)

**User profile note (non-technical hobbyist):**
Skip questions about stack, CI/CD, backtesting frameworks. Those belong in the chief brief, not clarification. Ask about *outcomes*, not *implementation*.
