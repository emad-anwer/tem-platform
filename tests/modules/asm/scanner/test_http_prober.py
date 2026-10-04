import httpx
import pytest

from app.core.scope import ScanScope
from app.modules.asm.scanner.http_prober import (
    MAX_BODY_BYTES,
    MAX_HEADER_VALUE_LENGTH,
    MAX_TITLE_LENGTH,
    _redirect_destination,
    probe_http_service,
)


def _client(handler, captured=None):
    def factory(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory


@pytest.mark.asyncio
async def test_bounded_http_observation_keeps_evidence_but_never_cookie_value():
    secret = "session-token-that-must-not-be-stored"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Server": "nginx/1.25.4",
                "X-Powered-By": "PHP/8.2.10",
                "Set-Cookie": f"PHPSESSID={secret}; HttpOnly",
            },
            content=(
                b"<title>" + b"x" * (MAX_TITLE_LENGTH + 10) + b"</title>wp-content"
            ),
            request=request,
        )

    result = await probe_http_service("lab-nginx", 80, client_factory=_client(handler))

    assert result is not None
    assert result.headers["Server"] == "nginx/1.25.4"
    assert result.cookie_names == ("PHPSESSID",)
    assert secret not in repr(result)
    assert result.title is not None and len(result.title) == MAX_TITLE_LENGTH
    assert {
        (claim["technology"], claim.get("version")) for claim in result.technologies
    } >= {
        ("nginx", "1.25.4"),
        ("PHP", "8.2.10"),
        ("WordPress", None),
    }


@pytest.mark.asyncio
async def test_redirects_stop_at_fixed_cap_and_use_standard_timeout():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        step = int(request.url.params.get("step", "0"))
        return httpx.Response(
            302,
            headers={"Location": f"/?step={step + 1}"},
            request=request,
        )

    result = await probe_http_service(
        "lab-nginx", 80, max_redirects=2, client_factory=_client(handler, captured)
    )

    assert result is not None
    assert result.status_code == 302
    assert result.redirects_followed == 2
    assert result.final_url.endswith("?step=2")
    assert captured["follow_redirects"] is False
    assert captured["timeout"].connect == 5.0
    assert captured["timeout"].read == 15.0


@pytest.mark.asyncio
async def test_oversized_body_and_headers_are_bounded():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Server": "n" * (MAX_HEADER_VALUE_LENGTH + 1)},
            content=b"a" * (MAX_BODY_BYTES + 1),
            request=request,
        )

    result = await probe_http_service("lab-nginx", 80, client_factory=_client(handler))

    assert result is not None
    assert result.body_truncated is True
    assert len(result.headers["Server"]) == MAX_HEADER_VALUE_LENGTH


@pytest.mark.asyncio
async def test_apache_is_not_mislabeled_as_nginx_and_protocol_errors_are_negative():
    def apache(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Server": "Apache/2.4.52 (Unix)"},
            request=request,
        )

    result = await probe_http_service("lab-apache", 80, client_factory=_client(apache))
    assert result is not None
    assert [
        (item["technology"], item.get("version")) for item in result.technologies
    ] == [("Apache HTTP Server", "2.4.52")]

    def broken(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("not HTTP")

    assert (
        await probe_http_service("lab-nginx", 9, client_factory=_client(broken)) is None
    )


@pytest.mark.asyncio
async def test_off_scope_redirect_is_recorded_but_never_followed():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            302,
            headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            request=request,
        )

    scope = ScanScope.parse(["lab-nginx"])
    result = await probe_http_service(
        "lab-nginx", 80, scope=scope, client_factory=_client(handler)
    )

    assert result is not None
    assert result.status_code == 302
    assert result.redirects_followed == 0
    assert calls == 1


@pytest.mark.asyncio
async def test_redirect_userinfo_is_never_followed_or_stored():
    secret = "s3cret"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                302,
                headers={"Location": f"http://admin:{secret}@lab-nginx/next"},
                request=request,
            )
        assert request.url.userinfo == b""
        return httpx.Response(200, request=request)

    result = await probe_http_service("lab-nginx", 80, client_factory=_client(handler))

    assert result is not None
    assert result.final_url == "http://lab-nginx/next"
    assert secret not in repr(result)
    assert (
        _redirect_destination("http://lab-nginx/", f"http://admin:{secret}@lab-nginx/")
        == "http://lab-nginx/"
    )
