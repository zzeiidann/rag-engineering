from unittest.mock import patch

import httpx

from tests.auth_service.test_auth_service import auth_client, login_admin  # noqa: F401


def test_guest_proxy_and_csrf(auth_client):  # noqa: F811
    session = auth_client.get("/api/workspace/session").get_json()
    assert session["user"] is None
    assert auth_client.post("/api/workspace/query", json={"query": "coverage"}).status_code == 403
    with patch(
        "auth_service.workspace.httpx.request", return_value=httpx.Response(200, json=[])
    ) as upstream:
        assert (
            auth_client.get(
                "/api/workspace/documents", headers={"Authorization": "Bearer forged"}
            ).status_code
            == 200
        )
        assert upstream.call_args.kwargs["headers"] == {}
        response = auth_client.post(
            "/api/workspace/query",
            json={"query": " coverage "},
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert response.status_code == 200
        assert upstream.call_args.kwargs["json"] == {"query": "coverage"}
        assert response.headers["Cache-Control"] == "no-store"


def test_no_caller_identity_override(auth_client):  # noqa: F811
    session = auth_client.get("/api/workspace/session").get_json()
    with patch("auth_service.workspace.httpx.request") as upstream:
        response = auth_client.post(
            "/api/workspace/query",
            json={"query": "secret", "principal": {"role": "internal"}},
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert response.status_code == 422
        upstream.assert_not_called()


def test_cookie_identity_logout_and_revocation(auth_client):  # noqa: F811
    login = login_admin(auth_client)
    assert auth_client.get("/api/workspace/session").get_json()["user"]["username"] == "rootadmin"
    cookie = auth_client.get_cookie("rag_token")
    assert cookie.http_only and cookie.same_site == "Strict"
    with patch(
        "auth_service.workspace.httpx.request", return_value=httpx.Response(200, json=[])
    ) as upstream:
        auth_client.get("/api/workspace/documents", headers={"Authorization": "Bearer forged"})
        assert upstream.call_args.kwargs["headers"] == {"Authorization": f"Bearer {login['token']}"}
    auth_client.post("/api/logout")
    assert auth_client.get("/api/workspace/session").get_json()["user"] is None
    auth_client.set_cookie("rag_token", login["token"])
    with patch("auth_service.workspace.httpx.request") as upstream:
        assert auth_client.get("/api/workspace/documents").status_code == 401
        assert auth_client.get("/api/workspace/session").status_code == 401
        upstream.assert_not_called()


def test_client_can_login_but_cannot_admin(auth_client):  # noqa: F811
    admin = login_admin(auth_client)
    auth_client.post(
        "/api/admin/users",
        json={
            "username": "customer.a",
            "password": "long-customer-password",
            "role": "client",
            "client_id": "client_a",
        },
        headers={"X-CSRF-Token": admin["csrf_token"]},
    )
    response = auth_client.post(
        "/api/login", json={"username": "customer.a", "password": "long-customer-password"}
    )
    assert response.status_code == 200
    assert auth_client.get("/api/workspace/session").get_json()["user"]["client_id"] == "client_a"
    assert auth_client.get("/api/admin/users").status_code in {401, 403}


def test_upstream_failure_does_not_leak_details(auth_client):  # noqa: F811
    with patch(
        "auth_service.workspace.httpx.request",
        return_value=httpx.Response(500, text="confidential provider detail"),
    ):
        response = auth_client.get("/api/workspace/documents")
        assert response.status_code == 503
        assert "confidential" not in response.text


def test_saturation_reserves_capacity_for_auth(auth_client):  # noqa: F811
    with patch("auth_service.workspace.upstream_slots") as slots:
        slots.acquire.return_value = False
        with patch("auth_service.workspace.httpx.request") as upstream:
            assert auth_client.get("/api/workspace/documents").status_code == 429
            upstream.assert_not_called()
            slots.release.assert_not_called()
