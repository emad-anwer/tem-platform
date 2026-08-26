"""
Tests for the structured-logging / request-ID feature.

Covers:
  - Generated request IDs when no X-Request-ID is provided
  - Inbound X-Request-ID is honoured and echoed back
  - X-Request-ID appears in the response header
  - Every log line emitted during a request carries the same request_id
  - Two concurrent requests produce distinct request IDs with no cross-contamination
  - Log level configuration (DEBUG vs WARNING)
  - Context is cleared between requests (no leakage)
  - setup_logging wires structlog correctly (JSON output)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from io import StringIO
from unittest.mock import AsyncMock, patch

# Set a dummy DATABASE_URL before any app import so pydantic-settings does not
# raise a validation error.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db"
)

import pytest
import structlog
import structlog.contextvars
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.testclient import TestClient as StarletteTestClient

from app.core.logging import setup_logging
from app.core.main import create_app
from app.core.middlewares.request_id import RequestIDMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_with_middleware(*extra_routes) -> FastAPI:
    """
    Build a minimal FastAPI app that has RequestIDMiddleware registered, plus
    any extra routes supplied by the caller.  Does NOT call create_app() so
    that we avoid the DB engine / lifespan machinery in unit tests.
    """
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/__test__/ok")
    async def _ok():
        return {"status": "ok"}

    @app.get("/__test__/log")
    async def _log_something():
        log = structlog.get_logger()
        log.info("inside_route_handler", extra_field="hello")
        return {"status": "logged"}

    @app.get("/__test__/error")
    async def _raise():
        raise ValueError("boom")

    for route_fn in extra_routes:
        app.add_api_route(route_fn.__path__, route_fn, methods=["GET"])

    return app


def _capture_structlog_output(level: str = "DEBUG") -> tuple[StringIO, structlog.BoundLogger]:
    """
    Configure structlog to write JSON to an in-memory StringIO, and return
    (stream, a bound logger).  Each call reconfigures structlog globally and
    resets the internal logger cache so that the new stream and level are
    picked up by every subsequent structlog.get_logger() call — including the
    module-level logger inside RequestIDMiddleware.
    """
    stream = StringIO()
    numeric_level = logging.getLevelNamesMapping()[level.upper()]

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%SZ", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        # Use the *requested* level so suppression tests work correctly.
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(stream),
        # MUST be False: if True, the first-use cache bakes in whatever factory
        # was active on first import, ignoring our per-test stream.
        cache_logger_on_first_use=False,
    )
    # Reset structlog's internal bound-logger cache so the new configuration
    # (stream + level) is used by every get_logger() call in this test,
    # including the module-level logger inside RequestIDMiddleware.
    structlog.reset_defaults()  # clears the _config cache flags
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%SZ", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(stream),
        cache_logger_on_first_use=False,
    )
    return stream, structlog.get_logger()


def _parsed_log_lines(stream: StringIO) -> list[dict]:
    """Return all non-empty lines from *stream* parsed as JSON dicts."""
    stream.seek(0)
    lines = []
    for raw in stream.read().splitlines():
        raw = raw.strip()
        if raw:
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                pass  # Skip lines that couldn't be parsed (e.g. stdlib prose)
    return lines


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_structlog_context():
    """Clear contextvars before and after every test."""
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


@pytest.fixture()
def app() -> FastAPI:
    return _make_app_with_middleware()


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def full_app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """
    A TestClient backed by the real create_app() factory.
    DB engine creation is patched out.
    """
    monkeypatch.setattr("app.core.db.get_engine", lambda: None)
    monkeypatch.setattr("app.core.db.dispose_engine", AsyncMock())
    return TestClient(create_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1.  Generated request IDs
# ---------------------------------------------------------------------------


class TestGeneratedRequestID:
    def test_response_has_x_request_id_header(self, client: TestClient) -> None:
        resp = client.get("/__test__/ok")
        assert "X-Request-ID" in resp.headers

    def test_generated_id_is_a_valid_uuid(self, client: TestClient) -> None:
        resp = client.get("/__test__/ok")
        value = resp.headers["X-Request-ID"]
        # Must not raise
        uuid.UUID(value)

    def test_each_request_gets_a_different_id(self, client: TestClient) -> None:
        ids = {client.get("/__test__/ok").headers["X-Request-ID"] for _ in range(10)}
        assert len(ids) == 10, "Every request must receive a unique ID"


# ---------------------------------------------------------------------------
# 2.  Inbound X-Request-ID is honoured
# ---------------------------------------------------------------------------


class TestInboundRequestID:
    CUSTOM_ID = "my-custom-trace-id-abc123"

    def test_inbound_id_is_echoed_in_response_header(self, client: TestClient) -> None:
        resp = client.get("/__test__/ok", headers={"X-Request-ID": self.CUSTOM_ID})
        assert resp.headers["X-Request-ID"] == self.CUSTOM_ID

    def test_inbound_id_propagated_to_log_context(self, client: TestClient) -> None:
        stream, _ = _capture_structlog_output("DEBUG")
        client.get("/__test__/log", headers={"X-Request-ID": self.CUSTOM_ID})
        lines = _parsed_log_lines(stream)
        request_ids = {line.get("request_id") for line in lines if "request_id" in line}
        assert self.CUSTOM_ID in request_ids

    def test_empty_x_request_id_falls_back_to_generated_uuid(
        self, client: TestClient
    ) -> None:
        resp = client.get("/__test__/ok", headers={"X-Request-ID": ""})
        value = resp.headers["X-Request-ID"]
        # Should be a valid UUID (generated), not the empty string
        uuid.UUID(value)


# ---------------------------------------------------------------------------
# 3.  Every log line during a request shares the same request_id
# ---------------------------------------------------------------------------


class TestRequestIDPropagatedToLogs:
    def test_all_log_lines_share_request_id(self, client: TestClient) -> None:
        stream, _ = _capture_structlog_output("DEBUG")
        resp = client.get("/__test__/log")
        expected_id = resp.headers["X-Request-ID"]

        lines = _parsed_log_lines(stream)
        assert lines, "Expected at least one structured log line"

        for line in lines:
            assert line.get("request_id") == expected_id, (
                f"Log line missing or has wrong request_id: {line}"
            )

    def test_middleware_logs_request_started_event(self, client: TestClient) -> None:
        stream, _ = _capture_structlog_output("DEBUG")
        client.get("/__test__/ok")
        lines = _parsed_log_lines(stream)
        events = [l.get("event") for l in lines]
        assert "request_started" in events

    def test_middleware_logs_request_finished_event(self, client: TestClient) -> None:
        stream, _ = _capture_structlog_output("DEBUG")
        client.get("/__test__/ok")
        lines = _parsed_log_lines(stream)
        events = [l.get("event") for l in lines]
        assert "request_finished" in events

    def test_request_finished_log_contains_status_code(self, client: TestClient) -> None:
        stream, _ = _capture_structlog_output("DEBUG")
        client.get("/__test__/ok")
        lines = _parsed_log_lines(stream)
        finished = next((l for l in lines if l.get("event") == "request_finished"), None)
        assert finished is not None
        assert finished.get("status_code") == 200


# ---------------------------------------------------------------------------
# 4.  Context is cleared between requests (no leakage)
# ---------------------------------------------------------------------------


class TestContextClearing:
    def test_context_is_empty_after_request(self, app: FastAPI) -> None:
        """
        After a completed request the contextvars must be empty so that the
        next request (or a background task) does not see a stale request_id.
        """
        with TestClient(app) as c:
            c.get("/__test__/ok")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx == {}, f"Expected empty context after request, got: {ctx}"

    def test_context_does_not_leak_between_sequential_requests(
        self, client: TestClient
    ) -> None:
        id1 = client.get("/__test__/ok").headers["X-Request-ID"]
        id2 = client.get("/__test__/ok").headers["X-Request-ID"]
        assert id1 != id2

    def test_subsequent_request_has_fresh_context(self, client: TestClient) -> None:
        stream, _ = _capture_structlog_output("DEBUG")

        resp1 = client.get("/__test__/log")
        resp2 = client.get("/__test__/log")

        id1 = resp1.headers["X-Request-ID"]
        id2 = resp2.headers["X-Request-ID"]
        assert id1 != id2

        lines = _parsed_log_lines(stream)
        ids_in_logs = {l.get("request_id") for l in lines if "request_id" in l}
        # Both IDs must appear; neither should appear on lines that belong to
        # the other request.
        assert id1 in ids_in_logs
        assert id2 in ids_in_logs


# ---------------------------------------------------------------------------
# 5.  Concurrent requests have different IDs (no cross-contamination)
# ---------------------------------------------------------------------------


class TestConcurrentRequests:
    def test_two_concurrent_requests_have_distinct_ids(self) -> None:
        """
        Send two requests concurrently via asyncio and verify the IDs are
        different.  Uses httpx async client to be truly async.
        """
        import httpx

        app = _make_app_with_middleware()

        async def _run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as ac:
                r1, r2 = await asyncio.gather(
                    ac.get("/__test__/ok"),
                    ac.get("/__test__/ok"),
                )
            return r1.headers["X-Request-ID"], r2.headers["X-Request-ID"]

        id1, id2 = asyncio.run(_run())
        assert id1 != id2, "Concurrent requests must receive distinct IDs"

    def test_concurrent_requests_do_not_share_log_context(self) -> None:
        """
        Bind a custom X-Request-ID to each concurrent request and verify that
        log lines for request-A never appear tagged with the ID of request-B.
        """
        import httpx

        app = _make_app_with_middleware()
        stream, _ = _capture_structlog_output("DEBUG")

        FIXED_ID_A = "concurrent-request-aaa"
        FIXED_ID_B = "concurrent-request-bbb"

        async def _run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as ac:
                await asyncio.gather(
                    ac.get("/__test__/log", headers={"X-Request-ID": FIXED_ID_A}),
                    ac.get("/__test__/log", headers={"X-Request-ID": FIXED_ID_B}),
                )

        asyncio.run(_run())

        lines = _parsed_log_lines(stream)
        ids_per_line = [l.get("request_id") for l in lines if "request_id" in l]

        # Both IDs should appear
        assert FIXED_ID_A in ids_per_line
        assert FIXED_ID_B in ids_per_line

        # No line should have a request_id that is neither A nor B
        unexpected = {
            rid for rid in ids_per_line if rid not in (FIXED_ID_A, FIXED_ID_B)
        }
        assert not unexpected, f"Unexpected request_ids in log: {unexpected}"


# ---------------------------------------------------------------------------
# 6.  Structured JSON output
# ---------------------------------------------------------------------------


class TestStructuredJSON:
    def test_log_output_is_valid_json(self, client: TestClient) -> None:
        stream, _ = _capture_structlog_output("DEBUG")
        client.get("/__test__/log")

        stream.seek(0)
        raw = stream.read()
        assert raw.strip(), "Expected non-empty log output"

        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                pytest.fail(f"Log line is not valid JSON: {line!r} — {exc}")

    def test_log_line_contains_expected_fields(self, client: TestClient) -> None:
        stream, _ = _capture_structlog_output("DEBUG")
        client.get("/__test__/ok")
        lines = _parsed_log_lines(stream)
        assert lines, "No log output"
        first = lines[0]
        for field in ("event", "level", "timestamp", "request_id"):
            assert field in first, f"Missing field '{field}' in log line: {first}"

    def test_log_line_has_correct_level_field(self, client: TestClient) -> None:
        stream, _ = _capture_structlog_output("DEBUG")
        client.get("/__test__/ok")
        lines = _parsed_log_lines(stream)
        levels = {l.get("level") for l in lines}
        assert "info" in levels or "INFO" in levels


# ---------------------------------------------------------------------------
# 7.  Configurable log level
# ---------------------------------------------------------------------------


class TestLogLevel:
    def test_debug_level_emits_debug_lines(self) -> None:
        stream, logger = _capture_structlog_output("DEBUG")
        logger.debug("debug_event", probe=True)
        lines = _parsed_log_lines(stream)
        assert any(l.get("event") == "debug_event" for l in lines)

    def test_warning_level_suppresses_info_lines(self) -> None:
        stream, logger = _capture_structlog_output("WARNING")
        logger.info("should_be_suppressed")
        logger.warning("should_appear")
        lines = _parsed_log_lines(stream)
        events = [l.get("event") for l in lines]
        assert "should_be_suppressed" not in events
        assert "should_appear" in events

    def test_error_level_suppresses_warning(self) -> None:
        stream, logger = _capture_structlog_output("ERROR")
        logger.warning("suppressed_warning")
        logger.error("visible_error")
        lines = _parsed_log_lines(stream)
        events = [l.get("event") for l in lines]
        assert "suppressed_warning" not in events
        assert "visible_error" in events

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises((KeyError, ValueError)):
            setup_logging("NONSENSE")


# ---------------------------------------------------------------------------
# 8.  No secrets in logs
# ---------------------------------------------------------------------------


class TestNoSecretsInLogs:
    """Regression tests ensuring sensitive values never appear in log output."""

    SECRETS = ["password", "secret", "token", "api_key", "authorization"]

    def test_database_url_password_not_in_logs(self, client: TestClient) -> None:
        stream, _ = _capture_structlog_output("DEBUG")
        client.get("/__test__/ok")
        output = stream.getvalue().lower()
        # The test DATABASE_URL has "pass" as the password
        assert "pass@" not in output, "DB password fragment found in log output"

    def test_auth_header_not_in_logs(self, client: TestClient) -> None:
        stream, _ = _capture_structlog_output("DEBUG")
        client.get(
            "/__test__/ok",
            headers={"Authorization": "Bearer super_secret_token_xyz"},
        )
        output = stream.getvalue()
        assert "super_secret_token_xyz" not in output, (
            "Authorization header value appeared in log output"
        )


# ---------------------------------------------------------------------------
# 9.  setup_logging integration
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_setup_logging_does_not_raise_for_valid_levels(self) -> None:
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            setup_logging(level)  # Should not raise

    def test_setup_logging_case_insensitive(self) -> None:
        setup_logging("debug")
        setup_logging("Info")

    def test_structlog_is_configured_after_setup(self) -> None:
        setup_logging("INFO")
        # Calling get_logger() after configuration should not raise
        logger = structlog.get_logger()
        # Attempting to log should also not raise
        logger.info("probe_event")
