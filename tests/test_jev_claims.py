import copy
import json

import httpx
import pytest
from pydantic import ValidationError

from evals.jev_claims import (
    ClaimCase,
    ClaimSpan,
    aggregate,
    experimental_settings,
    freeze_manifest,
    run_experiment,
)
from evals.jev_controls import ControlCase
from src.config import Settings
from src.models.schemas import Document


def case(**overrides):
    control = ControlCase(
        id="case",
        family="family",
        kind="reference",
        query="Como contratar usuários?",
        response="Abra Meu Plano. Ajuste a quantidade.",
        documents=[
            Document(id="source", content="Abra Meu Plano. Ajuste a quantidade.", embedding=[])
        ],
        expected_relation="supported",
        annotation_status="ai_reviewed",
        reviewed_by="IA teste",
        notes="Anotação offline de teste.",
    )
    fields = {
        "control": control,
        "purpose": "development",
        "coverage_reviewer": "IA teste",
        "segments": [
            ClaimSpan(
                id="first", start=0, end=15, expected_relation="supported", notes="Primeiro fato."
            ),
            ClaimSpan(
                id="second",
                start=16,
                end=len(control.response),
                expected_relation="supported",
                notes="Segundo fato.",
            ),
        ],
    }
    return ClaimCase(**(fields | overrides))


def test_missing_factual_suffix_cannot_be_treated_as_complete_response():
    with pytest.raises(ValidationError, match="coverage"):
        case(
            segments=[
                ClaimSpan(
                    id="first",
                    start=0,
                    end=15,
                    expected_relation="supported",
                    notes="Primeiro fato.",
                )
            ]
        )


def test_list_number_alone_is_not_a_factual_claim():
    control = case().control.model_copy(update={"response": "1."})
    with pytest.raises(ValidationError, match="factual content"):
        case(
            control=control,
            segments=[
                ClaimSpan(
                    id="number",
                    start=0,
                    end=2,
                    expected_relation="supported",
                    notes="Marcador de lista.",
                )
            ],
        )


def test_unmapped_factual_prefix_cannot_be_approved():
    with pytest.raises(ValidationError, match="coverage"):
        case(
            segments=[
                ClaimSpan(
                    id="second",
                    start=16,
                    end=35,
                    expected_relation="supported",
                    notes="Segundo fato.",
                )
            ]
        )


@pytest.mark.parametrize(
    "invalid", ["overlap", "bounds", "blank", "no_facts", "missing_label", "structural_label"]
)
def test_invalid_spans_rejected(invalid):
    control = case().control
    span = {
        "id": "all",
        "start": 0,
        "end": len(control.response),
        "expected_relation": "supported",
        "notes": "Fato.",
    }
    segments = [span]
    if invalid == "overlap":
        segments.append({**span, "id": "duplicate"})
    elif invalid == "bounds":
        span["end"] += 1
    elif invalid == "blank":
        span.update(start=15, end=16)
    elif invalid == "no_facts":
        span.update(kind="structural", expected_relation=None)
    elif invalid == "missing_label":
        span["expected_relation"] = None
    else:
        span["kind"] = "structural"
    with pytest.raises(ValidationError):
        case(segments=segments)


def test_missing_or_failed_claim_never_approves_aggregate():
    good = {
        "id": "good",
        "evaluation": {"transport_status": "ok", "verification": {"approved": True}},
    }
    bad = {
        "id": "bad",
        "evaluation": {"transport_status": "ok", "verification": {"approved": False}},
    }
    assert aggregate([good, bad], 2) == {
        "transport_status": "ok",
        "approved": False,
        "blocked_claim_ids": ["bad"],
    }
    assert not aggregate([good], 2)["approved"]
    assert (
        aggregate([good, {"id": "failed", "evaluation": {"transport_status": "error"}}], 2)[
            "transport_status"
        ]
        == "error"
    )


def experiment():
    development = case()
    seen = [development.control.model_copy(deep=True)]
    reserved = []
    for kind, relation in (
        ("reference", "supported"),
        ("paraphrase", "supported"),
        ("contradiction", "contradicted"),
        ("unsupported", "unsupported"),
    ):
        control = development.control.model_copy(deep=True)
        control.id = f"reserved-{kind}"
        control.family = "unseen-family"
        control.query = "Como exportar o relatório?"
        control.split = "reserved"
        control.kind = kind
        control.expected_relation = relation
        control.documents = [
            Document(id="unseen-source", content="Exporte no menu Relatórios.", embedding=[])
        ]
        control.response = (
            "Exporte no menu Relatórios."
            if relation == "supported"
            else "O relatório custa R$ 500."
        )
        reserved.append(
            ClaimCase(
                control=control,
                purpose="reserved",
                coverage_reviewer="IA teste",
                segments=[
                    ClaimSpan(
                        id="all",
                        start=0,
                        end=len(control.response),
                        expected_relation=relation,
                        notes="Trecho inteiro.",
                    )
                ],
            )
        )
    config = experimental_settings(Settings(typesafe_api_key="test"))
    cases = [development, *reserved]
    return cases, seen, config, freeze_manifest(cases, config, 1, seen)


