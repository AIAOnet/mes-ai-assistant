import os
import unittest
from unittest.mock import MagicMock, patch

from machine import MachineSimulator, PLCSimulator
from mes.main import build_processor
from mes.mqtt_client import MESMQTTTransport


class MQTTTransportSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plc = PLCSimulator(MachineSimulator())
        self.processor = build_processor(persist=False)

    @patch("mes.mqtt_client.mqtt.Client")
    def test_tls_and_credentials_are_applied(self, client_factory) -> None:
        client = client_factory.return_value
        security = {"tls_enabled": True, "username": "mes-client", "ca_certificate_path": "certs/mqtt/mqtt-ca.crt", "client_certificate_path": "certs/mqtt/mqtt-client.crt", "client_key_path": "certs/mqtt/mqtt-client.key"}
        with patch.dict(os.environ, {"MES_MQTT_PASSWORD": "secret"}):
            MESMQTTTransport(self.plc, self.processor, "127.0.0.1", 8883, "factory/test", security)
        client.username_pw_set.assert_called_once_with("mes-client", "secret")
        client.tls_set.assert_called_once()
        client.tls_insecure_set.assert_called_once_with(False)

    @patch("mes.mqtt_client.mqtt.Client", return_value=MagicMock())
    def test_username_without_password_fails_closed(self, _client_factory) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "MES_MQTT_PASSWORD"):
                MESMQTTTransport(self.plc, self.processor, "127.0.0.1", 8883, "factory/test", {"username": "mes-client"})


if __name__ == "__main__":
    unittest.main()
