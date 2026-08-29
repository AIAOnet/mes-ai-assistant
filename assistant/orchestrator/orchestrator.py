"""Deterministic Phase 2 intent routing and governed tool selection."""

from __future__ import annotations
import re
from assistant.orchestrator.intent import AssistantMode, Intent, QueryPlan
from assistant.orchestrator.context import ConversationContextStore, PageContext
from assistant.tools import MESReadTools, ToolResult


class AssistantOrchestrator:
    def __init__(self, tools: MESReadTools) -> None:
        self.tools = tools
        self.contexts = ConversationContextStore()

    def plan(
        self, question: str, page_context: PageContext | None = None,
        conversation_key: str = "default",
    ) -> QueryPlan:
        text = question.lower()
        context = (
            self.contexts.merge(conversation_key, page_context)
            if page_context else self.contexts.current(conversation_key) or PageContext(page="unknown")
        )
        context_data = context.as_dict()
        machine_id = self._machine_id(text) or context.machine_id
        period = self._period(text)
        if context.alarm_id and (
            re.search(r"\b(this|selected|current) alarm\b", text)
            or (context.page == "alarm_details" and re.search(r"\b(it|this|what happened|status|explain)\b", text))
        ):
            return QueryPlan(AssistantMode.DATA, Intent.ALARMS, "get_alarm_details",
                             {"alarm_id": context.alarm_id}, context_data)
        operational = bool(machine_id or re.search(
            r"\b(current|today|now|machine|alarm|production|produced|pressure|temperature|rpm|oee)\b", text
        ))
        analytical = bool(re.search(
            r"\b(trend|increas(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)|maximum|max|minimum|min|average|mean|median|compare|rate of change)\b",
            text,
        ))
        if analytical and period:
            return QueryPlan(AssistantMode.DATA, Intent.UNSUPPORTED_OPERATIONAL, context=context_data)
        if re.search(r"\bmaintenance\b|\btasks?\b", text) and period:
            return QueryPlan(AssistantMode.DATA, Intent.MAINTENANCE_HISTORY, "get_maintenance_history",
                             {"machine_id": machine_id or "MACHINE-01", "period": period}, context_data)
        if re.search(r"\bevents?\b", text) and period:
            return QueryPlan(AssistantMode.DATA, Intent.EVENT_HISTORY, "search_events",
                             {"machine_id": machine_id or "MACHINE-01", "period": period}, context_data)
        if re.search(r"\boee\b|overall equipment effectiveness", text):
            if re.search(r"\b(what is|explain|define)\b", text) and not re.search(
                r"\b(current|today|now|our|machine|value|show)\b", text
            ):
                return QueryPlan(AssistantMode.ASK, Intent.GENERAL_KNOWLEDGE, context=context_data)
            if operational:
                return QueryPlan(AssistantMode.DATA, Intent.OEE, "get_oee", {"machine_id": machine_id or "MACHINE-01"}, context_data)
            return QueryPlan(AssistantMode.ASK, Intent.GENERAL_KNOWLEDGE, context=context_data)
        if re.search(r"\balarm(s)?\b|high[- ]pressure|high[- ]temperature", text):
            if re.search(r"\b(what does|what is|explain|mean|definition)\b", text) and not re.search(
                r"\b(current|today|now|our|machine|active|open|show|how many)\b", text
            ):
                return QueryPlan(AssistantMode.ASK, Intent.GENERAL_KNOWLEDGE, context=context_data)
            return QueryPlan(AssistantMode.DATA, Intent.ALARMS, "get_machine_alarms", {
                "machine_id": machine_id or "MACHINE-01",
                "active_only": bool(re.search(r"\b(active|open|current)\b", text)),
                "period": period,
            }, context_data)
        if re.search(r"\bproduction\b|\bproduced\b|\bunits?\b|\border\b", text):
            if period:
                return QueryPlan(AssistantMode.DATA, Intent.PRODUCTION_HISTORY, "get_production_history",
                                 {"machine_id": machine_id or "MACHINE-01", "period": period}, context_data)
            arguments = {"machine_id": machine_id or "MACHINE-01"}
            if context.production_order_id:
                arguments["production_order_id"] = context.production_order_id
            return QueryPlan(AssistantMode.DATA, Intent.PRODUCTION, "get_production_status",
                             arguments, context_data)
        metric_match = re.search(r"\b(pressure|temperature|rpm|production count|status)\b", text)
        if metric_match and period:
            metric = metric_match.group(1).replace(" ", "_")
            return QueryPlan(AssistantMode.DATA, Intent.MACHINE_HISTORY, "get_machine_history", {
                "machine_id": machine_id or "MACHINE-01", "metric": metric, "period": period,
            }, context_data)
        if re.search(r"\bpressure\b|\btemperature\b|\brpm\b|machine\s+(status|state)|what is happening", text):
            return QueryPlan(AssistantMode.DATA, Intent.CURRENT_MACHINE_STATUS, "get_machine_status",
                             {"machine_id": machine_id or "MACHINE-01"}, context_data)
        if operational and re.search(r"\b(stop|stopped|why|downtime|maintenance|history|trend|compare)\b", text):
            return QueryPlan(AssistantMode.DATA, Intent.UNSUPPORTED_OPERATIONAL, context=context_data)
        return QueryPlan(AssistantMode.ASK, Intent.GENERAL_KNOWLEDGE, context=context_data)

    def execute(self, plan: QueryPlan) -> ToolResult | None:
        if not plan.tool:
            return None
        allowed = {
            "get_machine_status": self.tools.get_machine_status,
            "get_machine_alarms": self.tools.get_machine_alarms,
            "get_production_status": self.tools.get_production_status,
            "get_oee": self.tools.get_oee,
            "get_alarm_details": self.tools.get_alarm_details,
            "get_machine_history": self.tools.get_machine_history,
            "search_events": self.tools.search_events,
            "get_maintenance_history": self.tools.get_maintenance_history,
            "get_production_history": self.tools.get_production_history,
        }
        return allowed[plan.tool](**plan.arguments)

    def clear_context(self, conversation_key: str) -> None:
        self.contexts.clear(conversation_key)

    @staticmethod
    def _machine_id(text: str) -> str | None:
        match = re.search(r"\bmachine[\s_-]*0*(\d+)\b", text, flags=re.IGNORECASE)
        return f"MACHINE-{int(match.group(1)):02d}" if match else None

    @staticmethod
    def _period(text: str) -> str | None:
        if re.search(r"\byesterday\b", text):
            return "yesterday"
        if re.search(r"\btoday\b", text):
            return "today"
        match = re.search(r"\blast\s+(?:(\d+)\s+)?(minute|hour|day)s?\b", text)
        if match:
            amount = int(match.group(1) or 1)
            return f"last_{amount}_{match.group(2)}s"
        return None
