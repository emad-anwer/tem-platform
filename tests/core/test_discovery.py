import asyncio

import dns.resolver
import httpx
import pytest

from app.core.auth.context import set_current_principal
from app.core.auth.principal import Principal, Role
from app.core.discovery import (
    CertificateTransparencySource,
    DNSSource,
    SourceResult,
    _normalise_hostname,
    discover_domain,
)
from app.core.fingerprint import FindingKind
from app.core.repository import FindingRepository, ScanRunRepository, TargetRepository


@pytest.fixture
def crtsh_route(mock_jwks_endpoint):
    routes = []

    def register(**kwargs):
        route = mock_jwks_endpoint.get("https://crt.sh/").mock(**kwargs)
        mock_jwks_endpoint.routes._routes.remove(route)
        mock_jwks_endpoint.routes._routes.insert(0, route)
        routes.append(route)
        return route

    yield register

    for route in routes:
        mock_jwks_endpoint.routes._routes.remove(route)


class FakeResolver:
    def __init__(self, records: dict[str, set[str]]) -> None:
        self.records = records
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, hostname: str, record_type: str, *, lifetime: float):
        self.calls.append((hostname, record_type))
        return self.records.get(record_type, set())


class FailingResolver:
    """Resolver that simulates DNS infrastructure failures."""

    def __init__(self, exception: Exception) -> None:
        self.exception = exception
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, hostname: str, record_type: str, *, lifetime: float):
        self.calls.append((hostname, record_type))
        raise self.exception


class StaticSource:
    name = "static"

    def __init__(self, items: set[str] | None = None) -> None:
        self.items = items

    async def collect(self, domain: str) -> SourceResult:
        return SourceResult(
            self.items if self.items is not None else {f"admin.{domain}"}
        )


@pytest.mark.asyncio
async def test_discovery_upsert_is_idempotent_and_tenant_scoped(
    db_session, two_tenants
) -> None:
    tenant_a, tenant_b = two_tenants
    target_ids = []

    for tenant, user_id in ((tenant_a, "user-a"), (tenant_b, "user-b")):
        set_current_principal(
            Principal(user_id=user_id, tenant_id=tenant.id, role=Role.OWNER)
        )
        target = await TargetRepository(db_session).create(
            kind="domain", value="example.com", value_normalized="example.com"
        )
        target_ids.append(target.id)

    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant_a.id, role=Role.OWNER)
    )
    run_results = []
    for _ in range(3):
        run = await ScanRunRepository(db_session).create(
            target_id=target_ids[0], max_attempts=3
        )
        await discover_domain({"db": db_session}, run, sources=(StaticSource(),))
        run_results.append(run)
        await asyncio.sleep(0.001)

    assert [run.new_findings_count for run in run_results] == [2, 0, 0]
    assert [run.findings_count for run in run_results] == [2, 2, 2]

    findings_a, _ = await FindingRepository(db_session).list()
    assert len(findings_a) == 2
    assert {finding.value for finding in findings_a} == {
        "example.com",
        "admin.example.com",
    }
    for finding in findings_a:
        assert finding.times_seen == 3
        assert finding.first_seen_at < finding.last_seen_at
        assert finding.status == "active"

    set_current_principal(
        Principal(user_id="user-b", tenant_id=tenant_b.id, role=Role.OWNER)
    )
    run_b = await ScanRunRepository(db_session).create(
        target_id=target_ids[1], max_attempts=3
    )
    await discover_domain({"db": db_session}, run_b, sources=(StaticSource(),))

    findings_b, _ = await FindingRepository(db_session).list()
    assert len(findings_b) == 2
    assert {finding.fingerprint for finding in findings_a}.isdisjoint(
        {finding.fingerprint for finding in findings_b}
    )


@pytest.mark.asyncio
async def test_discovery_keeps_missing_findings_as_resolved(
    db_session, two_tenants
) -> None:
    tenant, _ = two_tenants
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant.id, role=Role.OWNER)
    )
    target = await TargetRepository(db_session).create(
        kind="domain", value="example.com", value_normalized="example.com"
    )
    run = await ScanRunRepository(db_session).create(
        target_id=target.id, max_attempts=3
    )
    await discover_domain({"db": db_session}, run, sources=(StaticSource(),))

    second_run = await ScanRunRepository(db_session).create(
        target_id=target.id, max_attempts=3
    )
    await discover_domain(
        {"db": db_session},
        second_run,
        sources=(StaticSource(set()),),
    )

    findings, _ = await FindingRepository(db_session).list()
    assert len(findings) == 2
    assert {finding.value: finding.status for finding in findings} == {
        "example.com": "active",
        "admin.example.com": "resolved",
    }


