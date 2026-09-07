from pathlib import Path

import pytest

from auth_service.app import create_app
from auth_service.config import AuthSettings


def settings(path: Path) -> AuthSettings:
    value = AuthSettings()
    value.database_path = str(path / "auth.db")
    value.secret_key = "test-session-secret"
    value.service_secret = "test-service-secret"
    value.bootstrap_username = "rootadmin"
    value.bootstrap_password = "strong-admin-password"
    value.cookie_secure = False
    value.token_ttl_hours = 24
    return value


@pytest.fixture
def auth_client(tmp_path):
    app = create_app(settings(tmp_path))
    app.config.update(TESTING=True)
    return app.test_client()


def login_admin(client):
    response = client.post(
        "/api/login", json={"username": "rootadmin", "password": "strong-admin-password"}
    )
    assert response.status_code == 200
    return response.get_json()


def test_admin_ui_and_bootstrap_login(auth_client):
    assert auth_client.get("/").status_code == 200
    assert b"Identity workspace" in auth_client.get("/admin").data
    assert auth_client.get("/health").get_json() == {"status": "ok"}
    login = login_admin(auth_client)
    assert login["user"]["is_admin"] is True
    assert login["token"] and login["csrf_token"]


def test_csrf_user_department_and_token_lifecycle(auth_client):
    login = login_admin(auth_client)
    csrf = login["csrf_token"]
    assert (
        auth_client.post(
            "/api/admin/departments", json={"id": "claims", "name": "Claims"}
        ).status_code
        == 403
    )
    department = auth_client.post(
        "/api/admin/departments",
        json={"id": "claims", "name": "Claims", "description": "Claims team"},
        headers={"X-CSRF-Token": csrf},
    )
    assert department.status_code == 201
    created = auth_client.post(
        "/api/admin/users",
        json={
            "username": "claims.user",
            "password": "strong-user-password",
            "role": "internal",
            "department": "claims",
            "permissions": ["documents:write"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    user = created.get_json()["user"]
    issued = auth_client.post(
        f"/api/admin/users/{user['id']}/token",
        json={},
        headers={"X-CSRF-Token": csrf},
    ).get_json()
    introspected = auth_client.post(
        "/api/introspect",
        headers={
            "Authorization": f"Bearer {issued['token']}",
            "X-Auth-Service-Secret": "test-service-secret",
        },
    )
    assert introspected.status_code == 200
    assert introspected.get_json()["principal"] == {
        "user_id": user["id"],
        "role": "internal",
        "client_id": None,
        "department": "claims",
        "permissions": ["documents:write"],
    }
    revoked = auth_client.post(
        f"/api/admin/users/{user['id']}/revoke-tokens",
        json={},
        headers={"X-CSRF-Token": csrf},
    )
    assert revoked.get_json()["revoked"] == 1
    assert (
        auth_client.post(
            "/api/introspect",
            headers={
                "Authorization": f"Bearer {issued['token']}",
                "X-Auth-Service-Secret": "test-service-secret",
            },
        ).status_code
        == 401
    )


def test_client_validation_and_disabled_user(auth_client):
    csrf = login_admin(auth_client)["csrf_token"]
    invalid = auth_client.post(
        "/api/admin/users",
        json={"username": "client.user", "password": "strong-client-pass", "role": "client"},
        headers={"X-CSRF-Token": csrf},
    )
    assert invalid.status_code == 422
    created = auth_client.post(
        "/api/admin/users",
        json={
            "username": "client.user",
            "password": "strong-client-pass",
            "role": "client",
            "client_id": "client_a",
        },
        headers={"X-CSRF-Token": csrf},
    ).get_json()["user"]
    login = auth_client.post(
        "/api/login", json={"username": "client.user", "password": "strong-client-pass"}
    )
    assert login.status_code == 200
    # Restore the admin session, then disable the client; existing tokens are revoked.
    csrf = login_admin(auth_client)["csrf_token"]
    response = auth_client.put(
        f"/api/admin/users/{created['id']}",
        json={"active": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.get_json()["user"]["active"] is False
    assert (
        auth_client.post(
            "/api/introspect",
            headers={
                "Authorization": f"Bearer {login.get_json()['token']}",
                "X-Auth-Service-Secret": "test-service-secret",
            },
        ).status_code
        == 401
    )


def test_introspection_requires_service_secret(auth_client):
    login = login_admin(auth_client)
    assert (
        auth_client.post(
            "/api/introspect", headers={"Authorization": f"Bearer {login['token']}"}
        ).status_code
        == 401
    )
