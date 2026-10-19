"""Manual contextual Choice experiment, isolated from application decisions."""

import argparse
import asyncio
import json
import math
from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from evals.jev_calibration import digest, output_path, read_json
from evals.jev_claims import ClaimCase, experimental_settings, load_claims, summarize
from evals.jev_claims import freeze_manifest as freeze_spans
from evals.jev_controls import ControlCase, load_controls
from src.config import Settings, get_settings
from src.models.typesafe import RelationAnswer
from src.services.claim_verification_service import (
    CONTEXT_CRITERIA_VERSION,
    DOCUMENTARY_CRITERIA_VERSION,
    ClaimVerificationService,
    DocumentaryVerificationService,
    curation_questions,
    documentary_questions,
    relation_questions,
)

SUPPORT_GRID = (0.95, 0.90, 0.88, 0.85, 0.80)
CONFIDENCE_FLOOR = 0.80
CURATION_FLOOR = 0.88
OPPOSITION_CEILING = 0.12


def protocol_contract(
    protocol: str,
) -> tuple[str, dict[str, dict[str, object]], type[ClaimVerificationService]]:
    if protocol == "context":
        return CONTEXT_CRITERIA_VERSION, relation_questions(), ClaimVerificationService
    if protocol == "documentary":
        return DOCUMENTARY_CRITERIA_VERSION, documentary_questions(), DocumentaryVerificationService
    raise ValueError("Unknown verification protocol")


def freeze_manifest(
    cases: list[ClaimCase],
    config: Settings,
    repetitions: int,
    seen: list[ControlCase],
    *,
    protocol: str = "context",
) -> dict[str, Any]:
    version, questions, _ = protocol_contract(protocol)
    manifest = freeze_spans(cases, config, repetitions, seen)
    development_relations = {
        c.control.expected_relation for c in cases if c.purpose == "development"
    }
    if development_relations != {"supported", "contradicted", "unsupported"}:
        raise ValueError("Calibration requires supported, contradicted and unsupported controls")
    planned = manifest["planned_evaluations"] + repetitions * len(cases)
    if planned > 600:
        raise ValueError("Context experiment exceeds 600 planned evaluations")
    manifest.update(
        schema="jev-context-choice-v1",
        context_criteria_version=version,
        context_criteria_hash=digest([questions, curation_questions()]),
        support_grid=list(SUPPORT_GRID),
        confidence_floor=CONFIDENCE_FLOOR,
        curation_floor=CURATION_FLOOR,
        opposition_ceiling=OPPOSITION_CEILING,
        planned_evaluations=planned,
        aggregate_policy="global curation plus every contextual fact; technical failures never approve",
    )
    if protocol != "context":
        manifest["protocol"] = protocol
    del manifest["manifest_hash"]
    manifest["manifest_hash"] = digest(manifest)
    return manifest


def aggregate(run: dict[str, Any], support: float, expected: int) -> dict[str, Any]:
    claims = run["claims"]
    # Fail closed when any constituent is missing or unavailable.
    if (
        expected < 1
        or len(claims) != expected
        or run["curation"]["transport_status"] != "ok"
        or any(c["evaluation"]["transport_status"] != "ok" for c in claims)
    ):
        return {"transport_status": "error", "approved": False}
    blocked = []
    for claim in claims:
        answer = RelationAnswer.model_validate(claim["evaluation"]["value"])
        if not (
            answer.choice == "supports"
            and answer.probabilities["supports"] >= support
            and answer.probabilities["contradicts"] <= OPPOSITION_CEILING
            and answer.confidence >= CONFIDENCE_FLOOR
        ):
            blocked.append(claim["id"])
    return {
        "transport_status": "ok",
        "approved": not blocked and run["curation"]["value"] >= CURATION_FLOOR,
        "blocked_claim_ids": blocked,
        "curation_blocked": run["curation"]["value"] < CURATION_FLOOR,
    }


