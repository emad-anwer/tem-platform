# Logging Documentation

This document explains how logging is configured in `tem-platform` and how developers should use it to ensure all logs are structured properly.

## Overview

The platform uses **structured JSON logging** powered by [`structlog`](https://www.structlog.org/). This ensures logs are machine-readable, indexable, and ready for log aggregators (like ELK, Datadog, or Grafana Loki).

We also implement a **Request ID Middleware**. Every HTTP request automatically gets a unique `request_id` (either generated via UUID4 or inherited from the `X-Request-ID` header). This ID is bound to the logging context and automatically appears in *every* log line emitted during the lifecycle of that request.

---

## How to Log

Always use `structlog.get_logger(__name__)` to instantiate a logger at the module level.

```python
import structlog

logger = structlog.get_logger(__name__)

async def my_business_logic(user_id: int):
    # Basic logging
    logger.info("processing_user", user_id=user_id)
    
    try:
        # DO NOT use string interpolation for data!
        # Wrong: logger.error(f"Failed to process user {user_id}: {exc}")
        
        # Right: Pass data as kwargs. 
        # If logging an exception, use logger.exception to automatically include the traceback
        raise ValueError("Database timeout")
    except ValueError as e:
        logger.exception("user_processing_failed", user_id=user_id)
```

### Best Practices

1. **Static Event Names:** The primary message (the first argument) should be a static, snake_case event name (e.g., `"user_created"`, `"database_connected"`).
2. **Context as Kwargs:** Pass all variable data as keyword arguments. This makes the data queryable.
3. **Never format strings:** Avoid `logger.info(f"User {user_id}")`. This defeats the purpose of structured logging.

---

## Standard Library Compatibility

The platform automatically bridges the Python standard library `logging` module to `structlog`. 

This means that third-party libraries (like SQLAlchemy, FastAPI, httpx) that use `logging.getLogger()` will automatically have their output converted to JSON and enriched with the `request_id`. You do not need to do anything special to capture their logs.

---

## Request Context and Error Bodies

The `RequestIDMiddleware` manages context variables. It binds the `request_id` when the request starts and clears it when the request ends. 

If an exception occurs and propagates to FastAPI, our custom exception handlers (in `src/app/core/errors.py`) will automatically include the `request_id` in the JSON response body. This allows clients to report the `request_id` to support for easy tracing.

Example 500 Response (RFC 9457 compliant):
```json
{
  "type": "https://tem-platform.dev/problems/internal-error",
  "title": "Internal Server Error",
  "status": 500,
  "detail": "An unexpected server error occurred.",
  "instance": "/api/v1/some-endpoint",
  "request_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef"
}
```
