"""SQL Server implementation of the MES persistence boundary."""

from __future__ import annotations

from pathlib import Path
import re
from datetime import date, datetime

import pymssql

from mes.alarms import Alarm
from mes.events import Event, EventType
from mes.tasks import MaintenanceTask
from mes.production import ProductionOrder


def _batches(script: str) -> list[str]:
    return [
        batch.strip()
        for batch in re.split(r"^\s*GO\s*$", script, flags=re.MULTILINE | re.IGNORECASE)
        if batch.strip()
    ]


def _connection_options(connection_string: str, database: str | None = None) -> dict:
    options = {}
    for item in connection_string.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            options[key.strip().upper()] = value.strip()
    server, _, port = options["SERVER"].partition(",")
    return {
        "server": server,
        "port": int(port or 1433),
        "user": options["UID"],
        "password": options["PWD"],
        "database": database or options["DATABASE"],
    }


def _connect(connection_string: str, database: str | None = None):
    return pymssql.connect(**_connection_options(connection_string, database))


def initialize_database(connection_string: str) -> None:
    """Create the learning database and apply idempotent SQL scripts."""
    script_dir = Path(__file__).parent
    with _connect(connection_string, "master") as connection:
        connection.autocommit(True)
        with connection.cursor() as cursor:
            cursor.execute((script_dir / "create_database.sql").read_text())

    with _connect(connection_string) as connection:
        with connection.cursor() as cursor:
            for filename in ("schema.sql", "procedures.sql", "triggers.sql"):
                script = (script_dir / filename).read_text(encoding="utf-8")
                for batch in _batches(script):
                    cursor.execute(batch)
        connection.commit()


