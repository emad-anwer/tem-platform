"""W4-02 — default-deny scan scope (issue #94).

The five tests the task specifies, plus the edges that make "mechanism, not
convention" checkable: what the API surfaces, what the worker logs, and what
the socket layer actually connects to. DNS is never touched — resolvers are
passed explicitly or come from the conftest stand-in.
"""

from __future__ import annotations

import asyncio
import ipaddress
from pathlib import Path

import dns.resolver
import httpx
import pytest

from app.core import scope as scope_module
from app.core.config import get_settings
from app.core.errors import ForbiddenError
from app.core.jobs.lifecycle import classify_failure, scrub_failure_message
from app.core.scope import (
    ScanScope,
    ScopedAsyncHTTPTransport,
    ScopeReason,
    ScopeViolationError,
    check_scope,
    get_scope,
    parse_scope_entry,
    scoped_http_client,
    scoped_open_connection,
)


def resolver(*addresses: str):
    """A recording stand-in for DNS: returns ``addresses``, remembers calls."""

    calls: list[str] = []

    async def _resolve(hostname: str) -> list[ipaddress.IPv4Address]:
        calls.append(hostname)
        return [ipaddress.ip_address(address) for address in addresses]

    _resolve.calls = calls
    return _resolve


# ------------------------------------------------------------------
# 1. Empty allowlist scans nothing (with the inversion guarded).
# ------------------------------------------------------------------


async def test_empty_allowlist_refuses_every_target() -> None:
    empty = ScanScope.parse([])
    assert empty.is_empty
    resolve = resolver("203.0.113.10")

    for target in (
        "scan-me.example.com",
        "lab-nginx",
        "203.0.113.10",
        "10.1.2.3",
        "127.0.0.1",
    ):
        with pytest.raises(ScopeViolationError) as exc_info:
            await check_scope(target, scope=empty, resolve=resolve)
        assert exc_info.value.reason is ScopeReason.EMPTY_ALLOWLIST
    assert resolve.calls == []

    # Inversion guard: once the very same targets are listed, they pass. If
    # anyone flips the condition ("empty allows, listed refuses"), one of the
    # two halves above/below fails.
    listed = ScanScope.parse(
        ["scan-me.example.com", "203.0.113.0/24", "127.0.0.1:8081"]
    )
    allowed = await check_scope(
        "scan-me.example.com", scope=listed, resolve=resolver("203.0.113.10")
    )
    assert [str(address) for address in allowed.addresses] == ["203.0.113.10"]
    loopback = await check_scope(
        "127.0.0.1", port=8081, scope=listed, resolve=resolver()
    )
    assert [str(address) for address in loopback.addresses] == ["127.0.0.1"]


async def test_settings_allowlist_drives_the_default_scope(monkeypatch) -> None:
    """The scope check reads configuration, not a hard-coded list."""
    monkeypatch.setenv("SCAN_SCOPE_ALLOWLIST", "")
    get_settings.cache_clear()

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope("scan-me.example.com", resolve=resolver("203.0.113.10"))
    assert exc_info.value.reason is ScopeReason.EMPTY_ALLOWLIST

    monkeypatch.setenv("SCAN_SCOPE_ALLOWLIST", "lab-nginx, 10.0.0.0/8 ")
    get_settings.cache_clear()
    scope = get_scope()
    assert [entry.raw.strip() for entry in scope.entries] == [
        "lab-nginx",
        "10.0.0.0/8",
    ]


def test_get_scope_rejects_malformed_entries(monkeypatch) -> None:
    monkeypatch.setenv("SCAN_SCOPE_ALLOWLIST", "lab-nginx, not a host!!")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="scope entry"):
        get_scope()


def test_shipped_default_allowlist_lists_every_lab_service() -> None:
    """W4-02's failure signal: deleting a lab entry from the committed default
    (`.env.example`) breaks this suite instead of quietly un-scanning the lab."""
    env_example = Path(__file__).resolve().parents[2] / ".env.example"
    allowlist_lines = [
        line
        for line in env_example.read_text().splitlines()
        if line.startswith("SCAN_SCOPE_ALLOWLIST=")
    ]
    assert len(allowlist_lines) == 1, "exactly one SCAN_SCOPE_ALLOWLIST entry"

    entries = [part.strip() for part in allowlist_lines[0].partition("=")[2].split(",")]
    ScanScope.parse(entries)  # the shipped default must parse
    assert entries == [
        "lab-nginx",
        "lab-apache",
        "lab-nonstandard",
        "lab-tls-san",
    ]


# ------------------------------------------------------------------
# 2. Resolve first, decide on the address, hand the address back.
# ------------------------------------------------------------------


