import copy
import json

import httpx
import pytest

from evals.jev_calibration import (
    digest,
    freeze_profile,
    run_reserved,
    validate_profile,
    validate_splits,
)
from evals.jev_controls import ControlCase
from src.config import Settings
from src.models.schemas import Document
from src.services.typesafe_criteria import CRITERIA_VERSION, verification_questions


def cases(split):
    return [
        ControlCase(
            id=f"{split}-{kind}",
            family=f"{split}-family",
            split=split,
            kind=kind,
            query=f"Como configurar o recurso {split}?",
            response=f"{kind} do recurso {split}",
            documents=[Document(id=f"{split}-source", content=f"Fonte {split}", embedding=[])],
            expected_relation=relation,
            annotation_status="ai_reviewed",
            reviewed_by="IA teste",
            notes="Revisão de suporte documental para teste offline.",
        )
        for kind, relation in (
            ("reference", "supported"),
            ("paraphrase", "supported"),
            ("contradiction", "contradicted"),
            ("unsupported", "unsupported"),
        )
    ]


def calibration_report(calibration):
    results = []
    for case in calibration:
        positive = case.expected_relation == "supported"
        points = {
            "supported": 0.88 if case.kind == "reference" else 0.89,
            "respects_curation": 0.89,
            "contradiction": 0.11,
        }
        if not positive:
            points = {"supported": 0.03, "respects_curation": 0.2, "contradiction": 0.9}
        results.append(
            {
                **case.model_dump(),
                "runs": [
                    {
                        "protocol": "v2",
                        "repeat": repeat,
                        "transport_status": "ok",
                        "verification": {"probabilities": points},
                        "events": [
                            {
                                "status": "ok",
                                "truncated": False,
                                "model": "jev-1.13.0",
                                "criteria_version": CRITERIA_VERSION,
                            }
                        ],
                    }
                    for repeat in (1, 2, 3)
                ],
            }
        )
    return {
        "model": "jev-1.13.0",
        "criteria_version": CRITERIA_VERSION,
        "protocol_hashes": {"v2": digest(verification_questions())},
        "repetitions": 3,
        "support_threshold": 0.9,
        "contradiction_threshold": 0.1,
        "results": results,
    }


@pytest.fixture
def experiment():
    calibration, reserved = cases("calibration"), cases("reserved")
    report = calibration_report(calibration)
    profile = freeze_profile(calibration, reserved, report, "jev-1.13.0")
    return calibration, reserved, report, profile


def test_identical_source_content_with_new_ids_cannot_leak_into_reserve():
    calibration, reserved = cases("calibration"), cases("reserved")
    for case in reserved:
        case.documents[0].content = calibration[0].documents[0].content
    with pytest.raises(ValueError, match="overlap"):
        validate_splits(calibration, reserved)


def test_conservative_feasible_policy_is_frozen_without_human_approval(experiment):
    calibration, reserved, report, profile = experiment
    assert profile["selected"]["support"] == 0.88
    assert profile["selected"]["contradiction"] == 0.12
    assert profile["selected"]["metrics"]["proposed_false_blocks"] == 0
    assert profile["selected"]["metrics"]["proposed_false_accepts"] == 0
    assert profile["baseline_calibration_metrics"]["proposed_false_blocks"] == 6
    assert profile["selected"]["metrics"]["human_reviewed_observations"] == 0
    assert profile["human_review_required"] and not profile["ready_for_enforcement"]
    validate_profile(profile, calibration, reserved, report, "jev-1.13.0")


@pytest.mark.parametrize("mutation", ["policy", "reserved", "calibration", "model", "report"])
def test_frozen_profile_or_evidence_changes_are_rejected(experiment, mutation):
    calibration, reserved, report, profile = experiment
    model = "jev-1.13.0"
    if mutation == "policy":
        profile["selected"]["support"] = 0.85
    elif mutation == "reserved":
        reserved[0].response = "Texto alterado depois do congelamento"
    elif mutation == "calibration":
        calibration[0].notes += " revisão nova"
    elif mutation == "model":
        model = "outro-modelo"
    else:
        report["results"][0]["runs"][0]["verification"]["probabilities"]["supported"] = 0.87
    with pytest.raises(ValueError):
        validate_profile(profile, calibration, reserved, report, model)


