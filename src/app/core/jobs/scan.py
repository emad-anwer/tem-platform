from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import structlog

from app.core.auth.job_context import tenant_job
from app.core.discovery import (
    CertificateTransparencySource,
    DNSSource,
    ScanSource,
    collect_domain_discoveries,
)
from app.core.fingerprint import (
    FindingKind,
    compute_fingerprint,
    normalize_finding_value,
)
from app.core.jobs.lifecycle import execute_scan_run
from app.core.models import ScanRun
from app.core.repository import (
    DiscoveryPersistenceSummary,
    FindingRepository,
    TargetRepository,
)
from app.core.scope import ScopeViolationError, check_scope
from app.modules.asm.scanner.http_prober import probe_open_ports
from app.modules.asm.scanner.port_findings import (
    collect_port_scan_findings,
    http_service_finding_items,
)
from app.modules.asm.scanner.port_scanner import scan_host

logger = structlog.get_logger(__name__)
MAX_PORT_SCAN_HOSTS = 25
_SOURCE_KINDS = {
    "dns": FindingKind.SUBDOMAIN,
    "crtsh": FindingKind.SUBDOMAIN,
    "subdomain_discovery": FindingKind.SUBDOMAIN,
    "ports": FindingKind.OPEN_PORT,
    "tls": FindingKind.TLS_CERTIFICATE,
    "http": FindingKind.HTTP_SERVICE,
}


@dataclass(frozen=True, slots=True)
class ScanPayload:
    tenant_id: UUID
    run_id: UUID


@tenant_job
async def run_scheduled_scan(
    ctx: dict[str, Any],
    payload: ScanPayload,
    *,
    domain_sources: Iterable[ScanSource] | None = None,
) -> ScanRun | None:
    """Run all ASM stages under one run id and the shared lifecycle."""
    ctx["run_id"] = str(payload.run_id)
    return await execute_scan_run(
        ctx,
        lambda job_ctx, run: orchestrate_scan_run(
            job_ctx, run, domain_sources=domain_sources
        ),
    )


