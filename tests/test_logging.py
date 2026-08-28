import json
import logging
import unittest

from dashboard.logging_config import JsonFormatter, RECENT_ERRORS, RecentErrorHandler, correlation_id


class StructuredLoggingTests(unittest.TestCase):
    def test_json_log_contains_correlation_and_redacts_secrets(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "connection PWD=hidden-value", (), None)
        record.fields = {"user": "operator", "password": "hidden-password", "token": "hidden-token"}
        token = correlation_id.set("request-123")
        try:
            payload = json.loads(formatter.format(record))
        finally:
            correlation_id.reset(token)
        rendered = json.dumps(payload)
        self.assertEqual(payload["correlation_id"], "request-123")
        self.assertEqual(payload["user"], "operator")
        self.assertNotIn("hidden-value", rendered)
        self.assertNotIn("hidden-password", rendered)
        self.assertNotIn("hidden-token", rendered)

    def test_recent_errors_are_safe_and_bounded(self) -> None:
        RECENT_ERRORS.clear()
        handler = RecentErrorHandler()
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "token=do-not-show", (), None)
        handler.emit(record)
        self.assertEqual(len(RECENT_ERRORS), 1)
        self.assertNotIn("do-not-show", RECENT_ERRORS[0]["message"])


if __name__ == "__main__":
    unittest.main()
