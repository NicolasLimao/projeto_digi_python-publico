import copy
import json

import httpx
import pytest

from evals.jev_claims import ClaimCase, experimental_settings
from evals.jev_context import aggregate, freeze_manifest, run_experiment, select_profile
from src.config import Settings
from src.services.claim_verification_service import documentary_questions, relation_questions


def observation(value):
    return {"transport_status": "ok", "value": value}


def good_run():
    return {
        "curation": observation(0.99),
        "claims": [
            {
                "id": "fact",
                "evaluation": observation(
                    {
                        "type": "choice",
                        "choice": "supports",
                        "probabilities": {
                            "supports": 0.98,
                            "contradicts": 0.01,
                            "says_nothing": 0.01,
                        },
                        "confidence": 0.90,
                    }
                ),
            }
        ],
    }


def test_global_curation_cannot_be_bypassed_by_supported_claims():
    run = good_run()
    run["curation"] = observation(0.2)
    assert not aggregate(run, 0.95, 1)["approved"]


@pytest.mark.parametrize("failure", ["claim", "curation", "missing", "uncertain"])
def test_missing_failed_or_uncertain_constituent_cannot_approve(failure):
    run = good_run()
    if failure == "claim":
        run["claims"][0]["evaluation"] = {"transport_status": "error"}
    elif failure == "curation":
        run["curation"] = {"transport_status": "error"}
    elif failure == "missing":
        run["claims"] = []
    else:
        run["claims"][0]["evaluation"]["value"]["confidence"] = 0.70
    assert not aggregate(run, 0.95, 1)["approved"]


def experiment():
    cases = []
    for purpose, kinds in (
        ("development", ["reference", "contradiction", "unsupported"]),
        ("reserved", ["reference", "paraphrase", "contradiction", "unsupported"]),
    ):
        for kind in kinds:
            relation = {
                "reference": "supported",
                "paraphrase": "supported",
                "contradiction": "contradicted",
                "unsupported": "unsupported",
            }[kind]
            response = {
                "supported": "Abra Relatórios.",
                "contradicted": "Não abra Relatórios.",
                "unsupported": "Custa R$ 999.",
            }[relation]
            cases.append(
                ClaimCase.model_validate(
                    {
                        "control": {
                            "id": purpose + kind,
                            "family": purpose,
                            "split": "calibration" if purpose == "development" else "reserved",
                            "kind": kind,
                            "query": "Como exportar?"
                            if purpose == "development"
                            else "Onde consultar?",
                            "response": response,
                            "documents": [
                                {
                                    "id": purpose,
                                    "content": "Abra Relatórios."
                                    if purpose == "development"
                                    else "Consulte os dados: abra Relatórios.",
                                    "embedding": [],
                                }
                            ],
                            "expected_relation": relation,
                            "annotation_status": "ai_reviewed",
                            "reviewed_by": "IA teste",
                            "notes": "Controle offline.",
                        },
                        "purpose": purpose,
                        "coverage_reviewer": "IA teste",
                        "segments": [
                            {
                                "id": "fact",
                                "start": 0,
                                "end": len(response),
                                "expected_relation": relation,
                                "notes": "Texto integral.",
                            }
                        ],
                    }
                )
            )
    seen = [c.control for c in cases if c.purpose == "development"]
    config = experimental_settings(Settings(typesafe_api_key="test"))
    return cases, seen, config, freeze_manifest(cases, config, 1, seen)


def handler(request):
    payload = json.loads(request.content)
    text = payload["state"].get("claim", payload["state"].get("response"))
    supported = text == "Abra Relatórios."
    if "relation" in payload["questions"]:
        answer = good_run()["claims"][0]["evaluation"]["value"]
        if not supported:
            answer.update(
                choice="says_nothing",
                probabilities={"supports": 0.01, "contradicts": 0.01, "says_nothing": 0.98},
            )
        answers = {"relation": answer}
    else:
        answers = {
            key: {
                "type": "noul",
                "noul": 0.01
                if key == "contradiction" or (key == "supported" and not supported)
                else 0.99,
            }
            for key in payload["questions"]
        }
    return httpx.Response(
        200,
        json={
            "model": "jev-1.13.0",
            "answers": answers,
            "usage": {"input_tokens": 100, "output_tokens": 10},
        },
    )


