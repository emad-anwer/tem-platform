import httpx
import pytest

from app.core.discovery import CertificateTransparencySource, DNSSource, SourceResult


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
    assert result.items == {"www.example.com", "api.example.com"}
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
