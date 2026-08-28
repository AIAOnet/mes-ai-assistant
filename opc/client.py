"""Learning client that subscribes to PLC tag changes."""

from __future__ import annotations

import asyncio
import logging

from asyncua import Client

from .server import OPCUAServer

LOGGER = logging.getLogger("OPC CLIENT")


class SubscriptionHandler:
    """Receive callbacks initiated by OPC UA data-change notifications."""

    def datachange_notification(self, node, value, data) -> None:
        LOGGER.info("DataChangeNotification: %s = %s", node, value)


async def run(
    endpoint: str = "opc.tcp://127.0.0.1:4840/mes-simulator/",
) -> None:
    async with Client(endpoint) as client:
        namespace_index = await client.get_namespace_index(
            OPCUAServer.NAMESPACE_URI
        )
        machine = await client.nodes.objects.get_child(
            [f"{namespace_index}:Machine01"]
        )
        pressure = await machine.get_child([f"{namespace_index}:Pressure"])

        subscription = await client.create_subscription(
            250, SubscriptionHandler()
        )
        await subscription.subscribe_data_change(pressure)
        LOGGER.info("Subscribed to Machine01.Pressure; press Ctrl+C to stop")

        try:
            while True:
                await asyncio.sleep(1)
        finally:
            await subscription.delete()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