async def test_scope_resolves_then_decides_and_returns_the_address() -> None:
    scope = ScanScope.parse(["203.0.113.0/24"])
    resolve = resolver("203.0.113.10")

    decision = await check_scope("scan-me.example.com", scope=scope, resolve=resolve)

    assert resolve.calls == ["scan-me.example.com"]
    assert decision.host == "scan-me.example.com"
    assert [str(address) for address in decision.addresses] == ["203.0.113.10"]


async def test_decision_is_on_the_resolved_address_not_the_name() -> None:
    scope = ScanScope.parse(["203.0.113.0/24"])
    resolve = resolver("198.51.100.7")

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope("scan-me.example.com", scope=scope, resolve=resolve)

    assert exc_info.value.reason is ScopeReason.ADDRESS_NOT_ALLOWLISTED
    assert exc_info.value.resolved == (ipaddress.ip_address("198.51.100.7"),)


async def test_hostname_entry_authorizes_the_addresses_it_resolves_to() -> None:
    """The lab rule: listing `lab-nginx` is the explicit listing of where it
    resolves to (an RFC1918 compose address) — nothing else needs listing."""
    scope = ScanScope.parse(["lab-nginx"])
    decision = await check_scope(
        "lab-nginx", scope=scope, resolve=resolver("172.18.0.5")
    )
    assert [str(address) for address in decision.addresses] == ["172.18.0.5"]


async def test_ip_literal_scope_check_never_resolves() -> None:
    scope = ScanScope.parse(["203.0.113.0/24"])
    resolve = resolver("203.0.113.10")

    decision = await check_scope("203.0.113.10", scope=scope, resolve=resolve)

    assert resolve.calls == []
    assert [str(address) for address in decision.addresses] == ["203.0.113.10"]


async def test_cidr_entry_permits_addresses_inside_and_refuses_ones_outside() -> None:
    scope = ScanScope.parse(["203.0.113.0/24"])

    inside = await check_scope("203.0.113.77", scope=scope, resolve=resolver())
    assert [str(address) for address in inside.addresses] == ["203.0.113.77"]

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope("198.51.100.7", scope=scope, resolve=resolver())
    assert exc_info.value.reason is ScopeReason.ADDRESS_NOT_ALLOWLISTED


# ------------------------------------------------------------------
# 3. Unconditional blocks beat the allowlist.
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [
        "169.254.169.254",  # cloud metadata address, in particular
        "169.254.1.1",
        "224.0.0.1",  # multicast
        "0.0.0.0",  # unspecified
        "fe80::1",  # IPv6 link-local
        "ff02::1",  # IPv6 multicast
    ],
)
async def test_blocked_ranges_win_over_the_allowlist(target: str) -> None:
    scope = ScanScope.parse(
        ["169.254.0.0/16", "169.254.169.254", "224.0.0.0/4", "fe80::/10", "0.0.0.0/8"]
    )

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope(target, scope=scope, resolve=resolver("203.0.113.10"))

    assert exc_info.value.reason is ScopeReason.BLOCKED_RANGE


async def test_blocked_range_wins_through_a_listed_hostname_too() -> None:
    scope = ScanScope.parse(["metadata.lab", "169.254.0.0/16"])

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope(
            "metadata.lab", scope=scope, resolve=resolver("169.254.169.254")
        )
    assert exc_info.value.reason is ScopeReason.BLOCKED_RANGE

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope("169.254.0.0/16", scope=scope, resolve=resolver())
    assert exc_info.value.reason is ScopeReason.BLOCKED_RANGE


# ------------------------------------------------------------------
# 4. Loopback needs a port-qualified entry.
# ------------------------------------------------------------------


async def test_loopback_refused_without_a_port_qualified_entry() -> None:
    scope = ScanScope.parse(["127.0.0.1", "203.0.113.0/24"])

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope("127.0.0.1", scope=scope, resolve=resolver())

    assert exc_info.value.reason is ScopeReason.LOOPBACK_PORT_NOT_ALLOWED


async def test_loopback_allowed_only_on_the_listed_port() -> None:
    scope = ScanScope.parse(["127.0.0.1:8081", "[::1]:8081"])

    decision = await check_scope(
        "127.0.0.1", port=8081, scope=scope, resolve=resolver()
    )
    assert [str(address) for address in decision.addresses] == ["127.0.0.1"]
    decision_v6 = await check_scope("::1", port=8081, scope=scope, resolve=resolver())
    assert [str(address) for address in decision_v6.addresses] == ["::1"]

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope("127.0.0.1", port=9090, scope=scope, resolve=resolver())
    assert exc_info.value.reason is ScopeReason.LOOPBACK_PORT_NOT_ALLOWED


# ------------------------------------------------------------------
# 5. Refusal is a 403 and a structured log.
# ------------------------------------------------------------------


