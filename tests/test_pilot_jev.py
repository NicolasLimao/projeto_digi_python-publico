from unittest.mock import AsyncMock, MagicMock

import pytest

from evals.compare_jev import FrozenCase
from evals.pilot_jev import (
    compare_pilot_case,
    historical_verification,
    require_config,
    select_cases,
    summarize,
    verify_response,
)
from src.config import Settings
from src.models.schemas import Document
from src.models.typesafe import VerificationResult
from src.services.pilot_source_service import PilotSourceError, PilotSourceService


def row(id, query, feedback=None, mode="orientacao", channel="dm"):
    return {
        "id": id,
        "pergunta": query,
        "resposta": "Resposta registrada",
        "modo": mode,
        "feedback": feedback,
        "canal": channel,
        "timestamp": "2026-10-02",
    }


def correction(query, answer="Resposta revisada", ingested=True, chunks=1, date="2026-10-01"):
    return {
        "pergunta": query,
        "resposta_correta": answer,
        "ingerida": ingested,
        "chunks_criados": chunks,
        "criado_em": date,
    }


def test_selection_excludes_tests_invalid_rows_and_normalized_duplicates():
    rows = [
        row("1", "Como configurar o horário de atendimento?", "negativo"),
        row("2", "COMO configurar o horario de atendimento!", "positivo"),
        row("3", "Como exportar o relatório de vendas?", channel="eval"),
        row("4", "ok"),
        row("5", "Como configurar uma conexão WABA?", mode="invalid"),
    ]
    cases = select_cases(rows, [], 12)
    assert len(cases) == 1
    assert cases[0]["query"] == rows[0]["pergunta"]
    assert "user_id" not in cases[0]
    assert cases[0]["analyst_reference"] is None


def test_selection_balances_feedback_and_modes_and_prioritizes_references():
    rows = [
        row("p1", "Como configurar o horário de atendimento?", "positivo"),
        row("p2", "Como configurar uma conexão WABA?", "positivo", "bug"),
        row("p3", "Como configurar o robô de atendimento?", "positivo"),
        row("n1", "Como solicitar um backup da plataforma?", "negativo"),
        row("u1", "Como exportar o relatório de atendimentos?", None),
    ]
    cases = select_cases(rows, [correction(rows[3]["pergunta"])], 4)
    assert len(cases) == 4
    assert {c["feedback"] for c in cases} == {None, "negativo", "positivo"}
    assert {c["mode"] for c in cases} == {"orientacao", "bug"}
    assert (
        next(c for c in cases if c["source_id"] == "n1")["analyst_reference"] == "Resposta revisada"
    )


def test_unconfirmed_discarded_and_superseded_references_are_not_answers():
    query = "Como configurar o horário de atendimento?"
    corrections = [
        correction(query),
        correction(query, "[descartada: correta]", False, 0, "2026-10-02"),
    ]
    assert select_cases([row("1", query)], corrections, 1)[0]["analyst_reference"] is None
    assert (
        select_cases([row("1", query)], [correction(query, ingested=False)], 1)[0][
            "analyst_reference"
        ]
        is None
    )
    assert (
        select_cases([row("1", query)], [correction(query, chunks=0)], 1)[0]["analyst_reference"]
        is None
    )


def test_pilot_rejects_invalid_limit():
    with pytest.raises(ValueError):
        select_cases([], [], 31)


def test_missing_configuration_rejects_anon_only_before_network():
    config = Settings(supabase_url="https://example.supabase.co", supabase_anon_key="anonymous")
    with pytest.raises(ValueError):
        require_config(config)
    with pytest.raises(PilotSourceError):
        PilotSourceService(config, client=MagicMock())


@pytest.mark.asyncio
async def test_source_capture_is_read_only_bounded_and_excludes_user_identifiers():
    import threading

    caller = threading.get_ident()
    read_threads = []
    client = MagicMock()
    builder = client.table.return_value
    for method in ("select", "eq", "is_", "order", "limit"):
        getattr(builder, method).return_value = builder

    def execute():
        read_threads.append(threading.get_ident())
        return MagicMock(data=[{"id": "record"}])

    builder.execute.side_effect = execute
    config = Settings(
        supabase_url="https://example.supabase.co", supabase_service_role_key="backend"
    )
    source = PilotSourceService(config, client=client)
    captured = await source.capture()
    assert len(captured["history"]) == 3
    assert len(captured["corrections"]) == 1
    assert read_threads and all(thread != caller for thread in read_threads)
    assert all("user_id" not in call.args[0] for call in builder.select.call_args_list)
    assert all(call.args == (100,) for call in builder.limit.call_args_list)
    builder.insert.assert_not_called()
    builder.update.assert_not_called()
    builder.delete.assert_not_called()
    await source.aclose()
    client.postgrest.aclose.assert_not_called()


@pytest.mark.asyncio
async def test_source_read_failure_is_generic_and_not_a_successful_empty_sample():
    client = MagicMock()
    client.table.side_effect = RuntimeError("internal server details")
    config = Settings(
        supabase_url="https://example.supabase.co", supabase_service_role_key="backend"
    )
    with pytest.raises(PilotSourceError, match="Unable to read pilot sources") as error:
        await PilotSourceService(config, client=client).capture()
    assert "internal" not in str(error.value)


