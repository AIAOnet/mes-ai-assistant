"""A small software PLC that maps machine state to named tags."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from .simulator import MachineSimulator

TagValue: TypeAlias = float | int | str | bool


@dataclass
class PLCSimulator:
    machine: MachineSimulator
    tags: dict[str, TagValue] = field(default_factory=dict, init=False)

    def scan(self) -> dict[str, TagValue]:
        """Perform one PLC scan and return an isolated tag snapshot."""
        self.tags = {
            "Machine01.Pressure": self.machine.pressure,
            "Machine01.Temperature": self.machine.temperature,
            "Machine01.RPM": self.machine.rpm,
            "Machine01.Status": self.machine.state.value,
            "Machine01.ProductionCount": self.machine.production_count,
            # Phase 3's rule engine will determine actual alarm conditions.
            "Machine01.AlarmState": False,
        }
        return self.tags.copy()