async def test_refusal_is_a_403_with_a_structured_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Capture the module's own warning call rather than structlog's global
    # pipeline: `setup_logging()` builds a fresh processor list on every
    # `create_app()`, so `capture_logs()` only reaches a module logger whose
    # first use happened after the last reconfigure — unrunnable here.
    class _Recorder:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def warning(self, event: str, **fields: object) -> None:
            self.calls.append((event, fields))

    recorder = _Recorder()
    monkeypatch.setattr(scope_module, "logger", recorder)

    scope = ScanScope.parse(["203.0.113.0/24"])

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope(
            "scan-me.example.com", scope=scope, resolve=resolver("198.51.100.7")
        )

    error = exc_info.value
    assert isinstance(error, ForbiddenError)
    assert error.status_code == 403
    # One 403 slug in the problem registry — scope refusals ride `forbidden`
    # rather than stealing it from permission checks.
    assert error.slug == "forbidden"

    refusals = [
        fields for event, fields in recorder.calls if event == "scan.scope_refused"
    ]
    assert len(refusals) == 1
    assert refusals[0]["reason"] == "address_not_allowlisted"
    assert refusals[0]["target"] == "scan-me.example.com"
    assert refusals[0]["resolved"] == ["198.51.100.7"]


def test_scope_failure_in_a_job_is_terminal_and_scrubbed() -> None:
    error = ScopeViolationError(
        "detail that must not be stored",
        reason=ScopeReason.BLOCKED_RANGE,
        host="169.254.169.254",
        resolved=[ipaddress.ip_address("169.254.169.254")],
    )

    assert classify_failure(error) == "terminal"
    assert (
        scrub_failure_message(error, error_kind="terminal")
        == "terminal: target outside scan scope (blocked_range)"
    )


# ------------------------------------------------------------------
# Fail-closed edges: DNS problems, unlisted names, junk targets.
# ------------------------------------------------------------------


async def test_resolution_failure_fails_closed() -> None:
    scope = ScanScope.parse(["lab-nginx", "203.0.113.0/24"])

    async def unreachable(hostname: str):
        raise dns.resolver.NXDOMAIN

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope("lab-nginx", scope=scope, resolve=unreachable)
    assert exc_info.value.reason is ScopeReason.RESOLUTION_FAILED

    async def empty_answer(hostname: str):
        return []

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope("lab-nginx", scope=scope, resolve=empty_answer)
    assert exc_info.value.reason is ScopeReason.RESOLUTION_FAILED


async def test_unlisted_hostname_is_refused_without_touching_dns() -> None:
    scope = ScanScope.parse(["lab-nginx"])
    resolve = resolver("203.0.113.10")

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope("evil.example.com", scope=scope, resolve=resolve)

    assert exc_info.value.reason is ScopeReason.HOSTNAME_NOT_ALLOWLISTED
    assert resolve.calls == []


@pytest.mark.parametrize(
    "target",
    ["https://example.com/path", "..", "-bad-.example.com", ""],
)
async def test_unparseable_targets_are_refused(target: str) -> None:
    scope = ScanScope.parse(["lab-nginx", "203.0.113.0/24"])
    resolve = resolver("203.0.113.10")

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope(target, scope=scope, resolve=resolve)

    assert exc_info.value.reason is ScopeReason.INVALID_TARGET
    assert resolve.calls == []


async def test_cidr_targets_must_sit_inside_an_allowlisted_network() -> None:
    scope = ScanScope.parse(["10.0.0.0/8"])

    decision = await check_scope("10.1.2.0/24", scope=scope, resolve=resolver())
    assert decision.host == "10.1.2.0/24"

    with pytest.raises(ScopeViolationError) as exc_info:
        await check_scope("172.16.0.0/12", scope=scope, resolve=resolver())
    assert exc_info.value.reason is ScopeReason.ADDRESS_NOT_ALLOWLISTED


# ------------------------------------------------------------------
# Entry parsing and the W4-04 connection seam.
# ------------------------------------------------------------------


def test_scope_entry_parsing_covers_the_documented_forms() -> None:
    assert parse_scope_entry("lab-nginx").hostname == "lab-nginx"
    assert parse_scope_entry("Example.COM.").hostname == "example.com"
    assert str(parse_scope_entry("203.0.113.5").address) == "203.0.113.5"
    assert parse_scope_entry("10.0.0.0/8").network.prefixlen == 8
    assert parse_scope_entry("127.0.0.1:8081").port == 8081
    bracketed = parse_scope_entry("[::1]:8081")
    assert str(bracketed.address) == "::1"
    assert bracketed.port == 8081

    for bad in (
        "",
        "10.0.0.0/8:80",
        "127.0.0.1:0",
        "127.0.0.1:70000",
        "[::1]",
        "not a host!!",
    ):
        with pytest.raises(ValueError):
            parse_scope_entry(bad)


