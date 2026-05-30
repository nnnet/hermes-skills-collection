"""desire-to-goal — phase prompt builders.

One function per phase. Each takes WorkflowState + latest user_msg and
returns a markdown string the bot should use as its TG reply.

Anti-patterns called out per-phase:
- DECOMPOSE: no brand-listing, no slot fabrication
- ASK: no non-answer interpretation, no training-fill
- REFLECT: stability (don't churn goal phrasing)
- LOCK: mandatory lock-phrase, defaults must be user-grounded

Global rule (enforced via STRICT_CLARIFICATION_ONLY in every prompt):
the skill output is ONLY clarification of the goal. No meta-explanations
about SDK, environment, available tools, or surrender phrases.
"""
from __future__ import annotations

from typing import Any


# Shared preamble injected at the top of every phase prompt.
# This skill MUST stay strictly inside goal-clarification scope; any
# explanation about infrastructure, available tools, or capability
# limits is out of scope and breaks the user contract.
STRICT_CLARIFICATION_ONLY = """\
**STRICT RULE — applies to ALL phases of this skill**:
Этот скилл занят ОДНИМ — прояснением цели пользователя. Всё остальное
вне scope'а. В ответе ты НИКОГДА не делаешь следующее:

1. НЕ объясняешь пользователю как ты устроен внутри:
   запрещены упоминания «Claude Agent SDK», «облегчённое окружение»,
   «у меня в этой сессии нет тулов», «ограниченный режим», «MCP», «API»,
   «schema этой сессии», «SDK», «провайдер», «hindsight», и любых других
   технических деталей о собственной инфраструктуре.
2. НЕ предлагаешь юзеру «открой терминал», «зайди в TUI», «напиши
   `hermes chat`», «используй CLI», «перезапусти», «открой
   другой клиент», «попробуй в другом интерфейсе» — это побег из роли.
3. НЕ объявляешь капитуляцию: «Цель ясна — передаю команде проекта»,
   «передаю задачу тим-лиду», «вот, перехожу к действию» — на этой
   фазе у тебя НЕТ права делать handoff. Скилл сам решает когда фаза
   DONE и handoff происходит автоматически.
4. НЕ называешь имена ролей исполнителей: «тим-лид», «разработчик»,
   «рисёрчер», «QA», «менеджер», «команда» — не часть этого скилла.
   Если user их упомянул — отнесись как к контексту, не подхватывай.
5. НЕ обещаешь сроков, не даёшь дедлайнов, не говоришь «скоро»,
   «завтра», «через 5 минут» — у тебя в этой фазе нет данных для этого.
6. НЕ генерируешь IMPLEMENTATION-уровень: запрещены «первая гипотеза»,
   «OSINT-вывод», «купить домен X», «выбор ниши», «kill-switch если…»,
   «pipeline: A → B → C», «архитектура: …», «стек: …». Это работа
   следующего скилла (chief-manager). Здесь — только формулировка
   ЦЕЛИ, а не как её достигать.
7. НЕ пиши filler-ответы: «Жду твоего сообщения», «Жду указаний»,
   «Здесь, жду», «Готов, пиши», «Что-то пошло не так? Напиши» — это
   признак того, что у тебя нет содержания. Если нечего сказать —
   эмитируй mini_prompt текущей фазы дословно, без обёрток.

Твой ответ — ТОЛЬКО структурированные вопросы о цели или подтверждение
декомпозиции в формате, который дан ниже для текущей фазы.
"""


def decompose(state: Any, user_msg: str) -> str:
    """First turn — decompose the vague desire into 3-slot template + 2 questions."""
    return STRICT_CLARIFICATION_ONLY + "\n\n" + f"""Ты получил **размытую хотелку** от user'а:

> {user_msg}

**Твой следующий ответ должен быть ТОЛЬКО:**

1. Разложение на 3 слота (markdown):
   ```
   Понял так. Разложу как услышал — поправь:

   — **Истинная цель**: <ровно потребность которую слышу за словами, или **не указано**>
   — **Средство**: <ровно то существительное что озвучено> — **детали не указаны** (если так)
   — **Место/контекст**: <ровно то что озвучено, или **не указано**>

   Правильно понял? И **два важных вопроса**:

   1. **Зачем тебе это?** <конкретные категории-варианты — финансовая независимость? хобби? давление? — БЕЗ перечисления конкретных продуктов/брендов>
   2. **Про рамки**: рассматриваем только этот вариант средства, или открыт к альтернативам?
   ```

**ЗАПРЕЩЕНО**:
- Дописывать в слоты бренды/стек/числа/конкретику из training (если user их не озвучил → **не указано**)
- Перечислять бренды/продукты в вопросе про рамки (категории — да; «Bybit/Binance/AmoCRM» — нет, если user не попросил)
- Задавать config-вопросы про средство («какая биржа?») до подтверждения декомпозиции

После этого жди ответ user'а и ничего больше не делай.
"""


