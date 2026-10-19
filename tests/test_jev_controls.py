import json

import httpx
import pytest
from pydantic import ValidationError

from evals.jev_controls import (
    ControlCase,
    ControlService,
    build_reserved_controls,
    evaluate_control,
    load_controls,
    run_controls,
    summarize_controls,
)
from src.config import Settings
from src.models.schemas import Document


def control(**overrides):
    fields = {
        "id": "positive",
        "family": "real-reference",
        "kind": "paraphrase",
        "query": "Como contratar usuários?",
        "response": "Ajuste a quantidade em Meu Plano.",
        "documents": [
            Document(
                id="real-id",
                content="A quantidade contratada é ajustada em Meu Plano.",
                embedding=[0.1],
                metadata={"tipo": "curadoria"},
            )
        ],
        "expected_relation": "supported",
    }
    return ControlCase(**(fields | overrides))


def write_cases(tmp_path, cases):
    path = tmp_path / "controls.jsonl"
    path.write_text("".join(case.model_dump_json() + "\n" for case in cases))
    return path


def test_same_question_with_different_source_ids_cannot_cross_splits(tmp_path):
    first = control()
    second = control(
        id="other",
        family="other-family",
        query="COMO contratar usuarios!",
        split="reserved",
        documents=[
            Document(
                id="other-id", content="Uma fonte distinta para a mesma pergunta", embedding=[]
            )
        ],
    )
    with pytest.raises(ValueError, match="question cannot cross"):
        load_controls(write_cases(tmp_path, [first, second]))


@pytest.mark.parametrize("duplicate", ["id", "family", "source"])
def test_duplicate_ids_and_cross_split_references_rejected(tmp_path, duplicate):
    first = control()
    second = control(
        id="other",
        family="other-family",
        query="Como excluir uma conexão?",
        split="reserved",
        documents=[Document(id="other-id", content="Outra fonte", embedding=[])],
    )
    if duplicate == "id":
        second.id = first.id
    elif duplicate == "family":
        second.family = first.family
    else:
        second.documents = first.documents
    with pytest.raises(ValueError):
        load_controls(write_cases(tmp_path, [first, second]))


@pytest.mark.parametrize(
    "fields",
    [
        {"annotation_status": "reviewed"},
        {"response": " "},
        {"query": "x" * 8001},
        {"documents": []},
        {
            "documents": [
                Document(
                    id="retired",
                    content="Old",
                    embedding=[],
                    metadata={"substituido_por": "current"},
                )
            ]
        },
    ],
)
def test_invalid_control_and_unconfirmed_annotation_rejected(fields):
    with pytest.raises(ValidationError):
        control(**fields)


def test_ai_annotation_is_explicit_and_does_not_count_as_human_review():
    case = control(annotation_status="ai_reviewed", reviewed_by="Codex (IA)")
    result = {
        **case.model_dump(),
        "runs": [
            {
                "protocol": "v2",
                "transport_status": "ok",
                "verification": {"approved": True, "status": "supported"},
            }
        ],
    }
    assert summarize_controls([result])["v2"]["human_reviewed_observations"] == 0


def test_ai_annotation_requires_a_named_reviewer():
    with pytest.raises(ValidationError, match="reviewer"):
        control(annotation_status="ai_reviewed")


@pytest.mark.asyncio
async def test_protocols_share_real_control_inputs_without_leaking_expected_labels():
    payloads = []

    def handler(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    key: {"type": "noul", "noul": 0.01 if key == "contradiction" else 0.98}
                    for key in payload["questions"]
                },
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = ControlService(Settings(typesafe_api_key="test"), client=client)
    result = await evaluate_control(control(), service, 2)
    assert [run["protocol"] for run in result["runs"]] == ["v1", "v2", "v2", "v1"]
    assert all(payload["state"] == payloads[0]["state"] for payload in payloads)
    assert set(payloads[0]["state"]) == {"query", "response", "documents"}
    assert payloads[0]["questions"] != payloads[1]["questions"]
    assert service._budget_used == pytest.approx(400 * 0.042 / 1_000_000)
    assert all(run["verification"]["approved"] for run in result["runs"])
    summary = summarize_controls([result])
    assert summary["v2"]["human_reviewed_observations"] == 0
    assert summary["v2"]["proposed_false_blocks"] == 0
    await service.aclose()
    assert not client.is_closed
    await client.aclose()


@pytest.mark.asyncio
async def test_external_failure_is_not_counted_as_a_labelled_rejection():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"detail": "private details"})
        )
    )
    service = ControlService(Settings(typesafe_api_key="test"), client=client)
    result = await evaluate_control(control(), service, 1)
    summary = summarize_controls([result])
    assert summary["v1"]["technical_errors"] == 1
    assert summary["v2"]["positive_evaluated"] == 0
    assert summary["v2"]["proposed_false_blocks"] == 0
    assert "private details" not in str(result)
    await client.aclose()


@pytest.mark.asyncio
async def test_shared_budget_exhaustion_blocks_both_protocols_before_transport():
    calls = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request)))
    service = ControlService(
        Settings(typesafe_api_key="test", typesafe_budget_usd=0.00000001), client=client
    )
    result = await evaluate_control(control(), service, 1)
    assert all(run["transport_status"] == "error" for run in result["runs"])
    assert not calls
    await client.aclose()


@pytest.mark.asyncio
async def test_missing_key_and_reserved_dataset_rejected_before_external_calls(tmp_path):
    with pytest.raises(ValueError, match="API_KEY"):
        await run_controls([control()], Settings(), tmp_path / "report.json", 1)
    with pytest.raises(ValueError, match="Reserved controls"):
        await run_controls(
            [control(split="reserved")],
            Settings(typesafe_api_key="test"),
            tmp_path / "report.json",
            1,
        )


def test_reserve_excludes_seen_and_superseded_references_and_stays_unreviewed():
    rows = [
        {
            "id": "seen",
            "pergunta": "COMO contratar usuarios!",
            "resposta_correta": "Resposta conhecida",
            "ingerida": True,
            "chunks_criados": 1,
        },
        {
            "id": "valid",
            "pergunta": "Como configurar o horário de atendimento?",
            "resposta_correta": "Abra Configurações e selecione Horários.",
            "ingerida": True,
            "chunks_criados": 1,
        },
        {
            "id": "discarded-new",
            "pergunta": "Como exportar os relatórios?",
            "resposta_correta": "[descartada: correta]",
            "ingerida": False,
            "chunks_criados": 0,
            "criado_em": "2026-10-02",
        },
        {
            "id": "discarded-old",
            "pergunta": "Como exportar os relatórios?",
            "resposta_correta": "Abra relatórios.",
            "ingerida": True,
            "chunks_criados": 1,
            "criado_em": "2026-10-01",
        },
    ]
    reserved = build_reserved_controls(rows, {"Como contratar usuários?"}, 8)
    assert len(reserved) == 1
    assert reserved[0].family == "valid"
    assert reserved[0].split == "reserved"
    assert reserved[0].annotation_status == "draft"
    assert reserved[0].response == reserved[0].documents[0].content
