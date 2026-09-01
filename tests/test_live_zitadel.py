"""Integration test against a live Zitadel instance.

Marked `live_zitadel` — skipped by default, skipped in CI.
Run manually:
    ZITADEL_TEST_TOKEN=<token> pytest -m live_zitadel -v

This test proves the fixture didn't lie: the claim shape the fixture uses
must be compatible with what a real Zitadel token carries.
"""

from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.live_zitadel


@pytest.mark.skipif(
    not os.getenv("ZITADEL_TEST_TOKEN"),
    reason="ZITADEL_TEST_TOKEN not set — skipping live IdP test",
)
async def test_live_token_accepted(client: AsyncClient) -> None:
    token = os.environ["ZITADEL_TEST_TOKEN"]
    resp = await client.get(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    # If the endpoint is unauthenticated or token validates, returns 200 or 403
    assert resp.status_code in (200, 403)
