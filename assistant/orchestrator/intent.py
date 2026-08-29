from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum


class AssistantMode(StrEnum):
    ASK = "ASK"
    DATA = "DATA"


class Intent(StrEnum):
    GENERAL_KNOWLEDGE = "GENERAL_KNOWLEDGE"
    CURRENT_MACHINE_STATUS = "CURRENT_MACHINE_STATUS"
    ALARMS = "ALARMS"
    PRODUCTION = "PRODUCTION"
    OEE = "OEE"
    MACHINE_HISTORY = "MACHINE_HISTORY"
    EVENT_HISTORY = "EVENT_HISTORY"
    MAINTENANCE_HISTORY = "MAINTENANCE_HISTORY"
    PRODUCTION_HISTORY = "PRODUCTION_HISTORY"
    METRIC_ANALYTICS = "METRIC_ANALYTICS"
    METRIC_COMPARISON = "METRIC_COMPARISON"
    OEE_ANALYTICS = "OEE_ANALYTICS"
    OEE_COMPARISON = "OEE_COMPARISON"
    DOWNTIME = "DOWNTIME"
    INVESTIGATION = "INVESTIGATION"
    KNOWLEDGE_RETRIEVAL = "KNOWLEDGE_RETRIEVAL"
    ONTOLOGY_SEARCH = "ONTOLOGY_SEARCH"
    UNSUPPORTED_OPERATIONAL = "UNSUPPORTED_OPERATIONAL"


@dataclass(frozen=True)
class QueryPlan:
    mode: AssistantMode
    intent: Intent
    tool: str | None = None
    arguments: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
