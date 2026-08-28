"""In-memory alarm management for Phase 3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from .events import Event, EventType


class AlarmStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


@dataclass
class Alarm:
    alarm_id: str
    machine_id: str
    alarm_type: str
    severity: str
    message: str
    triggered_time: datetime
    triggered_value: float
    status: AlarmStatus = AlarmStatus.ACTIVE
    acknowledged: bool = False
    acknowledged_by: str | None = None
    acknowledged_time: datetime | None = None
    resolved_time: datetime | None = None


class AlarmManager:
    def __init__(self) -> None:
        self.alarms: list[Alarm] = []

    @property
    def active_alarms(self) -> list[Alarm]:
        return [alarm for alarm in self.alarms if alarm.status == AlarmStatus.ACTIVE]

    def handle(self, event: Event) -> Alarm | None:
        if event.event_type == EventType.CONDITION_ENTERED:
            alarm = Alarm(
                # A process-local counter would collide after an MES restart.
                alarm_id=f"A-{uuid4().hex[:12].upper()}",
                machine_id=event.machine_id,
                alarm_type=event.condition,
                severity="HIGH",
                message=f"{event.condition} detected at {event.value:g}",
                triggered_time=event.occurred_at,
                triggered_value=event.value,
            )
            self.alarms.append(alarm)
            return alarm

        if event.event_type == EventType.CONDITION_RECOVERED:
            for alarm in reversed(self.active_alarms):
                if (
                    alarm.machine_id == event.machine_id
                    and alarm.alarm_type == event.condition
                ):
                    alarm.status = AlarmStatus.RESOLVED
                    alarm.resolved_time = event.occurred_at
                    return alarm

        return None

    def acknowledge(self, alarm_id: str, operator: str, acknowledged_at: datetime) -> Alarm | None:
        for alarm in self.alarms:
            if alarm.alarm_id == alarm_id:
                if not alarm.acknowledged:
                    alarm.acknowledged = True
                    alarm.acknowledged_by = operator
                    alarm.acknowledged_time = acknowledged_at
                return alarm
        return None
