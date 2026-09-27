"""Default-deny scan scope: where the platform is allowed to connect.

W4-02 (issue #94). A connect scanner pointed at the wrong address is not a bug
you get to explain afterwards, so this decides *before* W4-04 exists where any
scanner may point — and it is a **mechanism**, not a convention.

**Defense in depth, connection layer first.** Three layers refuse, each
catching a different mistake:

1. *The connection layer is the foundation.* Nothing in this platform opens a
   socket to a scan target except through this module —
   :func:`scoped_open_connection` for TCP (the seam W4-04 connects through)
   and :class:`ScopedAsyncHTTPTransport` / :func:`scoped_http_client` for
   HTTP (W4-06's). Both decide **at the moment the connection is about to
   open**: there is no "call ``check_scope()`` first" rule above them to
   forget — the argument W2-07 made about ``TenantScopedRepository`` and
   tenant IDs — and both hand the connection the *checked* address instead of
   resolving again, which is the DNS-rebinding answer: a name approved now
   must not re-resolve into something else half a second later.
2. *The worker layer.* ``discover_domain`` re-checks before any work runs, so
   a job queued (or replayed) against a now-refused target fails loud and
   terminal instead of scanning.
3. *The API layer.* ``start_scan`` answers ``403`` with a reason before a run
   row exists — the good error early, nothing enqueued.

:func:`check_scope` is the one decision all of them share: it resolves first,
decides on the *address*, and hands the caller the resolved addresses back.
Scope governs connections to **scan targets**; scanner infrastructure — the
resolver, crt.sh, the platform's own APIs — is not target traffic and does
not go through these gates.

Rules, in order:

1. An **empty allowlist refuses everything** — not "everything", not
   "localhost by accident": nothing. Fail closed, always.
2. **Unconditional blocks** win over every allowlist entry: link-local
   (``169.254.0.0/16`` and ``169.254.169.254`` in particular), IPv6 link-local,
   multicast, unspecified and reserved ranges.
3. **Loopback is port-qualified.** The lab is reachable on loopback from a
   laptop, so loopback is allowed only by entries that name a port
   (``127.0.0.1:8081``) — never by a bare ``127.0.0.1``.
4. Everything else must be **listed**: an IP/CIDR entry covers its addresses, a
   hostname entry covers that name and the addresses it resolves to (which is
   how the four compose-network lab services get in — they resolve to RFC1918
   container addresses, and listing ``lab-nginx`` *is* the explicit listing).

Per-tenant scope is a week-6 problem; this is configuration, not data.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeAlias

import dns.asyncresolver
import dns.exception
import dns.resolver
import httpx
import structlog

from app.core.errors import ForbiddenError
from app.core.pipeline.validation import normalize_hostname

logger = structlog.get_logger(__name__)

DNS_TIMEOUT_SECONDS = 3.0
MAX_PORT = 65535

IPAddress: TypeAlias = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork: TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network
ResolveFn: TypeAlias = Callable[[str], Awaitable[list[IPAddress]]]


class ScopeReason(StrEnum):
    """Why a target was refused — the machine-readable half of the 403."""

    EMPTY_ALLOWLIST = "empty_allowlist"
    BLOCKED_RANGE = "blocked_range"
    LOOPBACK_PORT_NOT_ALLOWED = "loopback_port_not_allowed"
    HOSTNAME_NOT_ALLOWLISTED = "hostname_not_allowlisted"
    ADDRESS_NOT_ALLOWLISTED = "address_not_allowlisted"
    RESOLUTION_FAILED = "resolution_failed"
    INVALID_TARGET = "invalid_target"


class ScopeViolationError(ForbiddenError):
    """The target is outside the configured scan scope.

    Subclasses :class:`ForbiddenError` on purpose: it surfaces as a ``403``
    RFC 9457 response at the API with the reason in ``detail``, and as a
    terminal failure inside a job. The structured fields below are what the
    worker log carries.
    """

    def __init__(
        self,
        detail: str,
        *,
        reason: ScopeReason,
        host: str,
        resolved: Sequence[IPAddress] = (),
    ) -> None:
        super().__init__(detail)
        self.reason = reason
        self.host = host
        self.resolved = tuple(resolved)


@dataclass(frozen=True, slots=True)
class ScopeEntry:
    """One parsed allowlist entry: hostname, IP or CIDR, optionally with a port."""

    raw: str
    hostname: str | None = None
    address: IPAddress | None = None
    network: IPNetwork | None = None
    port: int | None = None

    @property
    def covers_addresses(self) -> bool:
        return self.address is not None or self.network is not None

    def permits_hostname(self, hostname: str, port: int | None) -> bool:
        """Does this entry name ``hostname`` for the port being connected to?"""
        if self.hostname != hostname:
            return False
        return self.port is None or port is None or self.port == port

    def permits_address(self, address: IPAddress, port: int | None) -> bool:
        """Does this entry cover ``address`` for the port being connected to?"""
        if self.port is not None and self.port != port and port is not None:
            return False
        if self.address is not None:
            return self.address == address
        if self.network is not None:
            return address.version == self.network.version and address in self.network
        return False

    def permits_network(self, network: IPNetwork) -> bool:
        """Does this entry cover the whole target network?"""
        if self.port is not None:
            return False
        if self.network is not None:
            return (
                network.version == self.network.version
                and network.prefixlen >= self.network.prefixlen
                and network.network_address in self.network
            )
        if self.address is not None:
            single = ipaddress.ip_network(
                f"{self.address}/{self.address.max_prefixlen}", strict=False
            )
            return network == single
        return False


def _split_host_port(raw: str) -> tuple[str, int | None]:
    """Split ``host``, ``host:port`` or ``[host]:port``; validate the port."""
    text = raw.strip()
    if not text:
        raise ValueError("scope entry must not be empty")

    host_part = text
    port: int | None = None

    if text.startswith("["):
        end = text.find("]")
        if end == -1 or not text[end + 1 :].startswith(":"):
            raise ValueError(f"invalid bracketed scope entry: {raw!r}")
        host_part = text[1:end]
        port_text = text[end + 2 :]
        if not port_text.isdigit():
            raise ValueError(f"invalid port in scope entry: {raw!r}")
        port = int(port_text)
    elif text.count(":") == 1:
        possible_host, _, possible_port = text.partition(":")
        if possible_port.isdigit():
            host_part = possible_host
            port = int(possible_port)
    if port is not None and not 1 <= port <= MAX_PORT:
        raise ValueError(f"port out of range in scope entry: {raw!r}")
    return host_part, port


def parse_scope_entry(raw: str) -> ScopeEntry:
    """Parse one allowlist entry; raise ``ValueError`` on anything malformed.

    Accepted forms: ``lab-nginx``, ``example.com``, ``203.0.113.10``,
    ``203.0.113.0/24``, ``127.0.0.1:8081``, ``example.com:443``,
    ``[::1]:8081``. A bare IPv6 address is an address; IPv6 *with* a port must
    use brackets, because ``2001:db8::1:443`` is ambiguous.
    """
    host_part, port = _split_host_port(raw)

    if "/" in host_part:
        if port is not None:
            raise ValueError(f"a CIDR entry cannot carry a port: {raw!r}")
        try:
            return ScopeEntry(
                raw=raw, network=ipaddress.ip_network(host_part, strict=False)
            )
        except ValueError as exc:
            raise ValueError(f"invalid CIDR in scope entry: {raw!r}") from exc

    try:
        address = ipaddress.ip_address(host_part)
    except ValueError:
        try:
            hostname = normalize_hostname(host_part)
        except ValueError as exc:
            raise ValueError(f"invalid hostname in scope entry: {raw!r}") from exc
        return ScopeEntry(raw=raw, hostname=hostname, port=port)

    return ScopeEntry(raw=raw, address=address, port=port)


@dataclass(frozen=True, slots=True)
class ScanScope:
    """The parsed allowlist. No entries means nothing is scannable."""

    entries: tuple[ScopeEntry, ...] = ()

    @classmethod
    def parse(cls, entries: Iterable[str]) -> ScanScope:
        return cls(tuple(parse_scope_entry(entry) for entry in entries))

    @property
    def is_empty(self) -> bool:
        return not self.entries

    @property
    def has_address_entries(self) -> bool:
        return any(entry.covers_addresses for entry in self.entries)

    def permits_hostname(self, hostname: str, port: int | None) -> bool:
        return any(entry.permits_hostname(hostname, port) for entry in self.entries)

    def permits_address(self, address: IPAddress, port: int | None) -> bool:
        return any(entry.permits_address(address, port) for entry in self.entries)

    def permits_network(self, network: IPNetwork) -> bool:
        return any(entry.permits_network(network) for entry in self.entries)

    def permits_loopback(self, address: IPAddress, port: int | None) -> bool:
        """Loopback only via a port-qualified entry naming this address.

        With no port in hand (the API layer) any port-qualified entry for the
        address is enough — the socket layer enforces the port itself.
        """
        return any(
            entry.port is not None and entry.permits_address(address, port)
            for entry in self.entries
        )


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    """A permitted target: the addresses the caller must connect to."""

    host: str
    addresses: tuple[IPAddress, ...]


def _is_blocked_address(address: IPAddress) -> bool:
    """Unconditional blocks — these win over any allowlist entry.

    Loopback is deliberately not one of them: it has its own rule (reachable
    only through a port-qualified entry), and Python classifies `::1` as
    reserved as well as loopback — checking reserved first would make IPv6
    loopback impossible to list at all.
    """
    if address.is_loopback:
        return False
    return bool(
        address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def _is_blocked_network(network: IPNetwork) -> bool:
    return any(
        network.overlaps(blocked)
        for blocked in _BLOCKED_NETWORKS
        if blocked.version == network.version
    ) or any(
        _is_blocked_address(address)
        for address in (network.network_address, network.broadcast_address)
    )


_BLOCKED_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("169.254.0.0/16"),  # NOSONAR S1313: blocklist, by design
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("224.0.0.0/4"),  # NOSONAR S1313: blocklist, by design
    ipaddress.ip_network("ff00::/8"),
)


def _blocked_reason_detail(address: IPAddress) -> str:
    if address.is_link_local:
        return (
            f"{address} is link-local (cloud metadata lives at "
            "169.254.169.254); blocked regardless of the allowlist"
        )
    if address.is_multicast:
        return f"{address} is multicast; blocked regardless of the allowlist"
    if address.is_unspecified:
        return (
            f"{address} is the unspecified address; blocked regardless of the allowlist"
        )
    return f"{address} is reserved; blocked regardless of the allowlist"


async def resolve_addresses(hostname: str) -> list[IPAddress]:
    """Resolve a name to A/AAAA addresses. Any DNS problem raises.

    Not "returns an empty list" — an unresolvable target cannot be scope
    checked, so it is refused (fail closed) with
    :data:`ScopeReason.RESOLUTION_FAILED`.
    """
    resolver = dns.asyncresolver.Resolver()
    found: dict[IPAddress, None] = {}

    async def resolve_type(record_type: str) -> None:
        try:
            answer = await resolver.resolve(
                hostname, record_type, lifetime=DNS_TIMEOUT_SECONDS
            )
        except (
            dns.resolver.NXDOMAIN,
            dns.resolver.NoAnswer,
            dns.resolver.NoNameservers,
            dns.resolver.Timeout,
            dns.exception.DNSException,
        ):
            return
        for record in answer:
            found.setdefault(ipaddress.ip_address(str(record)))

    await asyncio.gather(*(resolve_type(kind) for kind in ("A", "AAAA")))
    if not found:
        raise LookupError(f"no address records for {hostname}")
    return list(found)


def get_scope() -> ScanScope:
    """Parse the configured allowlist. Reads settings per call — no cache to
    go stale, and an entry that fails to parse fails at startup, loudly."""
    from app.core.config import get_settings  # local import: config must stay
    # importable without pulling this module (and dns) into it.

    raw = get_settings().scan_scope_allowlist
    entries = [part.strip() for part in raw.split(",") if part.strip()]
    return ScanScope.parse(entries)


def _refuse(
    reason: ScopeReason,
    *,
    host: str,
    resolved: Sequence[IPAddress] = (),
    port: int | None = None,
    detail: str,
) -> ScopeViolationError:
    logger.warning(
        "scan.scope_refused",
        target=host,
        resolved=[str(address) for address in resolved],
        reason=reason.value,
        port=port,
        detail=detail,
    )
    return ScopeViolationError(detail, reason=reason, host=host, resolved=resolved)


def _check_one_address(
    address: IPAddress,
    *,
    host: str,
    port: int | None,
    scope: ScanScope,
    hostname_permitted: bool,
    resolved: Sequence[IPAddress],
) -> None:
    if _is_blocked_address(address):
        raise _refuse(
            ScopeReason.BLOCKED_RANGE,
            host=host,
            resolved=resolved,
            port=port,
            detail=_blocked_reason_detail(address),
        )

    if address.is_loopback:
        if not scope.permits_loopback(address, port):
            raise _refuse(
                ScopeReason.LOOPBACK_PORT_NOT_ALLOWED,
                host=host,
                resolved=resolved,
                port=port,
                detail=(
                    f"{address} is loopback; only loopback addresses listed "
                    "with an explicit port (e.g. 127.0.0.1:8081) may be scanned"
                ),
            )
        return

    if scope.permits_address(address, port) or hostname_permitted:
        return

    raise _refuse(
        ScopeReason.ADDRESS_NOT_ALLOWLISTED,
        host=host,
        resolved=resolved,
        port=port,
        detail=(
            f"resolved address {address} for '{host}' is not in the scan "
            "scope allowlist"
        ),
    )


def _check_cidr_target(
    host: str, *, port: int | None, scope: ScanScope
) -> ScopeDecision:
    """Decide a network target such as ``203.0.113.0/24``."""
    try:
        network = ipaddress.ip_network(host, strict=False)
    except ValueError:
        network = None
    if network is None:
        raise _refuse(
            ScopeReason.INVALID_TARGET,
            host=host,
            port=port,
            detail=f"'{host}' is not a hostname, address or CIDR",
        )
    if _is_blocked_network(network):
        raise _refuse(
            ScopeReason.BLOCKED_RANGE,
            host=host,
            port=port,
            detail=(
                f"{network} covers a blocked range (link-local, multicast "
                "or reserved); blocked regardless of the allowlist"
            ),
        )
    if not scope.permits_network(network):
        raise _refuse(
            ScopeReason.ADDRESS_NOT_ALLOWLISTED,
            host=host,
            port=port,
            detail=(f"network {network} is not inside the scan scope allowlist"),
        )
    return ScopeDecision(host=host, addresses=())


def _check_literal_target(
    host: str, *, port: int | None, scope: ScanScope
) -> ScopeDecision | None:
    """Decide an address literal; ``None`` means *it is not one*."""
    try:
        literal: IPAddress | None = ipaddress.ip_address(host)
    except ValueError:
        return None
    resolved = [literal]
    _check_one_address(
        literal,
        host=host,
        port=port,
        scope=scope,
        hostname_permitted=False,
        resolved=resolved,
    )
    return ScopeDecision(host=host, addresses=tuple(resolved))


async def _check_hostname_target(
    host: str,
    *,
    port: int | None,
    scope: ScanScope,
    resolve: ResolveFn | None,
) -> ScopeDecision:
    """Resolve a name, then decide on every address it resolved to."""
    try:
        hostname = normalize_hostname(host)
    except ValueError:
        raise _refuse(
            ScopeReason.INVALID_TARGET,
            host=host,
            port=port,
            detail=f"'{host}' is not a hostname, address or CIDR",
        ) from None

    hostname_permitted = scope.permits_hostname(hostname, port)
    if not hostname_permitted and not scope.has_address_entries:
        # No address entry could possibly match, so resolving would only leak
        # a query for a name we already know we will refuse.
        raise _refuse(
            ScopeReason.HOSTNAME_NOT_ALLOWLISTED,
            host=host,
            port=port,
            detail=f"'{hostname}' is not in the scan scope allowlist",
        )

    resolve_fn = resolve if resolve is not None else resolve_addresses
    try:
        resolved = await resolve_fn(hostname)
    except ForbiddenError:
        raise
    except Exception as exc:
        raise _refuse(
            ScopeReason.RESOLUTION_FAILED,
            host=host,
            port=port,
            detail=(
                f"could not resolve '{hostname}' to an address to verify "
                f"scope ({type(exc).__name__})"
            ),
        ) from exc

    if not resolved:
        raise _refuse(
            ScopeReason.RESOLUTION_FAILED,
            host=host,
            port=port,
            detail=f"'{hostname}' resolved to no address to verify scope",
        )

    for address in resolved:
        _check_one_address(
            address,
            host=host,
            port=port,
            scope=scope,
            hostname_permitted=hostname_permitted,
            resolved=resolved,
        )
    return ScopeDecision(host=host, addresses=tuple(resolved))


async def check_scope(
    target: str,
    *,
    port: int | None = None,
    scope: ScanScope | None = None,
    resolve: ResolveFn | None = None,
) -> ScopeDecision:
    """Resolve ``target`` (if it is a name), then decide, then return it.

    Raises :class:`ScopeViolationError` — with a reason — instead of returning
    "no". Never opens a socket; never resolves on the refusal paths that do
    not need a resolution to be certain.
    """
    scope = get_scope() if scope is None else scope
    host = target.strip()

    if scope.is_empty:
        raise _refuse(
            ScopeReason.EMPTY_ALLOWLIST,
            host=host,
            port=port,
            detail=(
                "scan scope allowlist is empty; nothing may be scanned (default deny)"
            ),
        )

    if "/" in host:
        return _check_cidr_target(host, port=port, scope=scope)

    literal_decision = _check_literal_target(host, port=port, scope=scope)
    if literal_decision is not None:
        return literal_decision

    return await _check_hostname_target(host, port=port, scope=scope, resolve=resolve)


async def scoped_open_connection(
    host: str,
    port: int,
    *,
    scope: ScanScope | None = None,
    resolve: ResolveFn | None = None,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Check scope, then connect — to the address that was checked.

    This is the mechanism half of W4-02: a scanner cannot open a socket
    without going through here, because here is where the connection comes
    from. It never asks the resolver again, so a name that was approved a
    moment ago cannot have changed underneath the connection. The caller
    owns the timeout: wrap the call in ``async with asyncio.timeout(...)``.
    """
    decision = await check_scope(host, port=port, scope=scope, resolve=resolve)
    if not decision.addresses:
        raise _refuse(
            ScopeReason.RESOLUTION_FAILED,
            host=host,
            port=port,
            detail=f"'{host}' has no checked address to connect to",
        )

    last_error: BaseException | None = None
    for address in decision.addresses:
        try:
            reader, writer = await asyncio.open_connection(str(address), port)
            return reader, writer
        except OSError as exc:
            last_error = exc

    if last_error is None:  # pragma: no cover - decision.addresses is non-empty
        raise ConnectionError(f"no address to connect to for {host}")
    raise last_error


