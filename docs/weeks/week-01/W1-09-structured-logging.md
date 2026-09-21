# W1-09 · Structured logging and request ID middleware

**GitHub issue:** [#9](https://github.com/emad-anwer/tem-platform/issues/9)

**Owner:** Tasneem · **Reviewer:** Islam · **Effort:** 3h · **Depends on:** #4

## What

- JSON-structured log output, not prose strings
- Middleware that generates a request ID (or accepts an inbound `X-Request-ID`) and binds it to
  the logging context
- Every log line emitted during a request carries that ID
- The ID comes back in the response header, and in error bodies (#8)
- Log level configurable through Settings

## Expected outcome

Make one request. Show in the PR that every log line it produced shares one request ID — and that
a second concurrent request has a different one.

## Non-negotiable

**No secrets, tokens, passwords, or API keys in logs. Ever.** Not at debug level, not "just
temporarily." Week 2 adds JWTs and a Zitadel masterkey — the habit needs to exist before then.

## Search for

- structlog contextvars
- Python JSON logging formatter
- FastAPI middleware request ID
- X-Request-ID header
- contextvars asyncio
