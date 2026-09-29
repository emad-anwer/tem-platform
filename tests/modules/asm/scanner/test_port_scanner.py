"""Scanner behaviour against a fake network. Asserts on numbers, not feelings."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Literal

import pytest

from app.core.scope import ScanScope
from app.modules.asm.scanner.ports import CURATED_TCP_PORTS
from app.modules.asm.scanner.port_scanner import PortState, scan_host

Behavior = Literal["open", "closed", "silent", "error"]
SCOPE = ScanScope.parse(["127.0.0.1:1"])  # host literal passes the host-level check


class FakeWriter:
    def __init__(self, net: "FakeNet", *, fail_wait_closed: bool = False) -> None:
        self._net = net
        self._fail = fail_wait_closed
        self.closed = False

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._net.live -= 1
            self._net.closed_writers += 1

    async def wait_closed(self) -> None:
        if self._fail:
            raise ConnectionResetError("boom")


class FakeNet:
    """Fake connect() that measures true concurrency independently of the scanner."""

    def __init__(self, behaviors: dict[int, Behavior], *, default: Behavior = "closed",
                 delay: float = 0.01, fail_wait_closed: bool = False) -> None:
        self.behaviors = behaviors
        self.default = default
        self.delay = delay
        self.fail_wait_closed = fail_wait_closed
        self.live = 0  # attempts in progress + writers not yet closed
        self.max_live = 0
        self.opened_writers = 0
        self.closed_writers = 0

    async def connect(self, host: str, port: int):
        self.live += 1
        self.max_live = max(self.max_live, self.live)
        behavior = self.behaviors.get(port, self.default)
        try:
            if behavior == "silent":
                await asyncio.sleep(3600)
            await asyncio.sleep(self.delay)
            if behavior == "closed":
                raise ConnectionRefusedError
            if behavior == "error":
                raise OSError("no route to host")
        except BaseException:
            self.live -= 1
            raise
        self.opened_writers += 1
        return object(), FakeWriter(self, fail_wait_closed=self.fail_wait_closed)


def _scan(net: FakeNet, ports, **kw):
    return scan_host(
        "127.0.0.1", ports=ports, scope=SCOPE, connect=net.connect,
        connect_timeout_seconds=kw.pop("timeout", 0.5), **kw,
    )


@pytest.mark.asyncio
async def test_three_outcomes_are_distinguished():
    net = FakeNet({80: "open", 81: "closed", 82: "silent", 83: "error"})
    report = await _scan(net, [80, 81, 82, 83], concurrency=4, timeout=0.1)
    states = {r.port: r.state for r in report.results}
    assert states == {
        80: PortState.OPEN,
        81: PortState.CLOSED,
        82: PortState.FILTERED,
        83: PortState.FILTERED,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 5, 10])
async def test_concurrency_never_exceeds_semaphore_limit(limit: int):
    ports = list(range(1000, 1200))  # 200 tasks
    net = FakeNet({p: "open" for p in ports}, delay=0.005)
    report = await _scan(net, ports, concurrency=limit)
    assert net.max_live <= limit  # measured by the fake, not by the scanner
    assert net.max_live == limit  # ...and the limit is actually used (not serial)
    assert report.max_in_flight <= limit


@pytest.mark.asyncio
async def test_silent_host_finishes_in_about_one_timeout_not_n_times():
    ports = list(range(2000, 2020))  # 20 ports, limit 50 -> one round
    net = FakeNet({}, default="silent")
    started = time.monotonic()
    report = await _scan(net, ports, concurrency=50, timeout=0.2)
    elapsed = time.monotonic() - started
    assert all(r.state is PortState.FILTERED for r in report.results)
    assert 0.2 <= elapsed < 0.5  # ~1 timeout; sequential would be 4.0s
    assert net.live == 0  # every timed-out attempt was cancelled cleanly


@pytest.mark.asyncio
async def test_silent_host_takes_ceil_ports_over_limit_rounds():
    ports = list(range(3000, 3020))
    net = FakeNet({}, default="silent")
    started = time.monotonic()
    await _scan(net, ports, concurrency=10, timeout=0.2)
    elapsed = time.monotonic() - started
    rounds = math.ceil(len(ports) / 10)
    assert 0.2 * rounds <= elapsed < 0.2 * rounds + 0.3


@pytest.mark.asyncio
async def test_every_connection_is_closed_and_counted():
    open_ports = list(range(4000, 4025))
    net = FakeNet({p: "open" for p in open_ports}, default="closed")
    report = await _scan(net, open_ports + list(range(5000, 5010)), concurrency=8)
    assert report.sockets_opened == 25
    assert report.sockets_closed == 25
    assert net.opened_writers == net.closed_writers == 25
    assert net.live == 0


@pytest.mark.asyncio
async def test_writer_is_closed_even_when_wait_closed_fails():
    net = FakeNet({80: "open"}, fail_wait_closed=True)
    report = await _scan(net, [80], concurrency=1)
    assert report.open_ports == [80]  # cleanup error did not lose the result
    assert net.closed_writers == 1
    assert report.sockets_closed == 1


@pytest.mark.asyncio
async def test_empty_allowlist_refuses_before_any_connection():
    from app.core.scope import ScopeViolationError

    net = FakeNet({})
    with pytest.raises(ScopeViolationError):
        await scan_host(
            "127.0.0.1", ports=[80], scope=ScanScope(), connect=net.connect
        )
    assert net.opened_writers == 0 and net.live == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, 65536, -1])
async def test_invalid_ports_rejected(bad: int):
    with pytest.raises(ValueError):
        await _scan(FakeNet({}), [80, bad])


def test_curated_port_list_shape():
    assert len(CURATED_TCP_PORTS) == len(set(CURATED_TCP_PORTS))
    assert all(1 <= p <= 65535 for p in CURATED_TCP_PORTS)
    assert 80 <= len(CURATED_TCP_PORTS) <= 150
    # short enough to be fast, long enough to find the lab's non-standard port
    assert {80, 443, 8888} <= set(CURATED_TCP_PORTS)