def ask(state: Any, user_msg: str) -> str:
    """Mid-cycle — user gave partial info, ask focused follow-up."""
    missing = [
        k for k in state.slots.required_keys()
        if not state.slots.get(k)
    ]
    motivation_answered = state.extras.get("motivation_answered", False)

    motivation_hint = ""
    if not motivation_answered:
        motivation_hint = (
            "\n**ВАЖНО**: вопрос «зачем тебе это» ещё НЕ получил ответа по существу. "
            "Переспроси его (можно перефразировать), потому что без motivation "
            "Истинная цель будет proxy/means."
        )

    return STRICT_CLARIFICATION_ONLY + "\n\n" + f"""Юзер ответил:

> {user_msg}

**State**: заполнено {state.slots.filled_required()}/{len(state.slots.required_keys())} обязательных слотов.
**Не заполнено**: {", ".join(missing) or "ничего"}.

**Твой ход**:
1. Кратко acknowledge что услышал из user-ответа
2. Зафиксируй (echo) что user уже сказал в слотах — НЕ добавляй своё
3. Задай ОДИН точный вопрос по самому критичному незаполненному слоту{motivation_hint}

**ЗАПРЕЩЕНО**:
- Интерпретировать non-answer как ответ («ты сказал X — это значит Y, правильно?»)
- Заполнять пустые слоты из training (NO Bybit/EMA/AmoCRM/HomeAssistant defaults без explicit user-mention)
- Перечислять бренды (категории — ок, бренды — нет, если user не просил)
- Делать chief_spawn / action

Если user explicit refused отвечать на какой-то слот — оставь `не указано`, не дави.
"""


def reflect(state: Any, user_msg: str) -> str:
    """User confirmed/refined — re-present locked decomposition for ack."""
    s = state.slots
    return STRICT_CLARIFICATION_ONLY + "\n\n" + f"""Юзер ответил:

> {user_msg}

**Текущий state**:
- Истинная цель: {s.get('истинная_цель') or '**не указано**'}
- Средство: {s.get('средство') or '**не указано**'}
- Место/контекст: {s.get('место') or '**не указано**'}

**Твой ход**: переподтверди декомпозицию в исправленной форме:
```
Тогда так:
— **Истинная цель**: <финальная формулировка>
— **Средство**: <финальная>
— **Место/контекст**: <финальная>

Всё верно? Если да — я готов перейти к действию.
```

**ВАЖНО**: формулировки должны быть **стабильны** vs предыдущий turn — если user не сказал «нет, не так», не меняй goal phrasing. Меняй только то что user поправил.
"""


def lock(state: Any, user_msg: str) -> str:
    """Final turn — MUST write lock-block before any action."""
    s = state.slots
    return STRICT_CLARIFICATION_ONLY + "\n\n" + f"""Юзер дал зелёный свет.

**ТВОЙ ОТВЕТ ОБЯЗАН начаться с lock-блока. БЕЗ ВАРИАЦИЙ.**:

```
**Истинная цель определена**: {s.get('истинная_цель') or '<сформулируй на основе диалога>'}
**Применяю defaults для не-озвученных слотов**:
- <slot1>: <короткое значение> (потому что <конкретное обоснование, опирающееся на user-input>)
- <slot2>: <короткое значение> (потому что <обоснование>)

Если что-то поправить — скажи сейчас, иначе передаю дальше.
```

**КРИТИЧНО**:
- Фраза «**Истинная цель определена**» — буквальная, без вариаций (это метрика)
- НИКАКОГО раздела «**План действия**», «**Pipeline**», «**Старт**»,
  «**OSINT**», «**Reporting**», «**Autonomy**», «**Kill-switch**» и
  любых других реализационных секций. На фазе LOCK ты только
  ФИКСИРУЕШЬ цель + defaults для слотов, не описываешь КАК будешь
  это делать. План реализации — работа следующего скилла, не твоя.
- НЕ делай chief_spawn / terminal в этом же turn'е (только текст-ответ); handoff случится автоматически после DONE
- Defaults — только те что **ОБОСНОВАНЫ user-input'ом** (если user сказал «без облака» → default = local stack). НЕ default = «Bybit потому что популярно» — это training-fill, НЕ ОК.
- Если slot заполнен user'ом — пиши его дословно. Если default — пометь «(default)» в скобках.
- Значение каждого slot'а — короткая строка (1-6 слов), не абзац.
"""


def done(state: Any, user_msg: str) -> str:
    """Already locked — execute action."""
    return (
        f"Цель уже зафиксирована на turn {state.iteration - 1}. "
        f"Выполняй action из плана. Если user написал новое — проверь "
        f"не отзывает ли lock; если нет — продолжай действие."
    )
