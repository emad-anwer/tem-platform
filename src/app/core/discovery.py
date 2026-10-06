from __future__ import annotations

import asyncio
import ipaddress
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

import dns.asyncresolver
import dns.exception
import dns.resolver
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fingerprint import (
    FindingKind,
)
from app.core.jobs.lifecycle import execute_scan_run
from app.core.jobs.timeouts import outbound_http_timeout
from app.core.models import ScanRun, Target
from app.core.rate_limit import SlidingWindowRateLimiter, configured_rate_limiter
from app.core.repository import FindingRepository, ScanRunRepository, TargetRepository
from app.core.scope import check_scope

DNS_RECORD_TYPES = ("A", "AAAA", "CNAME")
DEFAULT_MAX_RESULTS = 500
DEFAULT_DNS_CONCURRENCY = 50


@dataclass(frozen=True)
class SourceResult:
    items: set[str]
    degraded: bool = False
    note: str | None = None


class ScanSource(Protocol):
    name: str

    async def collect(self, domain: str) -> SourceResult:
        """Return candidate hostnames and degrade instead of raising upstream errors."""
        ...


class DNSSource:
    name = "dns"

    def __init__(
        self,
        *,
        resolver: dns.asyncresolver.Resolver | None = None,
        concurrency: int = DEFAULT_DNS_CONCURRENCY,
        timeout: float = 5.0,
        limiter: SlidingWindowRateLimiter | None = None,
    ) -> None:
        self._resolver = resolver or dns.asyncresolver.Resolver()
        self._concurrency = concurrency
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(concurrency)
        self._limiter = limiter or configured_rate_limiter()
        self._can_wait: Callable[[float], bool] | None = None

    def set_wait_guard(self, can_wait: Callable[[float], bool]) -> None:
        self._can_wait = can_wait

    async def collect(self, domain: str) -> SourceResult:
        try:
            await self.resolve(domain)
        except dns.resolver.NXDOMAIN:
            return SourceResult(set())
        except dns.exception.DNSException:
            return SourceResult(set(), degraded=True, note="DNS lookup failed")
        return SourceResult({domain})

    async def resolve(self, hostname: str) -> set[str]:
        async def resolve_type(record_type: str) -> set[str]:
            async with self._semaphore:
                try:
                    # Immediately before the resolver's network call: this is
                    # a mechanism, not a request for callers to remember.
                    await self._limiter.wait_for_permission(
                        f"dns:{hostname}",
                        operation="dns",
                        can_wait=self._can_wait,
                    )
                    answer = await self._resolver.resolve(
                        hostname,
                        record_type,
                        lifetime=self._timeout,
                    )
                except dns.resolver.NXDOMAIN:
                    raise
                except dns.resolver.NoAnswer:
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
        return {item for group in records for item in group}

    async def resolve_many(self, hostnames: Iterable[str]) -> SourceResult:
        names = sorted(set(hostnames))
        degraded = False
        note = None

        async def resolve_one(hostname: str) -> set[str]:
            nonlocal degraded, note
            try:
                return await self.resolve(hostname)
            except dns.resolver.NXDOMAIN:
                return set()
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
        limiter: SlidingWindowRateLimiter | None = None,
    ) -> None:
        self._client = client
        self._max_results = max_results
        self._limiter = limiter or configured_rate_limiter()
        self._can_wait: Callable[[float], bool] | None = None

    def set_wait_guard(self, can_wait: Callable[[float], bool]) -> None:
        self._can_wait = can_wait

    async def collect(self, domain: str) -> SourceResult:
        query = f"%.{domain}"

        await self._limiter.wait_for_permission(
            "crt.sh", operation="http", can_wait=self._can_wait
        )

        try:
            response = await self._client.get(
                "https://crt.sh/",
                params={"q": query, "output": "json"},
                timeout=outbound_http_timeout(),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, TypeError, ValueError):
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


