import unittest

from dashboard.monitoring import MonitoringRegistry


class MonitoringRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = MonitoringRegistry()
        self.healthy = {"database": {"connected": True}, "transport": {"connected": True}}

    def test_request_metrics_include_latency_and_prometheus_labels(self) -> None:
        self.registry.record_request("GET", "/api/state", 200, 0.025)
        self.registry.record_request("POST", "/api/action", 500, 0.075)
        snapshot = self.registry.snapshot(self.healthy)
        self.assertEqual(snapshot["requests_total"], 2)
        self.assertEqual(snapshot["errors_total"], 1)
        self.assertEqual(snapshot["error_rate_percent"], 50.0)
        self.assertEqual(snapshot["average_duration_ms"], 50.0)
        metrics = self.registry.prometheus(self.healthy)
        self.assertIn('mes_service_up{service="database"} 1', metrics)
        self.assertIn('path="/api/state",status="200"} 1', metrics)

    def test_alerts_detect_dependencies_and_repeated_failures(self) -> None:
        for _ in range(3):
            self.registry.record_request("GET", "/api/failing", 500, 0.01)
        services = {"database": {"connected": False}, "transport": {"connected": True}}
        self.assertEqual({alert["source"] for alert in self.registry.snapshot(services)["alerts"]}, {"database", "api"})

    def test_static_paths_have_bounded_cardinality(self) -> None:
        self.registry.record_request("GET", "/static/app.js", 200, 0.01)
        self.assertIn('path="/static/*"', self.registry.prometheus(self.healthy))


if __name__ == "__main__":
    unittest.main()
