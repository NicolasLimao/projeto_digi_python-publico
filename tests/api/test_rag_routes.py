from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.rag_routes import get_rag_pipeline, router
from src.config import Settings, get_settings
from src.models.schemas import QueryResponse


@pytest.fixture
def pipeline():
    service = MagicMock()
    service.process = AsyncMock(
        return_value=QueryResponse(
            response="Resposta",
            mode="orientacao",
            score=0.75,
            chunks_used=2,
            processing_time_ms=25,
            interaction_id="id-1",
        )
    )
    return service


@pytest.fixture
def app(pipeline):
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_settings] = lambda: Settings(environment="test")
    application.dependency_overrides[get_rag_pipeline] = lambda: pipeline
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


def test_query_returns_typed_response(client, pipeline):
    response = client.post(
        "/api/rag/query", params={"user_id": "user-1"}, json={"query": "Como configurar?"}
    )
    assert response.status_code == 200
    assert response.json()["chunks_used"] == 2
    pipeline.process.assert_awaited_once()


@pytest.mark.parametrize(
    ("params", "body"),
    [
        ({}, {"query": "teste"}),
        ({"user_id": ""}, {"query": "teste"}),
        ({"user_id": "user"}, {}),
        ({"user_id": "user"}, {"query": "   "}),
        ({"user_id": "user"}, {"query": "teste", "mode": "invalid"}),
    ],
)
def test_query_validation(client, params, body):
    assert client.post("/api/rag/query", params=params, json=body).status_code == 422


def test_query_forwards_explicit_mode_and_channel(client, pipeline):
    response = client.post(
        "/api/rag/query",
        params={"user_id": "user-1", "canal": "dm"},
        json={"query": "Erro ao salvar", "mode": "bug"},
    )
    assert response.status_code == 200
    assert pipeline.process.await_args.args == ("Erro ao salvar", "user-1", "bug", "dm")


def test_extra_request_fields_are_rejected(client):
    response = client.post(
        "/api/rag/query",
        params={"user_id": "user"},
        json={"query": "teste", "unexpected": True},
    )
    assert response.status_code == 422


def test_configured_auth_token_is_required(pipeline):
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_settings] = lambda: Settings(
        environment="test", api_auth_token="secret-token"
    )
    application.dependency_overrides[get_rag_pipeline] = lambda: pipeline
    client = TestClient(application)

    assert (
        client.post("/api/rag/query", params={"user_id": "u"}, json={"query": "q"}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/rag/query",
            params={"user_id": "u"},
            json={"query": "q"},
            headers={"X-API-Key": "wrong"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/rag/query",
            params={"user_id": "u"},
            json={"query": "q"},
            headers={"X-API-Key": "secret-token"},
        ).status_code
        == 200
    )


def test_feedback_contract_rejects_invalid_value(client):
    response = client.post(
        "/api/rag/feedback",
        json={"interaction_id": "id", "feedback": "talvez"},
    )
    assert response.status_code == 422
