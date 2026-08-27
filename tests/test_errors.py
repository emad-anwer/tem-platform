import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db"
)

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
import pytest

from app.core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
    register_error_handlers,
)
from app.core.main import create_app


class ItemPayload(BaseModel):
    name: str = Field(min_length=3)
    count: int = Field(gt=0)


def create_test_app() -> FastAPI:
    app = create_app()
    router = APIRouter(prefix="/test-errors")

    @router.get("/not-found")
    async def trigger_not_found():
        raise NotFoundError("Tenant '3fa85f64-5717-4562-b3fc-2c963f66afa6' does not exist.")

    @router.get("/conflict")
    async def trigger_conflict():
        raise ConflictError("Slug 'acme-corp' already exists.")

    @router.post("/validation")
    async def trigger_validation(payload: ItemPayload):
        return {"ok": True}

    @router.get("/manual-validation-error")
    async def trigger_manual_validation():
        raise ValidationError(
            "Validation failed.",
            errors=[{"field": "slug", "message": "must be lowercase"}],
        )

    @router.get("/unhandled-500")
    async def trigger_unhandled():
        raise RuntimeError("Database connection pool crashed! Secret SQL: SELECT * FROM secrets;")

    @router.get("/http-exception-403")
    async def trigger_http_forbidden():
        raise HTTPException(status_code=403, detail="Forbidden access to resource.")

    @router.get("/bad-request")
    async def trigger_bad_request():
        raise BadRequestError("Invalid filter parameter 'foo'.")

    @router.get("/unauthorized")
    async def trigger_unauthorized():
        raise UnauthorizedError("Missing authorization bearer token.")

    @router.get("/rate-limited")
    async def trigger_rate_limited():
        raise RateLimitedError("Too many scan requests.")

    @router.get("/service-unavailable")
    async def trigger_service_unavailable():
        raise ServiceUnavailableError("Database is down.")

    app.include_router(router)
    return app


@pytest.fixture
def client() -> TestClient:
    app = create_test_app()
    return TestClient(app, raise_server_exceptions=False)


def test_not_found_error_returns_rfc9457(client: TestClient) -> None:
    response = client.get("/test-errors/not-found")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert "x-request-id" in response.headers

    body = response.json()
    assert body["type"] == "https://tem-platform.dev/problems/not-found"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["detail"] == "Tenant '3fa85f64-5717-4562-b3fc-2c963f66afa6' does not exist."
    assert body["instance"] == "/test-errors/not-found"
    assert "request_id" in body
    assert body["request_id"] == response.headers["x-request-id"]


def test_conflict_error_returns_rfc9457(client: TestClient) -> None:
    response = client.get("/test-errors/conflict")

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"

    body = response.json()
    assert body["type"] == "https://tem-platform.dev/problems/conflict"
    assert body["title"] == "Conflict"
    assert body["status"] == 409
    assert body["detail"] == "Slug 'acme-corp' already exists."
    assert body["instance"] == "/test-errors/conflict"
    assert "request_id" in body


def test_request_validation_error_returns_rfc9457(client: TestClient) -> None:
    response = client.post("/test-errors/validation", json={"name": "a", "count": -1})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"

    body = response.json()
    assert body["type"] == "https://tem-platform.dev/problems/validation-error"
    assert body["title"] == "Validation Error"
    assert body["status"] == 422
    assert body["detail"] == "One or more fields failed validation."
    assert body["instance"] == "/test-errors/validation"
    assert "errors" in body
    assert len(body["errors"]) == 2
    fields = [err["field"] for err in body["errors"]]
    assert "name" in fields
    assert "count" in fields


def test_manual_validation_error_returns_rfc9457(client: TestClient) -> None:
    response = client.get("/test-errors/manual-validation-error")

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"

    body = response.json()
    assert body["type"] == "https://tem-platform.dev/problems/validation-error"
    assert body["title"] == "Validation Error"
    assert body["status"] == 422
    assert body["errors"] == [{"field": "slug", "message": "must be lowercase"}]


def test_unhandled_500_hides_stack_trace_and_raw_exception(client: TestClient) -> None:
    response = client.get("/test-errors/unhandled-500")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"

    body = response.json()
    assert body["type"] == "https://tem-platform.dev/problems/internal-error"
    assert body["title"] == "Internal Server Error"
    assert body["status"] == 500
    assert body["detail"] == "An unexpected server error occurred."
    assert body["instance"] == "/test-errors/unhandled-500"
    assert "request_id" in body
    # Crucial security check: raw exception / SQL string must never leak
    assert "Database connection pool crashed" not in response.text
    assert "SELECT * FROM secrets" not in response.text
    assert "traceback" not in response.text.lower()


def test_starlette_http_exception_returns_rfc9457(client: TestClient) -> None:
    response = client.get("/test-errors/http-exception-403")

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"

    body = response.json()
    assert body["type"] == "https://tem-platform.dev/problems/forbidden"
    assert body["title"] == "Forbidden"
    assert body["status"] == 403
    assert body["detail"] == "Forbidden access to resource."
    assert body["instance"] == "/test-errors/http-exception-403"


def test_custom_app_errors(client: TestClient) -> None:
    res_bad = client.get("/test-errors/bad-request")
    assert res_bad.status_code == 400
    assert res_bad.json()["type"] == "https://tem-platform.dev/problems/bad-request"

    res_unauth = client.get("/test-errors/unauthorized")
    assert res_unauth.status_code == 401
    assert res_unauth.json()["type"] == "https://tem-platform.dev/problems/unauthorized"

    res_rate = client.get("/test-errors/rate-limited")
    assert res_rate.status_code == 429
    assert res_rate.json()["type"] == "https://tem-platform.dev/problems/rate-limited"

    res_serv = client.get("/test-errors/service-unavailable")
    assert res_serv.status_code == 503
    assert res_serv.json()["type"] == "https://tem-platform.dev/problems/service-unavailable"


def test_x_request_id_forwarding(client: TestClient) -> None:
    custom_id = "test-request-id-12345"
    response = client.get("/test-errors/not-found", headers={"X-Request-ID": custom_id})

    assert response.status_code == 404
    assert response.headers["x-request-id"] == custom_id
    assert response.json()["request_id"] == custom_id