def select_profile(
    report: dict[str, Any], cases: list[ClaimCase], manifest: dict[str, Any]
) -> dict[str, Any]:
    expected = [c for c in cases if c.purpose == "development"]
    if (
        report.get("phase") != "calibration"
        or report.get("manifest") != manifest
        or report.get("complete") is not True
        or not expected
        or len(report["results"]) != len(expected)
    ):
        raise ValueError("Complete matching calibration required")
    for entry, case in zip(report["results"], expected, strict=True):
        if {key: entry[key] for key in case.model_dump()} != case.model_dump():
            raise ValueError("Calibration case or annotations changed")
        if len(entry["runs"]) != manifest["repetitions"]:
            raise ValueError("Calibration repetitions missing")
        for index, run in enumerate(entry["runs"], 1):
            facts = [s for s in case.segments if s.kind == "fact"]
            if run["repeat"] != index or len(run["claims"]) != len(facts):
                raise ValueError("Calibration claims missing")
            for claim, span in zip(run["claims"], facts, strict=True):
                if (
                    claim["id"] != span.id
                    or claim["text"] != case.control.response[span.start : span.end]
                    or claim["expected_relation"] != span.expected_relation
                ):
                    raise ValueError("Calibration claim identity changed")
                RelationAnswer.model_validate(claim["evaluation"]["value"])
            p = run["curation"].get("value")
            if type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1:
                raise ValueError("Invalid global curation observation")
            for evaluation in [
                run["whole"],
                run["curation"],
                *(c["evaluation"] for c in run["claims"]),
            ]:
                if (
                    evaluation["transport_status"] != "ok"
                    or not evaluation["events"]
                    or any(e["truncated"] or e["status"] != "ok" for e in evaluation["events"])
                ):
                    raise ValueError("Incomplete calibration transport")
    grid = []
    for support in SUPPORT_GRID:
        blocks = accepts = 0
        for case in report["results"]:
            for run in case["runs"]:
                decision = aggregate(run, support, len(run["claims"]))["approved"]
                positive = case["control"]["expected_relation"] == "supported"
                blocks += int(positive and not decision)
                accepts += int(not positive and decision)
        grid.append({"support_floor": support, "false_blocks": blocks, "false_accepts": accepts})
    eligible = [p for p in grid if not p["false_blocks"] and not p["false_accepts"]]
    profile: dict[str, Any] = {
        "manifest_hash": manifest["manifest_hash"],
        "calibration_report_hash": digest(report),
        "grid": grid,
        "selected_support_floor": eligible[0]["support_floor"] if eligible else None,
        "ready_for_reserved": bool(eligible),
        "ready_for_enforcement": False,
    }
    profile["profile_hash"] = digest(profile)
    return profile


async def observe(service: ClaimVerificationService, operation: Awaitable[Any]) -> dict[str, Any]:
    service.events.clear()
    try:
        value = await operation
        if not service.events or any(e.truncated for e in service.events):
            raise ValueError("Missing or truncated observation")
        result = {"transport_status": "ok", "value": value}
    except Exception as exc:
        result = {"transport_status": "error", "error_type": type(exc).__name__}
    result["events"] = [e.model_dump() for e in service.events]
    return result


