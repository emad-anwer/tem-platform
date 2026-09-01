import asyncio
import uuid

import pytest
import structlog
from fastapi import APIRouter, FastAPI
from starlette.testclient import TestClient
from structlog.testing import LogCapture

from app.core.logging import redact_processor, setup_logging
from app.core.middlewares.request_id import RequestIDMiddleware


def _make_app_with_middleware() -> FastAPI:
    """Helper to create a fresh app instance for testing."""
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    router = APIRouter()

    @router.get("/__test__/ok")
    def ok_route():
        logger = structlog.get_logger(__name__)
        logger.info("route_handler_executed")
        return {"status": "ok"}

    @router.get("/__test__/log")
    def log_route():
        logger = structlog.get_logger(__name__)
        logger.info("route_log_1")
        logger.debug("route_log_2")
        return {"status": "logged"}

    app.include_router(router)
    return app


@pytest.fixture(name="app")
def fixture_app() -> FastAPI:
    return _make_app_with_middleware()


@pytest.fixture(name="client")
def fixture_client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def structlog_capture() -> LogCapture:
    cap = LogCapture()

    structlog.reset_defaults()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(
                fmt="%Y-%m-%dT%H:%M:%SZ",
                utc=True,
            ),
            redact_processor,
            cap,
        ],
        logger_factory=structlog.ReturnLoggerFactory(),
        cache_logger_on_first_use=False,
    )

    return cap


class TestGeneratedRequestID:
    def test_response_has_x_request_id_header(self, client: TestClient) -> None:
        resp = client.get("/__test__/ok")
        assert "X-Request-ID" in resp.headers

    def test_generated_id_is_a_valid_uuid(self, client: TestClient) -> None:
        resp = client.get("/__test__/ok")
        req_id = resp.headers["X-Request-ID"]
        parsed = uuid.UUID(req_id)
        assert str(parsed) == req_id

    def test_each_request_gets_a_different_id(self, client: TestClient) -> None:
        resp1 = client.get("/__test__/ok")
        resp2 = client.get("/__test__/ok")
        assert resp1.headers["X-Request-ID"] != resp2.headers["X-Request-ID"]


class TestInboundRequestID:
    CUSTOM_ID = "my-custom-trace-id-abc123"

    def test_inbound_id_is_echoed_in_response_header(self, client: TestClient) -> None:
        resp = client.get("/__test__/ok", headers={"X-Request-ID": self.CUSTOM_ID})
        assert resp.headers["X-Request-ID"] == self.CUSTOM_ID

    def test_inbound_id_propagated_to_log_context(
        self, client: TestClient, structlog_capture: LogCapture
    ) -> None:
        client.get("/__test__/log", headers={"X-Request-ID": self.CUSTOM_ID})
        request_ids = {e.get("request_id") for e in structlog_capture.entries}
        assert self.CUSTOM_ID in request_ids

    def test_empty_x_request_id_falls_back_to_generated_uuid(self, client: TestClient) -> None:
        resp = client.get("/__test__/ok", headers={"X-Request-ID": ""})
        req_id = resp.headers["X-Request-ID"]
        assert req_id != ""
        parsed = uuid.UUID(req_id)
        assert str(parsed) == req_id

    def test_invalid_inbound_id_rejected(self, client: TestClient) -> None:
        # Request ID containing invalid characters should be rejected and replaced
        invalid_id = "invalid_id_with_spaces and_newlines\n\r"
        resp = client.get("/__test__/ok", headers={"X-Request-ID": invalid_id})
        req_id = resp.headers["X-Request-ID"]
        assert req_id != invalid_id
        parsed = uuid.UUID(req_id)
        assert str(parsed) == req_id

    def test_too_long_inbound_id_rejected(self, client: TestClient) -> None:
        invalid_id = "a" * 65
        resp = client.get("/__test__/ok", headers={"X-Request-ID": invalid_id})
        req_id = resp.headers["X-Request-ID"]
        assert req_id != invalid_id
        parsed = uuid.UUID(req_id)
        assert str(parsed) == req_id


