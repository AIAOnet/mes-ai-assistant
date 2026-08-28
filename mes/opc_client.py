"""OPC UA adapter that feeds subscribed PLC tags into the MES."""

from __future__ import annotations

import logging
from pathlib import Path

from asyncua import Client
from asyncua.common.node import Node
from asyncua.crypto.truststore import TrustStore
from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions

from opc.server import OPCUAServer

from .processor import EventProcessor

LOGGER = logging.getLogger("MES OPC")
PROJECT_ROOT = Path(__file__).resolve().parents[1]

MONITORED_TAGS = (
    "Pressure",
    "Temperature",
    "RPM",
    "Status",
    "ProductionCount",
    "AlarmState",
)


class MESSubscriptionHandler:
    def __init__(
        self, processor: EventProcessor, tag_names_by_node_id: dict[str, str]
    ) -> None:
        self.processor = processor
        self.tag_names_by_node_id = tag_names_by_node_id

    def datachange_notification(self, node, value, data) -> None:
        tag_name = self.tag_names_by_node_id[str(node.nodeid)]
        data_value = getattr(getattr(data, "monitored_item", None), "Value", None)
        status_code = getattr(data_value, "StatusCode", None)
        status_name = getattr(status_code, "name", None) or str(status_code or "Good")
        self.processor.process(
            tag_name,
            value,
            source="OPC_UA",
            delivery_payload={
                "monitoredItems": {"value": value, "statusCode": status_name}
            },
        )


class MESOPCClient:
    def __init__(self, endpoint: str, processor: EventProcessor, security: dict | None = None) -> None:
        self.client = Client(endpoint)
        self.client.application_uri = "urn:mes-simulator:mes-client"
        self.processor = processor
        self.subscription = None
        self.security = security or {"security_mode": "None"}

    async def start(self) -> None:
        if self.security.get("security_mode") != "None":
            client_cert = PROJECT_ROOT / self.security["certificate_path"]
            client_key = PROJECT_ROOT / self.security["private_key_path"]
            server_cert = PROJECT_ROOT / self.security["server_certificate_path"]
            security_string = f"{self.security['security_policy']},{self.security['security_mode']},{client_cert},{client_key},{server_cert}"
            await self.client.set_security_string(security_string)
            trust = TrustStore([PROJECT_ROOT / self.security["trusted_certificates_path"]], [])
            await trust.load()
            options = CertificateValidatorOptions.TRUSTED_VALIDATION | CertificateValidatorOptions.PEER_SERVER
            self.client.certificate_validator = CertificateValidator(options, trust)
        await self.client.connect()
        namespace_index = await self.client.get_namespace_index(
            OPCUAServer.NAMESPACE_URI
        )
        machine = await self.client.nodes.objects.get_child(
            [f"{namespace_index}:Machine01"]
        )
        nodes: dict[str, Node] = {}
        for short_name in MONITORED_TAGS:
            nodes[f"Machine01.{short_name}"] = await machine.get_child(
                [f"{namespace_index}:{short_name}"]
            )

        names_by_node_id = {
            str(node.nodeid): tag_name for tag_name, node in nodes.items()
        }
        handler = MESSubscriptionHandler(self.processor, names_by_node_id)
        self.subscription = await self.client.create_subscription(250, handler)
        await self.subscription.subscribe_data_change(list(nodes.values()))
        LOGGER.info("Subscribed to %d PLC tags", len(nodes))

    async def stop(self) -> None:
        if self.subscription is not None:
            await self.subscription.delete()
        await self.client.disconnect()
