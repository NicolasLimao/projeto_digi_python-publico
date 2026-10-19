"""Manual factual-span experiment, preserving production and original controls."""

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from evals.jev_calibration import digest, output_path, read_json
from evals.jev_controls import ControlCase
from src.config import Settings, get_settings
from src.services.curadoria import normalizar_pergunta
from src.services.typesafe_criteria import CRITERIA_VERSION, verification_questions
from src.services.typesafe_service import TypesafeService

ShortText = Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class ClaimSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    start: int = Field(ge=0, le=40000)
    end: int = Field(gt=0, le=40000)
    kind: Literal["fact", "structural"] = "fact"
    expected_relation: Literal["supported", "contradicted", "unsupported"] | None = None
    notes: ShortText


class ClaimCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control: ControlCase
    purpose: Literal["development", "reserved"]
    coverage_review: Literal["ai_reviewed", "reviewed"] = "ai_reviewed"
    coverage_reviewer: ShortText
    segments: list[ClaimSpan] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def validate_spans(self) -> "ClaimCase":
        previous_end = 0
        ids: set[str] = set()
        for span in self.segments:
            if self.control.response[previous_end : span.start].strip():
                raise ValueError("Incomplete factual coverage")
            text = self.control.response[span.start : span.end]
            if span.id in ids or span.start < previous_end or span.end <= span.start:
                raise ValueError("Duplicate or overlapping claim spans")
            if span.end > len(self.control.response) or not text.strip():
                raise ValueError("Invalid claim interval")
            if span.kind == "fact" and re.fullmatch(r"[\W\d_]+", text):
                raise ValueError("Claim span has no factual content")
            if (span.kind == "fact") != (span.expected_relation is not None):
                raise ValueError(
                    "Factual spans require a relation; structural spans cannot have one"
                )
            previous_end = span.end
            ids.add(span.id)
        if self.control.response[previous_end:].strip():
            raise ValueError("Incomplete factual coverage")
        if not any(span.kind == "fact" for span in self.segments):
            raise ValueError("At least one factual span is required")
        return self


def load_claims(path: Path) -> list[ClaimCase]:
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Claim dataset exceeds size limit")
    cases: list[ClaimCase] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            if len(line) > 500000 or len(cases) >= 40:
                raise ValueError("Claim dataset exceeds case limits")
            cases.append(ClaimCase.model_validate_json(line))
    if not cases:
        raise ValueError("Claim dataset is empty")
    return cases


def freeze_manifest(
    cases: list[ClaimCase],
    config: Settings,
    repetitions: int,
    seen: list[ControlCase],
) -> dict[str, Any]:
    if type(repetitions) is not int or not 1 <= repetitions <= 3:
        raise ValueError("Claim repetitions must be between 1 and 3")
    if not cases or len(cases) > 40 or not seen or len(seen) > 120:
        raise ValueError("Invalid experiment inputs")
    if (
        config.typesafe_model != "jev-1.13.0"
        or config.typesafe_criteria_version != CRITERIA_VERSION
    ):
        raise ValueError("Incompatible experimental model or criteria")
    if (config.typesafe_support_threshold, config.typesafe_contradiction_threshold) != (0.88, 0.12):
        raise ValueError("Claim experiment requires frozen thresholds 0.88/0.12")
    if any(c.control.annotation_status == "draft" for c in cases):
        raise ValueError("Claim controls require explicit annotation")
    ids: set[str] = set()
    source_purpose: dict[tuple[str, str], str] = {}
    seen_keys = {key for case in seen for key in case_keys(case)}
    purposes: set[str] = set()
    for case in cases:
        if case.control.id in ids:
            raise ValueError("Duplicate claim case ID")
        ids.add(case.control.id)
        purposes.add(case.purpose)
        for key in case_keys(case.control):
            if source_purpose.setdefault(key, case.purpose) != case.purpose:
                raise ValueError("Development and reserved references overlap")
            if case.purpose == "reserved" and key in seen_keys:
                raise ValueError("Reserved reference was seen in earlier controls")
    if purposes != {"development", "reserved"}:
        raise ValueError("Both development and independent reserved controls are required")
    families: dict[str, set[str]] = {}
    for case in cases:
        if case.purpose == "reserved":
            families.setdefault(case.control.family, set()).add(case.control.kind)
    if any(
        not kinds >= {"reference", "paraphrase", "contradiction", "unsupported"}
        for kinds in families.values()
    ):
        raise ValueError("Reserved families require positive and negative variants")
    planned = repetitions * sum(1 + sum(s.kind == "fact" for s in c.segments) for c in cases)
    if planned > 600:
        raise ValueError("Claim experiment exceeds 600 planned evaluations")
    manifest = {
        "schema": "jev-factual-spans-v1",
        "cases_hash": digest([c.model_dump() for c in cases]),
        "seen_controls_hash": digest([c.model_dump() for c in seen]),
        "criteria_hash": digest(verification_questions()),
        "criteria_version": CRITERIA_VERSION,
        "model": config.typesafe_model,
        "repetitions": repetitions,
        "support_threshold": 0.88,
        "contradiction_threshold": 0.12,
        "planned_evaluations": planned,
        "aggregate_policy": "every annotated factual span must be approved; complete coverage required",
        "ready_for_enforcement": False,
        "production_changed": False,
        "human_coverage_review_required": True,
    }
    manifest["manifest_hash"] = digest(manifest)
    return manifest


