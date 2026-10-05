from __future__ import annotations

import asyncio
import ipaddress
import ssl
import time
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.scope import ScanScope
from app.modules.asm.scanner.tls_certificate import probe_tls_certificate


class _AllowAllRedis:
    async def eval(self, *_args):
        return [1, 0]


def _write_certificate(tmp_path, *, expires_in_days: int):
    now = datetime.now(UTC)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TEM-Platform"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Target-Lab"),
            x509.NameAttribute(NameOID.COMMON_NAME, "target4.lab.local"),
        ]
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before((now - timedelta(days=30)).replace(tzinfo=None))
        .not_valid_after((now + timedelta(days=expires_in_days)).replace(tzinfo=None))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("target4.lab.local"),
                    x509.DNSName("sub1.target4.lab.local"),
                    x509.DNSName("api.target4.lab.local"),
                    x509.DNSName("admin.internal.tem.local"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certificate_path = tmp_path / "server.crt"
    private_key_path = tmp_path / "server.key"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private_key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, private_key_path


async def _probe_local_certificate(tmp_path, *, expires_in_days: int):
    certificate_path, private_key_path = _write_certificate(
        tmp_path, expires_in_days=expires_in_days
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificate_path, private_key_path)

    async def close_connection(_reader, writer):
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(
        close_connection, "127.0.0.1", 0, ssl=server_context
    )
    port = server.sockets[0].getsockname()[1]
    scope = ScanScope.parse([f"127.0.0.1:{port}"])
    limiter = SlidingWindowRateLimiter(redis=_AllowAllRedis())
    try:
        return await probe_tls_certificate(
            "127.0.0.1",
            port,
            scope=scope,
            limiter=limiter,
            timeout_seconds=1.0,
        )
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_probe_parses_self_signed_certificate_and_all_sans(tmp_path):
    observation = await _probe_local_certificate(tmp_path, expires_in_days=30)

    assert observation is not None
    assert observation.details["subject_common_name"] == "target4.lab.local"
    assert "CN=target4.lab.local" in observation.details["issuer"]
    assert observation.details["not_valid_before_utc"].endswith("+00:00")
    assert observation.details["not_valid_after_utc"].endswith("+00:00")
    assert len(observation.details["sha256_fingerprint"]) == 64
    assert observation.details["signature_algorithm"] == "1.2.840.113549.1.1.11"
    assert observation.details["sans"] == [
        {"type": "DNS", "value": "target4.lab.local"},
        {"type": "DNS", "value": "sub1.target4.lab.local"},
        {"type": "DNS", "value": "api.target4.lab.local"},
        {"type": "DNS", "value": "admin.internal.tem.local"},
        {"type": "IP", "value": "127.0.0.1"},
    ]
    assert observation.dns_names == (
        "target4.lab.local",
        "sub1.target4.lab.local",
        "api.target4.lab.local",
        "admin.internal.tem.local",
    )


@pytest.mark.asyncio
async def test_expired_certificate_is_still_returned_as_a_finding_observation(tmp_path):
    observation = await _probe_local_certificate(tmp_path, expires_in_days=-1)

    assert observation is not None
    assert datetime.fromisoformat(
        observation.details["not_valid_after_utc"]
    ) < datetime.now(UTC)


@pytest.mark.asyncio
async def test_plain_http_port_is_not_classified_as_tls_or_allowed_to_hang():
    async def respond_with_http(reader, writer):
        try:
            await reader.read(5)
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        except (ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(respond_with_http, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    scope = ScanScope.parse([f"127.0.0.1:{port}"])
    limiter = SlidingWindowRateLimiter(redis=_AllowAllRedis())
    started = time.monotonic()
    try:
        async with asyncio.timeout(1.0):
            observation = await probe_tls_certificate(
                "127.0.0.1",
                port,
                scope=scope,
                limiter=limiter,
                timeout_seconds=0.8,
            )
    finally:
        server.close()
        await server.wait_closed()

    assert observation is None
    assert time.monotonic() - started < 1.0