@pytest.mark.asyncio
async def test_variant_failure_preserves_baselines_and_never_approves_a_failed_verifier():
    document = Document(id="real-id", content="Fonte", embedding=[0.1])
    case = FrozenCase(id="case", query="Como configurar?", documents=[document])
    openai = MagicMock()
    openai.rerank = AsyncMock(return_value=[document])
    openai.generate_response = AsyncMock(return_value="Resposta")
    openai.format_response = AsyncMock(return_value="Resposta final")
    typesafe = MagicMock()
    typesafe.rerank = AsyncMock(side_effect=RuntimeError("private data"))
    typesafe.verify = AsyncMock(side_effect=RuntimeError("private data"))
    variants = await compare_pilot_case(case, openai, typesafe)
    assert variants["A"]["response"] == "Resposta final"
    assert variants["B"]["response"] == "Resposta final"
    assert variants["A"]["verification"]["transport_status"] == "error"
    assert not variants["A"]["verification"]["approved"]
    assert variants["C"] == {"status": "error", "error_type": "RuntimeError"}
    assert variants["D"]["status"] == "error"
    assert "private data" not in str(variants)


@pytest.mark.asyncio
async def test_d_simulates_delivery_of_exact_c_response_without_regeneration():
    document = Document(id="real-id", content="Fonte", embedding=[0.1])
    case = FrozenCase(id="case", query="Como configurar?", documents=[document])
    openai = MagicMock()
    openai.rerank = AsyncMock(return_value=[document])
    openai.generate_response = AsyncMock(return_value="Resposta")
    openai.format_response = AsyncMock(return_value="Resposta final")
    typesafe = MagicMock()
    typesafe.rerank = AsyncMock(return_value=[document])
    typesafe.verify = AsyncMock(return_value=VerificationResult(status="supported", approved=True))
    variants = await compare_pilot_case(case, openai, typesafe, top_n=3)
    assert variants["D"]["delivered_response"] == variants["C"]["response"]
    assert openai.generate_response.await_count == 3
    assert all(call.args[1] == "Resposta final" for call in typesafe.verify.await_args_list)
    assert all(call.args[1] == [document] for call in openai.rerank.await_args_list)
    assert typesafe.rerank.await_args.kwargs["top_n"] == 3


@pytest.mark.asyncio
async def test_historical_verification_requires_every_original_source():
    database = MagicMock()
    database.get_document = AsyncMock(return_value=None)
    typesafe = MagicMock()
    typesafe.verify = AsyncMock()
    case = {
        "query": "Pergunta",
        "historical_response": "Resposta",
        "historical_source_ids": ["old-id"],
    }
    result = await historical_verification(case, database, typesafe)
    assert result["transport_status"] == "not_evaluated"
    typesafe.verify.assert_not_called()
    case["historical_source_ids_valid"] = False
    database.get_document.reset_mock()
    assert (await historical_verification(case, database, typesafe))[
        "transport_status"
    ] == "not_evaluated"
    database.get_document.assert_not_called()


@pytest.mark.asyncio
async def test_empty_evidence_is_not_counted_as_live_model_evaluation():
    typesafe = MagicMock()
    typesafe.verify = AsyncMock()
    verification = await verify_response(typesafe, "Pergunta", "Resposta", [])
    typesafe.verify.assert_not_called()
    summary = summarize([{"variants": {"A": {"verification": verification}}}])
    assert summary["A"]["evaluated"] == 0
    assert summary["A"]["not_evaluated_or_error"] == 1


@pytest.mark.asyncio
async def test_historical_document_projection_uses_real_id_text_and_omits_vectors():
    client = MagicMock()
    query = client.table.return_value
    for name in ("select", "eq", "limit"):
        getattr(query, name).return_value = query
    query.execute.return_value.data = [{"id": 0, "content": "Fonte real", "metadata": {}}]
    config = Settings(
        supabase_url="https://example.supabase.co", supabase_service_role_key="backend"
    )
    source = PilotSourceService(config, client=client)
    document = await source.get_document("0")
    assert document is not None and document.id == "0" and document.content == "Fonte real"
    assert query.select.call_args.args == ("id,content,metadata",)
    query.execute.reset_mock()
    assert await source.get_document("discord-upload") is None
    query.execute.assert_not_called()


@pytest.mark.asyncio
async def test_historical_source_read_error_never_exposes_database_details():
    client = MagicMock()
    client.table.side_effect = RuntimeError("credential and internal details")
    config = Settings(
        supabase_url="https://example.supabase.co", supabase_service_role_key="backend"
    )
    with pytest.raises(PilotSourceError, match="Unable to read historical source") as error:
        await PilotSourceService(config, client=client).get_document("10")
    assert "credential" not in str(error.value)


@pytest.mark.asyncio
async def test_owned_source_closes_both_sdk_clients_even_after_close_failure(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(
        "src.services.pilot_source_service.create_client", lambda *args, **kwargs: client
    )
    config = Settings(
        supabase_url="https://example.supabase.co", supabase_service_role_key="backend"
    )
    source = PilotSourceService(config)
    client.postgrest.aclose.side_effect = RuntimeError("close failed")
    with pytest.raises(RuntimeError, match="close failed"):
        await source.aclose()
    client.postgrest.aclose.assert_called_once()
    client.auth.close.assert_called_once()


def test_incompatible_shared_candidate_limit_rejected_before_network():
    config = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="backend",
        openai_api_key="openai-test",
        typesafe_api_key="jev-test",
        max_chunks=15,
        typesafe_max_candidates=35,
    )
    with pytest.raises(ValueError, match="candidates exceed"):
        require_config(config)
