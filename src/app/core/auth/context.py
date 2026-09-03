"""Request and job scoped access to the authenticated principal."""

from __future__ import annotations

from contextvars import ContextVar, Token

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.auth.principal import Principal

_principal: ContextVar[Principal | None] = ContextVar(
    "principal", default=None
)


def set_current_principal(principal: Principal) -> Token[Principal | None]:
    """Set the principal for the current request or background task."""
    return _principal.set(principal)


def reset_current_principal(token: Token[Principal | None]) -> None:
    """Restore the principal that was active before a scoped operation."""
    _principal.reset(token)


def clear_current_principal() -> None:
    """Clear principal state in the current execution context."""
    _principal.set(None)


def get_current_principal() -> Principal:
    """Return the current principal, failing closed outside an auth scope."""
    principal = _principal.get()
    if principal is None:
        raise RuntimeError("No authenticated principal in the current context")
    return principal


class PrincipalContextMiddleware:
    """Keep principal state bounded to one HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = _principal.set(None)
        try:
            await self.app(scope, receive, send)
        finally:
            _principal.reset(token)