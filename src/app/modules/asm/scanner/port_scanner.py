from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import structlog

from app.core.config import get_settings
from app.core.scope import (
    IPAddress,
    ScanScope,
    ScopeViolationError,
    get_scope,
    check_scope,
    scoped_open_connection,
)
from app.modules.asm.scanner.ports import CURATED_TCP_PORTS

logger = structlog.get_logger(__name__)

MAX_PORT = 65535

ConnectFn = Callable[
    [str, int], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]
]


class PortState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    FILTERED = "filtered"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True, slots=True)
class PortResult:
    port: int
    state: PortState
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class PortScanReport:
    """What one scan did, including the numbers we can point at."""

    host: str
    addresses: tuple[IPAddress, ...]
    results: tuple[PortResult, ...]
    concurrency: int
    connect_timeout_seconds: float
    duration_seconds: float
    max_in_flight: int  # peak simultaneous attempts+open sockets, measured
    sockets_opened: int  # handshakes that completed
    sockets_closed: int  # writers we closed; must equal sockets_opened

    @property
    def open_ports(self) -> list[int]:
        return [r.port for r in self.results if r.state is PortState.OPEN]

    @property
    def attempted(self) -> int:
        return sum(1 for r in self.results if r.state is not PortState.OUT_OF_SCOPE)

    def count(self, state: PortState) -> int:
        return sum(1 for r in self.results if r.state is state)


class _Tally:
    """Per-scan counters. Never module-global: scans run concurrently."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0
        self.opened = 0
        self.closed = 0

    def enter(self) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)

    def leave(self) -> None:
        self.in_flight -= 1


def _validate_ports(ports: Sequence[int]) -> list[int]:
    unique = list(dict.fromkeys(ports))
    for port in unique:
        if not isinstance(port, int) or not 1 <= port <= MAX_PORT:
            raise ValueError(f"invalid port: {port!r}")
    if not unique:
        raise ValueError("at least one port is required")
    return unique


async def _close_writer(writer: asyncio.StreamWriter, tally: _Tally) -> None:
    try:
        writer.close()
        await writer.wait_closed()
    except OSError as exc:
        logger.debug("scan.ports_close_error", error=type(exc).__name__)
    finally:
        tally.closed += 1


async def _attempt(
    host: str,
    port: int,
    *,
    connect: ConnectFn,
    timeout_seconds: float,
    tally: _Tally,
) -> PortResult:
    try:
        async with asyncio.timeout(timeout_seconds):
            _reader, writer = await connect(host, port)
    except ScopeViolationError as exc:
        return PortResult(port, PortState.OUT_OF_SCOPE, exc.reason.value)
    except ConnectionRefusedError:
        return PortResult(port, PortState.CLOSED)
    except TimeoutError:
        return PortResult(port, PortState.FILTERED, "timeout")
    except OSError as exc:
        return PortResult(port, PortState.FILTERED, type(exc).__name__)

    tally.opened += 1
    await _close_writer(writer, tally)
    return PortResult(port, PortState.OPEN)


def _scoped_connector(scope: ScanScope, addresses: tuple[IPAddress, ...]) -> ConnectFn:
    """Connector that scope-checks every port but never re-resolves the name."""
    pinned = list(addresses)

    async def pinned_resolve(_hostname: str) -> list[IPAddress]:
        return pinned

    async def connect(
        host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await scoped_open_connection(
            host, port, scope=scope, resolve=pinned_resolve
        )

    return connect


async def scan_host(
    host: str,
    *,
    ports: Sequence[int] | None = None,
    concurrency: int | None = None,
    connect_timeout_seconds: float | None = None,
    scope: ScanScope | None = None,
    connect: ConnectFn | None = None,
) -> PortScanReport:
    settings = get_settings()
    port_list = _validate_ports(CURATED_TCP_PORTS if ports is None else ports)
    limit = concurrency if concurrency is not None else settings.port_scan_concurrency
    timeout_seconds = (
        connect_timeout_seconds
        if connect_timeout_seconds is not None
        else settings.port_scan_connect_timeout_seconds
    )
    if limit < 1:
        raise ValueError("concurrency must be at least 1")
    if timeout_seconds <= 0:
        raise ValueError("connect timeout must be positive")

    active_scope = get_scope() if scope is None else scope
    decision = await check_scope(host, scope=active_scope) 
    if not decision.addresses:
        raise ValueError(f"'{host}' is a network, not a host; scan hosts only")

    connector = connect or _scoped_connector(active_scope, decision.addresses)
    semaphore = asyncio.Semaphore(limit)
    tally = _Tally()

    async def probe(port: int) -> PortResult:
        async with semaphore: 
            tally.enter()
            try:
                return await _attempt(
                    host,
                    port,
                    connect=connector,
                    timeout_seconds=timeout_seconds,
                    tally=tally,
                )
            finally:
                tally.leave()

    started = time.monotonic()
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(probe(port)) for port in port_list]
    duration = time.monotonic() - started

    results = tuple(sorted((t.result() for t in tasks), key=lambda r: r.port))
    report = PortScanReport(
        host=host,
        addresses=decision.addresses,
        results=results,
        concurrency=limit,
        connect_timeout_seconds=timeout_seconds,
        duration_seconds=duration,
        max_in_flight=tally.max_in_flight,
        sockets_opened=tally.opened,
        sockets_closed=tally.closed,
    )
    logger.info(
        "scan.ports_completed",
        host=host,
        ports=len(port_list),
        open=report.count(PortState.OPEN),
        closed=report.count(PortState.CLOSED),
        filtered=report.count(PortState.FILTERED),
        out_of_scope=report.count(PortState.OUT_OF_SCOPE),
        concurrency=limit,
        max_in_flight=report.max_in_flight,
        sockets_opened=report.sockets_opened,
        sockets_closed=report.sockets_closed,
        duration_seconds=round(duration, 3),
    )
    return report