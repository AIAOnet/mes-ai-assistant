"""Run the Phase 3 MES OPC UA subscriber."""

from __future__ import annotations

import asyncio
import logging
import os

from database.bootstrap import DEFAULT_CONNECTION
from database.repository import SQLServerRepository

from .alarms import AlarmManager
from .config import load_settings
from .opc_client import MESOPCClient
from .processor import EventProcessor
from .rules import ThresholdRule, ThresholdRuleEngine


def build_rules(settings: dict) -> list[ThresholdRule]:
    return [
        ThresholdRule(
            "Machine01.Pressure",
            "HIGH_PRESSURE",
            settings["pressure"]["critical"],
            settings["pressure"]["warning"],
        ),
        ThresholdRule(
            "Machine01.Temperature",
            "HIGH_TEMPERATURE",
            settings["temperature"]["critical"],
            settings["temperature"]["warning"],
        ),
    ]


def build_processor(persist: bool = True) -> EventProcessor:
    settings = load_settings()
    rules = build_rules(settings)
    repository = None
    if persist:
        repository = SQLServerRepository(
            os.getenv("MES_SQL_CONNECTION", DEFAULT_CONNECTION)
        )
    return EventProcessor(
        ThresholdRuleEngine("MACHINE-01", rules), AlarmManager(), repository
    )


async def run() -> None:
    client = MESOPCClient(
        "opc.tcp://127.0.0.1:4840/mes-simulator/", build_processor()
    )
    await client.start()
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await client.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
