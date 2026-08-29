"""Deterministic Phase 2 intent routing and governed tool selection."""

from __future__ import annotations
import re
from assistant.orchestrator.intent import AssistantMode, Intent, QueryPlan
from assistant.orchestrator.context import ConversationContextStore, PageContext
from assistant.tools import MESReadTools, ToolResult
from assistant.security import authorize_read_tool


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
        if re.search(r"\b(everything related|related to|relationship|relationships|connected to|connections|linked to|ontology)\b", text):
            return QueryPlan(AssistantMode.DATA, Intent.ONTOLOGY_SEARCH, "search_ontology",
                             {"query":question,"depth":2}, context_data)
        knowledge_guidance = bool(re.search(
            r"\b(hydraulic|mechanical|component|components|equipment)\b", text
        ) and re.search(
            r"\b(what|which|how|could|should|involved|inspect|check|safe|excessive)\b", text
        ))
        knowledge_guidance = knowledge_guidance or bool(
            re.search(r"\b(high[-_ ]pressure|high[-_ ]temperature|alarm)\b", text)
            and re.search(r"\b(what should i do|procedure|instruction|safe|inspect|check)\b", text)
        )
        if context.page == "knowledge" or knowledge_guidance or re.search(
            r"\b(procedure|manual|sop|instruction|instructions|safety|troubleshoot|restart|repair|document|documentation|knowledge base)\b",
            text,
        ):
            return QueryPlan(AssistantMode.DATA, Intent.KNOWLEDGE_RETRIEVAL, "search_knowledge",
                             {"query": question, "machine_id": machine_id or context.machine_id or ""}, context_data)
        if context.alarm_id and (
            re.search(r"\b(this|selected|current) alarm\b", text)
            or (context.page == "alarm_details" and re.search(r"\b(it|this|what happened|why|before|status|explain)\b", text))
        ):
            if re.search(r"\b(why|before|what happened|investigate|cause|caused)\b", text):
                return QueryPlan(AssistantMode.DATA, Intent.INVESTIGATION, "investigate_alarm",
                                 {"alarm_id": context.alarm_id}, context_data)
            return QueryPlan(AssistantMode.DATA, Intent.ALARMS, "get_alarm_details",
                             {"alarm_id": context.alarm_id}, context_data)
        operational = bool(machine_id or re.search(
            r"\b(current|today|now|machine|alarm|production|produced|pressure|temperature|rpm|oee)\b", text
        ))
        analytical = bool(re.search(
            r"\b(trend|increas(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)|maximum|max|minimum|min|average|median|compare|rate of change)\b",
            text,
        ))
        analytical = analytical or bool(re.search(r"\bmean\s+(?:pressure|temperature|rpm)\b", text))
        metric_match = re.search(r"\b(pressure|temperature|rpm|production count)\b", text)
        if re.search(r"\b(why did|what happened before|investigate|abnormal.*before|what changed before)\b", text) and re.search(
            r"\b(stop|stopped|failure|machine|it)\b", text
        ):
            return QueryPlan(AssistantMode.DATA, Intent.INVESTIGATION, "investigate_machine_stop", {
                "machine_id": machine_id or "MACHINE-01", "period": period or "today",
            }, context_data)
        if operational and re.search(r"\b(why|cause|caused|root cause)\b", text):
            return QueryPlan(AssistantMode.DATA, Intent.UNSUPPORTED_OPERATIONAL, context=context_data)
        if re.search(r"\bdowntime\b|how long.*(?:stop|stopped)", text):
            return QueryPlan(AssistantMode.DATA, Intent.DOWNTIME, "get_downtime", {
                "machine_id": machine_id or "MACHINE-01", "period": period or "today",
            }, context_data)
        if re.search(r"\boee\b|overall equipment effectiveness", text) and re.search(r"\bcompare\b", text):
            return QueryPlan(AssistantMode.DATA, Intent.OEE_COMPARISON, "compare_oee", {
                "machine_id": machine_id or "MACHINE-01", "period_a": "today", "period_b": "yesterday",
            }, context_data)
        if metric_match and analytical and re.search(r"\bcompare\b", text):
            return QueryPlan(AssistantMode.DATA, Intent.METRIC_COMPARISON, "compare_metric", {
                "machine_id": machine_id or "MACHINE-01", "metric": metric_match.group(1).replace(" ", "_"),
                "period_a": "today", "period_b": "yesterday",
            }, context_data)
        if metric_match and analytical:
            return QueryPlan(AssistantMode.DATA, Intent.METRIC_ANALYTICS, "analyze_metric", {
                "machine_id": machine_id or "MACHINE-01", "metric": metric_match.group(1).replace(" ", "_"),
                "period": period or "last_1_hours",
            }, context_data)
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
            if period:
                return QueryPlan(AssistantMode.DATA, Intent.OEE_ANALYTICS, "analyze_oee", {
                    "machine_id": machine_id or "MACHINE-01", "period": period,
                }, context_data)
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

    def execute(self, plan: QueryPlan, role: str = "viewer") -> ToolResult | None:
        if not plan.tool:
            return None
        authorize_read_tool(role, plan.tool)
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
            "analyze_metric": self.tools.analyze_metric,
            "compare_metric": self.tools.compare_metric,
            "get_downtime": self.tools.get_downtime,
            "analyze_oee": self.tools.analyze_oee,
            "compare_oee": self.tools.compare_oee,
            "investigate_machine_stop": self.tools.investigate_machine_stop,
            "investigate_alarm": self.tools.investigate_alarm,
            "search_knowledge": self.tools.search_knowledge,
            "search_ontology": self.tools.search_ontology,
        }
        arguments = dict(plan.arguments)
        if plan.tool in {"search_knowledge","search_ontology"}: arguments["role"] = role
        return allowed[plan.tool](**arguments)

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
