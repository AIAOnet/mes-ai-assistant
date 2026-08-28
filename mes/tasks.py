"""Maintenance tasks created from MES alarms."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from .alarms import Alarm


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


@dataclass
class MaintenanceTask:
    machine_id: str
    related_alarm_id: str
    description: str
    priority: str
    task_id: int = 0
    status: TaskStatus = TaskStatus.OPEN
    created_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_time: datetime | None = None


class MaintenanceTaskManager:
    DESCRIPTIONS = {
        "HIGH_PRESSURE": "Inspect hydraulic pressure system",
        "HIGH_TEMPERATURE": "Inspect machine cooling system",
    }

    def __init__(self) -> None:
        self.tasks: list[MaintenanceTask] = []

    def create_for_alarm(self, alarm: Alarm) -> MaintenanceTask | None:
        description = self.DESCRIPTIONS.get(alarm.alarm_type)
        if description is None:
            return None
        task = MaintenanceTask(
            machine_id=alarm.machine_id,
            related_alarm_id=alarm.alarm_id,
            description=description,
            priority="HIGH",
            task_id=len(self.tasks) + 1,
        )
        self.tasks.append(task)
        return task

    def start(self, task_id: int) -> MaintenanceTask | None:
        task = self._find(task_id)
        if task is not None and task.status == TaskStatus.OPEN:
            task.status = TaskStatus.IN_PROGRESS
        return task

    def complete(self, task_id: int) -> MaintenanceTask | None:
        task = self._find(task_id)
        if task is not None and task.status == TaskStatus.IN_PROGRESS:
            task.status = TaskStatus.COMPLETED
            task.completed_time = datetime.now(timezone.utc)
        return task

    def _find(self, task_id: int) -> MaintenanceTask | None:
        return next((task for task in self.tasks if task.task_id == task_id), None)
