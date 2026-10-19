"""Exploratory calibration and held-out controls, never an operational approval."""

import argparse
import asyncio
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from evals.jev_controls import ControlCase, load_controls
from src.config import Settings, get_settings
from src.services.curadoria import normalizar_pergunta
from src.services.typesafe_criteria import CRITERIA_VERSION, verification_questions
from src.services.typesafe_service import TypesafeService

SUPPORT_GRID = (0.90, 0.89, 0.88, 0.87, 0.85)
CONTRADICTION_GRID = (0.10, 0.12, 0.15, 0.20)
REQUIRED_KINDS = {"reference", "paraphrase", "contradiction", "unsupported"}
PROBABILITY_KEYS = {"supported", "contradiction", "respects_curation"}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def case_identity(case: ControlCase) -> dict[str, Any]:
    return case.model_dump(exclude={"annotation_status", "reviewed_by", "notes"})


def validate_splits(calibration: list[ControlCase], reserved: list[ControlCase]) -> None:
    ids: set[str] = set()
    seen: dict[tuple[str, str], str] = {}
    for cases, split in ((calibration, "calibration"), (reserved, "reserved")):
        if not cases or len(cases) > 120:
            raise ValueError("Empty or oversized controls")
        families: dict[str, list[ControlCase]] = {}
        for case in cases:
            if case.split != split or case.id in ids:
                raise ValueError("Duplicate ID or wrong split")
            if case.annotation_status == "draft" or not case.notes.strip():
                raise ValueError("Controls require explicit review and rationale")
            ids.add(case.id)
            families.setdefault(case.family, []).append(case)
            keys = [("family", case.family), ("query", normalizar_pergunta(case.query))]
            keys.extend(("source", document.id) for document in case.documents)
            keys.extend(
                ("source_content", digest(" ".join(document.content.casefold().split())))
                for document in case.documents
            )
            for key in keys:
                if seen.setdefault(key, split) != split:
                    raise ValueError("Calibration and reserved evidence overlap")
        for family in families.values():
            if not {case.kind for case in family} >= REQUIRED_KINDS:
                raise ValueError("Each family requires positive and negative controls")
            expected = {
                "reference": "supported",
                "paraphrase": "supported",
                "contradiction": "contradicted",
                "unsupported": "unsupported",
            }
            if any(
                expected.get(c.kind, c.expected_relation) != c.expected_relation for c in family
            ):
                raise ValueError("Control kind and relation mismatch")


def probabilities(value: Any) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != PROBABILITY_KEYS:
        raise ValueError("Missing verification probabilities")
    if any(
        isinstance(p, bool)
        or not isinstance(p, int | float)
        or not math.isfinite(p)
        or not 0 <= p <= 1
        for p in value.values()
    ):
        raise ValueError("Invalid verification probabilities")
    return {key: float(p) for key, p in value.items()}


def approved(points: dict[str, float], support: float, contradiction: float) -> bool:
    return (
        points["supported"] >= support
        and points["respects_curation"] >= support
        and points["contradiction"] <= contradiction
    )


def metrics(results: list[dict[str, Any]], support: float, contradiction: float) -> dict[str, int]:
    stats = dict.fromkeys(
        (
            "observations",
            "positive_evaluated",
            "negative_evaluated",
            "proposed_false_blocks",
            "proposed_false_accepts",
            "technical_errors",
            "unstable_controls",
            "human_reviewed_observations",
        ),
        0,
    )
    for case in results:
        decisions = set()
        for run in case["runs"]:
            if run["protocol"] != "v2":
                continue
            stats["observations"] += 1
            if run["transport_status"] != "ok":
                stats["technical_errors"] += 1
                continue
            decision = approved(
                probabilities(run["verification"]["probabilities"]), support, contradiction
            )
            decisions.add(decision)
            positive = case["expected_relation"] == "supported"
            stats["positive_evaluated" if positive else "negative_evaluated"] += 1
            stats["proposed_false_blocks"] += int(positive and not decision)
            stats["proposed_false_accepts"] += int(not positive and decision)
            stats["human_reviewed_observations"] += int(case["annotation_status"] == "reviewed")
        stats["unstable_controls"] += int(len(decisions) > 1)
    return stats


