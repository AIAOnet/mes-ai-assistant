"""Expose PLC tags through an OPC UA server."""

from __future__ import annotations

import asyncio
import logging

from asyncua import Server, ua
from asyncua.common.node import Node
from asyncua.crypto.truststore import TrustStore
from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions

from machine import MachineSimulator, PLCSimulator

LOGGER = logging.getLogger("OPC")
PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


class OPCUAServer:
    """Map PLC tag snapshots to OPC UA nodes."""

    NAMESPACE_URI = "urn:mes-simulator:machine-plc"

    def __init__(
        self,
        plc: PLCSimulator,
        endpoint: str = "opc.tcp://127.0.0.1:4840/mes-simulator/",
        security: dict | None = None,
    ) -> None:
        self.plc = plc
        self.endpoint = endpoint
        self.server = Server()
        self.nodes: dict[str, Node] = {}
        self.security = security or {"security_mode": "None"}

    async def start(self) -> None:
        await self.server.init()
        await self.server.set_application_uri("urn:mes-simulator:opc-server")
        self.server.set_endpoint(self.endpoint)
        self.server.set_server_name("MES Factory PLC Simulator")
        if self.security.get("security_mode") != "None":
            cert = PROJECT_ROOT / self.security["server_certificate_path"]
            key = PROJECT_ROOT / self.security["server_private_key_path"]
            trust_path = PROJECT_ROOT / self.security["trusted_certificates_path"]
            await self.server.load_certificate(cert)
            await self.server.load_private_key(key)
            policy_name = f"{self.security['security_policy']}_{self.security['security_mode']}"
            self.server.set_security_policy([getattr(ua.SecurityPolicyType, policy_name)])
            trust = TrustStore([trust_path], [])
            await trust.load()
            options = CertificateValidatorOptions.TRUSTED_VALIDATION | CertificateValidatorOptions.PEER_CLIENT
            self.server.set_certificate_validator(CertificateValidator(options, trust))

        namespace_index = await self.server.register_namespace(self.NAMESPACE_URI)
        machine_node = await self.server.nodes.objects.add_object(
            namespace_index, "Machine01"
        )

        for tag_name, value in self.plc.scan().items():
            short_name = tag_name.removeprefix("Machine01.")
            self.nodes[tag_name] = await machine_node.add_variable(
                namespace_index, short_name, value
            )

        await self.server.start()
        LOGGER.info("Server listening at %s", self.endpoint)

    async def publish_scan(self) -> None:
        """Copy one current PLC snapshot into the OPC UA address space."""
        for tag_name, value in self.plc.scan().items():
            node = self.nodes[tag_name]
            old_value = await node.read_value()
            if old_value != value:
                await node.write_value(value)
                LOGGER.info("Data change published: %s = %s", tag_name, value)

    async def stop(self) -> None:
        await self.server.stop()
        LOGGER.info("Server stopped")


async def run() -> None:
    machine = MachineSimulator()
    plc = PLCSimulator(machine)
    opc_server = OPCUAServer(plc)
    await opc_server.start()

    try:
        while True:
            machine.tick()
            await opc_server.publish_scan()
            await asyncio.sleep(1)
    finally:
        await opc_server.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
