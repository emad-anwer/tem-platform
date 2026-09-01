from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_NAME = "tem-platform"
APPLICATION_NAME = "tem-platform-dev"
DEV_ORG_NAME = "tem-platform-dev"

ROLES = {
    "owner": "Owner",
    "analyst": "Analyst",
    "viewer": "Viewer",
}


@dataclass(frozen=True)
class Config:
    issuer: str
    pat_path: Path
    redirect_uri: str
    dev_username: str
    dev_email: str
    dev_password: str

    @classmethod
    def from_env(cls) -> Config:
        values = {
            "ZITADEL_ISSUER": os.getenv("ZITADEL_ISSUER"),
            "ZITADEL_BOOTSTRAP_PAT_PATH": os.getenv(
                "ZITADEL_BOOTSTRAP_PAT_PATH"
            ),
            "ZITADEL_REDIRECT_URI": os.getenv(
                "ZITADEL_REDIRECT_URI",
                "http://localhost:3000/callback",
            ),
            "ZITADEL_DEV_USERNAME": os.getenv(
                "ZITADEL_DEV_USERNAME",
                "dev-user",
            ),
            "ZITADEL_DEV_EMAIL": os.getenv(
                "ZITADEL_DEV_EMAIL",
                "dev-user@tem-platform.local",
            ),
            "ZITADEL_DEV_PASSWORD": os.getenv(
                "ZITADEL_DEV_PASSWORD"
            ),
        }

        missing = [
            key
            for key, value in values.items()
            if value is None
        ]

        if missing:
            raise RuntimeError(
                "Missing environment variables: "
                + ", ".join(missing)
            )

        return cls(
            issuer=values["ZITADEL_ISSUER"].rstrip("/"),
            pat_path=Path(values["ZITADEL_BOOTSTRAP_PAT_PATH"]),
            redirect_uri=values["ZITADEL_REDIRECT_URI"],
            dev_username=values["ZITADEL_DEV_USERNAME"],
            dev_email=values["ZITADEL_DEV_EMAIL"],
            dev_password=values["ZITADEL_DEV_PASSWORD"],
        )


class ZitadelClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.base_url = (
            f"{config.issuer}/management/v1"
        )
        self.admin_base_url = (
            f"{config.issuer}/admin/v1"
        )

    def wait_until_ready(self, timeout_seconds: int = 180) -> None:
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            try:
                request = urllib.request.Request(
                    f"{self.config.issuer}/debug/ready",
                    method="GET",
                )
                with urllib.request.urlopen(request, timeout=10):
                    return
            except Exception as exc:
                last_error = exc
                time.sleep(2)

        raise RuntimeError(
            "Timed out waiting for Zitadel management API to become ready"
        ) from last_error

    def wait_for_pat(self, timeout_seconds: int = 180) -> str:
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            try:
                if not self.config.pat_path.exists():
                    raise FileNotFoundError(self.config.pat_path)

                token = self.config.pat_path.read_text(
                    encoding="utf-8"
                ).strip()

                if not token:
                    raise RuntimeError(
                        f"Bootstrap PAT is empty: {self.config.pat_path}"
                    )

                return token
            except Exception as exc:
                last_error = exc
                time.sleep(2)

        raise RuntimeError(
            f"Timed out waiting for bootstrap PAT at {self.config.pat_path}"
        ) from last_error

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        org_id: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        url = f"{base_url or self.base_url}{path}"

        headers = dict(self.headers)

        if org_id:
            headers["x-zitadel-orgid"] = org_id

        data = None

        if body is not None:
            data = json.dumps(body).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                raw = response.read()

        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode(
                "utf-8",
                errors="replace",
            )

            try:
                error_payload = json.loads(response_body)
            except json.JSONDecodeError:
                error_payload = {}

            error_messages = []

            if isinstance(error_payload, dict):
                error_messages.append(error_payload.get("message", ""))
                error_messages.extend(
                    detail.get("message", "")
                    for detail in error_payload.get("details", [])
                    if isinstance(detail, dict)
                )

            normalized_messages = {
                "".join(
                    character.lower()
                    for character in message
                    if character.isalnum()
                )
                for message in error_messages
                if isinstance(message, str)
            }

            if (
                exc.code == 400
                and any(
                    (
                        "nochanges" in message
                        or "notchanged" in message
                        or "notbeenchanged" in message
                    )
                    for message in normalized_messages
                )
            ):
                return {}

            raise RuntimeError(
                f"Zitadel API request failed:\n"
                f"{method} {path}\n"
                f"HTTP {exc.code}\n"
                f"{response_body}"
            ) from exc

        if not raw:
            return {}

        return json.loads(raw)

    def search_projects(self) -> list[dict[str, Any]]:
        response = self.request(
            "POST",
            "/projects/_search",
            body={},
        )

        return response.get("result", [])

    def find_project(self) -> dict[str, Any] | None:
        for project in self.search_projects():
            if project.get("name") == PROJECT_NAME:
                return project

        return None

    def ensure_project(self) -> str:
        project = self.find_project()

        if project:
            project_id = project["id"]

            print(
                f"Project exists: "
                f"{PROJECT_NAME} ({project_id})"
            )

            self.request(
                "PUT",
                f"/projects/{project_id}",
                body={
                    "name": PROJECT_NAME,
                    "projectRoleAssertion": True,
                    "projectRoleCheck": False,
                    "hasProjectCheck": False,
                },
            )

            return project_id

        response = self.request(
            "POST",
            "/projects",
            body={
                "name": PROJECT_NAME,
                "projectRoleAssertion": True,
                "projectRoleCheck": False,
                "hasProjectCheck": False,
            },
        )

        project_id = response["id"]

        print(
            f"Created project: "
            f"{PROJECT_NAME} ({project_id})"
        )

        return project_id

    def search_project_roles(
        self,
        project_id: str,
    ) -> list[dict[str, Any]]:
        response = self.request(
            "POST",
            f"/projects/{project_id}/roles/_search",
            body={},
        )

        return response.get("result", [])

    def ensure_project_roles(
        self,
        project_id: str,
    ) -> None:
        existing = {
            role["key"]: role
            for role in self.search_project_roles(project_id)
        }

        for key, display_name in ROLES.items():
            role = existing.get(key)

            if role and role.get("displayName") == display_name:
                print(f"Role exists and is correct: {key}")
                continue

            if role:
                self.request(
                    "PUT",
                    f"/projects/{project_id}/roles/{key}",
                    body={"displayName": display_name},
                )
                print(f"Reconciled role: {key}")
                continue

            self.request(
                "POST",
                f"/projects/{project_id}/roles",
                body={
                    "roleKey": key,
                    "displayName": display_name,
                },
            )

            print(f"Created role: {key}")

    def search_applications(
        self,
        project_id: str,
    ) -> list[dict[str, Any]]:
        response = self.request(
            "POST",
            f"/projects/{project_id}/apps/_search",
            body={},
        )

        return response.get("result", [])

    def ensure_application(
        self,
        project_id: str,
    ) -> str:
        applications = self.search_applications(
            project_id
        )

        application = next(
            (
                app
                for app in applications
                if app.get("name") == APPLICATION_NAME
            ),
            None,
        )

        config = {
            "redirectUris": [
                self.config.redirect_uri
            ],
            "responseTypes": [
                "OIDC_RESPONSE_TYPE_CODE"
            ],
            "grantTypes": [
                "OIDC_GRANT_TYPE_AUTHORIZATION_CODE"
            ],
            "appType": "OIDC_APP_TYPE_NATIVE",
            "authMethodType": "OIDC_AUTH_METHOD_TYPE_NONE",
            "version": "OIDC_VERSION_1_0",
            "devMode": True,
            "accessTokenType": "OIDC_TOKEN_TYPE_JWT",
            "accessTokenRoleAssertion": True,
            "idTokenRoleAssertion": True,
        }

        if application:
            app_id = application["id"]

            print(
                f"Application exists: "
                f"{APPLICATION_NAME} ({app_id})"
            )

            self.request(
                "PUT",
                f"/projects/{project_id}/apps/{app_id}",
                body={"name": APPLICATION_NAME},
            )

            self.request(
                "PUT",
                (
                    f"/projects/{project_id}/apps/"
                    f"{app_id}/oidc_config"
                ),
                body=config,
            )

            return app_id

        response = self.request(
            "POST",
            f"/projects/{project_id}/apps/oidc",
            body={
                "name": APPLICATION_NAME,
                **config,
            },
        )

        app_id = response["appId"]

        print(
            f"Created application: "
            f"{APPLICATION_NAME} ({app_id})"
        )

        return app_id

    def search_organizations(
        self,
    ) -> list[dict[str, Any]]:
        response = self.request(
            "POST",
            "/orgs/_search",
            body={},
            base_url=self.admin_base_url,
        )

        return response.get("result", [])

    def search_project_grants(
        self,
        project_id: str,
    ) -> list[dict[str, Any]]:
        response = self.request(
            "POST",
            f"/projects/{project_id}/grants/_search",
            body={},
        )

        return response.get("result", [])

    def ensure_project_grant(
        self,
        project_id: str,
        org_id: str,
    ) -> str:
        grants = self.search_project_grants(project_id)
        grant = next(
            (
                grant
                for grant in grants
                if grant.get("grantedOrgId") == org_id
            ),
            None,
        )

        body = {
            "grantedOrgId": org_id,
            "roleKeys": list(ROLES.keys()),
        }

        if grant:
            grant_id = grant["grantId"]

            self.request(
                "PUT",
                f"/projects/{project_id}/grants/{grant_id}",
                body={"roleKeys": list(ROLES.keys())},
            )

            print(
                "Reconciled dev organization project grant: "
                "owner, analyst, viewer"
            )
            return grant_id

        response = self.request(
            "POST",
            f"/projects/{project_id}/grants",
            body=body,
        )

        print(
            "Created dev organization project grant: "
            "owner, analyst, viewer"
        )

        return response["grantId"]

    def ensure_organization(self) -> str:
        organizations = self.search_organizations()

        organization = next(
            (
                org
                for org in organizations
                if org.get("name") == DEV_ORG_NAME
            ),
            None,
        )

        if organization:
            org_id = organization["id"]

            print(
                f"Organization exists: "
                f"{DEV_ORG_NAME} ({org_id})"
            )

            return org_id

        response = self.request(
            "POST",
            "/orgs",
            body={
                "name": DEV_ORG_NAME,
            },
        )

        org_id = response["id"]

        print(
            f"Created organization: "
            f"{DEV_ORG_NAME} ({org_id})"
        )

        return org_id

    def search_users(
        self,
        org_id: str,
    ) -> list[dict[str, Any]]:
        response = self.request(
            "POST",
            "/users/_search",
            body={
                "query": {
                    "offset": 0,
                    "limit": 100,
                    "asc": True,
                },
                "queries": [
                    {
                        "userNameQuery": {
                            "userName": self.config.dev_username,
                        }
                    }
                ],
            },
            org_id=org_id,
        )

        return response.get("result", [])

    def ensure_dev_user(
        self,
        org_id: str,
    ) -> str:
        users = self.search_users(org_id)

        if users:
            user_id = users[0]["id"]

            print(
                f"Dev user exists: "
                f"{self.config.dev_username} ({user_id})"
            )

            self.ensure_dev_user_email(user_id, org_id)
            self.ensure_dev_user_password(user_id, org_id)
            return user_id

        response = self.request(
            "POST",
            "/users/human",
            body={
                "userName": self.config.dev_username,
                "profile": {
                    "firstName": "Dev",
                    "lastName": "User",
                    "displayName": "Development User",
                    "preferredLanguage": "en",
                },
                "email": {
                    "email": self.config.dev_email,
                    "isEmailVerified": True,
                },
                "initialPassword": (
                    self.config.dev_password
                ),
            },
            org_id=org_id,
        )

        user_id = response["userId"]

        print(
            f"Created dev user: "
            f"{self.config.dev_username} ({user_id})"
        )

        return user_id

    def ensure_dev_user_password(
        self,
        user_id: str,
        org_id: str,
    ) -> None:
        self.request(
            "POST",
            f"/users/{user_id}/password/_initialize",
            body={"password": self.config.dev_password},
            org_id=org_id,
        )
        print("Reconciled dev user initial password")

    def ensure_dev_user_email(
        self,
        user_id: str,
        org_id: str,
    ) -> None:
        response = self.request(
            "GET",
            f"/users/{user_id}/email",
            org_id=org_id,
        )
        email = response.get("email", {})

        if (
            email.get("email") == self.config.dev_email
            and email.get("isEmailVerified") is True
        ):
            print("Dev user email exists and is verified")
            return

        self.request(
            "PUT",
            f"/users/{user_id}/email",
            body={
                "email": self.config.dev_email,
                "isEmailVerified": True,
            },
            org_id=org_id,
        )
        print("Reconciled dev user email as verified")

    def search_user_grants(
        self,
        user_id: str,
        org_id: str,
    ) -> list[dict[str, Any]]:
        response = self.request(
            "POST",
            "/users/grants/_search",
            body={
                "query": {
                    "offset": 0,
                    "limit": 100,
                    "asc": True,
                },
                "queries": [
                    {
                        "userIdQuery": {
                            "userId": user_id,
                        }
                    }
                ],
            },
            org_id=org_id,
        )

        return response.get("result", [])

    def ensure_user_grant(
        self,
        user_id: str,
        project_id: str,
        project_grant_id: str,
        org_id: str,
    ) -> None:
        grants = self.search_user_grants(
            user_id,
            org_id,
        )

        grant = next(
            (
                grant
                for grant in grants
                if (
                    grant.get("projectId") == project_id
                    and grant.get("projectGrantId") == project_grant_id
                )
            ),
            None,
        )

        if grant:
            grant_id = grant["id"]

            self.request(
                "PUT",
                f"/users/{user_id}/grants/{grant_id}",
                body={
                    "roleKeys": list(ROLES.keys()),
                },
                org_id=org_id,
            )

            print(
                "Reconciled dev user roles: "
                "owner, analyst, viewer"
            )

            return

        self.request(
            "POST",
            f"/users/{user_id}/grants",
            body={
                "projectId": project_id,
                "projectGrantId": project_grant_id,
                "roleKeys": list(ROLES.keys()),
            },
            org_id=org_id,
        )

        print(
            "Created dev user role assignment: "
            "owner, analyst, viewer"
        )

    def bootstrap(self) -> None:
        self.wait_until_ready()
        token = self.wait_for_pat()
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        project_id = self.ensure_project()

        self.ensure_project_roles(project_id)

        self.ensure_application(project_id)

        org_id = self.ensure_organization()

        project_grant_id = self.ensure_project_grant(project_id, org_id)

        user_id = self.ensure_dev_user(org_id)

        self.ensure_user_grant(
            user_id,
            project_id,
            project_grant_id,
            org_id,
        )

        print()
        print("Zitadel bootstrap complete.")
        print(f"Project ID:      {project_id}")
        print(f"Organization ID: {org_id}")
        print(f"Application:     {APPLICATION_NAME}")
        print(f"Dev user:        {self.config.dev_username}")


def main() -> int:
    try:
        config = Config.from_env()

        client = ZitadelClient(config)

        print("Starting Zitadel bootstrap...")
        client.bootstrap()

        return 0

    except Exception as exc:
        print(f"\nBootstrap failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
