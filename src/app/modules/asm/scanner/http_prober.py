"""Bounded, scope-safe HTTP service probing for open TCP ports."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import structlog

from app.core.jobs.timeouts import outbound_http_timeout
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.scope import (
    ScanScope,
    ScopeViolationError,
    check_scope,
    scoped_http_client,
)

logger = structlog.get_logger(__name__)

# These caps are deliberately local to parsing hostile responses, not network timeouts.
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 64 * 1024
MAX_TITLE_LENGTH = 512
MAX_HEADER_VALUE_LENGTH = 4 * 1024
MAX_COOKIE_NAME_LENGTH = 256

_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class FingerprintRule:
    signal: str
    pattern: re.Pattern[str]
    technology: str
    confidence: str


# A table makes additions auditable and ensures every applicable rule is evaluated.
FINGERPRINT_RULES: tuple[FingerprintRule, ...] = (
    FingerprintRule(
        "server", re.compile(r"nginx(?:/([\d.]+))?", re.IGNORECASE), "nginx", "high"
    ),
    FingerprintRule(
        "server",
        re.compile(r"apache(?:/([\d.]+))?", re.IGNORECASE),
        "Apache HTTP Server",
        "high",
    ),
    FingerprintRule(
        "x-powered-by", re.compile(r"PHP(?:/([\d.]+))?", re.IGNORECASE), "PHP", "high"
    ),
    FingerprintRule(
        "body", re.compile(r"wp-content", re.IGNORECASE), "WordPress", "low"
    ),
)


@dataclass(frozen=True, slots=True)
class HTTPService:
    scheme: str
    host: str
    port: int
    status_code: int
    final_url: str
    title: str | None
    headers: dict[str, str]
    cookie_names: tuple[str, ...]
    technologies: tuple[dict[str, str], ...]
    body_truncated: bool
    redirects_followed: int

    @property
    def value(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


def _bounded(value: str, limit: int) -> str:
    return value[:limit]


def _retained_headers(headers: httpx.Headers) -> dict[str, str]:
    kept: dict[str, str] = {}
    for name in ("Server", "X-Powered-By", "Content-Type"):
        value = headers.get(name)
        if value is not None:
            kept[name] = _bounded(value, MAX_HEADER_VALUE_LENGTH)
    return kept


def _cookie_names(headers: httpx.Headers) -> tuple[str, ...]:
    names: list[str] = []
    for raw in headers.get_list("set-cookie"):
        # Only text before the first '=' is a cookie name.  Do not retain raw.
        name = raw.split(";", 1)[0].split("=", 1)[0].strip()
        if name and name not in names:
            names.append(_bounded(name, MAX_COOKIE_NAME_LENGTH))
    return tuple(names)


def _title(body: bytes) -> str | None:
    # Replacement decoding means malformed bytes cannot escape this parser.
    match = _TITLE_RE.search(body.decode("utf-8", errors="replace"))
    if match is None:
        return None
    return _bounded(match.group(1).strip(), MAX_TITLE_LENGTH)


def _fingerprints(headers: dict[str, str], body: bytes) -> tuple[dict[str, str], ...]:
    signals = {key.lower(): value for key, value in headers.items()}
    signals["body"] = body.decode("utf-8", errors="replace")
    matches: list[dict[str, str]] = []
    for rule in FINGERPRINT_RULES:
        signal = signals.get(rule.signal)
        if signal is None:
            continue
        for match in rule.pattern.finditer(signal):
            claim = {
                "technology": rule.technology,
                "confidence": rule.confidence,
                "evidence": _bounded(match.group(0), MAX_HEADER_VALUE_LENGTH),
                "signal": rule.signal,
            }
            if match.lastindex and match.group(1):
                claim["version"] = _bounded(match.group(1), 128)
            matches.append(claim)
    return tuple(matches)


async def _read_bounded(response: httpx.Response) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    remaining = MAX_BODY_BYTES
    truncated = False
    async for chunk in response.aiter_bytes():
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            truncated = True
            break
        chunks.append(chunk)
        remaining -= len(chunk)
        if remaining == 0:
            truncated = True
            break
    return b"".join(chunks), truncated


def _redirect_destination(current: str, location: str) -> str | None:
    try:
        parsed = urlsplit(urljoin(current, location))
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    # Location is hostile input. Userinfo can be a credential and must never
    # reach an outbound request, a finding, or a log line.
    host = parsed.hostname
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))


async def probe_http_service(
    host: str,
    port: int,
    *,
    scheme: str = "http",
    scope: ScanScope | None = None,
    limiter: SlidingWindowRateLimiter | None = None,
    max_redirects: int = MAX_REDIRECTS,
    client_factory: Callable[..., httpx.AsyncClient] = scoped_http_client,
) -> HTTPService | None:
    """Probe one endpoint. Protocol errors are normal negative results."""
    if scheme not in {"http", "https"}:
        raise ValueError("scheme must be http or https")
    if max_redirects < 0:
        raise ValueError("max_redirects must not be negative")

    current = f"{scheme}://{host}:{port}/"
    redirects = 0
    try:
        async with client_factory(
            scope=scope,
            limiter=limiter,
            timeout=outbound_http_timeout(),
            follow_redirects=False,
            # The target lab intentionally uses a self-signed TLS certificate.
            verify=False,
        ) as client:
            while True:
                async with client.stream("GET", current) as response:
                    body, truncated = await _read_bounded(response)
                    headers = _retained_headers(response.headers)
                    status_code = response.status_code
                    location = response.headers.get("location")

                if not (
                    300 <= status_code < 400 and location and redirects < max_redirects
                ):
                    break
                destination = _redirect_destination(current, location)
                if destination is None:
                    break
                parsed = urlsplit(destination)
                try:
                    await check_scope(
                        parsed.hostname or "",
                        port=parsed.port or (443 if parsed.scheme == "https" else 80),
                        scope=scope,
                    )
                except ScopeViolationError:
                    # This response is still a useful service observation; the hop is not.
                    break
                current = destination
                redirects += 1
    except (httpx.HTTPError, ScopeViolationError, OSError, ValueError):
        # An open TCP port that is not HTTP is expected scanner input.
        return None

    return HTTPService(
        scheme=scheme,
        host=host,
        port=port,
        status_code=status_code,
        final_url=current,
        title=_title(body),
        headers=headers,
        cookie_names=_cookie_names(response.headers),
        technologies=_fingerprints(headers, body),
        body_truncated=truncated,
        redirects_followed=redirects,
    )


async def probe_open_ports(
    host: str,
    ports: Iterable[int],
    *,
    scope: ScanScope | None = None,
    limiter: SlidingWindowRateLimiter | None = None,
) -> list[HTTPService]:
    """Probe all open ports, with HTTPS fallback for TLS-speaking services."""
    findings: list[HTTPService] = []
    for port in ports:
        result = await probe_http_service(host, port, scope=scope, limiter=limiter)
        # nginx (and some proxies) can answer a plaintext request on a TLS
        # socket with a 400.  It is not an HTTP service observation; retry it
        # as TLS so the service identity and title are accurate.
        needs_tls_retry = (
            result is not None
            and result.status_code == 400
            and result.title is not None
            and "plain http request was sent to https port" in result.title.lower()
        )
        if result is None or needs_tls_retry:
            tls_result = await probe_http_service(
                host, port, scheme="https", scope=scope, limiter=limiter
            )
            if tls_result is not None:
                result = tls_result
        if result is not None:
            findings.append(result)
    return findings
