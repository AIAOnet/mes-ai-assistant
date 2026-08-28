"""Route incoming communication values through MES business rules."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4
from typing import Protocol

from .alarms import Alarm, AlarmManager
from .events import Event, EventType
from .rules import ThresholdRuleEngine
from .tasks import MaintenanceTask, MaintenanceTaskManager

LOGGER = logging.getLogger("MES")


class PersistencePort(Protocol):
    def persist_reading(
        self, machine_id: str, tag_name: str, value: object
    ) -> None: ...

    def persist(self, event: Event, alarm: Alarm | None) -> None: ...

    def persist_task(self, task: MaintenanceTask) -> None: ...

    def acknowledge_alarm(self, alarm: Alarm) -> None: ...

    def update_task(self, task: MaintenanceTask) -> None: ...


class EventProcessor:
    def __init__(
        self,
        rule_engine: ThresholdRuleEngine,
        alarm_manager: AlarmManager,
        persistence: PersistencePort | None = None,
        task_manager: MaintenanceTaskManager | None = None,
    ) -> None:
        self.rule_engine = rule_engine
        self.alarm_manager = alarm_manager
        self.latest_tags: dict[str, object] = {}
        self.events: list[Event] = []
        self.persistence = persistence
        self.task_manager = task_manager or MaintenanceTaskManager()
        self.traces: deque[dict] = deque(maxlen=100)
        self.important_traces: deque[dict] = deque(maxlen=100)

    def process(
        self,
        tag_name: str,
        value: object,
        source: str = "DIRECT",
        delivery_payload: dict | None = None,
    ) -> None:
        started = perf_counter()
        trace = {
            "id": uuid4().hex[:10],
            "time": datetime.now(timezone.utc).isoformat(),
            "tag": tag_name,
            "value": value,
            "transport": source,
            "delivery_payload": delivery_payload or {"tag": tag_name, "value": value},
            "decision": "No threshold transition",
            "event": None,
            "alarm_id": None,
            "task_id": None,
            "tables": ["MachineReadings"] if self.persistence is not None else [],
            "database_records": {},
        }
        if self.persistence is not None:
            numeric_value = float(value) if isinstance(value, (int, float)) else None
            trace["database_records"]["MachineReadings"] = {
                "MachineId": "MACHINE-01",
                "TagName": tag_name,
                "NumericValue": numeric_value,
                "TextValue": None if numeric_value is not None else str(value),
            }
        self.latest_tags[tag_name] = value
        LOGGER.info("Tag event received: %s = %s", tag_name, value)
        if self.persistence is not None:
            self.persistence.persist_reading("MACHINE-01", tag_name, value)

        events = self.rule_engine.evaluate(tag_name, value)
        if tag_name not in self.rule_engine.rules:
            trace["decision"] = "No rule configured for this tag"
        elif not events:
            trace["decision"] = "Rule checked · state unchanged"
        for event in events:
            self.events.append(event)
            trace["decision"] = f"Rule produced {event.event_type.value}"
            trace["event"] = event.event_type.value
            if self.persistence is not None:
                trace["tables"].append("Events")
                trace["database_records"]["Events"] = {
                    "MachineId": event.machine_id,
                    "EventType": event.event_type.value,
                    "ConditionName": event.condition,
                    "NumericValue": event.value,
                    "OccurredTime": event.occurred_at.isoformat(),
                }
            LOGGER.info("%s: %s", event.event_type, event.condition)
            alarm = self.alarm_manager.handle(event)
            if alarm is not None:
                LOGGER.info("Alarm %s is %s", alarm.alarm_id, alarm.status)
                trace["alarm_id"] = alarm.alarm_id
                if self.persistence is not None:
                    trace["tables"].append("Alarms")
                    trace["database_records"]["Alarms"] = {
                        "AlarmId": alarm.alarm_id,
                        "AlarmType": alarm.alarm_type,
                        "Severity": alarm.severity,
                        "Status": alarm.status.value,
                        "TriggeredValue": alarm.triggered_value,
                    }
            if self.persistence is not None:
                self.persistence.persist(event, alarm)
            if alarm is not None and event.event_type == EventType.CONDITION_ENTERED:
                task = self.task_manager.create_for_alarm(alarm)
                if task is not None:
                    trace["task_id"] = task.task_id
                if task is not None and self.persistence is not None:
                    self.persistence.persist_task(task)
                    trace["task_id"] = task.task_id
                    trace["tables"].append("MaintenanceTasks")
                    trace["database_records"]["MaintenanceTasks"] = {
                        "TaskId": task.task_id,
                        "RelatedAlarmId": task.related_alarm_id,
                        "Description": task.description,
                        "Priority": task.priority,
                        "Status": task.status.value,
                    }
        trace["latency_ms"] = round((perf_counter() - started) * 1000, 2)
        self.traces.appendleft(trace)
        if trace["event"] is not None:
            self.important_traces.appendleft(trace.copy())
