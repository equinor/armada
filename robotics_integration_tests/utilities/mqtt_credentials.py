"""Generates the MQTT credentials for one test run, so that the suite needs none
from Azure Key Vault. The broker assembles them into its configuration on
startup; see broker/entrypoint.sh in equinor/flotilla.
"""

import datetime
import secrets
from dataclasses import dataclass, field

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# Must match broker/mosquitto/config/access_control in equinor/flotilla. A user
# missing here is caught at startup: the broker refuses to run when MQTT_PASSWORDS
# does not cover every user in that file, so the drift fails the suite loudly
# rather than silently leaving a service unable to authenticate.
MQTT_USERS = ["admin", "flotilla", "isar", "analytics", "sara"]

CERTIFICATE_VALIDITY = datetime.timedelta(days=1)
KEY_SIZE = 2048


@dataclass(frozen=True)
class MqttCredentials:
    """Throwaway MQTT credentials for a single test session."""

    ca_certificate: str
    server_certificate: str
    server_key: str
    passwords: dict[str, str] = field(default_factory=dict)

    @property
    def broker_password_list(self) -> str:
        """The MQTT_PASSWORDS value the broker expects."""
        return ",".join(
            f"{user}:{password}" for user, password in self.passwords.items()
        )


def _generate_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)


def _to_pem(certificate: x509.Certificate) -> str:
    return certificate.public_bytes(serialization.Encoding.PEM).decode()


def _key_to_pem(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def generate_mqtt_credentials(broker_hostname: str) -> MqttCredentials:
    """Mint a CA, a server certificate and a password per MQTT user.

    The certificate is issued for broker_hostname, which is what ISAR verifies.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    not_valid_before = now - datetime.timedelta(minutes=5)
    not_valid_after = now + CERTIFICATE_VALIDITY

    ca_key = _generate_key()
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Armada integration tests MQTT CA")]
    )
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before)
        .not_valid_after(not_valid_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = _generate_key()
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, broker_hostname)])
        )
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before)
        .not_valid_after(not_valid_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(broker_hostname)]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    # token_hex is alphanumeric, so it cannot contain the broker's separators.
    passwords = {user: secrets.token_hex(16) for user in MQTT_USERS}

    return MqttCredentials(
        ca_certificate=_to_pem(ca_certificate),
        server_certificate=_to_pem(server_certificate),
        server_key=_key_to_pem(server_key),
        passwords=passwords,
    )
