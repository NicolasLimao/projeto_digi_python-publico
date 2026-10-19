from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.classifier import ClassifierAgent
from src.config import Settings
from src.models.schemas import Document, QueryResponse
from src.models.typesafe import VerificationResult
from src.pipeline.rag_pipeline import RAGPipeline
from src.services.openai_service import OpenAIService


@pytest.fixture
def components():
    classifier = MagicMock()
    classifier.execute = AsyncMock(return_value="orientacao")
    validator = MagicMock()
    validator.execute = AsyncMock(return_value={"dentro_do_escopo": True})
    document = Document(id="1", content="contexto", embedding=[], metadata={}, score=0.8)
    rag = MagicMock()
    rag.retrieve = AsyncMock(
        return_value={
            "documents": [document],
            "search_query": "consulta",
            "fontes": ["1"],
            "score": 0.8,
            "chunks_used": 1,
        }
    )
    rag.generate = AsyncMock(return_value=" resposta gerada ")
    formatter = MagicMock()
    formatter.execute = AsyncMock(return_value="resposta gerada")
    history = MagicMock()
    history.format_history_for_prompt = AsyncMock(return_value="")
    history.save_interaction = AsyncMock(return_value="history-1")
    return classifier, validator, rag, formatter, history


@pytest.fixture
def pipeline(components):
    return RAGPipeline(*components)


@pytest.mark.asyncio
async def test_process_returns_query_response(pipeline):
    result = await pipeline.process("pergunta", "user-1")
    assert isinstance(result, QueryResponse)
    assert result.response == "resposta gerada"
    assert result.interaction_id == "history-1"


@pytest.mark.asyncio
async def test_independent_steps_run(pipeline, components):
    classifier, validator, rag, _, history = components
    await pipeline.process("pergunta", "user-1")
    classifier.execute.assert_awaited_once()
    validator.execute.assert_awaited_once()
    rag.retrieve.assert_awaited_once()
    history.format_history_for_prompt.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["pergunta", "o cliente ja utiliza um 16/16"])
async def test_explicit_mode_skips_classifier(pipeline, components, query):
    classifier, _, _, _, _ = components
    components[
        -1
    ].format_history_for_prompt.return_value = (
        "[1] Usuário: Qual servidor recomendado?\n[1] Digi: ..."
    )
    result = await pipeline.process(query, "user-1", mode="bug")
    classifier.execute.assert_not_awaited()
    assert result.mode == "bug"


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [True, False])
async def test_server_profile_update_is_orientation_with_or_without_classifier_configuration(
    components, configured
):
    _, validator, rag, formatter, history = components
    history.format_history_for_prompt.return_value = (
        "[1] Usuário: Qual servidor recomendado para 11 conexões WhatsApp?\n[1] Digi: ..."
    )
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="bug"))]
        )
    )
    classifier = ClassifierAgent(OpenAIService(client=client) if configured else OpenAIService())
    pipeline = RAGPipeline(classifier, validator, rag, formatter, history)
    result = await pipeline.process("o cliente ja utiliza um 16/16", "user-1")
    assert result.mode == "orientacao"
    assert history.save_interaction.await_args.kwargs["modo"] == "orientacao"
    client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_result_uses_retrieval_metrics(pipeline):
    result = await pipeline.process("pergunta", "user-1")
    assert result.score == 0.8
    assert result.chunks_used == 1


@pytest.mark.asyncio
async def test_out_of_scope_returns_without_generation(pipeline, components):
    _, validator, rag, formatter, _ = components
    validator.execute.return_value = {"dentro_do_escopo": False, "motivo": "externo"}
    rag.retrieve.return_value = {
        "documents": [],
        "search_query": "q",
        "fontes": [],
        "score": 0.0,
        "chunks_used": 0,
    }
    result = await pipeline.process("bolo", "user-1")
    assert "fora do escopo" in result.response
    rag.generate.assert_not_awaited()
    formatter.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_strong_retrieval_overrides_false_negative(pipeline, components):
    _, validator, rag, _, _ = components
    validator.execute.return_value = {"dentro_do_escopo": False}
    rag.retrieve.return_value["chunks_used"] = 5
    rag.retrieve.return_value["score"] = 0.4
    result = await pipeline.process("webhook", "user-1")
    assert result.response == "resposta gerada"


@pytest.mark.asyncio
async def test_history_failure_does_not_replace_valid_response(pipeline, components):
    *_, history = components
    history.save_interaction.side_effect = RuntimeError("database unavailable")
    result = await pipeline.process("pergunta", "user-1")
    assert result.response == "resposta gerada"
    assert result.interaction_id is None


@pytest.mark.asyncio
async def test_pipeline_hides_internal_error(pipeline, components):
    _, _, rag, _, _ = components
    rag.retrieve.side_effect = RuntimeError("secret connection string")
    result = await pipeline.process("pergunta", "user-1")
    assert "secret connection string" not in result.response
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_processing_time_is_non_negative(pipeline):
    result = await pipeline.process("pergunta", "user-1")
    assert result.processing_time_ms >= 0


@pytest.mark.asyncio
async def test_history_receives_retrieval_metadata(pipeline, components):
    *_, history = components
    await pipeline.process("pergunta", "user-1", canal="dm")
    kwargs = history.save_interaction.await_args.kwargs
    assert kwargs["pergunta_reescrita"] == "consulta"
    assert kwargs["fontes"] == ["1"]
    assert kwargs["canal"] == "dm"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,approved,failure",
    [
        ("off", False, False),
        ("shadow", False, False),
        ("shadow", False, True),
        ("enforce", True, False),
        ("enforce", False, False),
        ("enforce", False, True),
    ],
)
async def test_verification_checks_final_response_and_persists_only_delivered_text(
    components, mode, approved, failure
):
    verifier = MagicMock()
    verifier.verify = AsyncMock(
        return_value=VerificationResult(
            status="supported" if approved else "uncertain", approved=approved
        )
    )
    if failure:
        verifier.verify.side_effect = RuntimeError("secret upstream body")
    config = Settings(
        typesafe_api_key="test", typesafe_verify_mode=mode, typesafe_criteria_calibrated=True
    )
    pipeline = RAGPipeline(*components, config=config, typesafe=verifier)
    result = await pipeline.process("pergunta", "user-1")
    assert verifier.verify.await_count == int(mode != "off")
    if mode != "off":
        assert verifier.verify.await_args.args[1] == "resposta gerada"
    blocked = mode == "enforce" and (not approved or failure)
    assert (result.response != "resposta gerada") == blocked
    assert "secret" not in result.response
    assert components[-1].save_interaction.await_args.kwargs["resposta"] == result.response


@pytest.mark.asyncio
async def test_enforced_customer_response_routes_to_support(components):
    config = Settings(
        typesafe_api_key="test", typesafe_verify_mode="enforce", typesafe_criteria_calibrated=True
    )
    result = await RAGPipeline(*components, config=config).process(
        "pergunta", "user-1", mode="resposta-cliente"
    )
    assert "equipe de suporte" in result.response
