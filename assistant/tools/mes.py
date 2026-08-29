"""Strict, read-only MES tools backed by the existing MES controller."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any


class ToolValidationError(ValueError):
    """Reject tool parameters outside the MES allow-list."""


class ToolNotFoundError(LookupError):
    """The requested allow-listed MES entity does not exist."""


@dataclass(frozen=True)
class ToolResult:
    tool: str
    data: dict[str, Any]
    sources: list[dict[str, str]]

    def as_context(self) -> dict:
        return {"tool": self.tool, "data": self.data, "sources": self.sources}


class MESReadTools:
    ALLOWED_MACHINES = {"MACHINE-01"}
    METRICS = {
        "pressure": ("Machine01.Pressure", "bar"),
        "temperature": ("Machine01.Temperature", "°C"),
        "rpm": ("Machine01.RPM", "RPM"),
        "production_count": ("Machine01.ProductionCount", "units"),
        "status": ("Machine01.Status", None),
    }

    def __init__(self, controller) -> None:
        self.controller = controller

    def _machine(self, machine_id: str) -> str:
        normalized = machine_id.strip().upper()
        if normalized not in self.ALLOWED_MACHINES:
            raise ToolValidationError(f"Machine is not authorized: {normalized}")
        return normalized

    @staticmethod
    def _window(period: str) -> tuple[datetime, datetime]:
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "today":
            return day_start, now
        if period == "yesterday":
            return day_start - timedelta(days=1), day_start
        match = re.fullmatch(r"last_(\d+)_(minutes|hours|days)", period)
        if not match:
            raise ToolValidationError("Historical period is not allowed")
        amount = int(match.group(1))
        unit = match.group(2)
        maximum = {"minutes": 43200, "hours": 720, "days": 30}[unit]
        if amount < 1 or amount > maximum:
            raise ToolValidationError("Historical period exceeds the 30-day limit")
        return now - timedelta(**{unit: amount}), now

    def get_machine_status(self, machine_id: str) -> ToolResult:
        machine_id = self._machine(machine_id)
        state = self.controller.snapshot()
        data = {
            "machine_id": machine_id,
            "status": state["machine_status"],
            "pressure": state["pressure"],
            "pressure_unit": "bar",
            "temperature": state["temperature"],
            "temperature_unit": "°C",
            "rpm": state["rpm"],
            "rpm_unit": "RPM",
            "production_count": state["production_count"],
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        return ToolResult("get_machine_status", data, [{
            "type": "machine_status", "id": machine_id,
            "uri": f"/api/mes/machines/{machine_id}/status",
        }])

    def get_machine_alarms(
        self, machine_id: str, active_only: bool = False, period: str | None = None
    ) -> ToolResult:
        machine_id = self._machine(machine_id)
        since = until = None
        if period is not None:
            since, until = self._window(period)
        alarms = self.controller.read_machine_alarms(
            machine_id, active_only=active_only, since=since, until=until
        )
        data = {
            "machine_id": machine_id,
            "active_only": active_only,
            "period": period,
            "count": len(alarms),
            "alarms": alarms,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        sources = [{"type": "alarm", "id": item["id"], "uri": f"/api/mes/alarms/{item['id']}"}
                   for item in alarms]
        if not sources:
            sources = [{"type": "alarm_collection", "id": machine_id,
                        "uri": f"/api/mes/machines/{machine_id}/alarms"}]
        return ToolResult("get_machine_alarms", data, sources)

    def get_machine_history(self, machine_id: str, metric: str, period: str, limit: int = 100) -> ToolResult:
        machine_id = self._machine(machine_id)
        if metric not in self.METRICS:
            raise ToolValidationError(f"Historical metric is not allowed: {metric}")
        limit = max(1, min(int(limit), 200))
        start, end = self._window(period)
        tag, unit = self.METRICS[metric]
        readings = self.controller.read_machine_history(machine_id, tag, start, end, limit)
        data = {"machine_id": machine_id, "metric": metric, "unit": unit, "period": period,
                "start_time": start.isoformat(), "end_time": end.isoformat(),
                "count": len(readings), "readings": readings, "truncated": len(readings) == limit}
        return ToolResult("get_machine_history", data, [{
            "type": "machine_readings", "id": f"{machine_id}:{metric}:{period}",
            "uri": f"/api/mes/machines/{machine_id}/history?metric={metric}&period={period}",
        }])

    def search_events(self, machine_id: str, period: str, limit: int = 100) -> ToolResult:
        machine_id = self._machine(machine_id)
        limit = max(1, min(int(limit), 200))
        start, end = self._window(period)
        events = self.controller.read_event_history(machine_id, start, end, limit)
        return ToolResult("search_events", {"machine_id": machine_id, "period": period,
            "start_time": start.isoformat(), "end_time": end.isoformat(), "count": len(events),
            "events": events, "truncated": len(events) == limit}, [{
                "type": "event_history", "id": f"{machine_id}:{period}",
                "uri": f"/api/mes/machines/{machine_id}/events?period={period}",
            }])

    def get_maintenance_history(self, machine_id: str, period: str, limit: int = 100) -> ToolResult:
        machine_id = self._machine(machine_id)
        start, end = self._window(period)
        tasks = self.controller.read_maintenance_history(machine_id, start, end, min(int(limit), 200))
        return ToolResult("get_maintenance_history", {"machine_id": machine_id, "period": period,
            "start_time": start.isoformat(), "end_time": end.isoformat(), "count": len(tasks),
            "tasks": tasks}, [{"type": "maintenance_history", "id": f"{machine_id}:{period}",
            "uri": f"/api/mes/machines/{machine_id}/maintenance?period={period}"}])

    def get_production_history(self, machine_id: str, period: str, limit: int = 100) -> ToolResult:
        machine_id = self._machine(machine_id)
        start, end = self._window(period)
        records = self.controller.read_production_history(machine_id, start, end, min(int(limit), 200))
        return ToolResult("get_production_history", {"machine_id": machine_id, "period": period,
            "start_time": start.isoformat(), "end_time": end.isoformat(), "count": len(records),
            "records": records}, [{"type": "production_history", "id": f"{machine_id}:{period}",
            "uri": f"/api/mes/machines/{machine_id}/production-history?period={period}"}])

    def get_alarm_details(self, alarm_id: str) -> ToolResult:
        if not re.fullmatch(r"A-[A-Za-z0-9_-]{1,64}", alarm_id):
            raise ToolValidationError("Invalid alarm ID")
        alarm = next(
            (item for item in self.controller.read_machine_alarms("MACHINE-01")
             if item["id"] == alarm_id),
            None,
        )
        if alarm is None:
            raise ToolNotFoundError(f"Alarm not found: {alarm_id}")
        return ToolResult("get_alarm_details", {
            "alarm": alarm, "observed_at": datetime.now(timezone.utc).isoformat(),
        }, [{"type": "alarm", "id": alarm_id, "uri": f"/api/mes/alarms/{alarm_id}"}])

    def get_production_status(
        self, machine_id: str, production_order_id: str | None = None
    ) -> ToolResult:
        machine_id = self._machine(machine_id)
        status = self.controller.read_production_status(machine_id)
        if production_order_id is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", production_order_id):
                raise ToolValidationError("Invalid production order ID")
            orders = [item for item in status["orders"] if item["id"] == production_order_id]
            if not orders:
                raise ToolNotFoundError(f"Production order not found: {production_order_id}")
            status = {**status, "orders": orders, "selected_order_id": production_order_id}
        sources = [{"type": "production_order", "id": item["id"],
                    "uri": f"/api/mes/production-orders/{item['id']}"}
                   for item in status["orders"]]
        if not sources:
            sources = [{"type": "production_status", "id": machine_id,
                        "uri": f"/api/mes/machines/{machine_id}/production"}]
        return ToolResult("get_production_status", status, sources)

    def get_oee(self, machine_id: str) -> ToolResult:
        machine_id = self._machine(machine_id)
        result = self.controller.read_oee(machine_id)
        order_id = result.get("production_order_id")
        sources = [{"type": "production_order", "id": order_id,
                    "uri": f"/api/mes/production-orders/{order_id}"}] if order_id else [{
            "type": "oee", "id": machine_id, "uri": f"/api/mes/machines/{machine_id}/oee"
        }]
        return ToolResult("get_oee", result, sources)
