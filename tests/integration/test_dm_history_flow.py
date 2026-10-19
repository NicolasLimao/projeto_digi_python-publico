import pytest

from src.services.history_service import HistoryService
from tests.fakes import FakeSupabaseClient


@pytest.mark.asyncio
async def test_complete_history_cycle():
    service = HistoryService(FakeSupabaseClient())
    entry_id = await service.save_interaction(
        user_id="analyst-1",
        pergunta="Como fazer backup?",
        resposta="Abra Configurações.",
        modo="orientacao",
        score=0.85,
        chunks_used=3,
        processing_time_ms=500,
    )
    assert entry_id is not None
    context = await service.format_history_for_prompt("analyst-1")
    assert "Como fazer backup?" in context
    assert "Abra Configurações." in context


@pytest.mark.asyncio
async def test_multiple_users_never_share_context():
    service = HistoryService(FakeSupabaseClient())
    await service.save_interaction("user-a", "segredo-a", "resposta-a")
    await service.save_interaction("user-b", "segredo-b", "resposta-b")
    context = await service.format_history_for_prompt("user-a")
    assert "segredo-a" in context
    assert "segredo-b" not in context


@pytest.mark.asyncio
async def test_feedback_cycle():
    service = HistoryService(FakeSupabaseClient())
    entry_id = await service.save_interaction("user", "p", "r")
    assert entry_id is not None
    assert await service.update_feedback(entry_id, "negativo") is True
