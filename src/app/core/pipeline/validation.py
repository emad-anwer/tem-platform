from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

_DOMAIN_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
MAX_DOMAIN_LENGTH = 253
MAX_KEYWORD_LENGTH = 255


def normalize_domain(value: str) -> str:
    v = value.strip().lower()
    if v.endswith("."):
        v = v[:-1]
    if not v:
        raise ValueError("domain must not be empty")
    if "*" in v:
        raise ValueError("wildcard domains are not allowed")
    if len(v) > MAX_DOMAIN_LENGTH:
        raise ValueError("domain exceeds maximum length")

    labels = v.split(".")
    if len(labels) < 2:
        raise ValueError("domain must have at least two labels")

    encoded_labels: list[str] = []
    for label in labels:
        if not label:
            raise ValueError("domain contains an empty label")
        try:
            encoded = label.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError(f"invalid domain label: {label!r}") from exc
        if not _DOMAIN_LABEL_RE.match(encoded):
            raise ValueError(f"invalid domain label: {label!r}")
        encoded_labels.append(encoded)

    return ".".join(encoded_labels)


def normalize_ip(value: str, *, version: int) -> str:
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise ValueError(f"invalid IP address: {value!r}") from exc
    if addr.version != version:
        raise ValueError(f"expected an IPv{version} address, got IPv{addr.version}")
    return str(addr)


def normalize_cidr(value: str) -> str:
    try:
        network = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError as exc:
        raise ValueError(f"invalid CIDR: {value!r}") from exc
    return str(network)


def normalize_keyword(value: str) -> str:
    v = " ".join(value.split()).casefold()
    if not v:
        raise ValueError("keyword must not be empty")
    if len(v) > MAX_KEYWORD_LENGTH:
        raise ValueError("keyword exceeds maximum length")
    return v


def normalize_app_store_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https"):
        raise ValueError("app_store_url must be an http(s) URL")
    if not parts.netloc:
        raise ValueError("app_store_url must include a host")
    host = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, host, path, parts.query, ""))


def normalize_target(kind: str, value: str) -> str:
    if kind == "domain":
        return normalize_domain(value)
    if kind == "ipv4":
        return normalize_ip(value, version=4)
    if kind == "ipv6":
        return normalize_ip(value, version=6)
    if kind == "cidr":
        return normalize_cidr(value)
    if kind in ("keyword", "brand_name"):
        return normalize_keyword(value)
    if kind == "app_store_url":
        return normalize_app_store_url(value)
    raise ValueError(f"unsupported target kind: {kind!r}")
