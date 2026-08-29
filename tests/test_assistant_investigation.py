import unittest
from datetime import datetime, timezone

from assistant.investigation import build_timeline, correlations


class InvestigationTimelineTests(unittest.TestCase):
    def test_timeline_is_chronological_and_factual(self):
        timeline = build_timeline(
            {"pressure": [{"id": "R-1", "value": 105, "time": "2026-08-29T10:32:10+00:00"}]},
            [{"id": "E-1", "type": "CONDITION_ENTERED", "condition": "HIGH_PRESSURE",
              "value": 105, "time": "2026-08-29T10:32:12+00:00"}],
            [], [], [],
        )
        self.assertEqual([item["kind"] for item in timeline], ["reading", "event"])
        self.assertTrue(all(item["classification"] == "FACT" for item in timeline))

    def test_close_event_is_correlation_not_fact_or_cause(self):
        target = datetime(2026, 8, 29, 10, 32, 14, tzinfo=timezone.utc)
        timeline = [{"time": "2026-08-29T10:32:12+00:00", "kind": "alarm",
                     "source": {"type": "alarm", "id": "A-1"}}]
        result = correlations(timeline, target, "machine stop")
        self.assertEqual(result[0]["classification"], "CORRELATION")
        self.assertIn("2.0 seconds before", result[0]["statement"])


if __name__ == "__main__":
    unittest.main()
