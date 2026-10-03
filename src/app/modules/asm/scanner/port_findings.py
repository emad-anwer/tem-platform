from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.fingerprint import (
    FindingKind,
    compute_fingerprint,
    normalize_finding_value,
)
from app.core.repository import FindingRepository
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
) -> PortFindingsSummary:
    """Write bounded HTTP observations through the standard finding upsert path."""
    items = []
    seen: set[str] = set()
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
        seen.add(
            compute_fingerprint(
                FindingKind.HTTP_SERVICE,
                target_id,
                normalize_finding_value(FindingKind.HTTP_SERVICE, value),
            )
        )
    total, new = await repo.upsert_discovery_batch(items)
    resolved = await repo.resolve_missing_discoveries(
        target_id=target_id,
        seen_fingerprints=seen,
        kinds={FindingKind.HTTP_SERVICE},
    )
    return PortFindingsSummary(total=total, new=new, resolved=resolved)


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
    """Upsert this scan's open ports. resolve open_port findings not seen."""
    items = []
    seen: set[str] = set()
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
        seen.add(
            compute_fingerprint(
                FindingKind.OPEN_PORT,
                target_id,
                normalize_finding_value(FindingKind.OPEN_PORT, value),
            )
        )

    total, new = await repo.upsert_discovery_batch(items)

    resolved = 0
    if report.attempted > 0:  # a fully out-of-scope scan observed nothing
        resolved = await repo.resolve_missing_discoveries(
            target_id=target_id,
            seen_fingerprints=seen,
            kinds={FindingKind.OPEN_PORT},
        )
    return PortFindingsSummary(total=total, new=new, resolved=resolved)


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
        repo, target_id=target_id, run_id=run_id, services=services
    )
    return report, port_summary, http_summary
