from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from sqlalchemy import exc
import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)


class ZitadelUnavailableError(Exception):
    """Raised when Zitadel is unavailable."""


class ZitadelApiError(Exception):
    """Zitadel was reached but rejected the request (4xx)."""

    def __init__(self, message: str, *, status_code: int, body: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True, slots=True)
class ZitadelOrganization:
    org_id: str
    name: str


class ZitadelManagementClient:
    """Client for Zitadel's management API."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client or httpx.AsyncClient(
            base_url=self.settings.zitadel_issuer,
            timeout=self.settings.zitadel_http_timeout_seconds,
        )
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def _get_management_token(self) -> str:
        """Get a management token from Zitadel, caching it until it expires."""
        now = time.monotonic()
        if self._token and now < self._token_expires_at:
            return self._token

        try:
            response = await self.http_client.post(
                "/oauth/v2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.zitadel_management_client_id,
                    "client_secret": self.settings.zitadel_management_client_secret,
                },
            )
        except httpx.HTTPError as exc:
            raise ZitadelUnavailableError(
                "Unable to reach Zitadel token endpoint"
            ) from exc

        if response.status_code >= 500:
            raise ZitadelUnavailableError(
                f"Zitadel token endpoint returned {response.status_code}"
            )
        if response.status_code >= 400:
            raise ZitadelApiError(
                "Zitadel rejected management credentials",
                status_code=response.status_code,
                body=response.text,
            )

        data = response.json()
        self._token = data["access_token"]
        self._token_expires_at = (
            now + data.get("expires_in", 3600) - 10
        )  # refresh 10s before expiry
        return self._token

    async def create_organization(self, *, name: str) -> ZitadelOrganization:
        """Create a new organization in Zitadel."""
        token = await self._get_management_token()
        try:
            response = await self.http_client.post(
                "/management/v1/orgs",
                json={"name": name},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TimeoutException as exc:
            raise ZitadelUnavailableError(
                "Timed out calling Zitadel management API"
            ) from exc
        except httpx.HTTPError as exc:
            raise ZitadelUnavailableError(
                "Unable to reach Zitadel management API"
            ) from exc

        if response.status_code >= 500:
            raise ZitadelUnavailableError(
                f"Zitadel management API returned {response.status_code}"
            )
        if response.status_code >= 400:
            raise ZitadelApiError(
                "Zitadel rejected organization creation",
                status_code=response.status_code,
                body=response.text,
            )

        return ZitadelOrganization(org_id=response.json()["id"], name=name)

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self.http_client.aclose()


def get_zitadel_client() -> ZitadelManagementClient:
    return ZitadelManagementClient()
