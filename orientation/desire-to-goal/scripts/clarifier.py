"""
desire-to-goal — Clarifier

Cyclic clarification controller. Exit by sufficiency (confidence + stability),
not by completeness. Implements the protocol described in SKILL.md.

Core principles:
- Open questions, not interrogation
- Backtracking allowed (goal can shift across iterations)
- Contradictions are signals, logged as artifacts
- Truth lives in the dynamics of answers, not the words
- Sufficiency-based exit, not perfectionism
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, Any


# ============================================================
# Primitive types (8 core primitives)
# ============================================================

class Primitive(str, Enum):
    HOTELKA = "Хотелка"           # raw desire (always present)
    SUBJECT = "Субъект"
    CONTEXT = "Контекст"
    GOAL = "Цель"
    CRITERIA = "КритерийУспеха"
    METRIC = "Метрика"
    CONSTRAINTS = "Ограничения"
    HYPOTHESIS = "Гипотеза"


# ============================================================
# Actions the controller can pick
# ============================================================

class ClarificationAction(str, Enum):
    ASK = "ask"
    REFLECT = "reflect"
    HYPOTHESIZE = "hypothesize"
    RESEARCH = "research"
    ACKNOWLEDGE = "acknowledge"
    EXIT = "exit"


# ============================================================
# Contradictions
# ============================================================

@dataclass
class ContradictionRecord:
    iteration: int
    description: str
    entities: list[str] = field(default_factory=list)
    severity: float = 0.5  # 0..1
    status: str = "open"   # open | acknowledged | resolved
    human_comment: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ContradictionLog:
    records: list[ContradictionRecord] = field(default_factory=list)

    def add(self, iteration: int, description: str,
            entities: Optional[list[str]] = None,
            severity: float = 0.5) -> int:
        """Returns the index of the new record."""
        rec = ContradictionRecord(
            iteration=iteration,
            description=description,
            entities=entities or [],
            severity=severity,
        )
        self.records.append(rec)
        return len(self.records) - 1

    def unresolved(self) -> list[ContradictionRecord]:
        return [r for r in self.records if r.status == "open"]

    def to_list(self) -> list[dict]:
        return [r.to_dict() for r in self.records]


# ============================================================
# State
# ============================================================

@dataclass
class DesireClarificationState:
    raw_desire: str

    # 8 primitives
    subject: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    goal_statement: Optional[str] = None
    success_criteria: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)

    # Tracking
    goal_versions: list[str] = field(default_factory=list)  # for stability
    criteria_versions: list[list[str]] = field(default_factory=list)  # for churn
    unknowns: list[str] = field(default_factory=list)
    contradiction_log: ContradictionLog = field(default_factory=ContradictionLog)
    qa_history: list[dict] = field(default_factory=list)
    active_persona: Optional[str] = None

    # Computed metrics
    confidence: float = 0.0
    stability_score: float = 0.0
    iteration: int = 0


# ============================================================
# Stability + confidence (word-overlap based, no embeddings)
# ============================================================

_STOPWORDS = {
    "и", "в", "на", "по", "из", "для", "с", "что", "как", "к", "не", "это",
    "the", "a", "an", "of", "to", "and", "with", "for", "in", "on", "at",
    "is", "are", "was", "were", "be", "by", "this", "that", "it",
}


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    return set(re.findall(r"[A-Za-zА-Яа-яёЁ0-9_]+", text.lower())) - _STOPWORDS


def jaccard(a: str, b: str) -> float:
    """Word-level Jaccard similarity. 1.0 if both empty."""
    sa, sb = _tokenize(a), _tokenize(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _list_churn(prev: list[str], curr: list[str]) -> float:
    """Fraction of items added or removed between two lists. 0..1."""
    sp, sc = set(prev), set(curr)
    if not sp and not sc:
        return 0.0
    added = len(sc - sp)
    removed = len(sp - sc)
    return min(1.0, (added + removed) / max(1, max(len(sp), len(sc))))


def estimate_stability(state: DesireClarificationState, window: int = 3) -> float:
    """
    Composite stability score 0..1:
      0.5 * semantic_similarity (goal versions)
      0.3 * (1 - constraint churn)
      0.2 * (1 - criteria churn)
    """
    versions = state.goal_versions[-window:] if state.goal_versions else []

    # Single-version case: if goal text exists and didn't churn, treat as
    # partially stable (0.7) rather than 0. Full 1.0 requires >= 2 same versions.
    if len(versions) == 1:
        semantic = 0.7
    elif len(versions) < 2:
        return 0.0
    else:
        # Semantic stability — average pairwise jaccard
        sims = [jaccard(versions[i], versions[i + 1]) for i in range(len(versions) - 1)]
        semantic = sum(sims) / len(sims) if sims else 0.0

    # Criteria churn
    criteria_versions = state.criteria_versions[-window:]
    if len(criteria_versions) >= 2:
        churns = [_list_churn(criteria_versions[i], criteria_versions[i + 1])
                  for i in range(len(criteria_versions) - 1)]
        criteria_churn = sum(churns) / len(churns)
    else:
        criteria_churn = 0.5  # unknown — treat as middling

    # Constraint churn — we don't track versions for constraints in v1,
    # so use criteria churn as proxy
    constraint_churn = criteria_churn

    return (
        0.5 * semantic
        + 0.3 * (1.0 - constraint_churn)
        + 0.2 * (1.0 - criteria_churn)
    )


def estimate_confidence(state: DesireClarificationState) -> float:
    """
    Confidence = completeness - contradiction penalty - drift penalty.
    Completeness = filled primitives / 8.
    """
    filled = 0
    if state.raw_desire:        filled += 1  # Хотелка
    if state.subject:           filled += 1  # Субъект
    if state.context:           filled += 1  # Контекст
    if state.goal_statement:    filled += 1  # Цель
    if state.success_criteria:  filled += 1  # КритерийУспеха
    if state.metrics:           filled += 1  # Метрика
    if state.constraints:       filled += 1  # Ограничения
    if state.hypotheses:        filled += 1  # Гипотеза
    completeness = filled / 8.0

    # Unresolved contradiction penalty
    unresolved_count = len(state.contradiction_log.unresolved())
    contradiction_penalty = min(0.3, 0.1 * unresolved_count)

    return max(0.0, min(1.0, completeness - contradiction_penalty))


# ============================================================
# Controller
# ============================================================

class ClarificationController:
    """Selects next action based on state. Exit by sufficiency, not completeness."""

    def __init__(
        self,
        confidence_threshold: float = 0.7,
        stability_threshold: float = 0.7,
        soft_cap_iterations: int = 5,
    ):
        self.confidence_threshold = confidence_threshold
        self.stability_threshold = stability_threshold
        self.soft_cap = soft_cap_iterations

    def select_next_action(self, state: DesireClarificationState) -> ClarificationAction:
        # Sufficiency exit
        if (state.confidence >= self.confidence_threshold
                and state.stability_score >= self.stability_threshold):
            return ClarificationAction.EXIT

        # Unresolved contradictions first
        if state.contradiction_log.unresolved():
            return ClarificationAction.ACKNOWLEDGE

        # Low confidence — need info
        if state.confidence < 0.4:
            return ClarificationAction.ASK

        # Mid confidence, low stability — confirm understanding
        if state.stability_score < 0.5:
            return ClarificationAction.REFLECT

        # Stable but ambiguous — propose alternatives
        if state.confidence < 0.65:
            return ClarificationAction.HYPOTHESIZE

        # High confidence but stability just below threshold — final reflection
        # to lock in the goal (one more confirmation round before exit).
        if state.stability_score < self.stability_threshold:
            return ClarificationAction.REFLECT

        # Default — ask for missing pieces
        return ClarificationAction.ASK

    def soft_cap_reached(self, state: DesireClarificationState) -> bool:
        return state.iteration >= self.soft_cap


# ============================================================
# Anti-pattern detection
# ============================================================

def detect_anti_patterns(state: DesireClarificationState) -> list[dict]:
    """Returns list of {type, name, severity, explanation, description}.
    'name' and 'description' are aliases for 'type' and 'explanation' for
    consumers that expect either schema (Bug #2)."""
    issues: list[dict] = []

    def _emit(type_: str, severity: float, explanation: str):
        issues.append({
            "type": type_,
            "name": type_,
            "severity": severity,
            "explanation": explanation,
            "description": explanation,
        })

    # Effective goal: explicit statement, or fallback to last hypothesis summary
    eff_goal = state.goal_statement or ""
    if not eff_goal and state.hypotheses:
        h = state.hypotheses[-1]
        if isinstance(h, dict):
            eff_goal = h.get("summary") or h.get("statement") or ""
        elif isinstance(h, str):
            eff_goal = h

    if eff_goal and not state.success_criteria:
        _emit("GoalWithoutCriteria", 0.8,
              "Цель сформулирована, но критериев успеха нет")
    if eff_goal and not state.metrics:
        _emit("NonMeasurableGoal", 0.7,
              "Цель есть, но нет измеримых метрик")
    if eff_goal and not state.subject:
        _emit("GoalWithoutOwner", 0.6,
              "Цель есть, но субъект исполнения не определён")
    if state.success_criteria and not eff_goal:
        _emit("CriteriaWithoutGoal", 0.9,
              "Критерии есть, но сама цель не сформулирована")
    if state.metrics and not eff_goal:
        _emit("MetricsWithoutGoal", 0.9,
              "Метрики есть без сформулированной цели")
    if state.hypotheses and not state.context:
        _emit("HypothesisWithoutContext", 0.5,
              "Гипотеза без контекста — не на чём её проверять")

    # Goal drift — radical change in early iterations
    if len(state.goal_versions) >= 2 and state.iteration < 4:
        first, last = state.goal_versions[0], state.goal_versions[-1]
        sim = jaccard(first, last)
        if sim < 0.2:
            _emit("GoalDrift", 0.5,
                  f"Цель радикально изменилась за {state.iteration} итераций "
                  f"(similarity={sim:.2f})")

    return issues


# ============================================================
# Persona selection (keyword triggers)
# ============================================================

PERSONA_TRIGGERS = {
    "business":         ["прибыль", "выручка", "roi", "продукт", "клиент", "рынок", "бизнес"],
    "finance":          ["инвестиции", "портфель", "акции", "трейдинг", "p&l", "финанс"],
    "lawyer":           ["договор", "контракт", "право", "compliance", "регуляция", "иск"],
    "tech":             ["код", "api", "архитектура", "database", "production", "deploy"],
    "systems_engineer": ["scale", "распределённая", "infra", "kubernetes", "микросерв"],
    "art":              ["дизайн", "стиль", "композиция", "креатив", "иллюстрация"],
    "learning":         ["обучение", "освоить", "понять", "разобраться", "научиться"],
    "psychologist":     ["почему я", "мотивация", "не могу", "страх", "тревога", "выгорание"],
    "maieutic":         ["не уверен", "запутался", "помоги разобраться", "не понимаю"],
    "journalist":       ["факты", "что произошло", "разберись", "правда"],
    "anthropologist":   ["сообщество", "культура", "люди", "поведение", "стейкхолдер"],
    "devil_advocate":   ["должно работать", "наверное хорошо", "очевидно", "просто сделать"],
    "doctor":           ["симптом", "проблема с", "не работает", "болит"],
    "scientist":        ["гипотеза", "эксперимент", "доказать", "исследовать"],
    "product_manager":  ["пользователи", "конверсия", "feature", "retention", "engagement"],
    "negotiator":       ["конфликт", "сделка", "не согласны", "стороны"],
    "operator":         ["надёжность", "падает", "uptime", "мониторинг", "incident"],
    "child":            ["объясни просто", "не понимаю с нуля", "новичок"],
}


def detect_persona(text: str) -> str:
    """Pick best persona by keyword overlap. Defaults to maieutic."""
    if not text:
        return "maieutic"
    lower = text.lower()
    scores: dict[str, int] = {}
    for persona, kws in PERSONA_TRIGGERS.items():
        s = sum(1 for kw in kws if kw in lower)
        if s > 0:
            scores[persona] = s
    if not scores:
        return "maieutic"
    return max(scores, key=scores.get)


# ============================================================
# Output building
# ============================================================

def build_goal(state: DesireClarificationState) -> dict:
    """
    Build a Goal-compatible dict (matches chief-manager graph.Goal signature).
    Includes clarification metadata for downstream consumers.

    Resolution order for `statement`:
      1. explicit state.goal_statement
      2. last hypothesis with a 'summary' field
      3. last goal_versions entry
      4. empty string (with warning)
    """
    # Try to extract deliverable_format from constraints
    deliverable = ""
    for c in state.constraints:
        if any(kw in c.lower() for kw in ("формат", "format", "deliverable")):
            deliverable = c
            break

    out_of_scope = [c for c in state.constraints
                    if c.lower().startswith(("не ", "exclude", "out of scope"))]

    statement = state.goal_statement or ""
    if not statement and state.hypotheses:
        last_h = state.hypotheses[-1]
        if isinstance(last_h, dict):
            statement = last_h.get("summary") or last_h.get("statement") or ""
        elif isinstance(last_h, str):
            statement = last_h
    if not statement and state.goal_versions:
        statement = state.goal_versions[-1]

    return {
        "statement": statement,
        "success_criteria": list(state.success_criteria),
        "deliverable_format": deliverable,
        "out_of_scope": out_of_scope,
        "constraints": [c for c in state.constraints if c not in out_of_scope],
        "subgoals": [],  # filled by chief-manager Phase 1
        "_clarification_metadata": {
            "raw_desire": state.raw_desire,
            "confidence": round(state.confidence, 3),
            "stability_score": round(state.stability_score, 3),
            "iterations": state.iteration,
            "active_persona": state.active_persona,
            "subject": state.subject,
            "context": state.context,
            "hypotheses": state.hypotheses,
            "open_contradictions": [
                r.to_dict() for r in state.contradiction_log.unresolved()
            ],
        },
    }


def save_artifact(state: DesireClarificationState, workspace_path: str) -> dict[str, str]:
    """
    Save goal.json + contradictions.json + qa_history.json to workspace.
    Returns dict of {kind: path}.
    """
    p = Path(workspace_path)
    p.mkdir(parents=True, exist_ok=True)

    goal_path = p / "goal.json"
    with open(goal_path, "w", encoding="utf-8") as f:
        json.dump(build_goal(state), f, ensure_ascii=False, indent=2)

    contra_path = p / "contradictions.json"
    with open(contra_path, "w", encoding="utf-8") as f:
        json.dump(state.contradiction_log.to_list(), f, ensure_ascii=False, indent=2)

    qa_path = p / "qa_history.json"
    with open(qa_path, "w", encoding="utf-8") as f:
        json.dump(state.qa_history, f, ensure_ascii=False, indent=2)

    return {
        "goal": str(goal_path),
        "contradictions": str(contra_path),
        "qa_history": str(qa_path),
    }


# ============================================================
# Public Clarifier interface — agent uses this
# ============================================================

class Clarifier:
    """
    Cyclic clarifier. The agent drives the dialogue; this class manages state,
    picks the next action, computes metrics, and produces the final Goal.

    Typical agent loop:
        c = Clarifier(raw_desire="...")
        while True:
            step = c.next_step()
            if step["action"] == "exit":
                break
            # agent executes step["instruction"] — asks, reflects, etc.
            # agent receives user reply, extracts primitives:
            c.update_primitives(goal_statement="...", success_criteria=[...])
            c.record_qa(question="...", answer="...")
        goal = c.build_goal_for_chief_manager()
        c.save_artifact("/opt/data/workspace/<topic>/")
    """

    def __init__(self, raw_desire: str,
                 confidence_threshold: float = 0.7,
                 stability_threshold: float = 0.7,
                 soft_cap: int = 5):
        if not raw_desire or len(raw_desire.strip()) < 3:
            raise ValueError("raw_desire too short — pass at least a sentence")
        self.state = DesireClarificationState(raw_desire=raw_desire.strip())
        self.state.active_persona = detect_persona(raw_desire)
        self.controller = ClarificationController(
            confidence_threshold=confidence_threshold,
            stability_threshold=stability_threshold,
            soft_cap_iterations=soft_cap,
        )

    @classmethod
    def from_state_dict(cls, state_dict: dict,
                        confidence_threshold: float = 0.7,
                        stability_threshold: float = 0.7,
                        soft_cap: int = 5) -> "Clarifier":
        """
        Resume a Clarifier from a previously saved state dict
        (Bug #4 — preserves iteration counter across sessions).

        Accepts both the lean dump_state() output and the full
        _clarification_metadata block from a saved goal.json.
        """
        raw = state_dict.get("raw_desire") or "(restored session)"
        c = cls(raw_desire=raw,
                confidence_threshold=confidence_threshold,
                stability_threshold=stability_threshold,
                soft_cap=soft_cap)
        s = c.state
        s.iteration = int(state_dict.get("iteration", 0))
        s.confidence = float(state_dict.get("confidence", 0.0))
        s.stability_score = float(state_dict.get("stability_score", 0.0))
        s.active_persona = state_dict.get("active_persona") or s.active_persona
        s.subject = state_dict.get("subject") or {}
        s.context = state_dict.get("context") or {}
        s.success_criteria = list(state_dict.get("success_criteria", []))
        s.metrics = list(state_dict.get("metrics", []))
        s.constraints = list(state_dict.get("constraints", []))
        s.hypotheses = list(state_dict.get("hypotheses", []))
        s.unknowns = list(state_dict.get("unknowns", []))
        s.goal_statement = state_dict.get("goal_statement")
        s.goal_versions = list(state_dict.get("goal_versions", []))
        s.criteria_versions = list(state_dict.get("criteria_versions", []))
        s.qa_history = list(state_dict.get("qa_history", []))
        # Restore contradictions
        for rec_dict in state_dict.get("open_contradictions", []):
            s.contradiction_log.add(
                iteration=rec_dict.get("iteration", s.iteration),
                description=rec_dict.get("description", ""),
                entities=rec_dict.get("entities") or [],
                severity=rec_dict.get("severity", 0.5),
            )
        return c

    def next_step(self) -> dict:
        """Compute current metrics, select action, return instruction packet."""
        self.state.iteration += 1
        self.state.confidence = estimate_confidence(self.state)
        self.state.stability_score = estimate_stability(self.state)
        action = self.controller.select_next_action(self.state)
        soft_cap = self.controller.soft_cap_reached(self.state)
        return {
            "iteration": self.state.iteration,
            "action": action.value,
            "confidence": round(self.state.confidence, 3),
            "stability": round(self.state.stability_score, 3),
            "persona": self.state.active_persona,
            "soft_cap_reached": soft_cap,
            "anti_patterns": detect_anti_patterns(self.state),
            "instruction": self._build_instruction(action, soft_cap),
        }

    def _build_instruction(self, action: ClarificationAction, soft_cap: bool) -> str:
        persona = self.state.active_persona or "maieutic"
        base = {
            "ask": (
                f"Задай не более 3 ОТКРЫТЫХ уточняющих вопросов от персоны `{persona}`. "
                f"Выбирай вопросы по принципу EVPI — те, ответ на которые реально изменит "
                f"понимание цели. НЕ задавай yes/no, НЕ перечисляй обязательный чеклист."
            ),
            "reflect": (
                "Перефразируй текущее понимание цели в 1-2 предложениях и спроси: "
                "правильно понял? чего не хватает? что лишнее?"
            ),
            "hypothesize": (
                "Предложи 2-3 альтернативные интерпретации цели. Пусть user выберет "
                "или скажет 'ни одна не подходит'. Это снимает скрытые допущения."
            ),
            "research": (
                "Используй web_search/web_extract для расширения КОНТЕКСТА по домену. "
                "Это снижает model uncertainty (что ты не знаешь), не specification uncertainty "
                "(что хочет user). Не задавай пользователю вопросы, которые можно нагуглить."
            ),
            "acknowledge": (
                "Есть открытые противоречия в данных. Покажи их пользователю и спроси: "
                "(a) resolved — пользователь выбирает один вариант; "
                "(b) acknowledged — оставляем как есть, фиксируем как известное противоречие; "
                "(c) open — пока неясно, продолжаем уточнять."
            ),
            "exit": (
                f"Достаточно. confidence={self.state.confidence:.2f}, "
                f"stability={self.state.stability_score:.2f}. "
                f"Вызывай build_goal_for_chief_manager() и save_artifact()."
            ),
        }
        msg = base[action.value]
        if soft_cap and action.value != "exit":
            msg += (
                f"\n\n⚠️ Soft cap reached ({self.state.iteration} iterations). "
                f"Спроси user: продолжить уточнение или остановиться с текущим состоянием "
                f"(confidence={self.state.confidence:.2f})?"
            )
        return msg

    def update_primitives(self, **kwargs) -> None:
        """
        Update state primitives. Tracks goal_versions and criteria_versions for stability.

        Accepted keys: subject, context, goal_statement, success_criteria,
                       metrics, constraints, hypotheses, unknowns
        """
        if "goal_statement" in kwargs:
            new = kwargs["goal_statement"]
            if new and new != self.state.goal_statement:
                self.state.goal_versions.append(new)
            self.state.goal_statement = new

        if "success_criteria" in kwargs:
            new = list(kwargs["success_criteria"])
            if new != self.state.success_criteria:
                self.state.criteria_versions.append(list(self.state.success_criteria))
            self.state.success_criteria = new

        for k in ("subject", "context"):
            if k in kwargs:
                setattr(self.state, k, kwargs[k])

        for k in ("metrics", "constraints", "hypotheses", "unknowns"):
            if k in kwargs:
                setattr(self.state, k, list(kwargs[k]))

        # If hypotheses gained a new 'summary', track it as goal version
        # so stability/drift detection picks up rewordings (Bug #5).
        if "hypotheses" in kwargs and self.state.hypotheses:
            last_h = self.state.hypotheses[-1]
            summary = None
            if isinstance(last_h, dict):
                summary = last_h.get("summary") or last_h.get("statement")
            elif isinstance(last_h, str):
                summary = last_h
            if summary and (not self.state.goal_versions
                            or self.state.goal_versions[-1] != summary):
                self.state.goal_versions.append(summary)

    def record_qa(self, question: str, answer: str, action: Optional[str] = None) -> None:
        """Log a question-answer pair for audit and behavioral stability tracking."""
        self.state.qa_history.append({
            "iteration": self.state.iteration,
            "action": action,
            "question": question,
            "answer": answer,
        })

    def add_contradiction(self, description: str,
                          entities: Optional[list[str]] = None,
                          severity: float = 0.5) -> int:
        return self.state.contradiction_log.add(
            iteration=self.state.iteration,
            description=description,
            entities=entities,
            severity=severity,
        )

    def resolve_contradiction(self, idx: int, status: str = "acknowledged",
                              comment: str = "") -> None:
        """status: 'resolved' | 'acknowledged' | 'open'"""
        if 0 <= idx < len(self.state.contradiction_log.records):
            rec = self.state.contradiction_log.records[idx]
            rec.status = status
            rec.human_comment = comment

    def set_persona(self, persona: str) -> None:
        """Override auto-detected persona (e.g. for ad-hoc 'детский_врач')."""
        self.state.active_persona = persona

    def build_goal_for_chief_manager(self) -> dict:
        """Returns dict compatible with chief-manager's graph.Goal dataclass."""
        return build_goal(self.state)

    def save_artifact(self, workspace_path: str) -> dict[str, str]:
        return save_artifact(self.state, workspace_path)

    def dump_state(self) -> dict:
        """Full lossless snapshot — usable with Clarifier.from_state_dict()
        to resume a session across processes (Bug #4)."""
        return {
            "raw_desire": self.state.raw_desire,
            "iteration": self.state.iteration,
            "confidence": self.state.confidence,
            "stability_score": self.state.stability_score,
            "active_persona": self.state.active_persona,
            "subject": dict(self.state.subject),
            "context": dict(self.state.context),
            "goal_statement": self.state.goal_statement,
            "success_criteria": list(self.state.success_criteria),
            "metrics": list(self.state.metrics),
            "constraints": list(self.state.constraints),
            "hypotheses": list(self.state.hypotheses),
            "unknowns": list(self.state.unknowns),
            "goal_versions": list(self.state.goal_versions),
            "criteria_versions": [list(v) for v in self.state.criteria_versions],
            "qa_history": list(self.state.qa_history),
            "open_contradictions": [
                r.to_dict() for r in self.state.contradiction_log.records
            ],
            "summary": {
                "primitives_filled": {
                    "subject": bool(self.state.subject),
                    "context": bool(self.state.context),
                    "goal": bool(self.state.goal_statement or self.state.hypotheses),
                    "criteria": bool(self.state.success_criteria),
                    "metrics": bool(self.state.metrics),
                    "constraints": bool(self.state.constraints),
                    "hypotheses": bool(self.state.hypotheses),
                },
                "open_contradiction_count": len(self.state.contradiction_log.unresolved()),
                "goal_version_count": len(self.state.goal_versions),
            },
        }


__all__ = [
    "Clarifier",
    "ClarificationAction",
    "ClarificationController",
    "DesireClarificationState",
    "ContradictionRecord",
    "ContradictionLog",
    "Primitive",
    "estimate_confidence",
    "estimate_stability",
    "detect_anti_patterns",
    "detect_persona",
    "build_goal",
    "save_artifact",
    "jaccard",
]
