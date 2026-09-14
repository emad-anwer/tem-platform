import dns.resolver
import httpx
import pytest

from app.core.discovery import (
    CertificateTransparencySource,
    DNSSource,
    SourceResult,
    _normalise_hostname,
)


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
