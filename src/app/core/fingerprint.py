"""Shared finding identity and canonicalization rules."""

import hashlib
from enum import StrEnum
from urllib.parse import urlsplit


class FindingKind(StrEnum):
    SUBDOMAIN = "subdomain"
    OPEN_PORT = "open_port"
    HTTP_SERVICE = "http_service"
    TLS_CERTIFICATE = "tls_certificate"


def normalize_finding_value(kind: FindingKind, value: str) -> str:
    """Return the canonical identity value for a finding kind."""
    kind = FindingKind(kind)
    if not isinstance(value, str):
        raise TypeError("finding value must be a string")

    if kind is FindingKind.SUBDOMAIN:
        return value.strip().encode("idna").decode("ascii").lower().rstrip(".")

    if kind is FindingKind.OPEN_PORT:
        host, separator, port_protocol = value.rpartition(":")
        if not separator:
            raise ValueError("open_port value must be host:port/protocol")
        port_text, slash, protocol = port_protocol.partition("/")
        if not slash or not port_text.isdecimal() or not protocol:
            raise ValueError("open_port value must be host:port/protocol")
        return f"{_normalize_host(host)}:{int(port_text)}/{protocol.lower()}"

    if kind is FindingKind.HTTP_SERVICE:
        parts = urlsplit(value)
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("http_service value must be an absolute HTTP URL")
        host = _normalize_host(parts.hostname)
        port = parts.port
        if port is None:
            raise ValueError("http_service value must include a port")
        return f"{scheme}://{host}:{port}"

    if kind is FindingKind.TLS_CERTIFICATE:
        host, separator, port_text = value.rpartition(":")
        if not separator or not port_text.isdecimal():
            raise ValueError("tls_certificate value must be host:port")
        return f"{_normalize_host(host)}:{int(port_text)}"

    raise ValueError(f"unsupported finding kind: {kind}")


def compute_fingerprint(
    kind: FindingKind, target_id: object, value_normalized: str
) -> str:
    """Hash kind, target, and canonical identity value using ADR-0004's tuple."""
    kind = FindingKind(kind)
    identity = f"{kind}|{target_id}|{value_normalized}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _normalize_host(host: str) -> str:
    return host.strip().encode("idna").decode("ascii").lower().rstrip(".")