def case_keys(case: ControlCase) -> list[tuple[str, str]]:
    keys = [("family", case.family), ("query", normalizar_pergunta(case.query))]
    for document in case.documents:
        keys.extend(
            [
                ("source", document.id),
                ("content", digest(" ".join(document.content.casefold().split()))),
            ]
        )
    return keys


async def evaluate_text(service: TypesafeService, case: ControlCase, text: str) -> dict[str, Any]:
    service.events.clear()
    try:
        result = await service.verify(case.query, text, case.documents)
        if not service.events or any(event.truncated for event in service.events):
            raise ValueError("Missing or truncated verification observation")
        outcome: dict[str, Any] = {"transport_status": "ok", "verification": result.model_dump()}
    except Exception as exc:
        outcome = {"transport_status": "error", "error_type": type(exc).__name__}
    outcome["events"] = [event.model_dump() for event in service.events]
    return outcome


def aggregate(claim_results: list[dict[str, Any]], expected_claims: int) -> dict[str, Any]:
    if (
        expected_claims < 1
        or len(claim_results) != expected_claims
        or any(result["evaluation"]["transport_status"] != "ok" for result in claim_results)
    ):
        return {"transport_status": "error", "approved": False}
    return {
        "transport_status": "ok",
        "approved": all(
            result["evaluation"]["verification"]["approved"] for result in claim_results
        ),
        "blocked_claim_ids": [
            result["id"]
            for result in claim_results
            if not result["evaluation"]["verification"]["approved"]
        ],
    }


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for purpose in ("development", "reserved"):
        summary[purpose] = {}
        for method in ("whole", "by_claim"):
            stats = dict.fromkeys(
                (
                    "observations",
                    "positive_evaluated",
                    "negative_evaluated",
                    "proposed_false_blocks",
                    "proposed_false_accepts",
                    "technical_errors",
                    "unstable_cases",
                ),
                0,
            )
            for case in report["results"]:
                if case["purpose"] != purpose:
                    continue
                decisions = set()
                for run in case["runs"]:
                    result = run[method]
                    stats["observations"] += 1
                    if result["transport_status"] != "ok":
                        stats["technical_errors"] += 1
                        continue
                    decision = (
                        result["verification"]["approved"]
                        if method == "whole"
                        else result["approved"]
                    )
                    decisions.add(decision)
                    positive = case["control"]["expected_relation"] == "supported"
                    stats["positive_evaluated" if positive else "negative_evaluated"] += 1
                    stats["proposed_false_blocks"] += int(positive and not decision)
                    stats["proposed_false_accepts"] += int(not positive and decision)
                stats["unstable_cases"] += int(len(decisions) > 1)
            summary[purpose][method] = stats
    return summary


