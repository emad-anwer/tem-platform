# W1-08 · Error envelope and exception handlers

**GitHub issue:** [#8](https://github.com/emad-anwer/tem-platform/issues/8)

**Owner:** Islam · **Reviewer:** Tasneem · **Effort:** 3h · **Depends on:** #2, #4

## What

Implement whatever #2 decided. Not your own preference — the team's decision.

- Custom exception classes: `NotFoundError`, `ConflictError`, `ValidationError`
- FastAPI exception handlers mapping each to the agreed envelope and status code
- A handler for unhandled exceptions that returns a clean 500 — **never a stack trace**
- `request_id` included in every error response, matching the one from #9

## Expected outcome

Every error path in the API returns the same structure. Trigger a 404, a 409, a validation error
and an unhandled exception, and show all four in the PR description.

## Non-negotiable

No raw exception text, stack trace, or SQL error ever reaches a client. Those go to the logs.
A client gets a stable error code and a safe message.

## Search for

- FastAPI exception_handler
- RFC 9457 problem details
- FastAPI RequestValidationError handler
- custom exception hierarchy Python