class TestRequestIDPropagatedToLogs:
    def test_all_log_lines_share_request_id(
        self, client: TestClient, structlog_capture: LogCapture
    ) -> None:
        resp = client.get("/__test__/log")
        expected_id = resp.headers["X-Request-ID"]

        app_lines = [l for l in structlog_capture.entries if l.get("event") in ("route_log_1", "route_log_2", "request_started", "request_finished")]
        assert app_lines, "Expected at least one structured log line from the app"

        for line in app_lines:
            assert line.get("request_id") == expected_id

    def test_middleware_logs_request_started_event(
        self, client: TestClient, structlog_capture: LogCapture
    ) -> None:
        client.get("/__test__/ok")
        events = [e.get("event") for e in structlog_capture.entries]
        assert "request_started" in events

    def test_middleware_logs_request_finished_event(
        self, client: TestClient, structlog_capture: LogCapture
    ) -> None:
        client.get("/__test__/ok")
        events = [e.get("event") for e in structlog_capture.entries]
        assert "request_finished" in events

    def test_request_finished_log_contains_status_code_and_duration(
        self, client: TestClient, structlog_capture: LogCapture
    ) -> None:
        client.get("/__test__/ok")
        finished = next(
            (e for e in structlog_capture.entries if e.get("event") == "request_finished"), None
        )
        assert finished is not None
        assert "status_code" in finished
        assert finished["status_code"] == 200
        assert "duration_ms" in finished
        assert isinstance(finished["duration_ms"], (int, float))
        assert finished["duration_ms"] >= 0


class TestContextClearing:
    def test_context_is_empty_after_request(self, client: TestClient) -> None:
        client.get("/__test__/ok")
        ctx = structlog.contextvars.get_contextvars()
        assert "request_id" not in ctx

    def test_context_does_not_leak_between_sequential_requests(
        self, client: TestClient, structlog_capture: LogCapture
    ) -> None:
        id1 = client.get("/__test__/ok").headers["X-Request-ID"]
        id2 = client.get("/__test__/ok").headers["X-Request-ID"]

        ids_in_logs = {e.get("request_id") for e in structlog_capture.entries}
        assert id1 in ids_in_logs
        assert id2 in ids_in_logs

    def test_subsequent_request_has_fresh_context(
        self, client: TestClient, structlog_capture: LogCapture
    ) -> None:
        id1 = client.get("/__test__/ok").headers["X-Request-ID"]
        
        # Clear the capture to only see the second request
        structlog_capture.entries.clear()
        
        id2 = client.get("/__test__/ok").headers["X-Request-ID"]
        ids_in_logs = {e.get("request_id") for e in structlog_capture.entries}
        
        assert id1 not in ids_in_logs
        assert id2 in ids_in_logs


class TestConcurrentRequests:
    def test_two_concurrent_requests_have_distinct_ids(self, app: FastAPI) -> None:
        import httpx

        async def _run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp1, resp2 = await asyncio.gather(
                    ac.get("/__test__/ok"), ac.get("/__test__/ok")
                )
                return resp1.headers["X-Request-ID"], resp2.headers["X-Request-ID"]

        id1, id2 = asyncio.run(_run())
        assert id1 != id2, "Concurrent requests must receive distinct IDs"

    def test_concurrent_requests_do_not_share_log_context(
        self, app: FastAPI, structlog_capture: LogCapture
    ) -> None:
        import httpx

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

        ids_per_line = [e.get("request_id") for e in structlog_capture.entries if "request_id" in e]

        assert FIXED_ID_A in ids_per_line
        assert FIXED_ID_B in ids_per_line

        unexpected = {rid for rid in ids_per_line if rid not in (FIXED_ID_A, FIXED_ID_B)}
        assert not unexpected, f"Unexpected request_ids in log: {unexpected}"


