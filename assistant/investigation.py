"""Deterministic evidence timeline construction for MES investigations."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def evidence_item(time: str, classification: str, kind: str, statement: str,
                  source_type: str, source_id: str) -> dict[str, Any]:
    return {"time": time, "classification": classification, "kind": kind,
            "statement": statement, "source": {"type": source_type, "id": source_id}}


def build_timeline(readings: dict[str, list[dict]], events: list[dict], alarms: list[dict],
                   tasks: list[dict], production: list[dict]) -> list[dict]:
    timeline: list[dict] = []
    for metric, items in readings.items():
        for item in items:
            timeline.append(evidence_item(item["time"], "FACT", "reading",
                f"{metric} was {item['value']}", "machine_reading", item["id"]))
    for event in events:
        timeline.append(evidence_item(event["time"], "FACT", "event",
            f"{event['type']} for {event['condition']} at value {event['value']}",
            "event", event["id"]))
    for alarm in alarms:
        timeline.append(evidence_item(alarm["triggered_time"], "FACT", "alarm",
            f"Alarm {alarm['type']} became {alarm['status']}: {alarm['message']}",
            "alarm", alarm["id"]))
    for task in tasks:
        time = task.get("CreatedTime") or task.get("created_time")
        if time:
            task_id = str(task.get("TaskId") or task.get("id"))
            timeline.append(evidence_item(time, "FACT", "maintenance",
                f"Maintenance task {task_id} was created with status {task.get('Status') or task.get('status')}",
                "maintenance_task", task_id))
    for record in production:
        time = record.get("RecordedTime")
        if time:
            order_id = str(record.get("ProductionOrderId"))
            timeline.append(evidence_item(time, "FACT", "production",
                f"Order {order_id} recorded total quantity {record.get('TotalQuantity')}",
                "production_order", order_id))
    return sorted(timeline, key=lambda item: item["time"])


def correlations(timeline: list[dict], target_time: datetime, target_label: str) -> list[dict]:
    result = []
    for item in timeline:
        if item["kind"] not in {"alarm", "event"}:
            continue
        seconds = (parse_time(item["time"]) - target_time).total_seconds()
        if abs(seconds) <= 60:
            result.append({"classification": "CORRELATION",
                "statement": f"{item['kind'].title()} occurred {abs(seconds):.1f} seconds "
                             f"{'after' if seconds >= 0 else 'before'} {target_label}.",
                "source": item["source"]})
    return result
