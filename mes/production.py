"""Production-order tracking and compact OEE calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class ProductionStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


@dataclass
class ProductionOrder:
    order_id: str
    product_name: str
    target_quantity: int
    status: ProductionStatus = ProductionStatus.PLANNED
    total_quantity: int = 0
    good_quantity: int = 0
    rejected_quantity: int = 0
    started_time: datetime | None = None
    completed_time: datetime | None = None
    elapsed_seconds: float = 0.0
    operating_seconds: float = 0.0

    def start(self) -> None:
        if self.status != ProductionStatus.PLANNED:
            raise ValueError("Only a planned order can be started")
        self.status = ProductionStatus.RUNNING
        self.started_time = datetime.now(timezone.utc)

    def record_good(self, quantity: int = 1) -> None:
        if self.status != ProductionStatus.RUNNING:
            return
        remaining = self.target_quantity - self.total_quantity
        quantity = min(quantity, remaining)
        self.total_quantity += quantity
        self.good_quantity += quantity

    def reject_one(self) -> None:
        if self.status != ProductionStatus.RUNNING or self.good_quantity < 1:
            raise ValueError("No produced good part is available to reject")
        self.good_quantity -= 1
        self.rejected_quantity += 1

    def complete(self) -> None:
        if self.status != ProductionStatus.RUNNING:
            raise ValueError("Only a running order can be completed")
        self.status = ProductionStatus.COMPLETED
        self.completed_time = datetime.now(timezone.utc)

    def oee(self, ideal_cycle_seconds: float) -> dict[str, float]:
        availability = self.operating_seconds / self.elapsed_seconds if self.elapsed_seconds else 0.0
        performance = min(1.0, self.total_quantity * ideal_cycle_seconds / self.operating_seconds) if self.operating_seconds else 0.0
        quality = self.good_quantity / self.total_quantity if self.total_quantity else 0.0
        return {"availability": availability * 100, "performance": performance * 100, "quality": quality * 100, "oee": availability * performance * quality * 100}