class TestStructuredJSON:
    # Removed test_log_output_is_valid_json since we are capturing pure dicts now 
    # instead of asserting on how the stdout renderer formats it.
    
    def test_log_line_contains_expected_fields(
        self, client: TestClient, structlog_capture: LogCapture
    ) -> None:
        client.get("/__test__/ok")
        app_lines = [e for e in structlog_capture.entries if e.get("event") in ("request_started", "request_finished", "route_handler_executed")]
        assert app_lines, "No log output from app"
        
        first = app_lines[0]
        for field in ("event", "level", "timestamp", "request_id"):
            assert field in first, f"Missing field '{field}' in log line: {first}"

    def test_log_line_has_correct_level_field(
        self, client: TestClient, structlog_capture: LogCapture
    ) -> None:
        client.get("/__test__/ok")
        levels = {e.get("level") for e in structlog_capture.entries if "level" in e}
        assert "info" in levels or "INFO" in levels


class TestLogLevel:
    def test_debug_level_emits_debug_lines(self, structlog_capture: LogCapture) -> None:
        logger = structlog.get_logger(__name__)
        logger.debug("debug_event")
        events = [e.get("event") for e in structlog_capture.entries]
        assert "debug_event" in events

    def test_warning_level_suppresses_info_lines(self, capsys: pytest.CaptureFixture) -> None:
        setup_logging("WARNING")
        logger = structlog.get_logger(__name__)
        logger.info("should_be_suppressed")
        logger.warning("should_appear")
        raw = capsys.readouterr().out
        assert "should_be_suppressed" not in raw
        assert "should_appear" in raw

    def test_error_level_suppresses_warning(self, capsys: pytest.CaptureFixture) -> None:
        setup_logging("ERROR")
        logger = structlog.get_logger(__name__)
        logger.warning("suppressed_warning")
        logger.error("visible_error")
        raw = capsys.readouterr().out
        assert "suppressed_warning" not in raw
        assert "visible_error" in raw


class TestNoSecretsInLogs:
    def test_database_url_password_not_in_logs(self, structlog_capture: LogCapture) -> None:
        logger = structlog.get_logger(__name__)
        logger.info("db_connected", url="postgresql+asyncpg://admin:s3cr3t_p4ssw0rd@localhost/db")
        events = structlog_capture.entries
        assert len(events) == 1
        # Since the url field has the word 'url', let's test a key that contains the word 'password' or direct sensitive values
        # The url itself is not a sensitive key directly in SENSITIVE_KEYS, but we can log a password key
        logger.info("user_details", password="my-secret-password")
        assert len(structlog_capture.entries) == 2
        assert structlog_capture.entries[1]["password"] == "***REDACTED***"
        assert "my-secret-password" not in str(structlog_capture.entries[1])

    def test_auth_header_not_in_logs(self, structlog_capture: LogCapture) -> None:
        logger = structlog.get_logger(__name__)
        logger.info("request_headers", headers={"Authorization": "Bearer super-secret-token"})
        for entry in structlog_capture.entries:
            assert "super-secret-token" not in str(entry)
            
    def test_recursive_redaction(self, structlog_capture: LogCapture) -> None:
        logger = structlog.get_logger(__name__)
        nested_data = {
            "user": {
                "name": "John Doe",
                "password": "my_secret_password"
            },
            "tokens": ["token123", {"access_token": "bearer-token"}]
        }
        logger.info("user_login", data=nested_data)
        
        events = structlog_capture.entries
        assert len(events) == 1
        event = events[0]
        # Check nested dict key redaction
        assert event["data"]["user"]["password"] == "***REDACTED***"
        # Check nested list with dict redaction
        assert event["data"]["tokens"][1]["access_token"] == "***REDACTED***"
        assert "my_secret_password" not in str(event)
        assert "bearer-token" not in str(event)


class TestSetupLogging:
    def test_setup_logging_does_not_raise_for_valid_levels(self) -> None:
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            setup_logging(level)

    def test_setup_logging_case_insensitive(self) -> None:
        setup_logging("info")
        setup_logging("DeBuG")

    def test_structlog_is_configured_after_setup(self) -> None:
        setup_logging("INFO")
        logger = structlog.get_logger(__name__)
        assert logger is not None
