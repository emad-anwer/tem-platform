from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from app.core.fingerprint import FindingKind
from app.core.repository import DiscoveryPersistenceSummary, FindingRepository
from app.modules.asm.scanner.http_prober import HTTPService, probe_open_ports
from app.modules.asm.scanner.port_scanner import PortScanReport, PortState, scan_host

PROTOCOL = "tcp"


@dataclass(frozen=True, slots=True)
class PortFindingsSummary:
    total: int
    new: int
    resolved: int


async def record_http_services(
    repo: FindingRepository,
    *,
    target_id: UUID,
    run_id: UUID,
    services: list[HTTPService],
    degraded: bool,
) -> PortFindingsSummary:
    """Persist HTTP observations and this run's snapshots atomically."""
    items = []
    for service in services:
        value = service.value
        items.append(
            {
                "target_id": target_id,
                "run_id": run_id,
                "kind": FindingKind.HTTP_SERVICE,
                "value": value,
                "severity": "info",
                "details": {
                    "scheme": service.scheme,
                    "port": service.port,
                    "status_code": service.status_code,
                    "final_url": service.final_url,
                    "title": service.title,
                    "headers": service.headers,
                    "cookie_names": list(service.cookie_names),
                    "technologies": list(service.technologies),
                    "body_truncated": service.body_truncated,
                    "redirects_followed": service.redirects_followed,
                },
            }
        )
    summary = cast(
        DiscoveryPersistenceSummary,
        await repo.persist_discovery_run(
            target_id=target_id,
            run_id=run_id,
            items=items,
            kinds={FindingKind.HTTP_SERVICE},
            degraded=degraded,
            return_summary=True,
        ),
    )
    return PortFindingsSummary(
        total=summary.total, new=summary.new, resolved=summary.resolved
    )


def open_port_value(host: str, port: int) -> str:
    return f"{host}:{port}/{PROTOCOL}"


async def record_port_scan(
    repo: FindingRepository,
    *,
    target_id: UUID,
    run_id: UUID,
    host: str,
    report: PortScanReport,
) -> PortFindingsSummary:
    """Persist open ports and this run's snapshots atomically."""
    items = []
    for result in report.results:
        if result.state is not PortState.OPEN:
            continue
        value = open_port_value(host, result.port)
        items.append(
            {
                "target_id": target_id,
                "run_id": run_id,
                "kind": FindingKind.OPEN_PORT,
                "value": value,
                "severity": "info",
                "details": {"port": result.port, "protocol": PROTOCOL},
            }
        )
    summary = cast(
        DiscoveryPersistenceSummary,
        await repo.persist_discovery_run(
            target_id=target_id,
            run_id=run_id,
            items=items,
            kinds={FindingKind.OPEN_PORT},
            # Preserve the existing behaviour for a fully out-of-scope scan:
            # it observes nothing and must not resolve prior open-port findings.
            degraded=report.attempted == 0,
            return_summary=True,
        ),
    )
    return PortFindingsSummary(
        total=summary.total, new=summary.new, resolved=summary.resolved
    )


async def scan_and_record(
    repo: FindingRepository,
    *,
    target_id: UUID,
    run_id: UUID,
    host: str,
    **scan_kwargs,
) -> tuple[PortScanReport, PortFindingsSummary]:
    report = await scan_host(host, **scan_kwargs)
    summary = await record_port_scan(
        repo, target_id=target_id, run_id=run_id, host=host, report=report
    )
    return report, summary


async def scan_probe_and_record(
    repo: FindingRepository,
    *,
    target_id: UUID,
    run_id: UUID,
    host: str,
    **scan_kwargs,
) -> tuple[PortScanReport, PortFindingsSummary, PortFindingsSummary]:
    """Scan ports, persist them, then enrich every open port as HTTP when possible."""
    report, port_summary = await scan_and_record(
        repo, target_id=target_id, run_id=run_id, host=host, **scan_kwargs
    )
    services = await probe_open_ports(host, report.open_ports)
    http_summary = await record_http_services(
        repo,
        target_id=target_id,
        run_id=run_id,
        services=services,
        # No HTTP result from one or more open ports is ambiguous: it may be
        # a non-HTTP service, but it may also be a transient probe outage.
        # Do not resolve prior HTTP findings on an all-negative run.
        degraded=bool(report.open_ports) and not services,
    )
    return report, port_summary, http_summary
