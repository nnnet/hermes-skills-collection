"""clarify_engine.py — Python-driven orchestrator for desire-to-goal cycle.

Why this exists (architecture decision 2026-05-25 after F1 batch-011-p0):

  The desire-to-goal SKILL.md grew to ~3000 lines (decomposition rules +
  anti-patterns + lock protocol + examples). On every turn the LLM has
  to ingest all of it, which (a) costs ~5-10s skill_view time, (b)
  causes the bot to skip sections (4/16 cases ignored FINAL TURN
  PROTOCOL), (c) makes prompt engineering brittle because new rules
  push old rules out of the model's attention window.

  This engine replaces the giant skill prompt with a small per-phase
  prompt generated from a python state machine. The bot calls one
  tool, gets a focused 50-100 line template for the CURRENT phase,
  emits it (with minor adaptation). State persists in a JSON file
  keyed by session id, so multi-turn cycles compose.

Architecture:

  State machine (pytransitions):

      INIT ─start──► DECOMPOSE ─ask──► ASK ─reflect──► REFLECT
                                  ▲                       │
                                  └───────refine──────────┤
                                                          │
                                                       lock▼
                                                       LOCK ──action──► DONE

  Each state has an on_enter callback that builds the mini-prompt
  using the registered phase template + current ClarifyState.

  Detectors (non_answer / means_as_goal / training_grounded) wrap
  decisions inside transition guards — e.g. ASK→REFLECT only fires
  if user_reply was substantive, otherwise re-ASK.

  State persists to ~/.hermes/clarify_state/<session>.json. Read on
  every invocation, written before exit.

Usage from skill / Hermes:

  python3 clarify_engine.py \
      --session <session_id> \
      --user "<latest user message>" \
      [--prev-bot "<previous bot reply>"]

  Output (JSON to stdout):

      {
          "phase": "ASK",
          "iteration": 2,
          "state_summary": {...},
          "mini_prompt": "<markdown template for bot to use>",
          "instructions_for_bot": "<short imperative>"
      }

  Then Hermes-main uses mini_prompt as the body of its TG reply
  (possibly with personality/tone tweaks).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from transitions import Machine
except ImportError:
    print(
        '{"error": "pytransitions not installed", "install": '
        '"uv pip install --python /opt/hermes/.venv/bin/python3 transitions"}',
        file=sys.stderr,
    )
    sys.exit(2)


# ─── Constants ─────────────────────────────────────────────────────────


STATE_DIR_DEFAULT = Path(
    os.environ.get("CLARIFY_STATE_DIR", str(Path.home() / ".hermes" / "clarify_state"))
)
STATE_VERSION = 1


# ─── Slots (3-slot model — keep in sync with simple-3-slot.yaml) ──────


@dataclass
class Slots:
    """Three primitives extracted during decomposition.

    Each slot is either:
      - str (filled with substantive content)
      - None (not yet known / user hasn't told us)

    Optional slot 'команда' is captured but doesn't gate completion.
    """
    истинная_цель: str | None = None
    средство: str | None = None
    место: str | None = None
    команда: str | None = None

    def required_keys(self) -> list[str]:
        return ["истинная_цель", "средство", "место"]

    def filled_required(self) -> int:
        return sum(1 for k in self.required_keys() if getattr(self, k))

    def completeness(self) -> float:
        req = self.required_keys()
        return self.filled_required() / len(req) if req else 0.0


# ─── ClarifyState (persisted across turns) ────────────────────────────


@dataclass
class ClarifyState:
    """All persistent state for one clarification session.

    Serializable as JSON via dataclasses.asdict / dataclass(**dict).
    """
    session_id: str
    version: int = STATE_VERSION
    created_ts: float = 0.0
    updated_ts: float = 0.0
    iteration: int = 0
    phase: str = "INIT"  # mirrors state machine current state
    slots: Slots = field(default_factory=Slots)
    user_history: list[str] = field(default_factory=list)
    bot_history: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    action_log: list[str] = field(default_factory=list)
    last_question_asked: str | None = None
    motivation_asked: bool = False
    motivation_answered: bool = False
    means_as_goal_warned: bool = False
    user_pushed_for_action: bool = False  # «начинай», «уже всё ответил»

    @classmethod
    def load(cls, path: Path) -> "ClarifyState":
        if not path.exists():
            now = time.time()
            return cls(session_id=path.stem, created_ts=now, updated_ts=now)
        raw = json.loads(path.read_text(encoding="utf-8"))
        slots_dict = raw.pop("slots", {})
        st = cls(**raw)
        st.slots = Slots(**slots_dict)
        return st

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_ts = time.time()
        data = asdict(self)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_user_msg(self, msg: str) -> None:
        if msg:
            self.user_history.append(msg)

    def add_bot_msg(self, msg: str) -> None:
        if msg:
            self.bot_history.append(msg)

    def union_user_text(self) -> str:
        return " ".join(self.user_history)


# ─── Detectors (heuristics, reused from clarity.py logic) ─────────────


_WORD_RE = re.compile(r"[a-zа-яё]+", re.IGNORECASE | re.UNICODE)


def _tokens(text: str | None, min_len: int = 3) -> set[str]:
    if not text:
        return set()
    return {t.lower() for t in _WORD_RE.findall(text) if len(t) >= min_len}


# Means tokens (subset that's a goal-as-means, not the means is fine)
_MEANS_TOKENS = {
    "бот", "сайт", "канал", "приложение", "сервис", "магазин",
    "чат-бот", "чатбот", "торговля", "трейдинг",
    "прибыль", "доход", "деньги",
}
_QUALIFIER_HINTS = {
    "для", "чтобы", "ради", "потому",
    "независимость", "свобода", "развитие", "рост",
    "обучение", "практика", "помочь", "помощь", "решить",
    "здоровье", "комфорт", "удобство",
}


def is_means_as_goal(goal_text: str | None) -> bool:
    """True if the goal is just a means/proxy without qualifying context."""
    if not goal_text:
        return False
    norm = goal_text.lower()
    toks = _tokens(norm)
    has_means = any(t in _MEANS_TOKENS for t in toks)
    if not has_means:
        return False
    has_qualifier = any(t in _QUALIFIER_HINTS for t in toks) or any(
        q in norm for q in _QUALIFIER_HINTS
    )
    return not has_qualifier


_NON_ANSWER_PATTERNS = re.compile(
    r"начинай|начни|\bделай\b|уже\s+ответил|defaults?\b|"
    r"как\s+(считаешь|хочешь)|на\s+твой\s+вкус|продолжай|"
    r"go\s*ahead|пох(уй|ер)|не\s+хочу\s+(говорить|называть)",
    re.IGNORECASE,
)
_SURFACE_AFFIRM = re.compile(r"^\s*(ок|угу|да|\+|yes)\s*[.,!?]?\s*$", re.IGNORECASE)


def is_non_answer(user_msg: str | None, prev_question_type: str = "open") -> bool:
    """True if user's reply dodges the question.

    prev_question_type: "open" (zachem/motivation), "yesno" (confirm),
    "choice" (pick from list). Surface affirmations are non-answers
    for open questions but valid for yesno.
    """
    if not user_msg:
        return True
    text = user_msg.strip()
    if _NON_ANSWER_PATTERNS.search(text):
        return True
    if prev_question_type == "open" and _SURFACE_AFFIRM.match(text):
        return True
    return False


def detect_user_pushed_for_action(user_msg: str | None) -> bool:
    """True if user explicitly told the bot to start working."""
    if not user_msg:
        return False
    return bool(re.search(
        r"начинай|начни|defaults?\b|уже\s+(всё\s+)?(ответил|сказал)|"
        r"если\s+(можешь|можно)\s+начать|спрашивай\s+один",
        user_msg, re.IGNORECASE,
    ))


def extract_slots_from_bot_reply(bot_text: str) -> Slots:
    """Parse REFLECT-style bot output into Slots.

    Looks for markdown patterns like:
      — **Истинная цель**: <value-up-to-next-bullet>
    """
    slots = Slots()
    pattern_tmpl = (
        r"\*\*{label}\*\*\s*[:.]?\s*(.+?)"
        r"(?=\n[ \t]*[—\-\*]\s\*\*|\n\n|\Z)"
    )
    labels = {
        "истинная_цель": ["Истинная цель", "True goal", "Цель"],
        "средство": ["Средство", "Means", "Инструмент"],
        "место": ["Место/контекст", "Место", "Place", "Контекст"],
        "команда": ["Команда", "Team", "Состав"],
    }
    placeholder_re = re.compile(
        r"^\s*(не\s+указан[оаы]?|не\s+определен[оаы]?|неизвестно|нет\s+данных)",
        re.IGNORECASE,
    )
    for key, label_list in labels.items():
        for label in label_list:
            pat = pattern_tmpl.format(label=re.escape(label))
            m = re.search(pat, bot_text, flags=re.DOTALL | re.IGNORECASE)
            if not m:
                continue
            val = m.group(1).strip()
            # Strip parens with examples, bold/dash decorations
            val_clean = re.sub(r"\([^)]*\)", "", val).strip()
            val_clean = re.sub(r"^[*_\-—•:.,\s]+|[*_\-—•:.,\s]+$", "", val_clean)
            if placeholder_re.match(val_clean) or not val_clean:
                break
            setattr(slots, key, val)
            break
    return slots


# ─── Phase prompts (per-phase mini-templates) ─────────────────────────


def prompt_decompose(state: ClarifyState, user_msg: str) -> str:
    """First turn: ask bot to decompose the desire into 3-slot template
    PLUS ask 2 questions (motivation + scope)."""
    return f"""Ты получил **размытую хотелку** от user'а:

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


def prompt_ask(state: ClarifyState, user_msg: str, missing: list[str]) -> str:
    """Mid-cycle: user gave partial info, ask follow-up on what's missing."""
    motivation_hint = ""
    if not state.motivation_answered:
        motivation_hint = (
            "\n**ВАЖНО**: вопрос «зачем тебе это» ещё НЕ получил ответа по существу. "
            "Переспроси его (можно перефразировать), потому что без motivation "
            "Истинная цель будет proxy/means."
        )

    return f"""Юзер ответил:

> {user_msg}

**Что заполнено** (state): {state.slots.filled_required()}/3 обязательных слотов.
**Что НЕ заполнено**: {", ".join(missing) or "ничего"}.

**Твой ход**:
1. Кратко acknowledge что услышал из user-ответа
2. Зафиксируй (echo) что юзер уже сказал в слотах — НЕ добавляй своё
3. Задай ОДИН точный вопрос по самому критичному незаполненному слоту{motivation_hint}

**ЗАПРЕЩЕНО**:
- Интерпретировать non-answer как ответ («ты сказал X — это значит Y, правильно?»)
- Заполнять пустые слоты из training (NO Bybit/EMA/AmoCRM/Home Assistant defaults без explicit user-mention)
- Перечислять бренды (категории — ок, бренды — нет, если user не просил)
- Делать chief_spawn / action

Если user explicit refused отвечать на какой-то слот — оставь `не указано`, не дави.
"""


def prompt_reflect(state: ClarifyState, user_msg: str) -> str:
    """User confirmed/refined; bot re-presents the locked decomposition for ack."""
    s = state.slots
    return f"""Юзер ответил:

> {user_msg}

**Текущий state** (всё что собрано):
- Истинная цель: {s.истинная_цель or '**не указано**'}
- Средство: {s.средство or '**не указано**'}
- Место/контекст: {s.место or '**не указано**'}

**Твой ход**: переподтверди декомпозицию в исправленной форме:
```
Тогда так:
— **Истинная цель**: <финальная формулировка>
— **Средство**: <финальная>
— **Место/контекст**: <финальная>

Всё верно? Если да — я готов перейти к действию.
```

**ВАЖНО**: формулировки должны быть **стабильны** vs предыдущий turn — если user не сказал «нет, не так», не меняй goal phrasing. Меняешь только то что user поправил.
"""


def prompt_lock(state: ClarifyState, user_msg: str) -> str:
    """Final turn: bot MUST write lock-block before any action."""
    s = state.slots
    return f"""Юзер дал зелёный свет.

**ТВОЙ ОТВЕТ ОБЯЗАН начаться с lock-блока. БЕЗ ВАРИАЦИЙ.**:

```
**Истинная цель определена**: {s.истинная_цель or '<сформулируй на основе диалога>'}
**Применяю defaults для не-озвученных слотов**:
- <slot1>: <выбор> (потому что <конкретное обоснование, не "обычно так делают">)
- <slot2>: <выбор> (потому что <обоснование>)
**План действия**: <chief_spawn / self-execute / advisory — что именно делаешь>

Если что-то поправить — скажи сейчас, иначе перехожу.
```

**КРИТИЧНО**:
- Фраза «**Истинная цель определена**» — буквальная, без вариаций (это метрика)
- НЕ делай chief_spawn / terminal в этом же turn'е (только текст-ответ); пауза до следующего user-msg
- Если user уже пушил на действие (например «начинай с defaults») — можешь делать spawn ПОСЛЕ lock-блока в этом же turn'е
- Defaults в лок-блоке: только те что **ОБОСНОВАНЫ user-input'ом** (если user сказал «без облака» → default = local stack). НЕ default = "Bybit потому что популярно" — это training-fill, НЕ ОК.
- Если slot заполнен user'ом — пиши его дословно. Если default — пометь «(default)» в скобках.
"""


def prompt_done(state: ClarifyState) -> str:
    """Already locked. Bot should now execute action."""
    return (
        f"Цель уже зафиксирована (lock сделан на turn {state.iteration - 1}). "
        f"Теперь выполняй action из плана. Если user написал что-то новое — "
        f"проверь не отзывает ли он lock; если нет — продолжай действие."
    )


# ─── State machine (pytransitions) ────────────────────────────────────


class ClarifyMachine:
    """Wrapper for pytransitions Machine + ClarifyState mutation."""

    states = ["INIT", "DECOMPOSE", "ASK", "REFLECT", "LOCK", "DONE"]
    transitions = [
        {"trigger": "begin", "source": "INIT", "dest": "DECOMPOSE"},
        {"trigger": "advance_to_ask", "source": ["DECOMPOSE", "REFLECT"], "dest": "ASK"},
        {"trigger": "advance_to_reflect", "source": "ASK", "dest": "REFLECT"},
        {"trigger": "advance_to_lock", "source": ["REFLECT", "ASK", "DECOMPOSE"], "dest": "LOCK"},
        {"trigger": "finish", "source": "LOCK", "dest": "DONE"},
    ]

    def __init__(self, cstate: ClarifyState):
        # NOTE: pytransitions Machine binds `state` attribute on model;
        # we must not name our domain state `self.state` — use `cstate`.
        self.cstate = cstate
        self._machine = Machine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=cstate.phase if cstate.phase in self.states else "INIT",
            auto_transitions=False,
        )

    def decide(self, user_msg: str, prev_bot_msg: str | None = None) -> str:
        """Run one decision step. Returns target phase name."""
        st = self.cstate

        # Pull slots from previous bot reply (incremental update)
        if prev_bot_msg:
            parsed = extract_slots_from_bot_reply(prev_bot_msg)
            for k in ["истинная_цель", "средство", "место", "команда"]:
                v = getattr(parsed, k)
                if v and not getattr(st.slots, k):
                    setattr(st.slots, k, v)

        # Detect user push
        if detect_user_pushed_for_action(user_msg):
            st.user_pushed_for_action = True

        # Detect motivation answered (user provided substantive «зачем»)
        if st.motivation_asked and user_msg and not is_non_answer(user_msg, "open"):
            # Check user mentions any qualifier hint or expressed motivation
            if any(q in user_msg.lower() for q in _QUALIFIER_HINTS):
                st.motivation_answered = True

        # State machine logic — note `self.state` here is pytransitions current state
        if st.iteration <= 1 and (self.state == "INIT" or st.phase == "INIT"):
            self.begin()
            st.motivation_asked = True
            return "DECOMPOSE"

        missing = [
            k for k in st.slots.required_keys()
            if not getattr(st.slots, k)
        ]
        all_filled = not missing

        # If user pushed for action AND we have at least 1 slot — go to LOCK
        if st.user_pushed_for_action and st.slots.filled_required() >= 1:
            if st.phase != "LOCK":
                self.advance_to_lock()
            return "LOCK"

        # If all slots filled AND motivation answered — REFLECT then LOCK
        if all_filled and st.motivation_answered:
            if st.phase in ("ASK", "DECOMPOSE"):
                self.advance_to_reflect()
                return "REFLECT"
            if st.phase == "REFLECT":
                self.advance_to_lock()
                return "LOCK"

        # Otherwise ASK for missing
        if st.phase != "ASK":
            self.advance_to_ask()
        return "ASK"


