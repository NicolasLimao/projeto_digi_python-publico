from fastapi.testclient import TestClient

from src.app import create_app
from src.config import Settings


def test_health_is_public_and_has_security_headers():
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["version"] == "2.0.0"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]


def test_readiness_reports_missing_integrations():
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["openai"] is False


def test_production_disables_interactive_docs():
    config = Settings(
        environment="production",
        user_id_salt="test-stable-salt",
        openai_api_key="openai-secret",
        supabase_url="https://project.supabase.co",
        supabase_service_role_key="service-secret",
        api_auth_token="api-secret",
        trusted_hosts=["testserver"],
    )
    with TestClient(create_app(config)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/ready").status_code == 200


def test_api_responses_are_not_cached():
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.post("/api/rag/query", params={"user_id": "u"}, json={"query": "q"})
    assert response.headers["cache-control"] == "no-store"


def test_invalid_request_id_is_replaced():
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/health", headers={"X-Request-ID": "invalid id with spaces"})
    assert response.headers["x-request-id"] != "invalid id with spaces"


def test_private_http_contract_rejects_missing_key_before_initializing_services():
    app = create_app(Settings(environment="test", api_auth_token="test-api-key"))
    private_routes = {
        path: operations
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/")
    }
    assert private_routes

    with TestClient(app) as client:
        for template, operations in private_routes.items():
            path = template.replace("{user_id}", "test-user")
            for method in operations:
                response = client.request(method, path, params={"user_id": "test-user"}, json={})
                assert response.status_code == 401, (method, path, response.status_code)

    for service in ("openai_service", "supabase_service", "history_service", "ingestion_service"):
        assert not hasattr(app.state, service)
