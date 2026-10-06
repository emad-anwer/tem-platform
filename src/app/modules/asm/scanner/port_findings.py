from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from app.core.discovery import _belongs_to_domain, _normalise_hostname
from app.core.fingerprint import FindingKind
from app.core.repository import DiscoveryPersistenceSummary, FindingRepository
from app.core.scope import ScopeViolationError
from app.modules.asm.scanner.http_prober import HTTPService, probe_open_ports
from app.modules.asm.scanner.port_scanner import (
    PortResult,
    PortScanReport,
    PortState,
    scan_host,
)
from app.modules.asm.scanner.tls_certificate import probe_tls_certificate

PROTOCOL = "tcp"
TLS_PROBE_CONCURRENCY = 10


@dataclass(frozen=True, slots=True)
class PortFindingsSummary:
    total: int
    new: int
    resolved: int


@dataclass(frozen=True, slots=True)
class PortScanFindings:
    items: tuple[dict, ...]
    sources_degraded: tuple[str, ...]
    degradation_notes: tuple[str, ...]


async def record_http_services(
    repo: FindingRepository,
    *,
    target_id: UUID,
    run_id: UUID,
    services: list[HTTPService],
    degraded: bool,
) -> PortFindingsSummary:
    """Persist HTTP observations and this run's snapshots atomically."""
    items = http_service_finding_items(
        target_id=target_id, run_id=run_id, services=services
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


def http_service_finding_items(
    *, target_id: UUID, run_id: UUID, services: list[HTTPService]
) -> list[dict]:
    """Convert HTTP observations into the generic finding contract."""
    items: list[dict] = []
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
    return items


def open_port_value(host: str, port: int) -> str:
    return f"{host}:{port}/{PROTOCOL}"


async def record_port_scan(
    repo: FindingRepository,
    *,
    target_id: UUID,
    run_id: UUID,
    host: str,
    domain: str,
    report: PortScanReport,
) -> PortFindingsSummary:
    """Persist open ports and this run's snapshots atomically."""
    collection = await collect_port_scan_findings(
        target_id=target_id,
        run_id=run_id,
        host=host,
        domain=domain,
        report=report,
    )
    summary = cast(
        DiscoveryPersistenceSummary,
        await repo.persist_discovery_run(
            target_id=target_id,
            run_id=run_id,
            items=collection.items,
            kinds={FindingKind.OPEN_PORT, FindingKind.TLS_CERTIFICATE},
            degraded=report.attempted == 0,
            degraded_kinds=(
                {FindingKind.TLS_CERTIFICATE}
                if collection.sources_degraded and report.attempted > 0
                else None
            ),
            return_summary=True,
        ),
    )
    return PortFindingsSummary(
        total=summary.total, new=summary.new, resolved=summary.resolved
    )


async def collect_port_scan_findings(
    *,
    target_id: UUID,
    run_id: UUID,
    host: str,
    domain: str | None,
    report: PortScanReport,
) -> PortScanFindings:
    """Collect ports, certificates, and eligible SANs without database writes."""
    normalized_domain = _normalise_hostname(domain) if domain else None
    if domain is not None and not normalized_domain:
        raise ValueError("domain must be a valid hostname")

    items: list[dict] = []
    degradation_notes: list[str] = []
    open_results: list[PortResult] = []
    for result in report.results:
        if result.state is not PortState.OPEN:
            continue
        open_results.append(result)
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

    semaphore = asyncio.Semaphore(TLS_PROBE_CONCURRENCY)

    async def inspect_tls(result: PortResult):
        async with semaphore:
            try:
                return result, await probe_tls_certificate(host, result.port), None
            except ScopeViolationError:
                raise
            except Exception as error:  # noqa: BLE001 - one endpoint must not discard port findings.
                return result, None, type(error).__name__

    observations = await asyncio.gather(
        *(inspect_tls(result) for result in open_results), return_exceptions=True
    )
    seen_san_names: set[str] = set()
    for outcome in observations:
        if isinstance(outcome, BaseException):
            if not isinstance(outcome, Exception):
                raise outcome
            degradation_notes.append(
                f"tls: certificate probe failed ({type(outcome).__name__})"
            )
            continue
        result, observation, error_name = outcome
        if error_name:
            degradation_notes.append(f"tls: certificate probe failed ({error_name})")
        if observation is None:
            continue
        certificate_value = f"{host}:{result.port}"
        items.append(
            {
                "target_id": target_id,
                "run_id": run_id,
                "kind": FindingKind.TLS_CERTIFICATE,
                "value": certificate_value,
                "severity": "info",
                "details": observation.details,
            }
        )
        for san_name in observation.dns_names:
            normalized_name = _normalise_hostname(san_name)
            if (
                normalized_name
                and normalized_name not in seen_san_names
                and normalized_domain is not None
                and _belongs_to_domain(normalized_name, normalized_domain)
            ):
                seen_san_names.add(normalized_name)
                items.append(
                    {
                        "target_id": target_id,
                        "run_id": run_id,
                        "kind": FindingKind.SUBDOMAIN,
                        "value": normalized_name,
                        "severity": "info",
                    }
                )

    return PortScanFindings(
        items=tuple(items),
        sources_degraded=("tls",) if degradation_notes else (),
        degradation_notes=tuple(degradation_notes),
    )


async def scan_and_record(
    repo: FindingRepository,
    *,
    target_id: UUID,
    run_id: UUID,
    host: str,
    domain: str,
    **scan_kwargs,
) -> tuple[PortScanReport, PortFindingsSummary]:
    report = await scan_host(host, **scan_kwargs)
    summary = await record_port_scan(
        repo,
        target_id=target_id,
        run_id=run_id,
        host=host,
        domain=domain,
        report=report,
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
