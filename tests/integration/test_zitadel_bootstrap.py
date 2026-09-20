"""Minimal tests for Zitadel bootstrap idempotency.

Run with: pytest tests/integration/test_zitadel_bootstrap.py -v

Requires a running Zitadel instance (use `just zitadel-up` first).
Tests auto-skip if Zitadel is unreachable.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

# Set defaults for the Docker environment before importing the bootstrap module.
# These match the service names and paths in compose.yaml.
os.environ.setdefault("ZITADEL_ISSUER", "http://zitadel:8080")
os.environ.setdefault("ZITADEL_BOOTSTRAP_PAT_PATH", "/run/zitadel-bootstrap/admin.pat")
os.environ.setdefault("ZITADEL_DEV_PASSWORD", "DevOnlyPassw0rd!")

# Import the module under test. Adjust the path to match your project layout.
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from zitadel_bootstrap import (
    APPLICATION_NAME,
    DEV_ORG_NAME,
    PROJECT_NAME,
    ROLES,
    Config,
    ZitadelClient,
)

# ---------------------------------------------------------------------------
# Skip helper
# ---------------------------------------------------------------------------


def _zitadel_available() -> bool:
    """Check if Zitadel is reachable."""
    issuer = os.getenv("ZITADEL_ISSUER", "http://zitadel:8080").rstrip("/")
    try:
        req = urllib.request.Request(f"{issuer}/debug/ready", method="GET")
        with urllib.request.urlopen(req, timeout=5):
            return True
    except (urllib.error.URLError, TimeoutError):
        return False


ZITADEL_AVAILABLE = _zitadel_available()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


@pytest.mark.skipif(not ZITADEL_AVAILABLE, reason="Zitadel not available")
class TestZitadelBootstrap:
    """End-to-end idempotency tests against a real Zitadel instance."""

    @pytest.fixture(scope="class")
    def client(self) -> ZitadelClient:
        """Provide a configured ZitadelClient (does NOT run bootstrap)."""
        config = Config.from_env()
        return ZitadelClient(config)

    @pytest.fixture(scope="class")
    def bootstrapped(self, client: ZitadelClient) -> ZitadelClient:
        """Run a full bootstrap once before the test class."""
        client.wait_until_ready()
        token = client.wait_for_pat()
        client.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        client.bootstrap()
        return client

    # -------------------------------------------------------------------
    # 1. Fresh bootstrap (baseline correctness)
    # -------------------------------------------------------------------

    def test_fresh_project_exists(self, bootstrapped: ZitadelClient) -> None:
        """After bootstrap, the project exists with the correct name."""
        project = bootstrapped.find_project()
        assert project is not None
        assert project["name"] == PROJECT_NAME
        assert project.get("projectRoleAssertion") is True

    def test_fresh_roles_exist(self, bootstrapped: ZitadelClient) -> None:
        """All three ADR-0002 roles exist on the project."""
        project = bootstrapped.find_project()
        assert project is not None
        roles = bootstrapped.search_project_roles(project["id"])
        role_keys = {r["key"] for r in roles}
        assert role_keys == set(ROLES.keys())

    def test_fresh_application_exists(self, bootstrapped: ZitadelClient) -> None:
        """The OIDC application exists with JWT token type and role assertion."""
        project = bootstrapped.find_project()
        assert project is not None
        apps = bootstrapped.search_applications(project["id"])
        app = next((a for a in apps if a.get("name") == APPLICATION_NAME), None)
        assert app is not None
        config = app.get("oidcConfig", {})
        assert config.get("accessTokenType") == "OIDC_TOKEN_TYPE_JWT"
        assert config.get("accessTokenRoleAssertion") is True
        assert config.get("idTokenRoleAssertion") is True

    def test_fresh_organization_exists(self, bootstrapped: ZitadelClient) -> None:
        """The dev organization exists."""
        orgs = bootstrapped.search_organizations()
        org = next((o for o in orgs if o.get("name") == DEV_ORG_NAME), None)
        assert org is not None

    def test_fresh_dev_user_exists(self, bootstrapped: ZitadelClient) -> None:
        """The dev user exists in the dev org with the correct email."""
        orgs = bootstrapped.search_organizations()
        org = next((o for o in orgs if o.get("name") == DEV_ORG_NAME), None)
        assert org is not None
        users = bootstrapped.search_users(org["id"])
        assert len(users) == 1
        assert users[0]["userName"] == bootstrapped.config.dev_username

    def test_fresh_user_has_all_roles(self, bootstrapped: ZitadelClient) -> None:
        """The dev user has been granted all three roles."""
        orgs = bootstrapped.search_organizations()
        org = next((o for o in orgs if o.get("name") == DEV_ORG_NAME), None)
        assert org is not None
        users = bootstrapped.search_users(org["id"])
        user_id = users[0]["id"]
        grants = bootstrapped.search_user_grants(user_id, org["id"])
        assert len(grants) == 1
        # Management API returns roleKeys, not roles
        assert set(grants[0].get("roleKeys", [])) == set(ROLES.keys())

    # -------------------------------------------------------------------
    # 2. Idempotent re-run (run bootstrap twice, no errors, no duplicates)
    # -------------------------------------------------------------------

    def test_rerun_is_idempotent(self, bootstrapped: ZitadelClient) -> None:
        """Running bootstrap a second time must not fail or create duplicates."""
        # Capture state after first run
        project_1 = bootstrapped.find_project()
        assert project_1 is not None
        project_id_1 = project_1["id"]
        roles_1 = bootstrapped.search_project_roles(project_id_1)
        apps_1 = bootstrapped.search_applications(project_id_1)
        orgs_1 = bootstrapped.search_organizations()
        org = next((o for o in orgs_1 if o.get("name") == DEV_ORG_NAME), None)
        assert org is not None
        users_1 = bootstrapped.search_users(org["id"])
        grants_1 = bootstrapped.search_user_grants(users_1[0]["id"], org["id"])

        # Run bootstrap again
        bootstrapped.bootstrap()

        # Verify nothing changed (no new IDs, no duplicates)
        project_2 = bootstrapped.find_project()
        assert project_2 is not None
        assert project_2["id"] == project_id_1  # Same project

        roles_2 = bootstrapped.search_project_roles(project_id_1)
        assert len(roles_2) == len(roles_1)  # No duplicate roles

        apps_2 = bootstrapped.search_applications(project_id_1)
        assert len(apps_2) == len(apps_1)  # No duplicate apps

        users_2 = bootstrapped.search_users(org["id"])
        assert len(users_2) == len(users_1)  # No duplicate users

        grants_2 = bootstrapped.search_user_grants(users_2[0]["id"], org["id"])
        assert len(grants_2) == len(grants_1)  # No duplicate grants
        # Management API returns roleKeys, not roles
        assert set(grants_2[0].get("roleKeys", [])) == set(ROLES.keys())

    # -------------------------------------------------------------------
    # 3. Partial state: project exists but one role is missing
    # -------------------------------------------------------------------

    def test_partial_missing_role_is_reconciled(
        self, bootstrapped: ZitadelClient
    ) -> None:
        """If a role is deleted manually, re-running bootstrap recreates it."""
        project = bootstrapped.find_project()
        assert project is not None
        project_id = project["id"]

        # Delete the "analyst" role directly via API
        req = urllib.request.Request(
            f"{bootstrapped.config.issuer}/management/v1/projects/{project_id}/roles/analyst",
            headers=bootstrapped.headers,
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(req, timeout=30):
                pass
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

        # Verify it is gone
        roles_before = bootstrapped.search_project_roles(project_id)
        role_keys_before = {r["key"] for r in roles_before}
        assert "analyst" not in role_keys_before

        # Re-run bootstrap
        bootstrapped.ensure_project_roles(project_id)

        # Verify it is back
        roles_after = bootstrapped.search_project_roles(project_id)
        role_keys_after = {r["key"] for r in roles_after}
        assert role_keys_after == set(ROLES.keys())

    def test_partial_missing_app_is_reconciled(
        self, bootstrapped: ZitadelClient
    ) -> None:
        """If the application is deleted manually, re-running bootstrap recreates it."""
        project = bootstrapped.find_project()
        assert project is not None
        project_id = project["id"]

        # Find and delete the application
        apps = bootstrapped.search_applications(project_id)
        app = next((a for a in apps if a.get("name") == APPLICATION_NAME), None)
        assert app is not None

        req = urllib.request.Request(
            f"{bootstrapped.config.issuer}/management/v1/projects/{project_id}/apps/{app['id']}",
            headers=bootstrapped.headers,
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(req, timeout=30):
                pass
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

        # Verify it is gone
        apps_before = bootstrapped.search_applications(project_id)
        assert not any(a.get("name") == APPLICATION_NAME for a in apps_before)

        # Re-run just the application ensure step
        bootstrapped.ensure_application(project_id)

        # Verify it is back
        apps_after = bootstrapped.search_applications(project_id)
        app_after = next(
            (a for a in apps_after if a.get("name") == APPLICATION_NAME), None
        )
        assert app_after is not None
        config = app_after.get("oidcConfig", {})
        assert config.get("accessTokenType") == "OIDC_TOKEN_TYPE_JWT"
        assert config.get("accessTokenRoleAssertion") is True