@pytest.mark.parametrize(
    "invalid", ["seen_query", "seen_source", "seen_content", "family", "manifest", "budget"]
)
def test_frozen_policy_and_independent_reserve_reject_invalid_inputs(invalid):
    cases, seen, config, _manifest = experiment()
    if invalid == "seen_query":
        cases[1].control.query = seen[0].query
    elif invalid == "seen_source":
        cases[1].control.documents[0].id = seen[0].documents[0].id
    elif invalid == "seen_content":
        cases[1].control.documents[0].content = seen[0].documents[0].content
    elif invalid == "family":
        cases[1].control.family = seen[0].family
    elif invalid == "manifest":
        config = config.model_copy(update={"typesafe_support_threshold": 0.85})
    else:
        copies = []
        for index in range(30):
            item = cases[0].model_copy(deep=True)
            item.control.id = f"copy-{index}"
            item.control.response = "Fato. " * 10
            item.segments = [
                ClaimSpan(
                    id=str(i),
                    start=i * 6,
                    end=i * 6 + 6,
                    expected_relation="supported",
                    notes="Trecho.",
                )
                for i in range(10)
            ]
            copies.append(item)
        cases = [*copies, *cases[1:]]
    with pytest.raises(ValueError):
        freeze_manifest(cases, config, 3, seen)


@pytest.mark.asyncio
async def test_comparison_saves_each_claim_and_never_sends_expected_labels(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cases, seen, config, manifest = experiment()
    before = copy.deepcopy(config.model_dump())
    payloads = []

    def handler(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        text = payload["state"]["response"]
        valid = text != cases[0].control.response and "R$" not in text
        points = {
            "supported": 0.95 if valid else 0.05,
            "contradiction": 0.03,
            "respects_curation": 0.95,
        }
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {key: {"type": "noul", "noul": p} for key, p in points.items()},
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    output = tmp_path / "evals/reports/claims.json"
    await run_experiment(cases, seen, manifest, config, output, client=client)
    saved = json.loads(output.read_text())
    assert len(payloads) == manifest["planned_evaluations"] == 11
    assert all(set(p["state"]) == {"query", "response", "documents"} for p in payloads)
    assert saved["results"][0]["runs"][0]["by_claim"]["approved"]
    assert saved["summary"]["development"]["whole"]["proposed_false_blocks"] == 1
    assert saved["summary"]["development"]["by_claim"]["proposed_false_blocks"] == 0
    assert saved["summary"]["reserved"]["by_claim"]["proposed_false_accepts"] == 0
    assert config.model_dump() == before and not client.is_closed
    assert saved["complete"] and not saved["ready_for_enforcement"]
    with pytest.raises(ValueError, match="already exists"):
        await run_experiment(cases, seen, manifest, config, output, client=client)
    assert len(payloads) == 11
    await client.aclose()


@pytest.mark.asyncio
async def test_bad_atomic_claim_blocks_response_even_if_whole_response_approved(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    cases, seen, config, manifest = experiment()

    def handler(request):
        text = json.loads(request.content)["state"]["response"]
        points = {
            "supported": 0.05 if text == "Ajuste a quantidade." else 0.95,
            "contradiction": 0.03,
            "respects_curation": 0.95,
        }
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {key: {"type": "noul", "noul": p} for key, p in points.items()},
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    output = tmp_path / "evals/reports/mixed.json"
    await run_experiment(cases, seen, manifest, config, output, client=client)
    run = json.loads(output.read_text())["results"][0]["runs"][0]
    assert run["whole"]["verification"]["approved"]
    assert not run["by_claim"]["approved"]
    assert run["by_claim"]["blocked_claim_ids"] == ["second"]
    await client.aclose()


@pytest.mark.asyncio
async def test_failed_transport_is_persisted_and_not_a_semantic_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cases, seen, config, manifest = experiment()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"detail": "private failure"})
        )
    )
    output = tmp_path / "evals/reports/error.json"
    with pytest.raises(ValueError, match="Technical failures"):
        await run_experiment(cases, seen, manifest, config, output, client=client)
    saved = json.loads(output.read_text())
    assert not saved["complete"]
    assert saved["summary"]["development"]["by_claim"]["technical_errors"] == 1
    assert saved["summary"]["development"]["by_claim"]["positive_evaluated"] == 0
    assert saved["summary"]["development"]["by_claim"]["proposed_false_blocks"] == 0
    assert "private failure" not in output.read_text()
    await client.aclose()


@pytest.mark.asyncio
async def test_missing_key_and_changed_frozen_case_stop_before_network(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cases, seen, config, manifest = experiment()
    output = tmp_path / "evals/reports/a.json"
    with pytest.raises(ValueError, match="API_KEY"):
        await run_experiment(
            cases, seen, manifest, config.model_copy(update={"typesafe_api_key": None}), output
        )
    cases[0].coverage_reviewer = "Alterado depois do congelamento"
    with pytest.raises(ValueError, match="changed"):
        await run_experiment(cases, seen, manifest, config, output)
    assert not output.exists()