async def save(report: dict[str, Any], output: Path) -> None:
    report["summary"] = summarize(report)
    events = [
        event
        for case in report["results"]
        for run in case["runs"]
        for evaluation in [run["whole"], run["curation"], *(c["evaluation"] for c in run["claims"])]
        for event in evaluation["events"]
    ]
    report["observed_calls"] = sum(e["calls"] for e in events)
    report["observed_input_tokens"] = sum(e["input_tokens"] for e in events)
    report["observed_estimated_cost_usd"] = sum(e["estimated_cost_usd"] for e in events)
    lines = [
        "# Jev — contexto e curadoria global",
        "",
        "Experimento local. Rótulos e cobertura dos trechos anotados por IA; revisão humana pendente. Jev continua desligado na aplicação.",
        "",
        "| Conjunto | Método | Positivas | Bloqueios | Negativas | Aprovações negativas | Falhas técnicas |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for purpose, methods in report["summary"].items():
        for method, stats in methods.items():
            if stats["observations"]:
                lines.append(
                    f"| {purpose} | {method} | {stats['positive_evaluated']} | {stats['proposed_false_blocks']} | {stats['negative_evaluated']} | {stats['proposed_false_accepts']} | {stats['technical_errors']} |"
                )
    lines.extend(
        [
            "",
            "Na calibração, by_claim usa 0,95 provisório. A grade completa decide se existe perfil elegível; não é aprovação operacional.",
            "",
            f"Chamadas: {report['observed_calls']}; custo estimado: US$ {report['observed_estimated_cost_usd']:.6f}.",
        ]
    )
    await asyncio.to_thread(
        output.write_text, json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    await asyncio.to_thread(
        output.with_suffix(".md").write_text, "\n".join(lines) + "\n", encoding="utf-8"
    )


async def run_experiment(
    cases: list[ClaimCase],
    seen: list[ControlCase],
    manifest: dict[str, Any],
    config: Settings,
    output: Path,
    *,
    phase: str,
    protocol: str = "context",
    calibration: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> None:
    if not config.typesafe_api_key:
        raise ValueError("Context experiment requires TYPESAFE_API_KEY")
    repetitions = manifest.get("repetitions")
    if type(repetitions) is not int or manifest != freeze_manifest(
        cases, config, repetitions, seen, protocol=protocol
    ):
        raise ValueError("Frozen context protocol changed")
    if phase == "reserved":
        if (
            calibration is None
            or profile != select_profile(calibration, cases, manifest)
            or not profile
            or not profile["ready_for_reserved"]
        ):
            raise ValueError("Eligible frozen calibration profile required")
        support = float(profile["selected_support_floor"])
    elif phase == "calibration":
        if calibration is not None or profile is not None:
            raise ValueError("Calibration cannot consume a later profile")
        support = SUPPORT_GRID[0]
    else:
        raise ValueError("Invalid experimental phase")
    output_path(output)
    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "manifest": manifest,
        "phase": phase,
        "profile": profile,
        "support_floor": support,
        "results": [],
        "complete": False,
        "production_changed": False,
        "ready_for_enforcement": False,
        "human_coverage_review_required": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream)
    version, _, service_class = protocol_contract(protocol)
    service = service_class(config, client=client)
    selected = [
        c for c in cases if c.purpose == ("development" if phase == "calibration" else "reserved")
    ]
    try:
        for case in selected:
            result: dict[str, Any] = {**case.model_dump(), "runs": []}
            report["results"].append(result)
            facts = [s for s in case.segments if s.kind == "fact"]
            for repeat in range(repetitions):
                service.config = config
                whole = await observe(
                    service,
                    service.verify(
                        case.control.query, case.control.response, case.control.documents
                    ),
                )
                if whole["transport_status"] == "ok":
                    whole["verification"] = whole.pop("value").model_dump()
                service.config = config.model_copy(update={"typesafe_criteria_version": version})
                curation = await observe(
                    service,
                    service.verify_curation(
                        case.control.query, case.control.response, case.control.documents
                    ),
                )
                claims = []
                for span in facts:
                    claims.append(
                        {
                            "id": span.id,
                            "text": case.control.response[span.start : span.end],
                            "expected_relation": span.expected_relation,
                            "evaluation": await observe(
                                service,
                                service.verify_claim(
                                    case.control.query,
                                    case.control.response,
                                    span.start,
                                    span.end,
                                    case.control.documents,
                                ),
                            ),
                        }
                    )
                run = {"repeat": repeat + 1, "whole": whole, "curation": curation, "claims": claims}
                run["by_claim"] = aggregate(run, support, len(facts))
                result["runs"].append(run)
                await save(report, output)
            print(
                f"{case.control.id}: {len(report['results'])}/{len(selected)} context controls",
                flush=True,
            )
        report["complete"] = not any(
            s["technical_errors"]
            for methods in report["summary"].values()
            for s in methods.values()
        )
        await save(report, output)
        print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
        if not report["complete"]:
            raise ValueError("Technical failures recorded")
    finally:
        await service.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("input", "seen", "manifest"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--phase", choices=("calibration", "reserved"))
    parser.add_argument("--protocol", choices=("context", "documentary"), default="context")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--select-profile", action="store_true")
    args = parser.parse_args()
    try:
        cases, seen = load_claims(args.input), load_controls(args.seen)
        config = experimental_settings(get_settings())
        if args.freeze:
            payload = freeze_manifest(cases, config, args.repetitions, seen, protocol=args.protocol)
            target = args.manifest
        elif args.select_profile:
            manifest = read_json(args.manifest)
            if (
                manifest
                != freeze_manifest(
                    cases, config, manifest["repetitions"], seen, protocol=args.protocol
                )
                or args.calibration is None
                or args.profile is None
            ):
                raise ValueError("Frozen matching protocol and calibration required")
            payload = select_profile(read_json(args.calibration), cases, manifest)
            target = args.profile
        else:
            if args.output is None or args.phase is None:
                raise ValueError("Phase and new output required")
            asyncio.run(
                run_experiment(
                    cases,
                    seen,
                    read_json(args.manifest),
                    config,
                    args.output,
                    phase=args.phase,
                    protocol=args.protocol,
                    calibration=read_json(args.calibration) if args.calibration else None,
                    profile=read_json(args.profile) if args.profile else None,
                )
            )
            return
        output_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        print(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        parser.exit(
            1,
            f"Unable to run context experiment ({type(exc).__name__}); check local inputs and configuration.\n",
        )


if __name__ == "__main__":
    main()