async def test_scoped_open_connection_connects_to_the_checked_address(
    monkeypatch,
) -> None:
    scope = ScanScope.parse(["203.0.113.0/24"])
    resolve = resolver("203.0.113.10")
    opened: list[tuple[str, int]] = []

    async def fake_open_connection(host: str, port: int):
        opened.append((host, port))
        raise ConnectionRefusedError("stop after the address is chosen")

    monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)

    with pytest.raises(ConnectionRefusedError):
        await scoped_open_connection(
            "scan-me.example.com", 443, scope=scope, resolve=resolve
        )

    # Connects to the address the scope check approved, and resolves exactly
    # once — the connection never asks DNS again (DNS-rebinding).
    assert opened == [("203.0.113.10", 443)]
    assert resolve.calls == ["scan-me.example.com"]


async def test_scoped_open_connection_refuses_before_touching_a_socket(
    monkeypatch,
) -> None:
    opened: list[tuple[str, int]] = []

    async def fake_open_connection(host: str, port: int):  # pragma: no cover
        opened.append((host, port))
        raise AssertionError("no socket may be opened for an out-of-scope target")

    monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)

    with pytest.raises(ScopeViolationError) as exc_info:
        await scoped_open_connection(
            "evil.example.com",
            443,
            scope=ScanScope.parse(["203.0.113.0/24"]),
            resolve=resolver("198.51.100.7"),
        )

    assert exc_info.value.reason is ScopeReason.ADDRESS_NOT_ALLOWLISTED
    assert opened == []


# ------------------------------------------------------------------
# The HTTP connection layer: the same mechanism, for W4-06.
# ------------------------------------------------------------------


class _RecordingTransport(httpx.AsyncBaseTransport):
    """Inner transport stand-in: remembers requests, never touches the net."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, request=request)


async def test_http_transport_refuses_before_any_connection() -> None:
    inner = _RecordingTransport()
    transport = ScopedAsyncHTTPTransport(scope=ScanScope.parse([]), transport=inner)

    with pytest.raises(ScopeViolationError) as exc_info:
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("https://scan-me.example.com/")

    assert exc_info.value.reason is ScopeReason.EMPTY_ALLOWLIST
    # Assert on the mock, not on the result: the refusal path never reaches a
    # connection — no upper layer was involved, the gate held at the seam.
    assert inner.requests == []


async def test_http_transport_pins_the_request_to_the_checked_address() -> None:
    inner = _RecordingTransport()
    # Default scope (the pinned test allowlist) plus the offline resolver the
    # conftest installs — lab-nginx resolves to 203.0.113.10, in the CIDR.
    transport = ScopedAsyncHTTPTransport(transport=inner)

    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://lab-nginx/health")

    assert response.status_code == 200
    [request] = inner.requests
    # The socket would go to the address scope checked; the name survives as
    # SNI and Host, so TLS and virtual hosting still see lab-nginx — httpx
    # never resolves it a second time (DNS rebinding).
    assert request.url.host == "203.0.113.10"
    assert request.url.path == "/health"
    assert request.extensions["sni_hostname"] == "lab-nginx"
    assert request.headers["host"] == "lab-nginx"


async def test_http_transport_refuses_an_unlisted_address() -> None:
    inner = _RecordingTransport()
    transport = ScopedAsyncHTTPTransport(transport=inner)

    with pytest.raises(ScopeViolationError) as exc_info:
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("http://198.51.100.7/")

    assert exc_info.value.reason is ScopeReason.ADDRESS_NOT_ALLOWLISTED
    assert inner.requests == []


async def test_http_transport_enforces_the_loopback_port_rule() -> None:
    inner = _RecordingTransport()
    transport = ScopedAsyncHTTPTransport(transport=inner)

    with pytest.raises(ScopeViolationError) as exc_info:
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("http://127.0.0.1:8080/")
    assert exc_info.value.reason is ScopeReason.LOOPBACK_PORT_NOT_ALLOWED
    assert inner.requests == []

    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("http://127.0.0.1:8081/")
    assert response.status_code == 200
    assert len(inner.requests) == 1


async def test_scoped_http_client_carries_the_gate(monkeypatch) -> None:
    monkeypatch.setenv("SCAN_SCOPE_ALLOWLIST", "")
    get_settings.cache_clear()

    with pytest.raises(ScopeViolationError) as exc_info:
        async with scoped_http_client() as client:
            await client.get("https://scan-me.example.com/")

    assert exc_info.value.reason is ScopeReason.EMPTY_ALLOWLIST
