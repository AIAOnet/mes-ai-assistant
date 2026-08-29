"""Deterministic Phase 2 intent routing and governed tool selection."""

from __future__ import annotations
import re
from assistant.orchestrator.intent import AssistantMode, Intent, QueryPlan
from assistant.tools import MESReadTools, ToolResult


class AssistantOrchestrator:
    def __init__(self, tools: MESReadTools) -> None:
        self.tools = tools

    def plan(self, question: str) -> QueryPlan:
        text = question.lower()
        machine_id = self._machine_id(text)
        operational = bool(machine_id or re.search(
            r"\b(current|today|now|machine|alarm|production|produced|pressure|temperature|rpm|oee)\b", text
        ))
        if re.search(r"\boee\b|overall equipment effectiveness", text):
            if re.search(r"\b(what is|explain|define)\b", text) and not re.search(
                r"\b(current|today|now|our|machine|value|show)\b", text
            ):
                return QueryPlan(AssistantMode.ASK, Intent.GENERAL_KNOWLEDGE)
            if operational:
                return QueryPlan(AssistantMode.DATA, Intent.OEE, "get_oee", {"machine_id": machine_id or "MACHINE-01"})
            return QueryPlan(AssistantMode.ASK, Intent.GENERAL_KNOWLEDGE)
        if re.search(r"\balarm(s)?\b|high[- ]pressure|high[- ]temperature", text):
            if re.search(r"\b(what does|what is|explain|mean|definition)\b", text) and not re.search(
                r"\b(current|today|now|our|machine|active|open|show|how many)\b", text
            ):
                return QueryPlan(AssistantMode.ASK, Intent.GENERAL_KNOWLEDGE)
            return QueryPlan(AssistantMode.DATA, Intent.ALARMS, "get_machine_alarms", {
                "machine_id": machine_id or "MACHINE-01",
                "active_only": bool(re.search(r"\b(active|open|current)\b", text)),
                "period": "today" if re.search(r"\btoday\b", text) else None,
            })
        if re.search(r"\bproduction\b|\bproduced\b|\bunits?\b|\border\b", text):
            return QueryPlan(AssistantMode.DATA, Intent.PRODUCTION, "get_production_status",
                             {"machine_id": machine_id or "MACHINE-01"})
        if re.search(r"\bpressure\b|\btemperature\b|\brpm\b|machine\s+(status|state)|what is happening", text):
            return QueryPlan(AssistantMode.DATA, Intent.CURRENT_MACHINE_STATUS, "get_machine_status",
                             {"machine_id": machine_id or "MACHINE-01"})
        if operational and re.search(r"\b(stop|stopped|why|downtime|maintenance|history|trend|compare)\b", text):
            return QueryPlan(AssistantMode.DATA, Intent.UNSUPPORTED_OPERATIONAL)
        return QueryPlan(AssistantMode.ASK, Intent.GENERAL_KNOWLEDGE)

    def execute(self, plan: QueryPlan) -> ToolResult | None:
        if not plan.tool:
            return None
        allowed = {
            "get_machine_status": self.tools.get_machine_status,
            "get_machine_alarms": self.tools.get_machine_alarms,
            "get_production_status": self.tools.get_production_status,
            "get_oee": self.tools.get_oee,
        }
        return allowed[plan.tool](**plan.arguments)

    @staticmethod
    def _machine_id(text: str) -> str | None:
        match = re.search(r"\bmachine[\s_-]*0*(\d+)\b", text, flags=re.IGNORECASE)
        return f"MACHINE-{int(match.group(1)):02d}" if match else None
