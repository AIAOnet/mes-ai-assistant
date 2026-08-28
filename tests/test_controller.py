import asyncio
import socket
import unittest

from dashboard.controller import SimulationController
from dashboard.api import Configuration, SecurityConfiguration
from pydantic import ValidationError


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class SimulationControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        endpoint = f"opc.tcp://127.0.0.1:{available_port()}/dashboard-test/"
        self.controller = SimulationController(endpoint=endpoint, persist=False, update_interval=0.05)
        await self.controller.start()
        await asyncio.sleep(0.2)

    async def asyncTearDown(self) -> None:
        await self.controller.shutdown()

    async def test_pause_freezes_the_physical_simulation(self) -> None:
        await self.controller.pause_simulation()
        pressure = self.controller.machine.pressure
        await asyncio.sleep(0.15)
        self.assertEqual(self.controller.machine.pressure, pressure)

    async def test_health_reports_connected_transport(self) -> None:
        health = self.controller.health()
        self.assertEqual(health["status"], "healthy")
        self.assertTrue(health["transport_connected"])
        self.assertEqual(health["transport"], "OPC_UA")

    async def test_machine_stop_propagates_through_opc_to_mes(self) -> None:
        await self.controller.stop_machine()
        async with asyncio.timeout(2):
            while self.controller.processor.latest_tags.get("Machine01.Status") != "STOPPED":
                await asyncio.sleep(0.02)
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot["machine_status"], "STOPPED")
        self.assertEqual(snapshot["rpm"], 0)

    async def test_pressure_control_does_not_create_alarm_directly(self) -> None:
        await self.controller.pause_simulation()
        self.controller.raise_pressure()
        self.assertEqual(self.controller.processor.alarm_manager.alarms, [])

    async def test_configuration_updates_runtime_values(self) -> None:
        original = self.controller.configuration()
        changed = {
            **original,
            "pressure": {"warning": 85.0, "critical": 95.0},
            "simulation_update_interval": 0.2,
            "production_interval_ticks": 3,
        }
        try:
            result = self.controller.apply_configuration(changed)
            self.assertFalse(result["restart_required"])
            self.assertEqual(self.controller.update_interval, 0.2)
            self.assertEqual(self.controller.machine.production_interval_ticks, 3)
            rule = self.controller.processor.rule_engine.rules[
                "Machine01.Pressure"
            ]
            self.assertEqual(rule.critical_above, 95.0)
        finally:
            self.controller.apply_configuration(original)


class ConfigurationValidationTests(unittest.TestCase):
    def test_warning_must_be_lower_than_critical(self) -> None:
        with self.assertRaises(ValidationError):
            Configuration.model_validate(
                {
                    "pressure": {"warning": 100, "critical": 90},
                    "temperature": {"warning": 80, "critical": 90},
                    "simulation_update_interval": 1,
                    "production_interval_ticks": 5,
                    "opc_endpoint": "opc.tcp://127.0.0.1:4840/test/",
                    "communication_mode": "OPC_UA",
                }
            )

    def test_opc_security_requires_certificate_and_key(self) -> None:
        with self.assertRaises(ValidationError):
            SecurityConfiguration.model_validate({
                "dashboard": {"authentication_enabled": True, "session_timeout_minutes": 30, "audit_enabled": True},
                "opc_ua": {"security_mode": "SignAndEncrypt", "security_policy": "Basic256Sha256", "certificate_path": "", "private_key_path": "", "trusted_certificates_path": "certs/trusted"},
                "mqtt": {"tls_enabled": False, "username": "", "ca_certificate_path": "", "client_certificate_path": "", "client_key_path": ""},
            })

    def test_mqtt_tls_requires_ca_certificate(self) -> None:
        with self.assertRaises(ValidationError):
            SecurityConfiguration.model_validate({
                "dashboard": {"authentication_enabled": False, "session_timeout_minutes": 30, "audit_enabled": True},
                "opc_ua": {"security_mode": "None", "security_policy": "None", "certificate_path": "", "private_key_path": "", "trusted_certificates_path": ""},
                "mqtt": {"tls_enabled": True, "username": "mes-client", "ca_certificate_path": "", "client_certificate_path": "", "client_key_path": ""},
            })


if __name__ == "__main__":
    unittest.main()
