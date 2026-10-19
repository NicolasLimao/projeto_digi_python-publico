from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.rag_agent import RAGAgent
from src.config import Settings
from src.models.schemas import Document


@pytest.fixture
def documents() -> list[Document]:
    return [
        Document(id="1", content="backup", embedding=[], metadata={"fonte": "manual"}, score=0.9),
        Document(id="2", content="restore", embedding=[], metadata={"fonte": "faq"}, score=0.7),
    ]


@pytest.fixture
def services(documents):
    openai = MagicMock()
    openai.get_embeddings = AsyncMock(return_value=[0.1] * 4)
    openai.rewrite_query = AsyncMock(side_effect=lambda query, history="": query)
    openai.rerank = AsyncMock(
        side_effect=lambda query, chunks, top_n=10, full_context=False: chunks[:top_n]
    )
    openai.generate_response = AsyncMock(return_value="Resposta")
    openai.format_response = AsyncMock(side_effect=lambda response, mode: response.strip())
    supabase = MagicMock()
    supabase.search_hybrid = AsyncMock(return_value=documents)
    return openai, supabase


@pytest.fixture
def rag_agent(services):
    return RAGAgent(*services)


@pytest.mark.asyncio
async def test_retrieve_builds_metrics_and_sources(rag_agent):
    result = await rag_agent.retrieve("Como fazer backup?", k=10)
    assert result["chunks_used"] == 2
    assert result["score"] == pytest.approx(0.8)
    assert result["fontes"] == ["1", "2"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,shadow,failure",
    [
        ("openai", False, False),
        ("openai", True, False),
        ("typesafe", False, False),
        ("typesafe", False, True),
        ("openai", True, True),
    ],
)
async def test_typesafe_selection_shadow_and_fallback(
    services, documents, provider, shadow, failure
):
    openai, supabase = services
    typesafe = MagicMock()
    typesafe.rerank = AsyncMock(return_value=list(reversed(documents)))
    if failure:
        typesafe.rerank.side_effect = RuntimeError("secret external body")
    config = Settings(
        typesafe_api_key="test", rerank_provider=provider, typesafe_rerank_shadow=shadow
    )
    result = await RAGAgent(openai, supabase, config, typesafe=typesafe).retrieve("backup")
    assert result["documents"] == (
        list(reversed(documents)) if provider == "typesafe" and not failure else documents
    )
    assert typesafe.rerank.await_count == int(provider == "typesafe" or shadow)
    assert openai.rerank.await_count == int(provider == "openai" or failure)


@pytest.mark.asyncio
async def test_retrieve_expands_candidate_pool(rag_agent, services):
    await rag_agent.retrieve("teste", k=3)
    _, supabase = services
    assert supabase.search_hybrid.await_args.kwargs["k"] == 30


@pytest.mark.asyncio
async def test_retrieve_can_select_correction_beyond_first_fifteen(services):
    openai, supabase = services
    manual = [
        Document(id=str(i), content="Exportação geral", embedding=[], score=0.8) for i in range(18)
    ]
    correction = Document(
        id="correction",
        content="Esse filtro não existe",
        embedding=[],
        metadata={"tipo": "curadoria"},
        score=0.31,
    )
    pool = [*manual, correction]

    async def search(**kwargs):
        return pool[: kwargs["k"]]

    async def rank(query, chunks, top_n=10):
        relevant = [d for d in chunks if d.id == "correction"]
        return (relevant + [d for d in chunks if d.id != "correction"])[:top_n]

    supabase.search_hybrid = AsyncMock(side_effect=search)
    openai.rerank = AsyncMock(side_effect=rank)
    result = await RAGAgent(openai, supabase).retrieve("Como exportar contatos sem tags?", k=2)
    assert result["fontes"][0] == "correction"
    assert result["chunks_used"] == 2


@pytest.mark.asyncio
async def test_retrieve_caps_final_results(rag_agent, services, documents):
    openai, _ = services
    await rag_agent.retrieve("teste", k=1)
    assert openai.rerank.await_args.kwargs["top_n"] == 1


@pytest.mark.asyncio
async def test_retrieve_uses_injected_limits_and_threshold(services):
    openai, supabase = services
    config = Settings(max_chunks=2, score_threshold=0.65)
    agent = RAGAgent(openai, supabase, config)
    await agent.retrieve("teste", k=10)
    assert openai.rerank.await_args.kwargs["top_n"] == 2
    assert supabase.search_hybrid.await_args.kwargs["score_threshold"] == 0.65


@pytest.mark.asyncio
async def test_server_analysis_ranks_original_question_with_complete_evidence(services):
    openai, supabase = services
    query = "Analise o servidor: RAM esperada 4; vCPUs esperados 4. Precisa de upgrade?"
    openai.rewrite_query = AsyncMock(return_value="upgrade servidor")
    openai.rerank = AsyncMock(return_value=[])
    await RAGAgent(openai, supabase).retrieve(query, history_context="ctx")
    ranking = openai.rerank.await_args
    assert query in ranking.args[0]
    assert ranking.kwargs["full_context"] is True


@pytest.mark.asyncio
async def test_server_followup_ranks_complete_evidence_from_history(services):
    openai, supabase = services
    history = "[1] Usuário: Qual servidor recomendado para 11 conexões?\n[1] Digi: ..."
    await RAGAgent(openai, supabase).retrieve("qual recomendado", history_context=history)
    assert openai.rerank.await_args.kwargs["full_context"] is True


