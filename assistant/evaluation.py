"""Deterministic grounding checks and acceptance evaluation for the MES assistant."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any

from assistant.orchestrator import AssistantMode, AssistantOrchestrator, PageContext


@dataclass(frozen=True)
class ValidationResult:
    status: str
    score: float
    checks: dict[str, bool]
    warnings: list[str]
    verified_sources: list[dict[str, str]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class GroundingValidator:
    """Validate model output against deterministic tool evidence."""

    SOURCE_URI = re.compile(r"^/api/[A-Za-z0-9_?&=./:%+-]+$")
    NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")

    @classmethod
    def verify_sources(cls, tool_context: dict[str, Any]) -> list[dict[str, str]]:
        verified: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for source in tool_context.get("sources", []):
            if not isinstance(source, dict):
                continue
            source_type = str(source.get("type", "")).strip()
            source_id = str(source.get("id", "")).strip()
            uri = str(source.get("uri", "")).strip()
            if not source_type or not source_id or not cls.SOURCE_URI.fullmatch(uri):
                continue
            key = (source_type, source_id, uri)
            if key in seen:
                continue
            seen.add(key)
            verified.append({key: str(value) for key, value in source.items() if value is not None})
        return verified

    @classmethod
    def validate(cls, answer: str, tool_context: dict[str, Any]) -> ValidationResult:
        normalized = answer.strip()
        sources = cls.verify_sources(tool_context)
        evidence = json.dumps(tool_context.get("data", {}), separators=(",", ":"), default=str)
        claims = set(cls.NUMBER.findall(normalized))
        ungrounded_numbers = sorted(number for number in claims if number not in evidence)
        checks = {
            "answer_present": bool(normalized),
            "tool_identified": bool(tool_context.get("tool")),
            "sources_verified": bool(sources),
            "numeric_claims_grounded": not ungrounded_numbers,
            "model_sources_removed": not bool(re.search(r"(?:^|\n)\s*sources\s*(?:\n|:)", normalized, re.I)),
        }
        warnings = []
        if ungrounded_numbers:
            warnings.append("Unverified numeric claims: " + ", ".join(ungrounded_numbers))
        if not sources:
            warnings.append("No valid tool sources were available")
        score = round(sum(checks.values()) / len(checks), 2)
        return ValidationResult(
            "VERIFIED" if all(checks.values()) else "REVIEW", score, checks, warnings, sources
        )


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    question: str
    expected_mode: AssistantMode
    expected_tool: str | None
    context: PageContext = PageContext(page="machine_details", machine_id="MACHINE-01")


ACCEPTANCE_CASES = (
    EvaluationCase("current_machine_state", "What is Machine 01 pressure?", AssistantMode.DATA, "get_machine_status"),
    EvaluationCase("historical_maximum", "What was the maximum pressure during the last hour?", AssistantMode.DATA, "analyze_metric"),
    EvaluationCase("trend", "Is pressure increasing?", AssistantMode.DATA, "analyze_metric"),
    EvaluationCase("root_cause", "Why did Machine 01 stop?", AssistantMode.DATA, "investigate_machine_stop"),
    EvaluationCase("production_summary", "Summarize today's production.", AssistantMode.DATA, "get_production_history"),
    EvaluationCase("document_guidance", "Machine 01 has HIGH_PRESSURE. What should I do?", AssistantMode.DATA, "search_knowledge"),
    EvaluationCase("no_data_investigation", "Why did Machine 01 fail?", AssistantMode.DATA, "investigate_machine_stop"),
)


def evaluate_routing(orchestrator: AssistantOrchestrator) -> dict[str, Any]:
    results = []
    for index, case in enumerate(ACCEPTANCE_CASES):
        plan = orchestrator.plan(case.question, case.context, f"evaluation:{index}")
        passed = plan.mode == case.expected_mode and plan.tool == case.expected_tool
        results.append({
            "name": case.name,
            "question": case.question,
            "passed": passed,
            "expected": {"mode": case.expected_mode.value, "tool": case.expected_tool},
            "actual": {"mode": plan.mode.value, "intent": plan.intent.value, "tool": plan.tool,
                       "arguments": plan.arguments},
        })
        orchestrator.clear_context(f"evaluation:{index}")
    passed_count = sum(result["passed"] for result in results)
    return {
        "suite": "MES_AI_Assistant initial acceptance routing",
        "passed": passed_count,
        "total": len(results),
        "accuracy_percent": round(passed_count / len(results) * 100, 1),
        "results": results,
    }
