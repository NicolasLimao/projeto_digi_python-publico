from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from starlette.requests import Request

from src.api.dependencies import get_typesafe_service
from src.app import create_app
from src.config import Settings


def test_off_mode_does_not_construct_client():
    config = Settings()
    app = create_app(config)
    request = Request({"type": "http", "app": app})
    assert get_typesafe_service(request, config) is None
    assert not hasattr(app.state, "typesafe_service")


def test_active_service_is_reused_and_closed_by_lifespan():
    config = Settings(typesafe_api_key="test", typesafe_verify_mode="shadow")
    app = create_app(config)
    service = MagicMock()
    service.aclose = AsyncMock()
    app.state.typesafe_service = service
    with TestClient(app):
        request = Request({"type": "http", "app": app})
        assert get_typesafe_service(request, config) is service
        assert get_typesafe_service(request, config) is service
    service.aclose.assert_awaited_once()


def test_active_typesafe_cannot_bypass_authentication():
    app = create_app(
        Settings(typesafe_api_key="test", typesafe_verify_mode="shadow", api_auth_token="test")
    )
    with TestClient(app) as client:
        result = client.post("/api/rag/query", params={"user_id": "test"}, json={"query": "test"})
    assert result.status_code == 401
    assert not hasattr(app.state, "typesafe_service")