@pytest.mark.asyncio
async def test_subdomain_scan_does_not_resolve_other_finding_kinds(
    db_session, two_tenants
) -> None:
    tenant, _ = two_tenants
    set_current_principal(
        Principal(user_id="user-a", tenant_id=tenant.id, role=Role.OWNER)
    )
    target = await TargetRepository(db_session).create(
        kind="domain", value="example.com", value_normalized="example.com"
    )
    seed_run = await ScanRunRepository(db_session).create(
        target_id=target.id, max_attempts=3
    )
    repository = FindingRepository(db_session)
    await repository.upsert_discovery_batch(
        [
            {
                "target_id": target.id,
                "run_id": seed_run.id,
                "kind": FindingKind.SUBDOMAIN,
                "value": "admin.example.com",
            },
            {
                "target_id": target.id,
                "run_id": seed_run.id,
                "kind": FindingKind.OPEN_PORT,
                "value": "admin.example.com:443/tcp",
            },
        ]
    )

    scan_run = await ScanRunRepository(db_session).create(
        target_id=target.id, max_attempts=3
    )
    await discover_domain({"db": db_session}, scan_run, sources=(StaticSource(set()),))

    findings, _ = await repository.list(limit=10)
    status_by_identity = {
        (finding.kind, finding.value_normalized): finding.status for finding in findings
    }
    assert status_by_identity == {
        (FindingKind.SUBDOMAIN, "admin.example.com"): "resolved",
        (FindingKind.OPEN_PORT, "admin.example.com:443/tcp"): "active",
        (FindingKind.SUBDOMAIN, "example.com"): "active",
    }


@pytest.mark.asyncio
async def test_dns_source_uses_async_record_types_and_bounds_work() -> None:
    resolver = FakeResolver({"CNAME": {"edge.example.net."}})
    source = DNSSource(resolver=resolver, concurrency=2)

    result = await source.collect("example.com")

    assert result == SourceResult({"example.com"})
    assert {record_type for _, record_type in resolver.calls} == {"A", "AAAA", "CNAME"}


@pytest.mark.asyncio
async def test_crtsh_normalizes_wildcards_and_discards_out_of_scope_names(
    crtsh_route,
) -> None:
    route = crtsh_route(
        return_value=httpx.Response(
            200,
            json=[
                {"name_value": "WWW.Example.com.\n*.api.example.com"},
                {"name_value": "other.example.net"},
            ],
        )
    )

    async with httpx.AsyncClient() as client:
        result = await CertificateTransparencySource(client=client).collect(
            "example.com"
        )

    assert route.called
    assert result.items == {"www.example.com"}
    assert result.degraded is False


@pytest.mark.asyncio
async def test_crtsh_502_degrades_without_raising(crtsh_route) -> None:
    crtsh_route(return_value=httpx.Response(502))

    async with httpx.AsyncClient() as client:
        result = await CertificateTransparencySource(client=client).collect(
            "example.com"
        )

    assert result.items == set()
    assert result.degraded is True
    assert result.note == "crt.sh unavailable"


@pytest.mark.asyncio
async def test_crtsh_timeout_degrades_without_raising(crtsh_route) -> None:
    crtsh_route(side_effect=httpx.ReadTimeout("timed out"))

    async with httpx.AsyncClient() as client:
        result = await CertificateTransparencySource(client=client).collect(
            "example.com"
        )

    assert result.items == set()
    assert result.degraded is True


@pytest.mark.asyncio
async def test_dns_nxdomain_returns_empty_result() -> None:
    """NXDOMAIN should return empty set (normal non-existent hostname)."""
    resolver = FailingResolver(dns.resolver.NXDOMAIN())
    source = DNSSource(resolver=resolver, concurrency=2)

    result = await source.collect("nonexistent.example.com")

    assert result.items == set()
    assert result.degraded is False


@pytest.mark.asyncio
async def test_dns_timeout_returns_degraded_result() -> None:
    """DNS timeout should return degraded result (infrastructure failure)."""
    resolver = FailingResolver(dns.resolver.Timeout())
    source = DNSSource(resolver=resolver, concurrency=2)

    result = await source.collect("example.com")

    assert result.items == set()
    assert result.degraded is True
    assert result.note == "DNS lookup failed"


@pytest.mark.asyncio
async def test_dns_resolve_many_propagates_degradation() -> None:
    """resolve_many should propagate degradation notes from infrastructure failures."""
    resolver = FailingResolver(dns.resolver.Timeout())
    source = DNSSource(resolver=resolver, concurrency=2)

    result = await source.resolve_many(["example.com", "test.example.com"])

    assert result.items == set()
    assert result.degraded is True
    assert "DNS infrastructure failure" in result.note


def test_normalise_hostname_rejects_wildcards() -> None:
    """Wildcard entries should be rejected (return empty string)."""
    assert _normalise_hostname("*.example.com") == ""
    assert _normalise_hostname("*.api.example.com") == ""
    assert _normalise_hostname("api.example.com") == "api.example.com"
    assert _normalise_hostname("WWW.Example.com.") == "www.example.com"
    assert _normalise_hostname("Example.COM.") == "example.com"