def render(report: dict[str, Any]) -> str:
    lines = [
        "# Jev — verificação por afirmação",
        "",
        "Experimento com trechos anotados por IA; cobertura e rótulos humanos pendentes. Sem alteração operacional.",
        "",
        "| Conjunto | Método | Positivas | Bloqueios propostos | Negativas | Aprovações negativas propostas | Erros técnicos |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for purpose, methods in report["summary"].items():
        for method, stats in methods.items():
            lines.append(
                f"| {purpose} | {method} | {stats['positive_evaluated']} | {stats['proposed_false_blocks']} | {stats['negative_evaluated']} | {stats['proposed_false_accepts']} | {stats['technical_errors']} |"
            )
    for case in report["results"]:
        control = case["control"]
        lines.extend(
            [
                "",
                f"## {control['id']}",
                "",
                f"Conjunto: {case['purpose']}; relação proposta: {control['expected_relation']}.",
                "",
                control["query"],
                "",
                control["response"],
            ]
        )
        for run in case["runs"]:
            whole = run["whole"]
            lines.append(
                f"\nRepetição {run['repeat']}, resposta integral: {json.dumps(whole.get('verification', {'error_type': whole.get('error_type')}), ensure_ascii=False)}; agregado por afirmação: {json.dumps(run['by_claim'], ensure_ascii=False)}"
            )
            for claim in run["claims"]:
                outcome = claim["evaluation"]
                lines.append(
                    f"\n- {claim['id']}: {claim['text']}\n  {json.dumps(outcome.get('verification', {'error_type': outcome.get('error_type')}), ensure_ascii=False)}"
                )
        lines.append(
            "\nRevisão humana: fatos cobertos [ ]; relação correta [ ]; resposta útil [ ]; atualidade [ ]; comentário: ____.\n"
        )
    return "\n".join(lines) + "\n"


async def save(report: dict[str, Any], output: Path) -> None:
    report["summary"] = summarize(report)
    events = [
        event
        for case in report["results"]
        for run in case["runs"]
        for result in [run["whole"], *(c["evaluation"] for c in run["claims"])]
        for event in result["events"]
    ]
    report["observed_input_tokens"] = sum(event["input_tokens"] for event in events)
    report["observed_estimated_cost_usd"] = sum(event["estimated_cost_usd"] for event in events)
    await asyncio.to_thread(
        output.write_text, json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    await asyncio.to_thread(output.with_suffix(".md").write_text, render(report), encoding="utf-8")


async def run_experiment(
    cases: list[ClaimCase],
    seen: list[ControlCase],
    manifest: dict[str, Any],
    config: Settings,
    output: Path,
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    if not config.typesafe_api_key:
        raise ValueError("Claim experiment requires TYPESAFE_API_KEY")
    repetitions = manifest.get("repetitions")
    if type(repetitions) is not int:
        raise ValueError("Invalid frozen claim repetitions")
    expected = freeze_manifest(cases, config, repetitions, seen)
    if manifest != expected:
        raise ValueError("Frozen claim experiment or inputs changed")
    await asyncio.to_thread(output_path, output)
    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "manifest": manifest,
        "results": [],
        "complete": False,
        "production_changed": False,
        "ready_for_enforcement": False,
        "human_coverage_review_required": True,
    }
    await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)

    def create() -> None:
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False)

    await asyncio.to_thread(create)
    service = TypesafeService(config, client=client)
    try:
        for case in cases:
            result: dict[str, Any] = {**case.model_dump(), "runs": []}
            report["results"].append(result)
            factual = [span for span in case.segments if span.kind == "fact"]
            for repeat in range(manifest["repetitions"]):
                whole = await evaluate_text(service, case.control, case.control.response)
                claims = []
                for span in factual:
                    text = case.control.response[span.start : span.end]
                    claims.append(
                        {
                            "id": span.id,
                            "text": text,
                            "expected_relation": span.expected_relation,
                            "evaluation": await evaluate_text(service, case.control, text),
                        }
                    )
                result["runs"].append(
                    {
                        "repeat": repeat + 1,
                        "whole": whole,
                        "claims": claims,
                        "by_claim": aggregate(claims, len(factual)),
                    }
                )
                await save(report, output)
            print(
                f"{case.control.id}: {len(report['results'])}/{len(cases)} claim controls",
                flush=True,
            )
        report["complete"] = not any(
            stats["technical_errors"]
            for methods in report["summary"].values()
            for stats in methods.values()
        )
        await save(report, output)
        print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
        if not report["complete"]:
            raise ValueError("Technical failures recorded in claim experiment")
    finally:
        await service.aclose()


def experimental_settings(config: Settings) -> Settings:
    return config.model_copy(
        update={
            "rerank_provider": "openai",
            "typesafe_rerank_shadow": False,
            "typesafe_verify_mode": "off",
            "typesafe_criteria_calibrated": False,
            "typesafe_support_threshold": 0.88,
            "typesafe_contradiction_threshold": 0.12,
            "typesafe_criteria_version": CRITERIA_VERSION,
        }
    )


def main() -> None:
    from evals.jev_controls import load_controls

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--seen", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        cases, seen = load_claims(args.input), load_controls(args.seen)
        config = experimental_settings(get_settings())
        if args.freeze:
            manifest = freeze_manifest(cases, config, args.repetitions, seen)
            output_path(args.manifest)
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            with args.manifest.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False, indent=2)
            print(json.dumps(manifest, ensure_ascii=False))
        else:
            if args.output is None:
                raise ValueError("Claim experiment requires a new output path")
            asyncio.run(run_experiment(cases, seen, read_json(args.manifest), config, args.output))
    except Exception as exc:
        parser.exit(
            1,
            f"Unable to run claim experiment ({type(exc).__name__}); check local inputs and configuration.\n",
        )


if __name__ == "__main__":
    main()
