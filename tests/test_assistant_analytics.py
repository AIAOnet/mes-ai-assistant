import unittest
from datetime import datetime, timedelta, timezone

from assistant.analytics import downtime_statistics, metric_statistics


class DeterministicAnalyticsTests(unittest.TestCase):
    def test_metric_statistics_include_trend_rate_and_threshold_duration(self):
        start = datetime(2026, 8, 29, 8, tzinfo=timezone.utc)
        readings = [{"value": value, "time": (start + timedelta(minutes=index * 10)).isoformat()}
                    for index, value in enumerate((70.0, 80.0, 90.0, 100.0))]
        result = metric_statistics(readings, threshold=85.0)
        self.assertEqual(result["trend"], "INCREASING")
        self.assertEqual(result["median"], 85.0)
        self.assertEqual(result["upward_threshold_crossings"], 1)
        self.assertEqual(result["estimated_seconds_above_threshold"], 600.0)

    def test_downtime_closes_intervals_deterministically(self):
        start = datetime(2026, 8, 29, 8, tzinfo=timezone.utc)
        end = start + timedelta(hours=1)
        readings = [
            {"value": "RUNNING", "time": start.isoformat()},
            {"value": "STOPPED", "time": (start + timedelta(minutes=10)).isoformat()},
            {"value": "RUNNING", "time": (start + timedelta(minutes=25)).isoformat()},
        ]
        result = downtime_statistics(readings, start, end)
        self.assertEqual(result["downtime_minutes"], 15.0)
        self.assertEqual(result["stop_count"], 1)
        self.assertEqual(result["availability_percent"], 75.0)

    def test_empty_metric_period_is_explicitly_unavailable(self):
        self.assertFalse(metric_statistics([])["available"])


if __name__ == "__main__":
    unittest.main()