@pytest.mark.parametrize(
    "invalid",
    ["failure", "truncated", "missing", "duplicate", "nan", "rubric", "text", "no_policy"],
)
def test_incomplete_or_incompatible_calibration_cannot_create_profile(experiment, invalid):
    calibration, reserved, report, _ = experiment
    run = report["results"][0]["runs"][0]
    if invalid == "failure":
        run["transport_status"] = "error"
    elif invalid == "truncated":
        run["events"][0]["truncated"] = True
    elif invalid == "missing":
        report["results"][0]["runs"].pop()
    elif invalid == "duplicate":
        report["results"][0]["runs"][1]["repeat"] = 1
    elif invalid == "nan":
        run["verification"]["probabilities"]["supported"] = float("nan")
    elif invalid == "rubric":
        report["protocol_hashes"]["v2"] = "old"
    elif invalid == "text":
        report["results"][0]["response"] = "Outro texto"
    else:
        for result in report["results"][:2]:
            for observation in result["runs"]:
                observation["verification"]["probabilities"]["supported"] = 0.1
    with pytest.raises(ValueError):
        freeze_profile(calibration, reserved, report, "jev-1.13.0")


@pytest.mark.parametrize(
    "invalid", ["draft", "missing_negative", "family", "question", "source", "relation"]
)
def test_unreviewed_incomplete_or_overlapping_reserve_rejected(experiment, invalid):
    calibration, reserved, report, _ = experiment
    if invalid == "draft":
        reserved[0].annotation_status = "draft"
    elif invalid == "missing_negative":
        reserved.pop()
    elif invalid == "family":
        reserved[0].family = calibration[0].family
    elif invalid == "question":
        reserved[0].query = calibration[0].query.upper() + "!"
    elif invalid == "source":
        reserved[0].documents[0].id = calibration[0].documents[0].id
    else:
        reserved[0].expected_relation = "unsupported"
    with pytest.raises(ValueError):
        freeze_profile(calibration, reserved, report, "jev-1.13.0")


@pytest.mark.asyncio
async def test_reserve_compares_same_probabilities_and_preserves_configuration(
    experiment, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    calibration, reserved, report, profile = experiment
    payloads = []

    def handler(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        positive = payload["state"]["response"].startswith(("reference", "paraphrase"))
        points = {
            "supported": 0.89 if positive else 0.05,
            "respects_curation": 0.95,
            "contradiction": 0.11 if positive else 0.8,
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
    config = Settings(typesafe_api_key="test")
    original = copy.deepcopy(config.model_dump())
    output = tmp_path / "evals/reports/reserved.json"
    await run_reserved(calibration, reserved, report, profile, config, output, 2, client=client)
    result = json.loads(output.read_text())
    assert result["complete"] and len(payloads) == 8
    assert result["summary"]["baseline"]["proposed_false_blocks"] == 4
    assert result["summary"]["experimental"]["proposed_false_blocks"] == 0
    assert result["summary"]["experimental"]["proposed_false_accepts"] == 0
    assert not result["ready_for_enforcement"] and not result["quality_validated"]
    assert result["summary"]["experimental"]["human_reviewed_observations"] == 0
    assert result["results"][0]["runs"][0]["policy_approvals"] == {
        "baseline": False,
        "experimental": True,
    }
    assert all(set(p["state"]) == {"query", "response", "documents"} for p in payloads)
    assert config.model_dump() == original and not client.is_closed
    # A second evaluation must not overwrite its preceding observations.
    with pytest.raises(ValueError, match="already exists"):
        await run_reserved(calibration, reserved, report, profile, config, output, 1, client=client)
    assert len(payloads) == 8
    await client.aclose()


@pytest.mark.asyncio
async def test_external_failure_is_persisted_without_claiming_semantic_rejection(
    experiment, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    calibration, reserved, report, profile = experiment
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"detail": "private upstream details"})
        )
    )
    output = tmp_path / "evals/reports/failure.json"
    with pytest.raises(ValueError, match="Technical failures"):
        await run_reserved(
            calibration,
            reserved,
            report,
            profile,
            Settings(typesafe_api_key="test"),
            output,
            1,
            client=client,
        )
    saved = json.loads(output.read_text())
    assert not saved["complete"]
    assert saved["summary"]["experimental"]["technical_errors"] == 4
    assert saved["summary"]["experimental"]["positive_evaluated"] == 0
    assert saved["summary"]["experimental"]["proposed_false_blocks"] == 0
    assert "private upstream details" not in output.read_text()
    await client.aclose()


@pytest.mark.asyncio
async def test_missing_configuration_invalid_repetitions_and_path_stop_before_transport(
    experiment, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    calibration, reserved, report, profile = experiment
    for config, output, repeats, message in (
        (Settings(), tmp_path / "evals/reports/a.json", 1, "API_KEY"),
        (Settings(typesafe_api_key="test"), tmp_path / "evals/reports/b.json", 6, "repetitions"),
        (Settings(typesafe_api_key="test"), tmp_path / "outside.json", 1, "inside"),
    ):
        with pytest.raises(ValueError, match=message):
            await run_reserved(calibration, reserved, report, profile, config, output, repeats)
        assert not output.exists()
