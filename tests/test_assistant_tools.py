import unittest
from datetime import datetime, timezone

from assistant.orchestrator import AssistantMode, AssistantOrchestrator, Intent
from assistant.tools import MESReadTools, ToolValidationError


class FakeController:
    def snapshot(self):
        return {"machine_status": "RUNNING", "pressure": 72.0, "temperature": 58.0,
                "rpm": 1450, "production_count": 47}

    def read_machine_alarms(self, machine_id, active_only=False, since=None):
        alarms = [{"id": "A-103", "machine_id": machine_id, "type": "HIGH_PRESSURE",
                   "severity": "HIGH", "status": "ACTIVE", "message": "High pressure",
                   "triggered_time": "2026-08-29T10:32:00+00:00", "resolved_time": None}]
        return alarms if not active_only or alarms[0]["status"] == "ACTIVE" else []

    def read_production_status(self, machine_id):
        return {"machine_id": machine_id, "machine_production_count": 47,
                "active_order_id": "PO-1", "orders": [{
                    "id": "PO-1", "status": "RUNNING", "total_quantity": 47,
                    "good_quantity": 45, "rejected_quantity": 2,
                }]}

    def read_oee(self, machine_id):
        return {"machine_id": machine_id, "production_order_id": "PO-1",
                "availability": 90.0, "performance": 95.0, "quality": 98.0, "oee": 83.79}


class MESReadToolTests(unittest.TestCase):
    def setUp(self):
        self.tools = MESReadTools(FakeController())

    def test_machine_status_has_verified_source(self):
        result = self.tools.get_machine_status("machine-01")
        self.assertEqual(result.data["pressure"], 72.0)
        self.assertEqual(result.data["pressure_unit"], "bar")
        self.assertEqual(result.sources[0]["id"], "MACHINE-01")

    def test_unknown_machine_is_rejected(self):
        with self.assertRaises(ToolValidationError):
            self.tools.get_machine_status("MACHINE-99")

    def test_alarm_period_is_allow_listed(self):
        with self.assertRaises(ToolValidationError):
            self.tools.get_machine_alarms("MACHINE-01", period="all-time")

    def test_core_tools_are_read_only_results(self):
        self.assertEqual(self.tools.get_machine_alarms("MACHINE-01").tool, "get_machine_alarms")
        self.assertEqual(self.tools.get_production_status("MACHINE-01").data["active_order_id"], "PO-1")
        self.assertEqual(self.tools.get_oee("MACHINE-01").data["oee"], 83.79)


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.orchestrator = AssistantOrchestrator(MESReadTools(FakeController()))

    def test_general_oee_definition_uses_ask_mode(self):
        plan = self.orchestrator.plan("What is OEE?")
        self.assertEqual((plan.mode, plan.intent, plan.tool),
                         (AssistantMode.ASK, Intent.GENERAL_KNOWLEDGE, None))

    def test_current_oee_uses_data_tool(self):
        plan = self.orchestrator.plan("What is the current OEE?")
        self.assertEqual((plan.mode, plan.tool), (AssistantMode.DATA, "get_oee"))

    def test_machine_pressure_uses_status_tool(self):
        plan = self.orchestrator.plan("What is Machine 01 pressure?")
        self.assertEqual(plan.arguments, {"machine_id": "MACHINE-01"})
        self.assertEqual(plan.tool, "get_machine_status")

    def test_today_alarm_count_uses_filtered_alarm_tool(self):
        plan = self.orchestrator.plan("How many alarms occurred today?")
        self.assertEqual(plan.tool, "get_machine_alarms")
        self.assertEqual(plan.arguments["period"], "today")

    def test_alarm_definition_stays_in_ask_mode(self):
        plan = self.orchestrator.plan("What does a high-pressure alarm mean?")
        self.assertEqual(plan.mode, AssistantMode.ASK)

    def test_phase_three_question_is_not_guessed(self):
        plan = self.orchestrator.plan("Why did Machine 01 stop?")
        self.assertEqual(plan.intent, Intent.UNSUPPORTED_OPERATIONAL)


if __name__ == "__main__":
    unittest.main()
