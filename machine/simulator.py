"""Physical machine simulation for Phase 1."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import random


class MachineState(StrEnum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


@dataclass
class MachineSimulator:
    """Simulate sensors whose readings drift gradually between updates."""

    machine_id: str = "MACHINE-01"
    pressure: float = 70.0
    temperature: float = 55.0
    rpm: int = 1400
    production_count: int = 0
    production_interval_ticks: int = 5
    state: MachineState = MachineState.RUNNING
    random_seed: int | None = None
    _ticks_since_part: int = field(default=0, init=False, repr=False)
    _pressure_fault: bool = field(default=False, init=False, repr=False)
    _temperature_fault: bool = field(default=False, init=False, repr=False)
    _random: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._random = random.Random(self.random_seed)

    def tick(self) -> None:
        """Advance the simulated physical process by about one second."""
        if self.state == MachineState.RUNNING:
            pressure_change = self._random.uniform(-1.5, 1.5)
            temperature_change = self._random.uniform(-0.5, 0.5)
            rpm_change = self._random.randint(-30, 30)

            if self._pressure_fault:
                pressure_change += 4.0
            if self._temperature_fault:
                temperature_change += 2.5

            self.pressure = round(max(0.0, self.pressure + pressure_change), 1)
            self.temperature = round(
                max(20.0, self.temperature + temperature_change), 1
            )
            self.rpm = max(0, self.rpm + rpm_change)

            self._ticks_since_part += 1
            if self._ticks_since_part >= self.production_interval_ticks:
                self.production_count += 1
                self._ticks_since_part = 0
        else:
            # A stopped motor has no speed; pressure and heat decay gradually.
            self.rpm = 0
            self.pressure = round(max(0.0, self.pressure - 2.0), 1)
            self.temperature = round(max(20.0, self.temperature - 0.5), 1)

    def raise_pressure(self) -> None:
        """Begin a physical pressure fault; no MES alarm is created here."""
        self._pressure_fault = True

    def raise_temperature(self) -> None:
        """Begin a physical temperature fault; no MES alarm is created here."""
        self._temperature_fault = True

    def stop(self) -> None:
        self.state = MachineState.STOPPED
        self.rpm = 0

    def start(self) -> None:
        """Start the motor without resetting sensor or production history."""
        self.state = MachineState.RUNNING
        if self.rpm == 0:
            self.rpm = 1400

    def reset(self) -> None:
        """Return the physical simulation to normal operating conditions."""
        self.pressure = 70.0
        self.temperature = 55.0
        self.rpm = 1400
        self.state = MachineState.RUNNING
        self._pressure_fault = False
        self._temperature_fault = False
        self._ticks_since_part = 0
