from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.services.supabase_service import SupabaseService, SupabaseServiceError


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["save_document", "search_hybrid", "get_document"])
async def test_operations_require_configuration(method: str):
    service = SupabaseService()
    with pytest.raises(SupabaseServiceError, match="not configured"):
        if method == "save_document":
            await service.save_document("content", [0.1], {})
        elif method == "search_hybrid":
            await service.search_hybrid([0.1], "query")
        else:
            await service.get_document("id")


@pytest.mark.asyncio
async def test_search_hybrid_filters_and_normalizes_results():
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(
        data=[
            {"id": "1", "content": "alto", "score": 0.8, "metadata": {"fonte": "manual"}},
            {"id": "2", "content": "baixo", "score": 0.1, "metadata": {}},
        ]
    )
    documents = await SupabaseService(client=client).search_hybrid(
        [0.1], "backup", k=5, score_threshold=0.3
    )
    assert [document.id for document in documents] == ["1"]
    assert documents[0].score == 0.8
    assert client.rpc.call_args.args[0] == "match_documents_hybrid"


@pytest.mark.asyncio
async def test_save_document_returns_database_id():
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "doc-1"}]
    )
    result = await SupabaseService(client=client).save_document("content", [0.1], {"fonte": "x"})
    assert result == "doc-1"


@pytest.mark.asyncio
async def test_save_document_returns_none_when_database_returns_no_row():
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[])
    assert await SupabaseService(client=client).save_document("content", [0.1], {}) is None


@pytest.mark.asyncio
async def test_get_document_returns_typed_document():
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        SimpleNamespace(data=[{"id": "d1", "content": "texto", "embedding": [0.1], "metadata": {}}])
    )
    document = await SupabaseService(client=client).get_document("d1")
    assert document is not None
    assert document.id == "d1"


@pytest.mark.asyncio
async def test_get_document_returns_none_for_missing_row():
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        SimpleNamespace(data=[])
    )
    assert await SupabaseService(client=client).get_document("missing") is None


@pytest.mark.asyncio
async def test_search_hybrid_uses_real_document_id():
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": 1700, "content": "texto", "score": 0.8, "metadata": {}}]
    )
    documents = await SupabaseService(client=client).search_hybrid([0.1], "backup")
    assert documents[0].id == "1700"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "item",
    [
        {"id": None, "content": "texto", "score": 0.8, "metadata": {}},
        {"content": "texto", "score": 0.8, "metadata": {}},
    ],
    ids=["id_nulo", "id_ausente"],
)
async def test_search_hybrid_falls_back_when_id_is_unusable(item: dict):
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=[item])
    documents = await SupabaseService(client=client).search_hybrid([0.1], "backup")
    assert documents[0].id == "chunk_0"


@pytest.mark.asyncio
async def test_search_hybrid_keeps_falsy_but_valid_id_zero():
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": 0, "content": "texto", "score": 0.8, "metadata": {}}]
    )
    documents = await SupabaseService(client=client).search_hybrid([0.1], "backup")
    assert documents[0].id == "0"


@pytest.mark.asyncio
async def test_search_hybrid_descarta_curadoria_substituida():
    """Correcao aposentada nao volta na busca competindo com a que a substituiu."""
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(
        data=[
            {
                "id": "2855",
                "content": "versao antiga",
                "score": 0.62,
                "metadata": {"tipo": "curadoria", "substituido_por": "2861"},
            },
            {
                "id": "2861",
                "content": "versao vigente",
                "score": 0.61,
                "metadata": {"tipo": "curadoria"},
            },
            {"id": "1712", "content": "manual", "score": 0.33, "metadata": {}},
        ]
    )
    documents = await SupabaseService(client=client).search_hybrid([0.1], "usuario", k=5)
    assert [document.id for document in documents] == ["2861", "1712"]
