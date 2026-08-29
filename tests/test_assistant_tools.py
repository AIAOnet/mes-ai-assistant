import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from assistant.orchestrator import AssistantMode, AssistantOrchestrator, Intent, PageContext
from assistant.tools import MESReadTools, ToolNotFoundError, ToolValidationError


class FakeController:
    settings = {"pressure": {"warning": 85.0}, "temperature": {"warning": 75.0}}
    update_interval = 1.0
    machine = SimpleNamespace(production_interval_ticks=5)
    def snapshot(self):
        return {"machine_status": "RUNNING", "pressure": 72.0, "temperature": 58.0,
                "rpm": 1450, "production_count": 47}

    def read_machine_alarms(self, machine_id, active_only=False, since=None, until=None):
        alarms = [{"id": "A-103", "machine_id": machine_id, "type": "HIGH_PRESSURE",
                   "severity": "HIGH", "status": "ACTIVE", "message": "High pressure",
                   "triggered_time": "2026-08-29T10:32:00+00:00", "resolved_time": None}]
        return alarms if not active_only or alarms[0]["status"] == "ACTIVE" else []

    def read_machine_history(self, machine_id, tag_name, start, end, limit):
        if tag_name == "Machine01.Status":
            return [{"id": "S-1", "machine_id": machine_id, "tag": tag_name,
                     "value": "RUNNING", "time": start.isoformat()},
                    {"id": "S-2", "machine_id": machine_id, "tag": tag_name,
                     "value": "STOPPED", "time": (start + timedelta(minutes=10)).isoformat()},
                    {"id": "S-3", "machine_id": machine_id, "tag": tag_name,
                     "value": "RUNNING", "time": (start + timedelta(minutes=15)).isoformat()}][:limit]
        return [{"id": "1", "machine_id": machine_id, "tag": tag_name,
                 "value": 68.0, "time": start.isoformat()},
                {"id": "2", "machine_id": machine_id, "tag": tag_name,
                 "value": 72.0, "time": end.isoformat()}][:limit]

    def read_event_history(self, machine_id, start, end, limit):
        return [{"id": "E-1", "machine_id": machine_id, "type": "CONDITION_ENTERED",
                 "condition": "HIGH_PRESSURE", "value": 101, "time": start.isoformat()}]

    def read_maintenance_history(self, machine_id, start, end, limit):
        return [{"TaskId": 1, "MachineId": machine_id, "Status": "COMPLETED"}]

    def read_production_history(self, machine_id, start, end, limit):
        return [{"ProductionOrderId": "PO-1", "TotalQuantity": 47}]

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

    def test_alarm_details_are_selected_by_verified_id(self):
        result = self.tools.get_alarm_details("A-103")
        self.assertEqual(result.data["alarm"]["status"], "ACTIVE")
        self.assertEqual(result.sources[0]["uri"], "/api/mes/alarms/A-103")

    def test_unknown_alarm_is_not_found(self):
        with self.assertRaises(ToolNotFoundError):
            self.tools.get_alarm_details("A-999")

    def test_production_status_can_be_scoped_to_selected_order(self):
        result = self.tools.get_production_status("MACHINE-01", "PO-1")
        self.assertEqual(result.data["selected_order_id"], "PO-1")
        self.assertEqual(len(result.data["orders"]), 1)

    def test_historical_readings_have_bounded_window_and_source(self):
        result = self.tools.get_machine_history("MACHINE-01", "pressure", "last_24_hours")
        self.assertEqual(result.data["metric"], "pressure")
        self.assertEqual(result.data["unit"], "bar")
        self.assertEqual(result.data["count"], 2)
        self.assertEqual(result.sources[0]["type"], "machine_readings")

    def test_historical_period_and_metric_are_allow_listed(self):
        with self.assertRaises(ToolValidationError):
            self.tools.get_machine_history("MACHINE-01", "voltage", "last_1_hours")
        with self.assertRaises(ToolValidationError):
            self.tools.get_machine_history("MACHINE-01", "pressure", "last_31_days")

    def test_all_historical_data_families_are_available(self):
        self.assertEqual(self.tools.search_events("MACHINE-01", "today").data["count"], 1)
        self.assertEqual(self.tools.get_maintenance_history("MACHINE-01", "yesterday").data["count"], 1)
        self.assertEqual(self.tools.get_production_history("MACHINE-01", "last_1_days").data["count"], 1)


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

    def test_stop_question_uses_phase_six_investigation(self):
        plan = self.orchestrator.plan("Why did Machine 01 stop?")
        self.assertEqual(plan.intent, Intent.INVESTIGATION)
        self.assertEqual(plan.tool, "investigate_machine_stop")

    def test_machine_page_context_resolves_implicit_pressure_question(self):
        plan = self.orchestrator.plan(
            "What is its pressure?", PageContext("machine_details", "MACHINE-01"), "chat-1"
        )
        self.assertEqual(plan.tool, "get_machine_status")
        self.assertEqual(plan.context["machine_id"], "MACHINE-01")

    def test_selected_alarm_resolves_follow_up_reference(self):
        plan = self.orchestrator.plan(
            "What is this alarm?",
            PageContext("alarm_details", "MACHINE-01", alarm_id="A-103"),
            "chat-2",
        )
        self.assertEqual(plan.tool, "get_alarm_details")
        self.assertEqual(plan.arguments, {"alarm_id": "A-103"})
        follow_up = self.orchestrator.plan("Is it active?", conversation_key="chat-2")
        self.assertEqual(follow_up.tool, "get_alarm_details")

    def test_selected_order_scopes_production_tool(self):
        plan = self.orchestrator.plan(
            "Show production status",
            PageContext("production", "MACHINE-01", production_order_id="PO-1"),
            "chat-3",
        )
        self.assertEqual(plan.arguments["production_order_id"], "PO-1")

    def test_changing_page_clears_stale_entity_reference(self):
        self.orchestrator.plan(
            "What is this alarm?",
            PageContext("alarm_details", "MACHINE-01", alarm_id="A-103"),
            "chat-4",
        )
        plan = self.orchestrator.plan(
            "What is the current pressure?",
            PageContext("machine_details", "MACHINE-01"),
            "chat-4",
        )
        self.assertNotIn("alarm_id", plan.context)

    def test_pressure_readings_last_hour_use_historical_tool(self):
        plan = self.orchestrator.plan("Show pressure readings from the last hour")
        self.assertEqual(plan.tool, "get_machine_history")
        self.assertEqual(plan.arguments["period"], "last_1_hours")
        self.assertEqual(plan.arguments["metric"], "pressure")

    def test_alarm_and_production_history_route_to_specific_tools(self):
        alarm = self.orchestrator.plan("Show alarms from the last 24 hours")
        production = self.orchestrator.plan("Show today's production history")
        self.assertEqual(alarm.tool, "get_machine_alarms")
        self.assertEqual(alarm.arguments["period"], "last_24_hours")
        self.assertEqual(production.tool, "get_production_history")

    def test_trend_question_uses_deterministic_phase_five_tool(self):
        plan = self.orchestrator.plan("Any pressure increases in the last 24 hours?")
        self.assertEqual(plan.intent, Intent.METRIC_ANALYTICS)
        self.assertEqual(plan.tool, "analyze_metric")
        self.assertEqual(plan.arguments["period"], "last_24_hours")

    def test_metric_analytics_are_calculated_by_tool(self):
        result = self.orchestrator.tools.analyze_metric("MACHINE-01", "pressure", "last_1_hours")
        self.assertEqual(result.data["trend"], "INCREASING")
        self.assertEqual(result.data["minimum"], 68.0)
        self.assertEqual(result.data["maximum"], 72.0)
        self.assertEqual(result.sources[0]["type"], "metric_analysis")

    def test_metric_comparison_has_deterministic_deltas(self):
        result = self.orchestrator.tools.compare_metric("MACHINE-01", "pressure", "today", "yesterday")
        self.assertTrue(result.data["comparison_a_minus_b"]["available"])
        self.assertEqual(result.data["comparison_a_minus_b"]["mean_delta"], 0.0)

    def test_downtime_and_oee_tools_return_coverage_metadata(self):
        downtime = self.orchestrator.tools.get_downtime("MACHINE-01", "today")
        oee = self.orchestrator.tools.analyze_oee("MACHINE-01", "today")
        self.assertIn("coverage", downtime.data)
        self.assertIn("coverage_note", oee.data)

    def test_analytics_questions_route_to_specific_tools(self):
        maximum = self.orchestrator.plan("What was the maximum pressure during the last hour?")
        downtime = self.orchestrator.plan("How much downtime occurred today?")
        comparison = self.orchestrator.plan("Compare today's OEE with yesterday")
        self.assertEqual(maximum.tool, "analyze_metric")
        self.assertEqual(downtime.tool, "get_downtime")
        self.assertEqual(comparison.tool, "compare_oee")

    def test_stop_investigation_builds_labeled_evidence(self):
        result = self.orchestrator.tools.investigate_machine_stop("MACHINE-01", "today")
        self.assertEqual(result.tool, "investigate_machine_stop")
        self.assertEqual(result.data["target"]["type"], "machine_stop")
        self.assertTrue(all(item["classification"] == "FACT" for item in result.data["timeline"]))
        self.assertEqual(result.data["unknown"]["classification"], "UNKNOWN")

    def test_alarm_investigation_uses_selected_alarm_time(self):
        result = self.orchestrator.tools.investigate_alarm("A-103")
        self.assertEqual(result.data["target"]["id"], "A-103")
        self.assertEqual(result.sources[0]["type"], "alarm")

    def test_investigation_questions_route_to_evidence_tools(self):
        stop = self.orchestrator.plan("Why did Machine 01 stop?")
        alarm = self.orchestrator.plan(
            "What happened before this alarm?",
            PageContext("alarm_details", "MACHINE-01", alarm_id="A-103"), "investigation-chat",
        )
        self.assertEqual(stop.tool, "investigate_machine_stop")
        self.assertEqual(alarm.tool, "investigate_alarm")

    def test_generic_causal_question_still_fails_closed(self):
        plan = self.orchestrator.plan("What caused the OEE to decrease?")
        self.assertEqual(plan.intent, Intent.UNSUPPORTED_OPERATIONAL)


if __name__ == "__main__":
    unittest.main()
