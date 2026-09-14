from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import dns.asyncresolver
import dns.exception
import dns.resolver
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.job_context import tenant_job
from app.core.jobs.lifecycle import execute_scan_run
from app.core.jobs.timeouts import outbound_http_timeout
from app.core.models import ScanRun, Target
from app.core.repository import FindingRepository, ScanRunRepository, TargetRepository

DNS_RECORD_TYPES = ("A", "AAAA", "CNAME")
DEFAULT_MAX_RESULTS = 500
DEFAULT_DNS_CONCURRENCY = 50


@dataclass(frozen=True)
class SourceResult:
    items: set[str]
    degraded: bool = False
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SubdomainDiscoveryPayload:
    tenant_id: UUID
    run_id: UUID


class ScanSource(Protocol):
    name: str

    async def collect(self, domain: str) -> SourceResult:
        """Return candidate hostnames and degrade instead of raising upstream errors."""


class DNSSource:
    name = "dns"

    def __init__(
        self,
        *,
        resolver: dns.asyncresolver.Resolver | None = None,
        concurrency: int = DEFAULT_DNS_CONCURRENCY,
        timeout: float = 5.0,
    ) -> None:
        self._resolver = resolver or dns.asyncresolver.Resolver()
        self._concurrency = concurrency
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(concurrency)

    async def collect(self, domain: str) -> SourceResult:
        try:
            await self.resolve(domain)
        except dns.exception.DNSException:
            return SourceResult(set(), degraded=True, note="DNS lookup failed")
        return SourceResult({domain})

    async def resolve(self, hostname: str) -> set[str]:
        async def resolve_type(record_type: str) -> set[str]:
            async with self._semaphore:
                try:
                    answer = await self._resolver.resolve(
                        hostname,
                        record_type,
                        lifetime=self._timeout,
                    )
                except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                    return set()
                except (
                    dns.resolver.Timeout,
                    dns.resolver.NoNameservers,
                    dns.exception.DNSException,
                ) as e:
                    raise dns.exception.DNSException(
                        f"DNS infrastructure failure: {type(e).__name__}"
                    ) from e
                return {
                    _normalise_hostname(str(record))
                    for record in answer
                    if record_type == "CNAME"
                }

        records = await asyncio.gather(
            *(resolve_type(kind) for kind in DNS_RECORD_TYPES)
        )
        return {hostname, *(item for group in records for item in group)}

    async def resolve_many(self, hostnames: Iterable[str]) -> SourceResult:
        names = sorted(set(hostnames))
        degraded = False
        note = None

        async def resolve_one(hostname: str) -> set[str]:
            nonlocal degraded, note
            try:
                return await self.resolve(hostname)
            except dns.exception.DNSException as e:
                degraded = True
                note = f"DNS infrastructure failure: {type(e).__name__}"
                return set()

        results = await asyncio.gather(*(resolve_one(name) for name in names))
        resolved = {item for group in results for item in group}
        return SourceResult(resolved, degraded=degraded, note=note)


class CertificateTransparencySource:
    name = "crtsh"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> None:
        self._client = client
        self._max_results = max_results

    async def collect(self, domain: str) -> SourceResult:
        query = f"%.{domain}"
        try:
            response = await self._client.get(
                "https://crt.sh/",
                params={"q": query, "output": "json"},
                timeout=outbound_http_timeout(),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError):
            return SourceResult(set(), degraded=True, note="crt.sh unavailable")

        names: set[str] = set()
        for record in payload if isinstance(payload, list) else []:
            if not isinstance(record, dict):
                continue
            for name in str(record.get("name_value", "")).splitlines():
                normalised = _normalise_hostname(name)
                if normalised and _belongs_to_domain(normalised, domain):
                    names.add(normalised)
                if len(names) >= self._max_results:
                    return SourceResult(names)
        return SourceResult(names)


