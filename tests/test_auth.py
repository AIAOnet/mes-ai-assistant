import os
import unittest
from unittest.mock import patch

from dashboard.auth import User, authenticate, create_session, read_session, secure_cookie_enabled


class DashboardAuthenticationTests(unittest.TestCase):
    def test_secure_cookie_flag_is_environment_controlled(self) -> None:
        with patch.dict(os.environ, {"MES_COOKIE_SECURE": "true"}):
            self.assertTrue(secure_cookie_enabled())
        with patch.dict(os.environ, {"MES_COOKIE_SECURE": "false"}):
            self.assertFalse(secure_cookie_enabled())

    def test_signed_session_round_trip(self) -> None:
        with patch.dict(os.environ, {"MES_DASHBOARD_SECRET": "s" * 32}):
            user = read_session(create_session(User("alice", "operator"), 30))
        self.assertEqual(user, User("alice", "operator"))

    def test_tampered_session_is_rejected(self) -> None:
        with patch.dict(os.environ, {"MES_DASHBOARD_SECRET": "s" * 32}):
            token = create_session(User("alice", "operator"), 30)
            self.assertIsNone(read_session(token + "x"))

    def test_environment_users_have_roles(self) -> None:
        environment = {
            "MES_ADMIN_USERNAME": "admin-user", "MES_ADMIN_PASSWORD": "admin-password",
            "MES_OPERATOR_USERNAME": "line-user", "MES_OPERATOR_PASSWORD": "line-password",
            "MES_MAINTENANCE_USERNAME": "maint-user", "MES_MAINTENANCE_PASSWORD": "maint-password",
            "MES_ENGINEER_USERNAME": "eng-user", "MES_ENGINEER_PASSWORD": "eng-password",
            "MES_MANAGER_USERNAME": "manager-user", "MES_MANAGER_PASSWORD": "manager-password",
            "MES_VIEWER_USERNAME": "viewer-user", "MES_VIEWER_PASSWORD": "viewer-password",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(authenticate("admin-user", "admin-password"), User("admin-user", "admin"))
            self.assertEqual(authenticate("line-user", "line-password"), User("line-user", "operator"))
            self.assertEqual(authenticate("maint-user", "maint-password"), User("maint-user", "maintenance"))
            self.assertEqual(authenticate("eng-user", "eng-password"), User("eng-user", "engineer"))
            self.assertEqual(authenticate("manager-user", "manager-password"), User("manager-user", "manager"))
            self.assertEqual(authenticate("viewer-user", "viewer-password"), User("viewer-user", "viewer"))
            self.assertIsNone(authenticate("line-user", "wrong"))


if __name__ == "__main__":
    unittest.main()
