import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from scripts.demo import IDENTITIES


def test_authentication_and_resource_endpoints(service):
    settings = Settings(
        auth_tokens_json=json.dumps({"a-token": IDENTITIES["client_a"].model_dump()}),
        auth_service_url="",
    )
    with TestClient(create_app(settings, service)) as client:
        assert client.get("/health").status_code == 200
        assert {d["document_id"] for d in client.get("/documents").json()} == {
            "public_faq",
            "public_brochure",
        }
        response = client.post(
            "/query", json={"query": "coverage", "principal": IDENTITIES["client_a"].model_dump()}
        )
        assert response.status_code == 403
        assert client.get("/documents", headers={"Authorization": "Bearer bad"}).status_code == 401
        response = client.post(
            "/query", json={"query": "coverage"}, headers={"Authorization": "Bearer a-token"}
        )
        assert response.status_code == 200
        assert "retrieval_debug" not in response.json()
        assert not any(d.startswith("client_b") for d in response.json()["retrieved_resources"])
        private = service.resolver.catalog.get("actuarial_pricing")
        assert client.get(f"/graph/entities/{private.id}:{private.version}:main").status_code == 404
        assert (
            client.post("/documents/index", json={"document_id": "public_faq"}).status_code == 403
        )


def test_authorized_ingestion_api(service):
    admin = dict(
        user_id="admin", role="internal", department="engineering", permissions=["documents:write"]
    )
    with TestClient(
        create_app(
            Settings(auth_tokens_json=json.dumps({"admin": admin}), auth_service_url=""), service
        )
    ) as c:
        headers = {"Authorization": "Bearer admin"}
        response = c.post(
            "/documents",
            headers=headers,
            data={
                "document_id": "new",
                "title": "New",
                "metadata": '{"visibility":"public"}',
                "source_metadata": (
                    '{"source_type":"web","source_url":"https://www.sunlife.com/en/example/",'
                    '"canonical_url":"https://www.sunlife.com/en/example/","content_hash":"abc"}'
                ),
            },
            files={"file": ("new.txt", b"New product coverage documentation")},
        )
        assert response.status_code == 201
        assert service.resolver.catalog.get("new") is None
        assert (
            c.post("/documents/index", headers=headers, json={"document_id": "new"}).status_code
            == 200
        )
        document = service.resolver.catalog.get("new")
        assert document is not None
        assert document.source_metadata and document.source_metadata.source_type == "web"
        answer = c.post(
            "/query",
            headers=headers,
            json={"query": "new product coverage"},
        )
        assert answer.status_code == 200
        source = next(item for item in answer.json()["sources"] if item["document_id"] == "new")
        assert source["source_url"] == "https://www.sunlife.com/en/example/"


def test_logs_omit_contents(service, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="rag.audit"):
        service.query("How is risk pricing calculated?", IDENTITIES["actuarial"])
    assert "ACTUARIAL_SECRET" not in caplog.text
    record = json.loads(caplog.records[-1].message)
    assert record["principal_role"] == "internal"
    assert "llm_latency_ms" in record and "query_id" in record