async def _load_domain_target(
    session: AsyncSession, target_id: Any
) -> tuple[Target, str]:
    """Fetch the target, validate it as a domain, and re-check scope in-worker."""
    target = await _get_target(session, target_id)
    if target.kind != "domain":
        raise ValueError("Only domain targets can use subdomain discovery.")
    domain = _normalise_hostname(target.value_normalized)
    if not domain or not _is_domain(domain):
        raise ValueError("Target is not a valid domain.")

    # W4-02: the worker re-checks scope itself — the API refusing to queue a
    # scan is not the same guarantee as a job refusing to run one. A refusal
    # raises ScopeViolationError, which execute_scan_run turns into a terminal
    # failure instead of a retry loop.
    await check_scope(domain)
    return target, domain


async def _resolve_with_dns(
    source_list: list[ScanSource],
    names: set[str],
    degraded: list[str],
    degradation_notes: list[str],
) -> None:
    """Resolve everything collected so far through the DNS source, if present."""
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


@dataclass(frozen=True, slots=True)
class DiscoveryCollection:
    hostnames: tuple[str, ...]
    items: tuple[dict[str, Any], ...]
    sources_attempted: tuple[str, ...]
    sources_degraded: tuple[str, ...]
    degradation_notes: tuple[str, ...]


async def collect_domain_discoveries(
    ctx: dict[str, Any],
    run: ScanRun,
    *,
    sources: Iterable[ScanSource],
    max_results: int = DEFAULT_MAX_RESULTS,
) -> DiscoveryCollection:
    """Collect in-domain hostnames and findings without committing a partial run."""
    _target, domain = await _load_domain_target(ctx["db"], run.target_id)
    source_list = list(sources)
    deadline = ctx.get("scan_deadline_monotonic")
    if deadline is not None:

        def can_wait(wait: float) -> bool:
            return time.monotonic() + wait < deadline

        for source in source_list:
            set_guard = getattr(source, "set_wait_guard", None)
            if set_guard is not None:
                set_guard(can_wait)

    names = {domain}
    degraded: list[str] = []
    degradation_notes: list[str] = []
    results = await asyncio.gather(
        *(source.collect(domain) for source in source_list), return_exceptions=True
    )
    for source, result in zip(source_list, results, strict=True):
        if isinstance(result, BaseException):
            if not isinstance(result, Exception):
                raise result
            degraded.append(source.name)
            degradation_notes.append(
                f"{source.name}: source failed ({type(result).__name__})"
            )
            continue
        names.update(result.items)
        if result.degraded:
            degraded.append(source.name)
            if result.note:
                degradation_notes.append(f"{source.name}: {result.note}")

    try:
        await _resolve_with_dns(source_list, names, degraded, degradation_notes)
    except Exception as error:
        dns_source = next(
            (source for source in source_list if isinstance(source, DNSSource)), None
        )
        if dns_source is None:
            raise
        degraded.append(dns_source.name)
        degradation_notes.append(
            f"{dns_source.name}: resolution failed ({type(error).__name__})"
        )

    hostnames = tuple(
        sorted(
            {
                name
                for name in (_normalise_hostname(item) for item in names)
                if name and _belongs_to_domain(name, domain)
            }
        )[:max_results]
    )
    items = tuple(
        {
            "target_id": run.target_id,
            "run_id": run.id,
            "kind": FindingKind.SUBDOMAIN,
            "value": name,
        }
        for name in hostnames
    )
    return DiscoveryCollection(
        hostnames=hostnames,
        items=items,
        sources_attempted=tuple(source.name for source in source_list),
        sources_degraded=tuple(dict.fromkeys(degraded)),
        degradation_notes=tuple(dict.fromkeys(degradation_notes)),
    )


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
    collection = await collect_domain_discoveries(
        ctx, run, sources=sources, max_results=max_results
    )
    await _record_sources(
        ctx["db"],
        run.id,
        list(collection.sources_attempted),
        list(collection.sources_degraded),
        list(collection.degradation_notes),
    )

    if persist_finding:
        repository = FindingRepository(ctx["db"])
        new_findings_count = await repository.persist_discovery_run(
            target_id=target.id,
            run_id=run.id,
            items=collection.items,
            kinds={FindingKind.SUBDOMAIN},
            degraded=bool(collection.sources_degraded),
        )
    else:
        new_findings_count = 0

    run.findings_count = len(collection.hostnames)
    run.new_findings_count = new_findings_count
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