async def discover_domain(
    ctx: dict[str, Any],
    run: ScanRun,
    *,
    sources: Iterable[ScanSource],
    max_results: int = DEFAULT_MAX_RESULTS,
    persist_finding: bool = True,
) -> None:
    """Collect, normalize, resolve, and persist passive domain discoveries."""
    target = await _get_target(ctx["db"], run.target_id)
    if target.kind != "domain":
        raise ValueError("Only domain targets can use subdomain discovery.")
    domain = _normalise_hostname(target.value_normalized)
    if not domain or not _is_domain(domain):
        raise ValueError("Target is not a valid domain.")

    source_list = list(sources)
    await _record_sources(
        ctx["db"], run.id, [source.name for source in source_list], [], None
    )
    results = await asyncio.gather(*(source.collect(domain) for source in source_list))
    names = {domain}
    degraded: list[str] = []
    degradation_notes: list[str] = []
    for source, result in zip(source_list, results, strict=True):
        names.update(result.items)
        if result.degraded:
            degraded.append(source.name)
            if result.note:
                degradation_notes.append(f"{source.name}: {result.note}")

    dns_source = next(
        (source for source in source_list if isinstance(source, DNSSource)), None
    )
    if dns_source is not None:
        dns_result = await dns_source.resolve_many(names)
        names.update(dns_result.items)
        if dns_result.degraded:
            if dns_source.name not in degraded:
                degraded.append(dns_source.name)
            if dns_result.note:
                degradation_notes.append(f"{dns_source.name}: {dns_result.note}")

    names = {
        name
        for name in (_normalise_hostname(item) for item in names)
        if name and _belongs_to_domain(name, domain)
    }
    names = set(sorted(names)[:max_results])
    await _record_sources(
        ctx["db"],
        run.id,
        [source.name for source in source_list],
        degraded,
        degradation_notes,
    )

    if persist_finding:
        repository = FindingRepository(ctx["db"])
        for name in sorted(names):
            await repository.upsert_discovery(
                target_id=target.id,
                run_id=run.id,
                value=name,
                fingerprint=_fingerprint(target.id, name),
            )

    run.findings_count = len(names)
    run.new_findings_count = len(names)
    ctx["db"].add(run)
    await ctx["db"].commit()


async def run_subdomain_discovery(
    ctx: dict[str, Any],
    *,
    sources: Iterable[ScanSource],
) -> ScanRun | None:
    return await execute_scan_run(
        ctx,
        lambda job_ctx, run: discover_domain(job_ctx, run, sources=sources),
    )


@tenant_job
async def subdomain_discovery_job(
    ctx: dict[str, Any], payload: SubdomainDiscoveryPayload
) -> ScanRun | None:
    """Run passive DNS and certificate-transparency discovery for one run."""
    ctx["run_id"] = str(payload.run_id)
    async with httpx.AsyncClient() as client:
        sources: tuple[ScanSource, ...] = (
            DNSSource(),
            CertificateTransparencySource(client=client),
        )
        return await run_subdomain_discovery(ctx, sources=sources)


async def _get_target(session: AsyncSession, target_id: Any) -> Target:
    target = await TargetRepository(session).get_by_id(target_id)
    if target is None:
        raise ValueError("Target not found.")
    return target


async def _record_sources(
    session: AsyncSession,
    run_id: Any,
    attempted: list[str],
    degraded: list[str],
    degradation_notes: list[str] | None = None,
) -> None:
    repository = ScanRunRepository(session)
    run = await repository.get_by_id(run_id)
    if run is None:
        raise ValueError("Scan run not found.")
    run.sources_attempted = attempted
    run.sources_degraded = degraded
    if degradation_notes:
        run.error_message = "; ".join(degradation_notes)
    session.add(run)
    await session.commit()


def _normalise_hostname(value: str) -> str:
    name = value.strip().lower().rstrip(".")
    if name.startswith("*."):
        return ""
    try:
        return name.encode("idna").decode("ascii")
    except UnicodeError:
        return ""


def _belongs_to_domain(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def _is_domain(value: str) -> bool:
    if len(value) > 253 or "." not in value:
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return all(part and len(part) <= 63 for part in value.split("."))
    return False


def _fingerprint(target_id: Any, value: str) -> str:
    identity = f"subdomain|{target_id}|{value}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