class ScopedAsyncHTTPTransport(httpx.AsyncBaseTransport):
    """HTTP's connection layer: scope is decided where the request would leave.

    Every request through this transport — redirect hops included — runs
    :func:`check_scope` against the URL's host and port before the wrapped
    transport sees it, then the request is **pinned to the checked address**:
    the URL is rewritten to the IP, and the original name rides along as the
    ``sni_hostname`` extension, so TLS still speaks for the hostname while
    the socket goes exactly where scope approved. httpx never gets to
    resolve the name a second time — the rebinding answer, applied to HTTP.
    """

    def __init__(
        self,
        *,
        scope: ScanScope | None = None,
        resolve: ResolveFn | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._scope = scope
        self._resolve = resolve
        self._transport = (
            transport if transport is not None else httpx.AsyncHTTPTransport()
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        port = url.port or (443 if url.scheme == "https" else 80)
        decision = await check_scope(
            url.host, port=port, scope=self._scope, resolve=self._resolve
        )
        _pin_request_to_checked_address(request, decision)
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self._transport.aclose()


def _pin_request_to_checked_address(
    request: httpx.Request, decision: ScopeDecision
) -> None:
    """Send the request to the address scope approved, hostname intact."""
    if not decision.addresses:  # pragma: no cover - URL hosts are never CIDRs
        raise _refuse(
            ScopeReason.RESOLUTION_FAILED,
            host=decision.host,
            detail=f"'{decision.host}' has no checked address to connect to",
        )
    original = request.url.host
    address = str(decision.addresses[0])
    if original == address:
        return
    request.url = request.url.copy_with(host=address)
    if request.url.scheme == "https":
        request.extensions["sni_hostname"] = original


def scoped_http_client(
    *,
    scope: ScanScope | None = None,
    resolve: ResolveFn | None = None,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """An ``httpx`` client that cannot reach an out-of-scope host.

    The gate lives in the transport (:class:`ScopedAsyncHTTPTransport`), not
    in a rule about when to call it: every request the client sends — the
    ones its caller remembered to think about and the ones it did not — is
    refused at the connection layer, and refused *before* a socket exists.
    """
    return httpx.AsyncClient(
        transport=ScopedAsyncHTTPTransport(scope=scope, resolve=resolve),
        **kwargs,
    )
