import pytest

from src.api.history_routes import router
from src.models.schemas import HistoryContextRequest

# These tests are templates for integration testing with FastAPI
# Full integration testing requires app fixture setup


@pytest.mark.asyncio
async def test_history_router_imported():
    """Verify history router is properly defined"""
    assert router is not None
    assert router.prefix == "/api/history"
    assert router.tags == ["history"]


def test_history_context_request_model():
    """Test HistoryContextRequest model validation"""
    request = HistoryContextRequest(user_id="test_user", limit=5)

    assert request.user_id == "test_user"
    assert request.limit == 5


def test_history_context_request_default_limit():
    """Test HistoryContextRequest has proper default"""
    request = HistoryContextRequest(user_id="test_user")

    assert request.limit == 5


def test_history_context_request_custom_limit():
    """Test HistoryContextRequest accepts custom limit"""
    request = HistoryContextRequest(user_id="test_user", limit=20)

    assert request.limit == 20
