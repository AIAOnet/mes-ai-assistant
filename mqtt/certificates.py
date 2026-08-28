"""Generate a local CA and MQTT server/client certificates for the learning broker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parents[1]
CERTS = ROOT / "certs" / "mqtt"


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MES Learning"), x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def generate() -> None:
    CERTS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ca_key = _key()
    ca_name = _name("MES Learning MQTT CA")
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=3650)).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True).add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False).add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False).sign(ca_key, hashes.SHA256()))

    def issue(common_name: str, usage: x509.ObjectIdentifier, san: x509.SubjectAlternativeName | None = None):
        key = _key()
        builder = (x509.CertificateBuilder().subject_name(_name(common_name)).issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=825)).add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True).add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True).add_extension(x509.ExtendedKeyUsage([usage]), critical=False).add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False).add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False))
        if san:
            builder = builder.add_extension(san, critical=False)
        return key, builder.sign(ca_key, hashes.SHA256())

    server_key, server = issue("localhost", ExtendedKeyUsageOID.SERVER_AUTH, x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ip_address("127.0.0.1")), x509.DNSName("mqtt-broker")]))
    client_key, client = issue("mes-client", ExtendedKeyUsageOID.CLIENT_AUTH)
    _write_key(CERTS / "mqtt-ca.key", ca_key)
    _write_key(CERTS / "mqtt-server.key", server_key)
    _write_key(CERTS / "mqtt-client.key", client_key)
    (CERTS / "mqtt-ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (CERTS / "mqtt-server.crt").write_bytes(server.public_bytes(serialization.Encoding.PEM))
    (CERTS / "mqtt-client.crt").write_bytes(client.public_bytes(serialization.Encoding.PEM))


if __name__ == "__main__":
    generate()
