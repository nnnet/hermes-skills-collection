---
name: desire-to-goal
description: |
  Schema-driven clarification. Engine handles slot extraction, phase
  routing, anti-pattern detection and final YAML artifact. Bot calls
  /opt/workflow-engine/cli.py and forwards mini_prompt to TG.
when_to_load: |
  On any vague-desire user message ("автоматизируй мой дом", "помоги
  с X", "хочу Y"). Trigger same as v1.

# Tool-gating policy. Standard declarative format for skill-level
# tool restrictions. Read by ``desire-to-goal-driver`` plugin (and
# any future generic skill-policy plugin). NOT read by workflow-engine —
# phase machine stays tool-agnostic.
#
# Semantics:
#   by_phase: per-phase override. Phase names match workflow/schema.yaml.
#     Each entry: ``allowed: [...]`` (whitelist) OR ``blocked: [...]`` (blocklist)
#     OR ``allowed: ['*']`` (open everything, typically on DONE).
#     Globs supported: ``kanban_*`` matches all kanban_* tools.
#   default: applied when current phase has no by_phase entry.
#
# Resolution at hook time (in desire-to-goal-driver plugin):
#   1. Look up current state.phase from workflow_invocations.
#   2. Apply by_phase[<phase>] if present, else default.
#   3. Violating tool call → plugin returns synthetic error and does NOT
#      forward to the real tool.
#   4. pre_llm_call also injects current block-list into system message
#      (defence-in-depth: model usually obeys text, hook catches misses).
tools:
  # Blacklist semantics: by default ALL tools are available; we only
  # block the ones that conflict with goal-clarification (delegation +
  # destructive execution). The bot keeps cronjob, fs_*, web_*, voice
  # and everything else needed for normal one-shot self-execute tasks.
  by_phase:
    DECOMPOSE:
      blocked: [chief_spawn, mc_task_create, mc_task_assign, mc_project_create, kanban_create, kanban_assign, kanban_block]
    REFLECT:
      blocked: [chief_spawn, mc_task_create, mc_task_assign, mc_project_create, kanban_create, kanban_assign, kanban_block]
    LOCK:
      blocked: [chief_spawn, mc_task_create, mc_task_assign, mc_project_create, kanban_create, kanban_assign, kanban_block]
    DONE:
      blocked: []  # everything allowed — handoff to next skill
  default:
    blocked: [chief_spawn, mc_task_create, mc_task_assign, mc_project_create, kanban_create, kanban_assign, kanban_block]
---

# desire-to-goal (engine-driven, v4 — registry + lifecycle)

## Lifecycle (с 2026-05-25)

Скилл больше **НЕ владеет** session id. Владелец — плагин
`desire-to-goal-driver`. Workflow-движок хранит state в sqlite-таблице
`workflow_invocations` (в `state.db`), а не в .json файлах. Идентичность:

  `(workflow_name, agent_id, conversation_id, invocation_id)`

где `invocation_id` = `YYYYMMDDTHHMMSS-<rand4>` (UTC, генерируется при
INIT и **не меняется** до FINISH).

Лайфцикл (плагин делает сам):
- **INIT** — первое vague-desire сообщение → `Registry.start(...)` →
  новый invocation_id.
- **CONTINUE** — следующий turn → `Registry.find_active(...)` находит
  ту же invocation, движок продолжает с того же state-blob.
- **CANCEL** — intent "забудь / сначала / отмени" → `Registry.cancel(...)`
  ДО следующего вызова движка. Новая vague-desire → новая invocation.
- **FINISH** — фаза достигла терминала (DONE) → движок сам вызывает
  `Registry.finish(...)`. Артефакт YAML на диск, state-blob в БД с
  `finished_ts` для аудита.
- **JANITOR** — cron каждые 10 мин сметает invocations с
  `last_active_ts < cutoff` (3h default, 5min для is_test=1).

Одновременно может быть N активных invocations от разных
agent_id+conversation_id (main vs chief-XYZ vs worker-N) — каждая в
своей строке БД, изолированы.

## Алгоритм каждого turn'а

**КРИТИЧНО**: плагин `desire-to-goal-driver` запускает движок
**АВТОМАТИЧЕСКИ** на `pre_llm_call`. Ты **НЕ ДОЛЖЕН** вызывать его
вручную через `terminal`, `execute_code` или любой shell-tool. Если
ты увидел запрос пользователя, плагин уже подготовил `mini_prompt` —
он попадёт в твой следующий system message.

**Что делать каждый turn:**

**Шаг 1.** В system message ищи блок от plugin: `mini_prompt`,
`state_summary`, `phase`. Это уже подготовлено плагином.

**Шаг 2.** Возьми `mini_prompt` и **скопируй дословно в reply_to_user**.
Заполни `<placeholders>` из `state_summary.slots` (extractor уже
извлёк) или последнего user-сообщения.

**Шаг 3.** Если `state_summary.phase == DONE` — workflow закончен.
Плагин сам передаст управление следующему скиллу (chief-manager).
Ты НЕ делаешь chief_spawn / delegate_task сам в этом turn'е.

**Шаг 4.** Stop. Никаких additional tool calls в этом turn'е.

**ЗАПРЕЩЕНО**:
- `terminal: python3 /opt/workflow-engine/cli.py ...` — это уже
  делает плагин. Ручной вызов = двойная работа + security-scan
  блокирует Cyrillic-text в args (homoglyph detection).
- `execute_code` с импортом engine модулей.
- Любые попытки «помочь движку» вручную. Плагин — единственный
  invoker.

## Что extractor умеет

Extractor LLM получает (1) schema из `schema.yaml`, (2) текущее
состояние slots, (3) последние 6 turn'ов диалога. Возвращает на
каждый slot:
- `value` — извлечённое значение или null
- `confidence` 0..1 — насколько прямо следует из user-text
- `reasoning` — короткое обоснование

Calibration confidence:
- 0.95 — прямая цитата
- 0.75 — близкий перифраз
- 0.50 — разумный вывод из контекста
- < 0.40 — отбрасывается

## Что НЕ делай

- НЕ заполняй slots сам — это работа extractor'а. Если extractor дал
  низкую confidence (`< threshold_high`), движок сам форсит re-ask.
- НЕ переписывай mini_prompt своими словами — anti-pattern guards
  внутри уже учтены.
- НЕ зови движок больше одного раза в turn'е.

## Критический питфолл: свободный текст НЕ двигает движок

**Выводить декомпозицию в свободном тексте («Цель: ..., Средство: ...»)
и получать текстовое подтверждение пользователя НЕ достаточно для перехода
в фазу DONE.** Движок отслеживает своё состояние через post_llm_call хук,
который ищет `mini_prompt` дословно скопированный из system message.

Пока движок не в DONE — F1-ворота блокируют `execute_code`, `terminal`,
`write_file` и другие side-effecting инструменты, даже если пользователь
написал «ОК, жду».

**Правильный алгоритм:**
1. Получить `mini_prompt` из system message (блок от плагина).
2. Скопировать его **дословно** в ответ пользователю.
3. Дождаться следующего turn'а — движок сам зафиксирует переход.

Если `mini_prompt` нет в system message — движок уже в DONE или не
запустился (fallback к v1-стилю).

## Питфолл: простые медиа/плейбэк-запросы застревают в воротах

Запрос «включи меланхоличную музыку» с явными предпочтениями в профиле
пользователя НЕ требует полного clarification-цикла. Проверь
`references/skip-criteria.md` — такие запросы должны проходить через
skip-path и не запускать invocation.

## STRICT scope — только прояснение цели

Этот скилл занимается **строго одним** — прояснением цели пользователя.
Что **запрещено** в любом ответе скилла (фазы DECOMPOSE / ASK / REFLECT
/ LOCK), без исключений:

- **Meta-объяснения про инфраструктуру**: нельзя писать «Claude Agent
  SDK», «облегчённое окружение», «у меня в схеме сессии только
  WebSearch», «MCP не зарегистрирован», «provider/hindsight/SDK» — это
  утечка деталей реализации в чат с заказчиком.
- **Переадресация юзера**: нельзя писать «открой терминал»,
  «`hermes chat`», «`hermes tui`», «зайди в другой клиент»,
  «попробуй заново в TUI» — побег из роли.
- **Капитуляция / самовольный handoff**: нельзя писать «Цель ясна —
  передаю команде проекта», «передаю задачу тим-лиду», «перехожу к
  действию». Handoff (вызов chief-manager / chief_spawn) делается
  автоматически плагином при достижении фазы DONE — не вручную из
  reply скилла.
- **Имена исполнительских ролей**: нельзя предлагать «тим-лид»,
  «менеджер», «разработчик», «рисёрчер», «QA», «архитектор». User
  заказал результат, организационная форма исполнения — НЕ часть
  прояснения цели.
- **Сроки и обещания**: нельзя писать «сегодня», «завтра», «через
  5 минут», «скоро» — нет данных для оценки в этой фазе.

Ответ скилла — **только** структурированные вопросы и подтверждения
декомпозиции в формате, прописанном в `workflow/prompts.py` для текущей
фазы. Никаких сопроводительных абзацев, никаких «небольших
объяснений», никаких «давайте я расскажу как у меня устроено».

## Session id

TG chat_id. В тестах — run-id. Иначе `"default"`.

## Артефакт (на DONE phase)

YAML на диске рядом со state'ом:

```yaml
session: <id>
workflow: desire-to-goal
желание: [...]              # ВСЕ user-сообщения (audit, не экспорт)
goal:                       # ТОЛЬКО это идёт в next skill
  истинная_цель: "..."
  средство: "..."
  место: "..."
  команда: "..."             # optional
  мотивация: "..."           # optional
confidence: {...}            # per slot, 0..1
turns_used: <N>
clarity_score: 0..1          # F1 metric computed programmatically
export_fields: [goal, confidence, turns_used, clarity_score]
next_skill_hint: goal-to-plan
```

`желание[]` собирает всё что говорит user (для отладки). В следующий
скилл уходит только `goal/confidence/turns_used/clarity_score`.

## Fallback

Если движок падает — используй v1-стиль (3 слота + 2 вопроса +
lock-block в финале). Это деградация — флагни в ответ.

## Инспекция

```bash
# state без advance
python3 /opt/workflow-engine/cli.py --workflow .../workflow --session X --status

# reset (если user сменил тему)
python3 /opt/workflow-engine/cli.py --workflow .../workflow --session X --reset

# история по turn'ам
ls /opt/data/workflow_state/desire-to-goal/history/<session>/v*.json
```

## История изменений архитектуры

- v1 (435 строк промпта): бот сам интерпретировал slots по prompt-инструкциям → drift в 4/16 кейсов.
- v2: state-machine движок + bot заполняет placeholders → надёжнее, но slots всё ещё от LLM-инференса главного бота.
- v3 (текущая): schema.yaml как single source + extractor LLM с
  confidence + programmatic anti-patterns + final YAML artifact. Slots
  заполняет dedicated маленькая модель, главный бот только
  переформулирует mini_prompt и форвардит в TG.
