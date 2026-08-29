import unittest

from assistant.security import AssistantAuthorizationError, VALID_ROLES, authorize_read_tool

class AssistantSecurityPolicyTests(unittest.TestCase):
    def test_supported_roles_can_use_allow_listed_read_tool(self):
        for role in VALID_ROLES:
            authorize_read_tool(role, "get_machine_status")

    def test_write_or_unknown_tool_is_denied(self):
        for tool in ("start_machine", "acknowledge_alarm", "execute_sql", "change_configuration"):
            with self.assertRaises(AssistantAuthorizationError):
                authorize_read_tool("admin", tool)

    def test_unknown_role_is_denied(self):
        with self.assertRaises(AssistantAuthorizationError):
            authorize_read_tool("anonymous", "get_machine_status")