@pytest.mark.asyncio
async def test_calibration_profile_then_reserved_preserves_inputs_and_counts_global_once(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    cases, seen, config, manifest = experiment()
    original = copy.deepcopy(config.model_dump())
    requests = []

    def recording(request):
        requests.append(json.loads(request.content))
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(recording))
    output = tmp_path / "evals/reports/calibration.json"
    await run_experiment(cases, seen, manifest, config, output, phase="calibration", client=client)
    calibration = json.loads(output.read_text())
    profile = select_profile(calibration, cases, manifest)
    assert profile["selected_support_floor"] == 0.95
    assert profile["ready_for_reserved"] and not profile["ready_for_enforcement"]
    reserved = tmp_path / "evals/reports/reserved.json"
    await run_experiment(
        cases,
        seen,
        manifest,
        config,
        reserved,
        phase="reserved",
        calibration=calibration,
        profile=profile,
        client=client,
    )
    report = json.loads(reserved.read_text())
    assert len(requests) == manifest["planned_evaluations"] == 21
    assert sum(set(p["questions"]) == {"respects_curation"} for p in requests) == 7
    assert report["observed_calls"] == 12
    assert report["summary"]["reserved"]["by_claim"]["proposed_false_blocks"] == 0
    assert report["summary"]["reserved"]["by_claim"]["proposed_false_accepts"] == 0
    assert report["complete"] and not report["production_changed"]
    assert config.model_dump() == original and not client.is_closed
    with pytest.raises(ValueError, match="already exists"):
        await run_experiment(
            cases,
            seen,
            manifest,
            config,
            reserved,
            phase="reserved",
            calibration=calibration,
            profile=profile,
            client=client,
        )
    profile["selected_support_floor"] = 0.8
    with pytest.raises(ValueError, match="frozen"):
        await run_experiment(
            cases,
            seen,
            manifest,
            config,
            tmp_path / "evals/reports/tampered.json",
            phase="reserved",
            calibration=calibration,
            profile=profile,
            client=client,
        )
    assert len(requests) == 21
    await client.aclose()


@pytest.mark.asyncio
async def test_no_eligible_calibration_does_not_unlock_reserve(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cases, seen, config, manifest = experiment()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    output = tmp_path / "evals/reports/calibration.json"
    await run_experiment(cases, seen, manifest, config, output, phase="calibration", client=client)
    calibration = json.loads(output.read_text())
    calibration["results"][0]["runs"][0]["claims"][0]["evaluation"]["value"]["confidence"] = 0.7
    profile = select_profile(calibration, cases, manifest)
    assert not profile["ready_for_reserved"] and profile["selected_support_floor"] is None
    reserved = tmp_path / "evals/reports/reserved.json"
    with pytest.raises(ValueError, match="Eligible"):
        await run_experiment(
            cases,
            seen,
            manifest,
            config,
            reserved,
            phase="reserved",
            calibration=calibration,
            profile=profile,
            client=client,
        )
    assert not reserved.exists()
    await client.aclose()


@pytest.mark.asyncio
async def test_upstream_failure_saved_without_semantic_error_or_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cases, seen, config, manifest = experiment()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(401, json={"detail": "private upstream text"})
        )
    )
    output = tmp_path / "evals/reports/failed.json"
    with pytest.raises(ValueError, match="Technical"):
        await run_experiment(
            cases, seen, manifest, config, output, phase="calibration", client=client
        )
    report = json.loads(output.read_text())
    stats = report["summary"]["development"]["by_claim"]
    assert stats["technical_errors"] == 3 and stats["positive_evaluated"] == 0
    assert stats["proposed_false_blocks"] == 0
    assert "private upstream text" not in output.read_text()
    with pytest.raises(ValueError, match="Complete"):
        select_profile(report, cases, manifest)
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["key", "manifest", "leak", "profile"])
async def test_invalid_configuration_or_protocol_stops_before_network(
    tmp_path, monkeypatch, invalid
):
    monkeypatch.chdir(tmp_path)
    cases, seen, config, manifest = experiment()
    if invalid == "key":
        config = config.model_copy(update={"typesafe_api_key": None})
    elif invalid == "manifest":
        manifest["confidence_floor"] = 0.5
    elif invalid == "leak":
        cases[-1].control.query = cases[0].control.query
    output = tmp_path / "evals/reports/invalid.json"
    with pytest.raises(ValueError):
        await run_experiment(
            cases,
            seen,
            manifest,
            config,
            output,
            phase="reserved" if invalid == "profile" else "calibration",
        )
    assert not output.exists()


