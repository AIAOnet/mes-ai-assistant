import asyncio
import socket
import unittest

from asyncua import Client

from machine import MachineSimulator, PLCSimulator
from mes import AlarmManager, AlarmStatus, EventProcessor, ThresholdRule, ThresholdRuleEngine
from mes.opc_client import MESOPCClient
from opc.server import OPCUAServer


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def wait_until(predicate, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


class RecordingHandler:
    def __init__(self, initial_value: float) -> None:
        self.initial_value = initial_value
        self.values: list[float] = []
        self.changed = asyncio.Event()

    def datachange_notification(self, node, value, data) -> None:
        self.values.append(value)
        if value != self.initial_value:
            self.changed.set()


class OPCUASubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_plc_change_reaches_subscribed_client(self) -> None:
        machine = MachineSimulator(random_seed=7)
        plc = PLCSimulator(machine)
        port = available_port()
        endpoint = f"opc.tcp://127.0.0.1:{port}/test/"
        server = OPCUAServer(plc, endpoint)
        await server.start()

        try:
            async with Client(endpoint) as client:
                namespace_index = await client.get_namespace_index(
                    OPCUAServer.NAMESPACE_URI
                )
                machine_node = await client.nodes.objects.get_child(
                    [f"{namespace_index}:Machine01"]
                )
                pressure = await machine_node.get_child(
                    [f"{namespace_index}:Pressure"]
                )
                initial_value = await pressure.read_value()
                handler = RecordingHandler(initial_value)
                subscription = await client.create_subscription(50, handler)
                await subscription.subscribe_data_change(pressure)

                machine.tick()
                await server.publish_scan()
                await asyncio.wait_for(handler.changed.wait(), timeout=2)

                self.assertIn(machine.pressure, handler.values)
                await subscription.delete()
        finally:
            await server.stop()

    async def test_opc_notification_drives_state_aware_mes_alarm(self) -> None:
        machine = MachineSimulator(random_seed=7)
        server = OPCUAServer(
            PLCSimulator(machine),
            f"opc.tcp://127.0.0.1:{available_port()}/mes-test/",
        )
        rules = [
            ThresholdRule(
                "Machine01.Pressure", "HIGH_PRESSURE", 100.0, 90.0
            )
        ]
        processor = EventProcessor(
            ThresholdRuleEngine("MACHINE-01", rules), AlarmManager()
        )
        mes_client = MESOPCClient(server.endpoint, processor)
        await server.start()

        try:
            await mes_client.start()
            machine.pressure = 101.0
            await server.publish_scan()
            await wait_until(lambda: len(processor.alarm_manager.alarms) == 1)

            machine.pressure = 105.0
            await server.publish_scan()
            await asyncio.sleep(0.3)
            self.assertEqual(len(processor.alarm_manager.alarms), 1)

            machine.pressure = 80.0
            await server.publish_scan()
            await wait_until(
                lambda: processor.alarm_manager.alarms[0].status
                == AlarmStatus.RESOLVED
            )
            self.assertEqual(len(processor.events), 2)
        finally:
            await mes_client.stop()
            await server.stop()


if __name__ == "__main__":
    unittest.main()
