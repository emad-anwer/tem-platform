from __future__ import annotations

import asyncio
import base64
import ssl
from dataclasses import dataclass
from typing import Any

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID

from app.core.rate_limit import SlidingWindowRateLimiter, configured_rate_limiter
from app.core.scope import ResolveFn, ScanScope, scoped_open_connection

TLS_HANDSHAKE_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True, slots=True)
class TLSCertificateObservation:
    details: dict[str, Any]
    dns_names: tuple[str, ...]


def parse_certificate(certificate_der: bytes) -> TLSCertificateObservation:
    certificate = x509.load_der_x509_certificate(certificate_der)
    common_names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    try:
        general_names = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
    except x509.ExtensionNotFound:
        general_names = x509.SubjectAlternativeName([])

    sans = [_serialize_general_name(name) for name in general_names]
    dns_names = tuple(
        name.value for name in general_names if isinstance(name, x509.DNSName)
    )
    try:
        signature_hash_algorithm = certificate.signature_hash_algorithm
    except UnsupportedAlgorithm:
        signature_hash_algorithm = None

    return TLSCertificateObservation(
        details={
            "subject_common_name": common_names[0].value if common_names else None,
            "issuer": certificate.issuer.rfc4514_string(),
            "not_valid_before_utc": certificate.not_valid_before_utc.isoformat(),
            "not_valid_after_utc": certificate.not_valid_after_utc.isoformat(),
            "sha256_fingerprint": certificate.fingerprint(hashes.SHA256()).hex(),
            "signature_algorithm": certificate.signature_algorithm_oid.dotted_string,
            "signature_hash_algorithm": (
                signature_hash_algorithm.name if signature_hash_algorithm else None
            ),
            "sans": sans,
        },
        dns_names=dns_names,
    )


async def probe_tls_certificate(
    host: str,
    port: int,
    *,
    scope: ScanScope | None = None,
    resolve: ResolveFn | None = None,
    limiter: SlidingWindowRateLimiter | None = None,
    timeout_seconds: float = TLS_HANDSHAKE_TIMEOUT_SECONDS,
) -> TLSCertificateObservation | None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    # A scanner records expired and self-signed certificates; it is not validating a client connection.
    context.verify_mode = ssl.CERT_NONE
    active_limiter = limiter or configured_rate_limiter()
    writer: asyncio.StreamWriter | None = None
    certificate_der: bytes | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            _, writer = await scoped_open_connection(
                host,
                port,
                scope=scope,
                resolve=resolve,
                limiter=active_limiter,
                ssl_context=context,
                server_hostname=host,
            )
            ssl_object = writer.get_extra_info("ssl_object")
            if ssl_object is not None:
                certificate_der = ssl_object.getpeercert(binary_form=True)
    except (OSError, TimeoutError):
        return None
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    if not certificate_der:
        return None
    try:
        return parse_certificate(certificate_der)
    except (UnsupportedAlgorithm, ValueError):
        return None


def _serialize_general_name(name: x509.GeneralName) -> dict[str, str]:
    if isinstance(name, x509.DNSName):
        return {"type": "DNS", "value": name.value}
    if isinstance(name, x509.IPAddress):
        return {"type": "IP", "value": str(name.value)}
    if isinstance(name, x509.RFC822Name):
        return {"type": "email", "value": name.value}
    if isinstance(name, x509.UniformResourceIdentifier):
        return {"type": "URI", "value": name.value}
    if isinstance(name, x509.RegisteredID):
        return {"type": "RID", "value": name.value.dotted_string}
    if isinstance(name, x509.DirectoryName):
        return {"type": "directory", "value": name.value.rfc4514_string()}
    if isinstance(name, x509.OtherName):
        return {
            "type": "otherName",
            "oid": name.type_id.dotted_string,
            "value_der_base64": base64.b64encode(name.value).decode("ascii"),
        }
    return {"type": type(name).__name__, "value": str(name.value)}
