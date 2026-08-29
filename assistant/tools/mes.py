"""Strict, read-only MES tools backed by the existing MES controller."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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

    def __init__(self, controller) -> None:
        self.controller = controller

    def _machine(self, machine_id: str) -> str:
        normalized = machine_id.strip().upper()
        if normalized not in self.ALLOWED_MACHINES:
            raise ToolValidationError(f"Machine is not authorized: {normalized}")
        return normalized

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
        if period not in {None, "today"}:
            raise ToolValidationError("Alarm period is not allowed")
        since = None
        if period == "today":
            now = datetime.now(timezone.utc)
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        alarms = self.controller.read_machine_alarms(machine_id, active_only=active_only, since=since)
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
