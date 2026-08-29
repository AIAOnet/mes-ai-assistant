"""Explicit Stage 2 authorization boundary for read-only assistant tools."""

VALID_ROLES = {"admin", "operator", "maintenance", "engineer", "manager", "viewer"}

READ_ONLY_TOOLS = {
    "get_machine_status", "get_machine_alarms", "get_production_status", "get_oee",
    "get_alarm_details", "get_machine_history", "search_events", "get_maintenance_history",
    "get_production_history", "analyze_metric", "compare_metric", "get_downtime",
    "analyze_oee", "compare_oee", "investigate_machine_stop", "investigate_alarm",
    "search_knowledge", "search_ontology",
}

class AssistantAuthorizationError(PermissionError):
    pass

def authorize_read_tool(role: str, tool: str) -> None:
    if role not in VALID_ROLES:
        raise AssistantAuthorizationError("Assistant role is not authorized")
    if tool not in READ_ONLY_TOOLS:
        raise AssistantAuthorizationError("Assistant tools are read-only in Stage 2")