def calibration_results(
    cases: list[ControlCase], report: dict[str, Any], model: str
) -> list[dict[str, Any]]:
    if (
        report.get("model") != model
        or report.get("criteria_version") != CRITERIA_VERSION
        or report.get("protocol_hashes", {}).get("v2") != digest(verification_questions())
    ):
        raise ValueError("Incompatible calibration model or criteria")
    repeats = report.get("repetitions")
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("Invalid calibration repetitions")
    raw = report.get("results", [])
    if not isinstance(raw, list) or len(raw) != len(cases):
        raise ValueError("Incomplete calibration results")
    by_id = {case.id: case for case in cases}
    observed: set[str] = set()
    output: list[dict[str, Any]] = []
    for result in raw:
        recorded = ControlCase.model_validate({k: v for k, v in result.items() if k != "runs"})
        expected = by_id.get(recorded.id)
        if (
            expected is None
            or recorded.id in observed
            or case_identity(recorded) != case_identity(expected)
        ):
            raise ValueError("Calibration text or evidence mismatch")
        observed.add(recorded.id)
        runs = [run for run in result["runs"] if run["protocol"] == "v2"]
        if len(runs) != repeats or {run["repeat"] for run in runs} != set(range(1, repeats + 1)):
            raise ValueError("Incomplete or duplicate calibration observations")
        for run in runs:
            events = run.get("events", [])
            if (
                run.get("transport_status") != "ok"
                or not events
                or any(
                    event.get("status") != "ok"
                    or event.get("truncated") is not False
                    or event.get("model") != model
                    or event.get("criteria_version") != CRITERIA_VERSION
                    for event in events
                )
            ):
                raise ValueError("Failed or truncated calibration observations")
            probabilities(run["verification"]["probabilities"])
        output.append({**expected.model_dump(), "runs": runs})
    return output


def freeze_profile(
    calibration: list[ControlCase], reserved: list[ControlCase], report: dict[str, Any], model: str
) -> dict[str, Any]:
    validate_splits(calibration, reserved)
    results = calibration_results(calibration, report, model)
    candidates: list[dict[str, Any]] = []
    for support in SUPPORT_GRID:
        for contradiction in CONTRADICTION_GRID:
            scores = metrics(results, support, contradiction)
            candidates.append(
                {"support": support, "contradiction": contradiction, "metrics": scores}
            )
    eligible = [
        candidate
        for candidate in candidates
        if not candidate["metrics"]["proposed_false_accepts"]
        and not candidate["metrics"]["proposed_false_blocks"]
    ]
    if not eligible:
        raise ValueError("No experimental policy meets the calibration objective")
    # The ordered grid prefers the largest support floor and smallest opposition ceiling.
    selected = eligible[0]
    baseline = {
        "support": report["support_threshold"],
        "contradiction": report["contradiction_threshold"],
    }
    if any(
        type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
        for p in baseline.values()
    ):
        raise ValueError("Invalid baseline thresholds")
    profile = {
        "schema": "jev-experimental-profile-v1",
        "model": model,
        "criteria_version": CRITERIA_VERSION,
        "criteria_hash": digest(verification_questions()),
        "calibration_cases_hash": digest([case.model_dump() for case in calibration]),
        "reserved_cases_hash": digest([case.model_dump() for case in reserved]),
        "calibration_report_hash": digest(report),
        "objective": "zero proposed false accepts and false blocks on calibration repetitions",
        "selection_rule": "largest support floor, then smallest contradiction ceiling",
        "candidates": candidates,
        "selected": selected,
        "baseline": baseline,
        "baseline_calibration_metrics": metrics(results, **baseline),
        "human_review_required": True,
        "ready_for_enforcement": False,
        "production_changed": False,
    }
    profile["profile_hash"] = digest(profile)
    return profile


def validate_profile(
    profile: dict[str, Any],
    calibration: list[ControlCase],
    reserved: list[ControlCase],
    report: dict[str, Any],
    model: str,
) -> None:
    if profile != freeze_profile(calibration, reserved, report, model):
        raise ValueError("Frozen experimental profile or inputs changed")


def output_path(path: Path) -> None:
    if not path.resolve().is_relative_to(Path("evals/reports").resolve()) or path.suffix != ".json":
        raise ValueError("Experimental artifacts must be JSON inside evals/reports")
    if path.exists() or path.with_suffix(".md").exists():
        raise ValueError("Experimental output already exists")


def read_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Experimental input exceeds size limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Experimental input must be an object")
    return value


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# Jev — reserva experimental",
        "",
        "Revisão assistida por IA; aceite humano pendente. Fidelidade à referência, não verdade atual do produto.",
        "Nenhuma alteração em produção. Repetições não são amostras independentes.",
        "",
        "| Política | Positivas | Bloqueios propostos | Negativas | Aprovações indevidas propostas | Falhas técnicas |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for policy, scores in report["summary"].items():
        lines.append(
            f"| {policy} | {scores['positive_evaluated']} | {scores['proposed_false_blocks']} | {scores['negative_evaluated']} | {scores['proposed_false_accepts']} | {scores['technical_errors']} |"
        )
    for case in report["results"]:
        lines.extend(
            [
                "",
                f"## {case['id']}",
                "",
                case["query"],
                "",
                case["response"],
                "",
                f"Relação proposta: {case['expected_relation']}. Revisão: {case['annotation_status']}. {case['notes']}",
            ]
        )
        for run in case["runs"]:
            lines.append(
                f"- Repetição {run['repeat']}: {json.dumps(run.get('verification', {'error_type': run.get('error_type')}), ensure_ascii=False)}; aprovações por política: {json.dumps(run.get('policy_approvals', {}), ensure_ascii=False)}"
            )
        lines.append(
            "\nRevisão humana: relação [ ]; evidência [ ]; atualidade [ ]; comentário: ____."
        )
    return "\n".join(lines) + "\n"


