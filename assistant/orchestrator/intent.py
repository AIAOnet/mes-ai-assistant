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
    UNSUPPORTED_OPERATIONAL = "UNSUPPORTED_OPERATIONAL"


@dataclass(frozen=True)
class QueryPlan:
    mode: AssistantMode
    intent: Intent
    tool: str | None = None
    arguments: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