# ─── Main entry point ─────────────────────────────────────────────────


def build_prompt(state: ClarifyState, user_msg: str, target_phase: str) -> str:
    """Dispatch to the right phase prompt builder."""
    if target_phase == "DECOMPOSE":
        return prompt_decompose(state, user_msg)
    if target_phase == "ASK":
        missing = [k for k in state.slots.required_keys() if not getattr(state.slots, k)]
        return prompt_ask(state, user_msg, missing)
    if target_phase == "REFLECT":
        return prompt_reflect(state, user_msg)
    if target_phase == "LOCK":
        return prompt_lock(state, user_msg)
    if target_phase == "DONE":
        return prompt_done(state)
    return f"<unknown phase {target_phase}>"


def instructions_for_bot(target_phase: str) -> str:
    """One-liner imperative for the bot about what to do with the prompt."""
    return {
        "DECOMPOSE": "Use the template AS YOUR REPLY. Do not add tool calls, do not start work.",
        "ASK": "Use the template AS YOUR REPLY. Do not echo state to user verbatim — just ask the question.",
        "REFLECT": "Use the template AS YOUR REPLY. Wait for user confirmation.",
        "LOCK": "Use the template AS YOUR REPLY. Lock phrase «Истинная цель определена» is MANDATORY.",
        "DONE": "Cycle complete. Execute the action from the lock block. If user wrote new info, re-evaluate.",
    }.get(target_phase, "Unknown phase")


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    state_dir = Path(args.state_dir or STATE_DIR_DEFAULT)
    state_path = state_dir / f"{args.session}.json"
    state = ClarifyState.load(state_path)

    if args.prev_bot:
        state.add_bot_msg(args.prev_bot)
    if args.user:
        state.add_user_msg(args.user)

    state.iteration += 1
    machine = ClarifyMachine(state)
    target_phase = machine.decide(args.user or "", args.prev_bot)
    state.phase = target_phase

    state.action_log.append(
        f"iter={state.iteration} phase={target_phase} "
        f"filled={state.slots.filled_required()}/3 "
        f"motivation_answered={state.motivation_answered} "
        f"user_pushed={state.user_pushed_for_action}"
    )
    state.save(state_path)

    mini_prompt = build_prompt(state, args.user or "", target_phase)
    instructions = instructions_for_bot(target_phase)

    return {
        "phase": target_phase,
        "iteration": state.iteration,
        "state_summary": {
            "slots": asdict(state.slots),
            "completeness": state.slots.completeness(),
            "motivation_answered": state.motivation_answered,
            "user_pushed_for_action": state.user_pushed_for_action,
            "user_history_len": len(state.user_history),
        },
        "mini_prompt": mini_prompt,
        "instructions_for_bot": instructions,
        "state_file": str(state_path),
    }


