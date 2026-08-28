import unittest
from datetime import datetime, timezone

from mes import (
    AlarmManager,
    AlarmStatus,
    EventProcessor,
    EventType,
    ThresholdRule,
    ThresholdRuleEngine,
    TaskStatus,
)


def build_processor() -> EventProcessor:
    rules = [
        ThresholdRule(
            "Machine01.Pressure", "HIGH_PRESSURE", 100.0, 90.0
        )
    ]
    return EventProcessor(ThresholdRuleEngine("MACHINE-01", rules), AlarmManager())


class MESEventRuleTests(unittest.TestCase):
    def test_normal_pressure_creates_no_alarm(self) -> None:
        processor = build_processor()
        processor.process("Machine01.Pressure", 70)
        self.assertEqual(processor.alarm_manager.alarms, [])

    def test_crossing_threshold_creates_one_alarm(self) -> None:
        processor = build_processor()
        for value in (95, 101, 105, 110):
            processor.process("Machine01.Pressure", value)

        self.assertEqual(len(processor.alarm_manager.alarms), 1)
        self.assertEqual(
            processor.alarm_manager.alarms[0].alarm_type, "HIGH_PRESSURE"
        )
        self.assertEqual(len(processor.events), 1)

    def test_recovery_resolves_alarm_and_records_event(self) -> None:
        processor = build_processor()
        processor.process("Machine01.Pressure", 101)
        processor.process("Machine01.Pressure", 95)
        self.assertEqual(len(processor.events), 1, "95 is inside hysteresis band")

        processor.process("Machine01.Pressure", 80)

        alarm = processor.alarm_manager.alarms[0]
        self.assertEqual(alarm.status, AlarmStatus.RESOLVED)
        self.assertIsNotNone(alarm.resolved_time)
        self.assertEqual(processor.events[-1].event_type, EventType.CONDITION_RECOVERED)

    def test_unrelated_tag_is_recorded_but_creates_no_alarm(self) -> None:
        processor = build_processor()
        processor.process("Machine01.RPM", 1450)
        self.assertEqual(processor.latest_tags["Machine01.RPM"], 1450)
        self.assertEqual(processor.events, [])

    def test_trace_explains_transport_rule_and_alarm_lineage(self) -> None:
        processor = build_processor()
        processor.process("Machine01.Pressure", 101, source="MQTT")
        trace = processor.traces[0]
        self.assertEqual(trace["transport"], "MQTT")
        self.assertEqual(trace["tag"], "Machine01.Pressure")
        self.assertEqual(trace["event"], "CONDITION_ENTERED")
        self.assertTrue(trace["alarm_id"].startswith("A-"))
        self.assertIn("Rule produced", trace["decision"])
        self.assertEqual(processor.important_traces[0]["id"], trace["id"])

    def test_domain_event_is_passed_to_persistence_boundary(self) -> None:
        class RecordingPersistence:
            def __init__(self) -> None:
                self.calls = []
                self.readings = []
                self.tasks = []

            def persist_reading(self, machine_id, tag_name, value) -> None:
                self.readings.append((machine_id, tag_name, value))

            def persist(self, event, alarm) -> None:
                self.calls.append((event, alarm))

            def persist_task(self, task) -> None:
                self.tasks.append(task)

        persistence = RecordingPersistence()
        rules = [
            ThresholdRule(
                "Machine01.Pressure", "HIGH_PRESSURE", 100.0, 90.0
            )
        ]
        processor = EventProcessor(
            ThresholdRuleEngine("MACHINE-01", rules),
            AlarmManager(),
            persistence,
        )

        processor.process("Machine01.Pressure", 101)

        self.assertEqual(len(persistence.calls), 1)
        event, alarm = persistence.calls[0]
        self.assertEqual(event.condition, "HIGH_PRESSURE")
        self.assertTrue(alarm.alarm_id.startswith("A-"))
        self.assertEqual(
            persistence.readings,
            [("MACHINE-01", "Machine01.Pressure", 101)],
        )
        self.assertEqual(len(persistence.tasks), 1)
        records = processor.traces[0]["database_records"]
        self.assertEqual(records["MachineReadings"]["NumericValue"], 101.0)
        self.assertEqual(records["Events"]["ConditionName"], "HIGH_PRESSURE")
        self.assertEqual(records["Alarms"]["Status"], "ACTIVE")
        self.assertEqual(records["MaintenanceTasks"]["Status"], "OPEN")

    def test_alarm_acknowledgement_does_not_resolve_alarm(self) -> None:
        processor = build_processor()
        processor.process("Machine01.Pressure", 101)
        alarm = processor.alarm_manager.alarms[0]

        processor.alarm_manager.acknowledge(
            alarm.alarm_id, "Operator One", datetime.now(timezone.utc)
        )

        self.assertTrue(alarm.acknowledged)
        self.assertEqual(alarm.acknowledged_by, "Operator One")
        self.assertEqual(alarm.status, AlarmStatus.ACTIVE)

    def test_alarm_creates_one_task_with_valid_lifecycle(self) -> None:
        processor = build_processor()
        for value in (101, 105, 110):
            processor.process("Machine01.Pressure", value)

        self.assertEqual(len(processor.task_manager.tasks), 1)
        task = processor.task_manager.tasks[0]
        self.assertEqual(task.status, TaskStatus.OPEN)
        processor.task_manager.start(task.task_id)
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        processor.task_manager.complete(task.task_id)
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIsNotNone(task.completed_time)


if __name__ == "__main__":
    unittest.main()
