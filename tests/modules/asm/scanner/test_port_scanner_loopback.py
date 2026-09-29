"""Real sockets on 127.0.0.1 through the real scoped connector; no lab needed."""

from __future__ import annotations

import asyncio
import socket

import pytest

from app.core.scope import ScanScope
from app.modules.asm.scanner.port_scanner import PortState, scan_host


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_open_closed_and_out_of_scope_over_real_sockets():
    async def handler(reader, writer):
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    open_port = server.sockets[0].getsockname()[1]
    closed_port = _free_port()  # bound then released: nothing listens
    unlisted_port = _free_port()  # loopback but not in the allowlist

    scope = ScanScope.parse([f"127.0.0.1:{open_port}", f"127.0.0.1:{closed_port}"])
    try:
        report = await scan_host(
            "127.0.0.1",
            ports=[open_port, closed_port, unlisted_port],
            scope=scope,
            concurrency=3,
            connect_timeout_seconds=1.0,
        )
    finally:
        server.close()
        await server.wait_closed()

    states = {r.port: r.state for r in report.results}
    assert states[open_port] is PortState.OPEN
    assert states[closed_port] is PortState.CLOSED
    assert states[unlisted_port] is PortState.OUT_OF_SCOPE
    assert report.sockets_opened == report.sockets_closed == 1
