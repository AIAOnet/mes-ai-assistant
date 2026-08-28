"""Generate learning-environment OPC UA application certificates."""

from __future__ import annotations

import asyncio
import shutil
import socket
from pathlib import Path

from asyncua.crypto import cert_gen
from cryptography.x509.oid import ExtendedKeyUsageOID

ROOT = Path(__file__).resolve().parents[1]
CERTS = ROOT / "certs" / "opc"


async def generate() -> None:
    CERTS.mkdir(parents=True, exist_ok=True)
    server_key, server_cert = CERTS / "server.pem", CERTS / "server.der"
    client_key, client_cert = CERTS / "client.pem", CERTS / "client.der"
    host = socket.gethostname()
    await cert_gen.setup_self_signed_certificate(server_key, server_cert, "urn:mes-simulator:opc-server", host, [ExtendedKeyUsageOID.SERVER_AUTH], {"organizationName": "MES Learning"})
    await cert_gen.setup_self_signed_certificate(client_key, client_cert, "urn:mes-simulator:mes-client", host, [ExtendedKeyUsageOID.CLIENT_AUTH], {"organizationName": "MES Learning"})
    trust = CERTS / "trusted"
    trust.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(server_cert, trust / "server.der")
    shutil.copyfile(client_cert, trust / "client.der")


if __name__ == "__main__":
    asyncio.run(generate())
