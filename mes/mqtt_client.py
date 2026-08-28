"""MQTT publisher/subscriber adapter between PLC tags and the MES."""

from __future__ import annotations

import json
import os
import ssl
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

from machine import PLCSimulator
from .processor import EventProcessor


class MESMQTTTransport:
    def __init__(self, plc: PLCSimulator, processor: EventProcessor, host: str, port: int, prefix: str, security: dict | None = None) -> None:
        self.plc, self.processor = plc, processor
        self.host, self.port, self.prefix = host, port, prefix.rstrip("/")
        self.connected = False
        self.messages: deque[dict] = deque(maxlen=30)
        self._last_values: dict[str, object] = {}
        self.security = security or {}
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="mes-simulator")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self._configure_security()

    @staticmethod
    def _path(value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return str(path.resolve())

    def _configure_security(self) -> None:
        username = self.security.get("username", "").strip()
        password = os.getenv("MES_MQTT_PASSWORD", "")
        if username:
            if not password:
                raise ValueError("MES_MQTT_PASSWORD is required when an MQTT username is configured")
            self.client.username_pw_set(username, password)
        if self.security.get("tls_enabled"):
            ca_path = self._path(self.security["ca_certificate_path"])
            certificate = self.security.get("client_certificate_path", "").strip()
            private_key = self.security.get("client_key_path", "").strip()
            self.client.tls_set(
                ca_certs=ca_path,
                certfile=self._path(certificate) if certificate else None,
                keyfile=self._path(private_key) if private_key else None,
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            self.client.tls_insecure_set(False)

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        self.connected = reason_code == 0
        if self.connected:
            client.subscribe(f"{self.prefix}/+")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        self.connected = False

    def _on_message(self, client, userdata, message) -> None:
        payload = json.loads(message.payload.decode("utf-8"))
        tag_name, value = payload["tag"], payload["value"]
        self.messages.appendleft({"topic": message.topic, "tag": tag_name, "value": value, "time": datetime.now(timezone.utc).isoformat()})
        self.processor.process(
            tag_name,
            value,
            source="MQTT",
            delivery_payload={"tag": tag_name, "value": value},
        )

    def start(self) -> None:
        self.client.connect(self.host, self.port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()
        self.connected = False

    def publish_scan(self) -> None:
        for tag_name, value in self.plc.scan().items():
            if self._last_values.get(tag_name) == value:
                continue
            short_name = tag_name.removeprefix("Machine01.").lower()
            self.client.publish(f"{self.prefix}/{short_name}", json.dumps({"tag": tag_name, "value": value}))
            self._last_values[tag_name] = value
