"""desire-to-goal — workflow configuration (schema + generic phases, v3).

All real logic lives upstream:
  - slot definitions in ``../schema.yaml``
  - phase pattern (DECOMPOSE → ASK/REFLECT → LOCK → DONE) in
    ``core.phases.decompose_reflect_lock``
  - decide_fn factory in the same module
  - LLM extractor that fills slots from conversation in
    ``core.extractor`` (driven by runner.run)

This file just wires schema + prompts + DRL pattern into a
WorkflowConfig the engine consumes. New "DRL-shaped" skills can copy
this file verbatim — only schema.yaml + prompts.py differ.
"""
from __future__ import annotations

from pathlib import Path

from core.phases import DRL_TRANSITIONS, build_DRL_decide_fn, build_DRL_phases
from core.schema import SchemaSlots, load_schema
from core.state import WorkflowConfig

from . import prompts


SCHEMA = load_schema(Path(__file__).parent.parent / "schema.yaml")
DesireToGoalSlots = SchemaSlots.bind(SCHEMA)

# Legacy regex label map — extractor LLM now does the heavy lifting,
# but the regex sweep stays as a belt-and-suspenders fallback for
# turns where the extractor fails (network, JSON parse, etc.).
LABEL_MAP = {
    "истинная_цель": ["Истинная цель", "True goal", "Цель"],
    "средство": ["Средство", "Means", "Инструмент"],
    "место": ["Место/контекст", "Место", "Place", "Контекст"],
    "команда": ["Команда", "Team", "Состав"],
    "мотивация": ["Мотивация", "Motivation", "Зачем"],
}


WORKFLOW = WorkflowConfig(
    name=SCHEMA.name,
    slots_cls=DesireToGoalSlots,
    phases=build_DRL_phases(prompts),
    transitions=DRL_TRANSITIONS,
    initial_phase=SCHEMA.phases.initial,
    decide_fn=build_DRL_decide_fn(SCHEMA, label_map=LABEL_MAP),
    mandatory_lock_phrase=SCHEMA.mandatory_lock_phrase,
    schema=SCHEMA,
)