async def orchestrate_scan_run(
    ctx: dict[str, Any],
    run: ScanRun,
    *,
    domain_sources: Iterable[ScanSource] | None = None,
) -> None:
    """Collect scanner stages, then persist their union and snapshots once."""
    session = ctx["db"]
    target = await TargetRepository(session).get_by_id(run.target_id)
    if target is None:
        raise ValueError("Scan target not found.")
    if target.kind not in {"domain", "hostname", "ipv4", "ipv6"}:
        raise ValueError("ASM scans require a domain, hostname, or IP target.")

    # A queued job may outlive the scope configuration it was admitted under.
    # Refuse the root before a data source or scanner performs any work.
    await check_scope(target.value_normalized)
    logger.info(
        "scan.started",
        scan_run_id=str(run.id),
        target_id=str(target.id),
        target_kind=target.kind,
    )

    attempted: list[str] = []
    degraded: list[str] = []
    degradation_notes: list[str] = []
    items: list[dict[str, Any]] = []
    kinds = set(_SOURCE_KINDS.values())
    hostnames = [target.value_normalized]

    if target.kind == "domain":
        supplied_sources = tuple(domain_sources) if domain_sources is not None else None
        if supplied_sources is None:
            attempted.extend(("dns", "crtsh"))
        else:
            attempted.extend(source.name for source in supplied_sources)
        try:
            if domain_sources is None:
                async with httpx.AsyncClient() as client:
                    sources: Iterable[ScanSource] = (
                        DNSSource(),
                        CertificateTransparencySource(client=client),
                    )
                    discovery = await collect_domain_discoveries(
                        ctx, run, sources=sources
                    )
            else:
                discovery = await collect_domain_discoveries(
                    ctx, run, sources=supplied_sources or ()
                )
        except Exception as error:  # noqa: BLE001 - discovery degradation must not abort other stages.
            degraded.extend(attempted)
            degradation_notes.append(
                f"subdomain_discovery: stage failed ({type(error).__name__})"
            )
        else:
            items.extend(discovery.items)
            hostnames = list(discovery.hostnames)
            degraded.extend(discovery.sources_degraded)
            degradation_notes.extend(discovery.degradation_notes)
    else:
        kinds.discard(FindingKind.SUBDOMAIN)

    candidates = list(dict.fromkeys([target.value_normalized, *hostnames]))
    if len(candidates) > MAX_PORT_SCAN_HOSTS:
        candidates = candidates[:MAX_PORT_SCAN_HOSTS]
        degraded.extend(("ports", "tls", "http"))
        degradation_notes.append(
            f"port_scan: host limit reached ({MAX_PORT_SCAN_HOSTS}); remaining hosts deferred"
        )

    attempted.extend(("ports", "tls", "http"))
    for host in candidates:
        try:
            # A SAN or passive result is not trusted because its parent was
            # in scope. Every candidate re-enters the W4-02 gate independently.
            await check_scope(host)
        except ScopeViolationError as error:
            degraded.extend(("ports", "tls", "http"))
            degradation_notes.append(
                f"ports: discovered host refused ({error.reason.value})"
            )
            continue
        except Exception as error:  # noqa: BLE001 - one discovered host must not abort the scan.
            degraded.extend(("ports", "tls", "http"))
            degradation_notes.append(
                f"ports: discovered host check failed ({type(error).__name__})"
            )
            continue

        try:
            report = await scan_host(host)
        except Exception as error:  # noqa: BLE001 - port failures preserve other hosts' findings.
            degraded.extend(("ports", "tls", "http"))
            degradation_notes.append(
                f"ports: host scan failed ({type(error).__name__})"
            )
            logger.warning(
                "scan.stage_degraded",
                scan_run_id=str(run.id),
                stage="ports",
                error=type(error).__name__,
            )
            continue
        if report.attempted == 0:
            degraded.append("ports")
            degradation_notes.append("ports: no in-scope port attempts")

        identity_domain = target.value_normalized if target.kind == "domain" else None
        try:
            port_collection = await collect_port_scan_findings(
                target_id=target.id,
                run_id=run.id,
                host=host,
                domain=identity_domain,
                report=report,
            )
            items.extend(port_collection.items)
            degraded.extend(port_collection.sources_degraded)
            degradation_notes.extend(port_collection.degradation_notes)
        except Exception as error:  # noqa: BLE001 - TLS enrichment must not discard open ports.
            degraded.extend(("ports", "tls"))
            degradation_notes.append(
                f"tls: finding collection failed ({type(error).__name__})"
            )
            items.extend(_open_port_items(target.id, run.id, host, report.open_ports))

        try:
            services = await probe_open_ports(host, report.open_ports)
        except Exception as error:  # noqa: BLE001 - HTTP failure is local to this stage.
            degraded.append("http")
            degradation_notes.append(f"http: probe failed ({type(error).__name__})")
            logger.warning(
                "scan.stage_degraded",
                scan_run_id=str(run.id),
                stage="http",
                error=type(error).__name__,
            )
        else:
            items.extend(
                http_service_finding_items(
                    target_id=target.id, run_id=run.id, services=services
                )
            )

    # Multiple certificates can advertise the same SAN. Keep one observation
    # per ADR-0004 identity before sending a single upsert batch.
    items_by_fingerprint: dict[str, dict[str, Any]] = {}
    for item in items:
        kind = FindingKind(item["kind"])
        normalized = normalize_finding_value(kind, item["value"])
        fingerprint = compute_fingerprint(kind, target.id, normalized)
        items_by_fingerprint[fingerprint] = item
    items = list(items_by_fingerprint.values())

    degraded = list(dict.fromkeys(degraded))
    degraded_kinds = {
        _SOURCE_KINDS[source] for source in degraded if source in _SOURCE_KINDS
    }
    run.sources_attempted = list(dict.fromkeys(attempted))
    run.sources_degraded = degraded
    run.error_message = "; ".join(dict.fromkeys(degradation_notes))[:2000] or None

    for stage in run.sources_attempted:
        if stage in degraded:
            logger.warning("scan.stage_degraded", scan_run_id=str(run.id), stage=stage)
        else:
            logger.info("scan.stage_completed", scan_run_id=str(run.id), stage=stage)

    summary = await FindingRepository(session).persist_discovery_run(
        target_id=target.id,
        run_id=run.id,
        items=items,
        kinds=kinds,
        degraded=bool(degraded_kinds),
        degraded_kinds=degraded_kinds,
        return_summary=True,
    )
    assert isinstance(summary, DiscoveryPersistenceSummary)
    run.findings_count = summary.total
    run.new_findings_count = summary.new
    session.add(run)
    await session.commit()
    logger.info(
        "scan.completed",
        scan_run_id=str(run.id),
        findings_count=run.findings_count,
        new_findings_count=run.new_findings_count,
        degraded_sources=run.sources_degraded,
    )


def _open_port_items(
    target_id: UUID, run_id: UUID, host: str, ports: list[int]
) -> list[dict[str, Any]]:
    return [
        {
            "target_id": target_id,
            "run_id": run_id,
            "kind": FindingKind.OPEN_PORT,
            "value": f"{host}:{port}/tcp",
            "severity": "info",
            "details": {"port": port, "protocol": "tcp"},
        }
        for port in ports
    ]