def status_only(args: argparse.Namespace) -> dict[str, Any]:
    state_dir = Path(args.state_dir or STATE_DIR_DEFAULT)
    state_path = state_dir / f"{args.session}.json"
    if not state_path.exists():
        return {"error": "no state", "session": args.session, "state_file": str(state_path)}
    state = ClarifyState.load(state_path)
    return {
        "session": args.session,
        "phase": state.phase,
        "iteration": state.iteration,
        "slots": asdict(state.slots),
        "completeness": state.slots.completeness(),
        "motivation_answered": state.motivation_answered,
        "user_pushed_for_action": state.user_pushed_for_action,
        "action_log": state.action_log[-10:],
    }


def reset_state(args: argparse.Namespace) -> dict[str, Any]:
    state_dir = Path(args.state_dir or STATE_DIR_DEFAULT)
    state_path = state_dir / f"{args.session}.json"
    if state_path.exists():
        state_path.unlink()
        return {"reset": True, "session": args.session}
    return {"reset": False, "session": args.session, "note": "no state existed"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--session", required=True, help="session id (used as state file name)")
    ap.add_argument("--user", default=None, help="latest user message")
    ap.add_argument("--prev-bot", default=None, help="previous bot reply for slot extraction")
    ap.add_argument("--state-dir", default=None, help="override state dir")
    ap.add_argument("--status", action="store_true", help="report state without advancing")
    ap.add_argument("--reset", action="store_true", help="reset state for this session")
    args = ap.parse_args()

    if args.reset:
        out = reset_state(args)
    elif args.status:
        out = status_only(args)
    else:
        if not args.user:
            print(json.dumps({"error": "--user required for advance"}), file=sys.stderr)
            return 2
        out = run_once(args)

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
