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
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(authenticate("admin-user", "admin-password"), User("admin-user", "admin"))
            self.assertEqual(authenticate("line-user", "line-password"), User("line-user", "operator"))
            self.assertIsNone(authenticate("line-user", "wrong"))


if __name__ == "__main__":
    unittest.main()