def test_positive_only_calibration_cannot_define_a_rejection_profile():
    cases, seen, config, _ = experiment()
    cases = [
        c for c in cases if c.purpose == "reserved" or c.control.expected_relation == "supported"
    ]
    with pytest.raises(ValueError, match="Calibration requires"):
        freeze_manifest(cases, config, 1, seen)


def test_documentary_protocol_cannot_reuse_context_manifest():
    cases, seen, config, original = experiment()
    documentary = freeze_manifest(cases, config, 1, seen, protocol="documentary")
    assert documentary["context_criteria_hash"] != original["context_criteria_hash"]
    assert documentary["context_criteria_version"] == "pilot-v4-documentary-fidelity"
    assert documentary["cases_hash"] == original["cases_hash"]
    assert documentary["manifest_hash"] != original["manifest_hash"]


@pytest.mark.asyncio
async def test_documentary_manifest_matches_requests_and_cannot_unlock_with_v3_profile(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    cases, seen, config, v3_manifest = experiment()
    manifest = freeze_manifest(cases, config, 1, seen, protocol="documentary")
    requests = []

    def recording(request):
        requests.append(json.loads(request.content))
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(recording))
    output = tmp_path / "evals/reports/documentary.json"
    await run_experiment(
        cases,
        seen,
        manifest,
        config,
        output,
        phase="calibration",
        protocol="documentary",
        client=client,
    )
    report = json.loads(output.read_text())
    relation_requests = [p for p in requests if "relation" in p["questions"]]
    assert len(relation_requests) == 3
    assert all(p["questions"] == documentary_questions() for p in relation_requests)
    assert all(p["questions"] != relation_questions() for p in relation_requests)
    for case in report["results"]:
        run = case["runs"][0]
        assert run["whole"]["events"][0]["criteria_version"] == "pilot-v2-specific-rubrics"
        assert (
            run["claims"][0]["evaluation"]["events"][0]["criteria_version"]
            == "pilot-v4-documentary-fidelity"
        )
    profile = select_profile(report, cases, manifest)
    wrong_report = copy.deepcopy(report)
    wrong_report["manifest"] = v3_manifest
    with pytest.raises(ValueError, match="matching"):
        await run_experiment(
            cases,
            seen,
            manifest,
            config,
            tmp_path / "evals/reports/wrong-profile.json",
            phase="reserved",
            protocol="documentary",
            calibration=wrong_report,
            profile=profile,
            client=client,
        )
    with pytest.raises(ValueError, match="changed"):
        await run_experiment(
            cases,
            seen,
            manifest,
            config,
            tmp_path / "evals/reports/wrong-protocol.json",
            phase="calibration",
            client=client,
        )
    assert len(requests) == 9
    await client.aclose()


def test_unknown_protocol_cannot_freeze_rubrics():
    cases, seen, config, _ = experiment()
    with pytest.raises(ValueError, match="Unknown"):
        freeze_manifest(cases, config, 1, seen, protocol="unknown")