@pytest.mark.asyncio
async def test_candidate_limit_never_reduces_final_capacity(services):
    agent = RAGAgent(*services, Settings(max_chunks=2, retrieval_candidate_count=1))
    result = await agent.retrieve("backup")
    assert result["fontes"] == ["1", "2"]
    assert services[1].search_hybrid.await_args.kwargs["k"] == 2


@pytest.mark.asyncio
async def test_dual_query_pool_stays_bounded(services):
    openai, supabase = services
    openai.rewrite_query = AsyncMock(return_value="reescrita")
    left = [Document(id=str(i), content="left", embedding=[], score=0.5) for i in range(30)]
    right = [Document(id=str(i), content="right", embedding=[], score=0.8) for i in range(20, 50)]

    async def search(**kwargs):
        return left if kwargs["query"] == "reescrita" else right

    supabase.search_hybrid = AsyncMock(side_effect=search)
    agent = RAGAgent(openai, supabase, Settings(retrieval_candidate_count=30))
    result = await agent.retrieve("pergunta do cliente", history_context="ctx")
    candidates = openai.rerank.await_args.args[1]
    assert len(candidates) == len({d.id for d in candidates}) == 30
    assert all(d.score == 0.8 for d in candidates)
    assert result["chunks_used"] == 10


@pytest.mark.asyncio
async def test_rewrite_is_skipped_for_simple_query(rag_agent, services):
    openai, _ = services
    await rag_agent.retrieve("backup")
    openai.rewrite_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_rewrite_is_used_for_followup(rag_agent, services):
    openai, _ = services
    await rag_agent.retrieve("e isso?", history_context="pergunta anterior")
    openai.rewrite_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_dual_query_searches_with_original_and_rewrite(services):
    """Quando a query é reescrita, busca também com a pergunta ORIGINAL: se a
    reescrita perder a intenção, a original ainda ancora o chunk certo."""
    openai, supabase = services
    openai.rewrite_query = AsyncMock(return_value="reescrita curta")
    agent = RAGAgent(openai, supabase)
    await agent.retrieve("Pergunta longa do cliente sobre algo", history_context="ctx")
    queries = [call.kwargs["query"] for call in supabase.search_hybrid.await_args_list]
    assert supabase.search_hybrid.await_count == 2
    assert "reescrita curta" in queries
    assert "Pergunta longa do cliente sobre algo" in queries


@pytest.mark.asyncio
async def test_dual_query_merges_dedup_keeping_max_score(services):
    """Funde os candidatos das duas buscas: dedup por id, mantendo o maior score,
    e ordena por score antes do rerank."""
    openai, supabase = services
    openai.rewrite_query = AsyncMock(return_value="reescrita")

    async def fake_search(*, embedding, query, k, score_threshold):
        if query == "reescrita":
            return [
                Document(id="X", content="a", embedding=[], metadata={}, score=0.4),
                Document(id="Y", content="b", embedding=[], metadata={}, score=0.3),
            ]
        return [
            Document(id="X", content="a", embedding=[], metadata={}, score=0.9),
            Document(id="Z", content="c", embedding=[], metadata={}, score=0.2),
        ]

    supabase.search_hybrid = AsyncMock(side_effect=fake_search)
    agent = RAGAgent(openai, supabase)
    result = await agent.retrieve("pergunta do cliente", history_context="ctx")
    # X aparece nas duas buscas: deduplicado mantendo o maior score (0.9).
    # União {X, Y, Z} ordenada por score desc.
    assert result["fontes"] == ["X", "Y", "Z"]


@pytest.mark.asyncio
async def test_single_query_when_rewrite_returns_same_text(services):
    """Se a reescrita devolver o mesmo texto, não vale disparar a segunda busca."""
    openai, supabase = services
    openai.rewrite_query = AsyncMock(side_effect=lambda query, history="": query)
    agent = RAGAgent(openai, supabase)
    await agent.retrieve("e isso?", history_context="pergunta anterior")
    assert supabase.search_hybrid.await_count == 1


@pytest.mark.asyncio
async def test_generate_uses_documents_and_mode(rag_agent, services, documents):
    result = await rag_agent.generate("pergunta", documents, "bug", "histórico")
    openai, _ = services
    assert result == "Resposta"
    assert openai.generate_response.await_args.args[2] == "bug"


@pytest.mark.asyncio
async def test_generate_without_documents_returns_safe_message(rag_agent, services):
    result = await rag_agent.generate("desconhecido", [], "orientacao")
    openai, _ = services
    assert "não encontrei" in result
    openai.generate_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_returns_compatibility_payload(rag_agent):
    result = await rag_agent.execute("backup", mode="resposta-cliente")
    assert result["response"] == "Resposta"
    assert result["mode"] == "resposta-cliente"
    assert result["chunks_used"] == 2


@pytest.mark.asyncio
async def test_execute_hides_internal_exception(rag_agent, services):
    openai, _ = services
    openai.get_embeddings.side_effect = RuntimeError("secret internal detail")
    result = await rag_agent.execute("backup")
    assert "secret internal detail" not in result["response"]
    assert result["score"] == 0.0
