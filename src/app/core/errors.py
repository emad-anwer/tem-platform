from __future__ import annotations

from typing import Any

from fastapi import Request


class ProblemDetailError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        title: str,
        detail: str,
        problem_type: str,
        errors: list[dict[str, str]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.problem_type = problem_type
        self.errors = errors or []


class ValidationError(ProblemDetailError):
    def __init__(self, *, detail: str, errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(
            status_code=422,
            title="Validation Error",
            detail=detail,
            problem_type="validation-error",
            errors=errors,
        )


class NotFoundError(ProblemDetailError):
    def __init__(self, *, detail: str) -> None:
        super().__init__(
            status_code=404,
            title="Not Found",
            detail=detail,
            problem_type="not-found",
        )


class ConflictError(ProblemDetailError):
    def __init__(self, *, detail: str) -> None:
        super().__init__(
            status_code=409,
            title="Conflict",
            detail=detail,
            problem_type="conflict",
        )


def build_problem_details(
    *,
    request: Request,
    status: int,
    title: str,
    detail: str,
    problem_type: str,
    errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": f"https://tem-platform.dev/problems/{problem_type}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": str(request.url.path),
    }
    if errors:
        payload["errors"] = errors
    return payload
