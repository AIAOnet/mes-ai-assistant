"""Strict, read-only MES tools backed by the existing MES controller."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any
from assistant.analytics import compare_statistics, downtime_statistics, metric_statistics
from assistant.investigation import build_timeline, correlations, evidence_item, parse_time


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

    def analyze_metric(self, machine_id: str, metric: str, period: str) -> ToolResult:
        machine_id = self._machine(machine_id)
        if metric not in self.METRICS or metric == "status":
            raise ToolValidationError(f"Metric cannot be analyzed: {metric}")
        start, end = self._window(period)
        tag, unit = self.METRICS[metric]
        readings = self.controller.read_machine_history(machine_id, tag, start, end, 500)
        threshold = None
        if metric in {"pressure", "temperature"}:
            threshold = self.controller.settings.get(metric, {}).get("warning")
        analysis = metric_statistics(readings, threshold)
        data = {"machine_id": machine_id, "metric": metric, "unit": unit, "period": period,
                "start_time": start.isoformat(), "end_time": end.isoformat(), **analysis}
        return ToolResult("analyze_metric", data, [{"type": "metric_analysis",
            "id": f"{machine_id}:{metric}:{period}",
            "uri": f"/api/mes/machines/{machine_id}/analytics/metric?metric={metric}&period={period}"}])

    def compare_metric(self, machine_id: str, metric: str, period_a: str, period_b: str) -> ToolResult:
        first = self.analyze_metric(machine_id, metric, period_a).data
        second = self.analyze_metric(machine_id, metric, period_b).data
        comparison = compare_statistics(first, second)
        data = {"machine_id": self._machine(machine_id), "metric": metric,
                "period_a": first, "period_b": second, "comparison_a_minus_b": comparison}
        return ToolResult("compare_metric", data, [{"type": "metric_comparison",
            "id": f"{machine_id}:{metric}:{period_a}:{period_b}",
            "uri": f"/api/mes/machines/{machine_id}/analytics/compare?metric={metric}&period_a={period_a}&period_b={period_b}"}])

    def get_downtime(self, machine_id: str, period: str) -> ToolResult:
        machine_id = self._machine(machine_id)
        start, end = self._window(period)
        status_tag, _ = self.METRICS["status"]
        readings = self.controller.read_machine_history(machine_id, status_tag, start, end, 500)
        data = {"machine_id": machine_id, "period": period, "start_time": start.isoformat(),
                "end_time": end.isoformat(), **downtime_statistics(readings, start, end)}
        return ToolResult("get_downtime", data, [{"type": "downtime_analysis",
            "id": f"{machine_id}:{period}",
            "uri": f"/api/mes/machines/{machine_id}/analytics/downtime?period={period}"}])

    def analyze_oee(self, machine_id: str, period: str) -> ToolResult:
        machine_id = self._machine(machine_id)
        start, end = self._window(period)
        status_tag, _ = self.METRICS["status"]
        statuses = self.controller.read_machine_history(machine_id, status_tag, start, end, 500)
        downtime = downtime_statistics(statuses, start, end)
        records = self.controller.read_production_history(machine_id, start, end, 200)
        grouped: dict[str, list[dict]] = {}
        for record in records:
            grouped.setdefault(str(record.get("ProductionOrderId")), []).append(record)
        total = good = rejected = 0
        for order_records in grouped.values():
            ordered = sorted(order_records, key=lambda item: item.get("RecordedTime") or "")
            if len(ordered) < 2:
                continue
            total += max(0, int(ordered[-1].get("TotalQuantity") or 0) - int(ordered[0].get("TotalQuantity") or 0))
            good += max(0, int(ordered[-1].get("GoodQuantity") or 0) - int(ordered[0].get("GoodQuantity") or 0))
            rejected += max(0, int(ordered[-1].get("RejectedQuantity") or 0) - int(ordered[0].get("RejectedQuantity") or 0))
        operating = (max(0.0, downtime["period_seconds"] - downtime["downtime_seconds"])
                     if downtime["downtime_seconds"] is not None else None)
        ideal_cycle = self.controller.update_interval * self.controller.machine.production_interval_ticks
        availability = downtime["availability_percent"]
        performance = min(100.0, total * ideal_cycle / operating * 100) if operating else None
        quality = good / total * 100 if total else None
        oee = availability / 100 * performance / 100 * quality if None not in (availability, performance, quality) else None
        data = {"machine_id": machine_id, "period": period, "start_time": start.isoformat(),
                "end_time": end.isoformat(), "availability": availability, "performance": performance,
                "quality": quality, "oee": oee, "produced_delta": total, "good_delta": good,
                "rejected_delta": rejected, "production_orders_with_baseline":
                sum(1 for items in grouped.values() if len(items) >= 2), "downtime": downtime,
                "coverage_note": "OEE uses orders with at least two production records in the selected period."}
        return ToolResult("analyze_oee", data, [{"type": "oee_analysis",
            "id": f"{machine_id}:{period}",
            "uri": f"/api/mes/machines/{machine_id}/analytics/oee?period={period}"}])

    def compare_oee(self, machine_id: str, period_a: str, period_b: str) -> ToolResult:
        first = self.analyze_oee(machine_id, period_a).data
        second = self.analyze_oee(machine_id, period_b).data
        deltas = {name: first[name] - second[name] if first[name] is not None and second[name] is not None else None
                  for name in ("availability", "performance", "quality", "oee")}
        return ToolResult("compare_oee", {"machine_id": self._machine(machine_id),
            "period_a": first, "period_b": second, "deltas_a_minus_b": deltas}, [{
                "type": "oee_comparison", "id": f"{machine_id}:{period_a}:{period_b}",
                "uri": f"/api/mes/machines/{machine_id}/analytics/oee-compare?period_a={period_a}&period_b={period_b}"}])

    @staticmethod
    def _sample(items: list[dict], maximum: int = 24) -> list[dict]:
        if len(items) <= maximum:
            return items
        indexes = {round(index * (len(items) - 1) / (maximum - 1)) for index in range(maximum)}
        return [item for index, item in enumerate(items) if index in indexes]

    def _investigation(
        self, machine_id: str, target_time: datetime, target_type: str, target_id: str,
        before_minutes: int = 5, after_minutes: int = 2,
    ) -> ToolResult:
        machine_id = self._machine(machine_id)
        if not 1 <= before_minutes <= 30 or not 1 <= after_minutes <= 10:
            raise ToolValidationError("Investigation window is outside the allowed range")
        start = target_time - timedelta(minutes=before_minutes)
        end = target_time + timedelta(minutes=after_minutes)
        readings = {}
        for metric in ("pressure", "temperature", "rpm", "status"):
            tag, _ = self.METRICS[metric]
            readings[metric] = self._sample(
                self.controller.read_machine_history(machine_id, tag, start, end, 500)
            )
        events = self.controller.read_event_history(machine_id, start, end, 200)
        alarms = self.controller.read_machine_alarms(machine_id, since=start, until=end)
        tasks = self.controller.read_maintenance_history(machine_id, start, end, 100)
        production = self.controller.read_production_history(machine_id, start, end, 100)
        timeline = build_timeline(readings, events, alarms, tasks, production)
        target_label = f"{target_type} {target_id}"
        findings = correlations(timeline, target_time, target_label)
        high_pressure_nearby = any(
            item["kind"] in {"alarm", "event"} and "PRESSURE" in item["statement"].upper()
            and abs((parse_time(item["time"]) - target_time).total_seconds()) <= 60
            for item in timeline
        )
        inference = ({"classification": "INFERENCE",
            "statement": "The timing indicates pressure may be associated with the target event; "
                         "the MES evidence does not prove mechanical causation."}
                     if high_pressure_nearby else None)
        unknown = {"classification": "UNKNOWN",
                   "statement": "A confirmed mechanical root cause cannot be determined from MES data alone."}
        window_id = f"{machine_id}:{start.isoformat()}:{end.isoformat()}"
        sources = [
            {"type": target_type, "id": target_id, "uri": f"/api/mes/{target_type}s/{target_id}"},
            {"type": "machine_readings", "id": window_id, "uri": f"/api/mes/machines/{machine_id}/history"},
            {"type": "event_history", "id": window_id, "uri": f"/api/mes/machines/{machine_id}/events"},
            {"type": "alarm_history", "id": window_id, "uri": f"/api/mes/machines/{machine_id}/alarms"},
            {"type": "maintenance_history", "id": window_id, "uri": f"/api/mes/machines/{machine_id}/maintenance"},
            {"type": "production_history", "id": window_id, "uri": f"/api/mes/machines/{machine_id}/production-history"},
        ]
        data = {"machine_id": machine_id, "target": {"type": target_type, "id": target_id,
                "time": target_time.isoformat()}, "window": {"start": start.isoformat(),
                "end": end.isoformat(), "before_minutes": before_minutes,
                "after_minutes": after_minutes}, "timeline": timeline, "correlations": findings,
                "inference": inference, "unknown": unknown}
        return ToolResult("investigate_event", data, sources)

    def investigate_machine_stop(self, machine_id: str, period: str = "today") -> ToolResult:
        machine_id = self._machine(machine_id)
        start, end = self._window(period)
        status_tag, _ = self.METRICS["status"]
        statuses = self.controller.read_machine_history(machine_id, status_tag, start, end, 500)
        stop = next((item for item in reversed(statuses) if str(item.get("value")).upper() == "STOPPED"), None)
        if stop is None:
            return ToolResult("investigate_machine_stop", {"machine_id": machine_id,
                "period": period, "target": None, "timeline": [], "correlations": [],
                "inference": None, "unknown": {"classification": "UNKNOWN",
                "statement": "No machine stop was found in the selected period."}}, [{
                    "type": "status_history", "id": f"{machine_id}:{period}",
                    "uri": f"/api/mes/machines/{machine_id}/history?metric=status&period={period}"}])
        result = self._investigation(machine_id, parse_time(stop["time"]), "machine_stop", stop["id"])
        return ToolResult("investigate_machine_stop", result.data, result.sources)

    def investigate_alarm(self, alarm_id: str) -> ToolResult:
        details = self.get_alarm_details(alarm_id).data["alarm"]
        result = self._investigation(details["machine_id"], parse_time(details["triggered_time"]),
                                     "alarm", alarm_id)
        return ToolResult("investigate_alarm", result.data, result.sources)

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
