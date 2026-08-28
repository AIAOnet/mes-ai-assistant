"""State-aware MES threshold rules."""

from __future__ import annotations

from dataclasses import dataclass

from .events import Event, EventType


@dataclass(frozen=True)
class ThresholdRule:
    tag_name: str
    condition: str
    critical_above: float
    recover_below: float


class ThresholdRuleEngine:
    """Emit events only when a condition changes state."""

    def __init__(self, machine_id: str, rules: list[ThresholdRule]) -> None:
        self.machine_id = machine_id
        self.rules = {rule.tag_name: rule for rule in rules}
        self._active = {rule.condition: False for rule in rules}

    def update_rules(self, rules: list[ThresholdRule]) -> None:
        """Replace limits while preserving active alarm-condition state."""
        previous_state = self._active
        self.rules = {rule.tag_name: rule for rule in rules}
        self._active = {
            rule.condition: previous_state.get(rule.condition, False)
            for rule in rules
        }

    def evaluate(self, tag_name: str, value: object) -> list[Event]:
        rule = self.rules.get(tag_name)
        if rule is None or not isinstance(value, (int, float)):
            return []

        active = self._active[rule.condition]
        numeric_value = float(value)

        if not active and numeric_value > rule.critical_above:
            self._active[rule.condition] = True
            return [
                Event(
                    self.machine_id,
                    EventType.CONDITION_ENTERED,
                    rule.condition,
                    numeric_value,
                )
            ]

        if active and numeric_value < rule.recover_below:
            self._active[rule.condition] = False
            return [
                Event(
                    self.machine_id,
                    EventType.CONDITION_RECOVERED,
                    rule.condition,
                    numeric_value,
                )
            ]

        return []
