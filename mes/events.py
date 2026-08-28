"""Domain events created by the MES rule engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class EventType(StrEnum):
    CONDITION_ENTERED = "CONDITION_ENTERED"
    CONDITION_RECOVERED = "CONDITION_RECOVERED"


@dataclass(frozen=True)
class Event:
    machine_id: str
    event_type: EventType
    condition: str
    value: float
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

