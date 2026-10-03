from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from app.core.discovery import _belongs_to_domain, _normalise_hostname
from app.core.fingerprint import (
    FindingKind,
    compute_fingerprint,
    normalize_finding_value,
)
from app.core.repository import FindingRepository
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
    """Persist open ports, TLS certificates, and in-domain DNS SAN observations."""
    normalized_domain = _normalise_hostname(domain)
    if not normalized_domain:
        raise ValueError("domain must be a valid hostname")

    items = []
    seen_service_fingerprints: set[str] = set()
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
        seen_service_fingerprints.add(
            compute_fingerprint(
                FindingKind.OPEN_PORT,
                target_id,
                normalize_finding_value(FindingKind.OPEN_PORT, value),
            )
        )

    semaphore = asyncio.Semaphore(TLS_PROBE_CONCURRENCY)

    async def inspect_tls(result: PortResult):
        async with semaphore:
            return await probe_tls_certificate(host, result.port)

    observations = await asyncio.gather(
        *(inspect_tls(result) for result in open_results)
    )
    seen_san_names: set[str] = set()
    for result, observation in zip(open_results, observations, strict=True):
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
        seen_service_fingerprints.add(
            compute_fingerprint(
                FindingKind.TLS_CERTIFICATE,
                target_id,
                normalize_finding_value(FindingKind.TLS_CERTIFICATE, certificate_value),
            )
        )
        for san_name in observation.dns_names:
            normalized_name = _normalise_hostname(san_name)
            if (
                normalized_name
                and normalized_name not in seen_san_names
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

    # SANs are additive observations: a certificate cannot establish that
    # DNS names absent from its SAN list are missing, so they are never resolved here.
    total, new = await repo.upsert_discovery_batch(items)

    resolved = 0
    if report.attempted > 0:  # a fully out-of-scope scan observed nothing
        resolved = await repo.resolve_missing_discoveries(
            target_id=target_id,
            seen_fingerprints=seen_service_fingerprints,
            kinds={FindingKind.OPEN_PORT, FindingKind.TLS_CERTIFICATE},
        )
    return PortFindingsSummary(total=total, new=new, resolved=resolved)


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