class SQLServerRepository:
    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string

    def persist_reading(
        self, machine_id: str, tag_name: str, value: object
    ) -> None:
        numeric_value = float(value) if isinstance(value, (int, float)) else None
        text_value = None if numeric_value is not None else str(value)
        with _connect(self.connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                """
                INSERT dbo.MachineReadings
                    (MachineId, TagName, NumericValue, TextValue)
                VALUES (%s, %s, %s, %s)
                """,
                (machine_id, tag_name, numeric_value, text_value),
                )
            connection.commit()

    def persist(self, event: Event, alarm: Alarm | None) -> None:
        with _connect(self.connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                """
                INSERT dbo.[Events]
                    (MachineId, EventType, ConditionName, NumericValue, OccurredTime)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    event.machine_id,
                    event.event_type.value,
                    event.condition,
                    event.value,
                    event.occurred_at,
                ),
                )

                if alarm is not None and event.event_type == EventType.CONDITION_ENTERED:
                    cursor.execute(
                    """
                    INSERT dbo.Alarms
                        (AlarmId, MachineId, AlarmType, Severity, Message,
                         TriggeredValue, TriggeredTime, Status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        alarm.alarm_id,
                        alarm.machine_id,
                        alarm.alarm_type,
                        alarm.severity,
                        alarm.message,
                        alarm.triggered_value,
                        alarm.triggered_time,
                        alarm.status.value,
                    ),
                    )
                elif alarm is not None and event.event_type == EventType.CONDITION_RECOVERED:
                    cursor.execute(
                    """
                    UPDATE dbo.Alarms
                    SET Status = %s, ResolvedTime = %s
                    WHERE AlarmId = %s
                    """,
                    (alarm.status.value, alarm.resolved_time, alarm.alarm_id),
                    )

            connection.commit()

    def acknowledge_alarm(self, alarm: Alarm) -> None:
        with _connect(self.connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE dbo.Alarms
                    SET Acknowledged = %s, AcknowledgedBy = %s,
                        AcknowledgedTime = %s
                    WHERE AlarmId = %s
                    """,
                    (
                        alarm.acknowledged,
                        alarm.acknowledged_by,
                        alarm.acknowledged_time,
                        alarm.alarm_id,
                    ),
                )
            connection.commit()

    def persist_task(self, task: MaintenanceTask) -> None:
        with _connect(self.connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT dbo.MaintenanceTasks
                        (MachineId, RelatedAlarmId, Description, Priority,
                         Status, CreatedTime)
                    OUTPUT INSERTED.TaskId
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        task.machine_id,
                        task.related_alarm_id,
                        task.description,
                        task.priority,
                        task.status.value,
                        task.created_time,
                    ),
                )
                task.task_id = int(cursor.fetchone()[0])
            connection.commit()

    def update_task(self, task: MaintenanceTask) -> None:
        with _connect(self.connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE dbo.MaintenanceTasks
                    SET Status = %s, CompletedTime = %s
                    WHERE TaskId = %s
                    """,
                    (task.status.value, task.completed_time, task.task_id),
                )
            connection.commit()

    def persist_production_order(self, order: ProductionOrder, machine_id: str) -> None:
        with _connect(self.connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT dbo.ProductionOrders
                        (ProductionOrderId, MachineId, ProductName, TargetQuantity, Status)
                    VALUES (%s, %s, %s, %s, %s)
                """, (order.order_id, machine_id, order.product_name, order.target_quantity, order.status.value))
            connection.commit()

    def update_production_order(self, order: ProductionOrder) -> None:
        with _connect(self.connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE dbo.ProductionOrders
                    SET Status=%s, StartedTime=%s, CompletedTime=%s
                    WHERE ProductionOrderId=%s
                """, (order.status.value, order.started_time, order.completed_time, order.order_id))
            connection.commit()

    def persist_production_record(self, order: ProductionOrder) -> None:
        with _connect(self.connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT dbo.ProductionRecords
                        (ProductionOrderId, TotalQuantity, GoodQuantity, RejectedQuantity)
                    VALUES (%s, %s, %s, %s)
                """, (order.order_id, order.total_quantity, order.good_quantity, order.rejected_quantity))
            connection.commit()

    def persist_operator_action(self, username: str, role: str, method: str, path: str, status: int, client_address: str | None) -> None:
        with _connect(self.connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT dbo.OperatorActionAudit
                        (Username, UserRole, HttpMethod, ActionPath, ResultStatus, ClientAddress)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (username, role, method, path, status, client_address))
            connection.commit()

    def database_snapshot(self, limit: int = 50) -> dict[str, list[dict]]:
        """Return recent rows from a fixed, read-only learning view."""
        limit = max(1, min(limit, 200))
        queries = {
            "readings": f"""
                SELECT TOP {limit} ReadingId, MachineId, TagName,
                    NumericValue, TextValue, RecordedTime
                FROM dbo.MachineReadings ORDER BY ReadingId DESC
            """,
            "events": f"""
                SELECT TOP {limit} EventId, MachineId, EventType,
                    ConditionName, NumericValue, OccurredTime
                FROM dbo.[Events] ORDER BY EventId DESC
            """,
            "alarms": f"""
                SELECT TOP {limit} AlarmId, AlarmType, Severity, Status,
                    Acknowledged, AcknowledgedBy, TriggeredTime, ResolvedTime
                FROM dbo.Alarms ORDER BY TriggeredTime DESC
            """,
            "tasks": f"""
                SELECT TOP {limit} TaskId, RelatedAlarmId, Description,
                    Priority, Status, CreatedTime, CompletedTime
                FROM dbo.MaintenanceTasks ORDER BY TaskId DESC
            """,
            "audit": f"""
                SELECT TOP {limit} AuditId, AlarmId, PreviousStatus,
                    NewStatus, ChangedTime
                FROM dbo.AlarmAudit ORDER BY AuditId DESC
            """,
            "actions": f"""
                SELECT TOP {limit} ActionAuditId, Username, UserRole,
                    HttpMethod, ActionPath, ResultStatus, ClientAddress, OccurredTime
                FROM dbo.OperatorActionAudit ORDER BY ActionAuditId DESC
            """,
            "orders": f"""
                SELECT TOP {limit} ProductionOrderId, ProductName, MachineId,
                    TargetQuantity, Status, StartedTime, CompletedTime
                FROM dbo.ProductionOrders ORDER BY ProductionOrderId DESC
            """,
            "production": f"""
                SELECT TOP {limit} ProductionRecordId, ProductionOrderId,
                    TotalQuantity, GoodQuantity, RejectedQuantity, RecordedTime
                FROM dbo.ProductionRecords ORDER BY ProductionRecordId DESC
            """,
        }
        result: dict[str, list[dict]] = {}
        with _connect(self.connection_string) as connection:
            with connection.cursor(as_dict=True) as cursor:
                for name, query in queries.items():
                    cursor.execute(query)
                    result[name] = [
                        {
                            key: value.isoformat()
                            if isinstance(value, (datetime, date))
                            else value
                            for key, value in row.items()
                        }
                        for row in cursor.fetchall()
                    ]
        return result
