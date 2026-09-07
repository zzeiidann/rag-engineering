from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_fastapi_uses_remote_principal(service, monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {
        "active": True,
        "principal": {
            "user_id": "remote-user",
            "role": "client",
            "client_id": "client_a",
            "department": None,
            "permissions": [],
        },
    }
    post = Mock(return_value=response)
    monkeypatch.setattr("app.api.authentication.httpx.post", post)
    config = Settings(auth_service_url="http://auth:5000", auth_service_secret="shared")
    with TestClient(create_app(config, service)) as client:
        result = client.get("/documents", headers={"Authorization": "Bearer opaque-token"})
    assert result.status_code == 200
    assert {item["document_id"] for item in result.json()} >= {
        "client_a_policy",
        "client_a_coverage",
    }
    headers = post.call_args.kwargs["headers"]
    assert headers["X-Auth-Service-Secret"] == "shared"
    assert headers["Authorization"] == "Bearer opaque-token"


def test_fastapi_fails_closed_when_auth_service_is_down(service, monkeypatch):
    import httpx

    monkeypatch.setattr(
        "app.api.authentication.httpx.post",
        Mock(side_effect=httpx.ConnectError("down")),
    )
    config = Settings(auth_service_url="http://auth:5000", auth_service_secret="shared")
    with TestClient(create_app(config, service)) as client:
        result = client.get("/documents", headers={"Authorization": "Bearer opaque-token"})
    assert result.status_code == 503
