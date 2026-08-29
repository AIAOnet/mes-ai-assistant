import unittest

from assistant.evaluation import GroundingValidator, evaluate_routing
from assistant.orchestrator import AssistantOrchestrator
from assistant.tools import MESReadTools


class GroundingValidatorTests(unittest.TestCase):
    def test_accepts_only_verified_api_sources(self):
        context = {
            "tool": "get_machine_status",
            "data": {"pressure": 72, "pressure_unit": "bar"},
            "sources": [
                {"type": "machine_status", "id": "MACHINE-01",
                 "uri": "/api/mes/machines/MACHINE-01/status"},
                {"type": "invented", "id": "X", "uri": "javascript:alert(1)"},
            ],
        }
        result = GroundingValidator.validate("Pressure is 72 bar.", context)
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(len(result.verified_sources), 1)

    def test_flags_numeric_claim_not_present_in_evidence(self):
        context = {"tool": "get_machine_status", "data": {"pressure": 72}, "sources": [
            {"type": "machine_status", "id": "MACHINE-01",
             "uri": "/api/mes/machines/MACHINE-01/status"}
        ]}
        result = GroundingValidator.validate("Pressure is 99 bar.", context)
        self.assertEqual(result.status, "REVIEW")
        self.assertFalse(result.checks["numeric_claims_grounded"])


class AcceptanceEvaluationTests(unittest.TestCase):
    def test_initial_acceptance_questions_route_to_governed_tools(self):
        orchestrator = AssistantOrchestrator(MESReadTools(controller=None))
        result = evaluate_routing(orchestrator)
        self.assertEqual(result["passed"], result["total"])
        self.assertEqual(result["accuracy_percent"], 100.0)


if __name__ == "__main__":
    unittest.main()
