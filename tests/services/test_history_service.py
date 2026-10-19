from datetime import UTC, datetime, timedelta

import pytest

from src.services.history_service import HistoryService
from tests.fakes import FakeSupabaseClient


@pytest.fixture
def service() -> HistoryService:
    return HistoryService(FakeSupabaseClient())


@pytest.mark.asyncio
async def test_save_and_read_interaction(service):
    entry_id = await service.save_interaction("user", "pergunta", "resposta", score=0.8)
    history = await service.get_recent_history("user")
    assert entry_id is not None
    assert history[0].pergunta == "pergunta"


@pytest.mark.asyncio
async def test_history_is_isolated_by_user(service):
    await service.save_interaction("a", "A", "resposta")
    await service.save_interaction("b", "B", "resposta")
    assert [entry.pergunta for entry in await service.get_recent_history("a")] == ["A"]


@pytest.mark.asyncio
async def test_limit_is_respected(service):
    for index in range(5):
        await service.save_interaction("user", f"p{index}", "r")
    assert len(await service.get_recent_history("user", limit=2)) == 2


@pytest.mark.asyncio
async def test_prompt_history_is_chronological_and_marked_untrusted(service):
    await service.save_interaction("user", "primeira", "r1")
    await service.save_interaction("user", "segunda", "r2")
    formatted = await service.format_history_for_prompt("user")
    assert "não confiável" in formatted
    assert formatted.index("primeira") < formatted.index("segunda")


@pytest.mark.asyncio
async def test_feedback_updates_existing_row(service):
    entry_id = await service.save_interaction("user", "p", "r")
    assert entry_id is not None
    assert await service.update_feedback(entry_id, "positivo") is True


@pytest.mark.asyncio
async def test_cleanup_removes_old_rows():
    client = FakeSupabaseClient()
    old = (datetime.now(UTC) - timedelta(days=100)).isoformat()
    client.tables["historico_digi"] = [
        {"id": "old", "user_id": "u", "pergunta": "p", "resposta": "r", "timestamp": old}
    ]
    service = HistoryService(client)
    assert await service.clear_old_history(90) == 1
    assert await service.get_recent_history("u") == []


@pytest.mark.asyncio
async def test_unconfigured_history_is_explicitly_empty():
    service = HistoryService(None)
    assert await service.save_interaction("u", "p", "r") is None
    assert await service.get_recent_history("u") == []


@pytest.mark.asyncio
async def test_save_grava_hash_nao_o_id_cru():
    from src.security import pseudonimizar_user_id

    client = FakeSupabaseClient()
    service = HistoryService(client, salt="salt-de-teste")
    await service.save_interaction("123456789012345678", "p", "r")
    guardado = client.tables["historico_digi"][0]["user_id"]
    assert guardado == pseudonimizar_user_id("123456789012345678", "salt-de-teste")
    assert guardado != "123456789012345678"


@pytest.mark.asyncio
async def test_get_recent_history_consulta_pelo_hash():
    client = FakeSupabaseClient()
    service = HistoryService(client, salt="salt-de-teste")
    await service.save_interaction("123456789012345678", "pergunta X", "r")
    achados = await service.get_recent_history("123456789012345678")
    assert [e.pergunta for e in achados] == ["pergunta X"]