async def save_report(report: dict[str, Any], output: Path) -> None:
    selected = report["profile"]["selected"]
    for case in report["results"]:
        for run in case["runs"]:
            if run["transport_status"] == "ok":
                points = probabilities(run["verification"]["probabilities"])
                run["policy_approvals"] = {
                    "baseline": approved(points, **report["profile"]["baseline"]),
                    "experimental": approved(
                        points, selected["support"], selected["contradiction"]
                    ),
                }
    report["summary"] = {
        key: metrics(report["results"], **report["profile"][key]) for key in ("baseline",)
    }
    report["summary"]["experimental"] = metrics(
        report["results"], selected["support"], selected["contradiction"]
    )
    events = [
        event for case in report["results"] for run in case["runs"] for event in run["events"]
    ]
    report["observed_input_tokens"] = sum(event["input_tokens"] for event in events)
    report["observed_estimated_cost_usd"] = sum(event["estimated_cost_usd"] for event in events)
    await asyncio.to_thread(
        output.write_text, json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    await asyncio.to_thread(
        output.with_suffix(".md").write_text, render_report(report), encoding="utf-8"
    )


async def run_reserved(
    calibration: list[ControlCase],
    reserved: list[ControlCase],
    calibration_report: dict[str, Any],
    profile: dict[str, Any],
    config: Settings,
    output: Path,
    repetitions: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    if not config.typesafe_api_key:
        raise ValueError("Experimental evaluation requires TYPESAFE_API_KEY")
    if type(repetitions) is not int or not 1 <= repetitions <= 5:
        raise ValueError("Experimental repetitions must be between 1 and 5")
    validate_profile(profile, calibration, reserved, calibration_report, config.typesafe_model)
    await asyncio.to_thread(output_path, output)
    local_config = config.model_copy(
        update={
            "typesafe_verify_mode": "off",
            "rerank_provider": "openai",
            "typesafe_rerank_shadow": False,
            "typesafe_criteria_calibrated": False,
            "typesafe_criteria_version": CRITERIA_VERSION,
            "typesafe_support_threshold": profile["baseline"]["support"],
            "typesafe_contradiction_threshold": profile["baseline"]["contradiction"],
        }
    )
    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "profile": profile,
        "repetitions": repetitions,
        "results": [],
        "human_review_required": True,
        "ready_for_enforcement": False,
        "production_changed": False,
        "quality_validated": False,
        "complete": False,
    }
    await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)

    # Exclusive creation protects a prior run. Subsequent writes belong to this invocation.
    def create() -> None:
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False)

    await asyncio.to_thread(create)
    service = TypesafeService(local_config, client=client)
    try:
        for case in reserved:
            result: dict[str, Any] = {**case.model_dump(), "runs": []}
            report["results"].append(result)
            for repeat in range(repetitions):
                service.events.clear()
                run: dict[str, Any] = {"protocol": "v2", "repeat": repeat + 1}
                try:
                    verification = await service.verify(case.query, case.response, case.documents)
                    if any(event.truncated for event in service.events):
                        raise ValueError("Truncated reserved evidence")
                    run.update(transport_status="ok", verification=verification.model_dump())
                except Exception as exc:
                    run.update(transport_status="error", error_type=type(exc).__name__)
                run["events"] = [event.model_dump() for event in service.events]
                result["runs"].append(run)
                await save_report(report, output)
            print(
                f"{case.id}: {len(report['results'])}/{len(reserved)} experimental controls",
                flush=True,
            )
        report["complete"] = not report["summary"]["experimental"]["technical_errors"]
        await save_report(report, output)
        print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
        if not report["complete"]:
            raise ValueError("Technical failures recorded in experimental report")
    finally:
        await service.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--reserved", type=Path, required=True)
    parser.add_argument("--calibration-report", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    try:
        calibration = load_controls(args.calibration)
        reserved = load_controls(args.reserved)
        report = read_json(args.calibration_report)
        config = get_settings()
        if args.freeze:
            output_path(args.profile)
            profile = freeze_profile(calibration, reserved, report, config.typesafe_model)
            args.profile.parent.mkdir(parents=True, exist_ok=True)
            with args.profile.open("x", encoding="utf-8") as stream:
                json.dump(profile, stream, ensure_ascii=False, indent=2)
            print(json.dumps(profile["selected"], ensure_ascii=False))
        else:
            if args.output is None:
                raise ValueError("Reserved evaluation requires a new output path")
            asyncio.run(
                run_reserved(
                    calibration,
                    reserved,
                    report,
                    read_json(args.profile),
                    config,
                    args.output,
                    args.repetitions,
                )
            )
    except Exception as exc:
        parser.exit(
            1,
            f"Unable to run experimental evaluation ({type(exc).__name__}); check local inputs and configuration.\n",
        )


if __name__ == "__main__":
    main()
