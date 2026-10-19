"""Manual A/B/C/D comparison using frozen real candidates; never runs in CI."""

import argparse
import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from src.agents.formatter_agent import FormatterAgent
from src.config import get_settings
from src.models.schemas import Document, Mode
from src.services.curadoria import foi_substituido
from src.services.openai_service import OpenAIService
from src.services.typesafe_service import TypesafeService


class FrozenCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    query: Annotated[str, StringConstraints(min_length=1, max_length=8000)]
    rewritten: Annotated[str, StringConstraints(max_length=8000)] = ""
    mode: Mode = "orientacao"
    documents: list[Document] = Field(max_length=15)
    expected_ids: list[str] = Field(default_factory=list, max_length=35)


def load_cases(path: Path) -> list[FrozenCase]:
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Frozen dataset exceeds size limit")
    cases: list[FrozenCase] = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            if len(line) > 500000 or len(cases) >= 500:
                raise ValueError("Frozen dataset exceeds case limits")
            try:
                case = FrozenCase.model_validate_json(line)
            except ValidationError:
                raise ValueError(f"Invalid frozen case at line {number}") from None
            if len({d.id for d in case.documents}) != len(case.documents) or case.id in {
                c.id for c in cases
            }:
                raise ValueError("Duplicate frozen case or document IDs")
            if any(foi_substituido(d.metadata) for d in case.documents):
                raise ValueError("Retired corrections are not valid benchmark candidates")
            cases.append(case)
    if not cases:
        raise ValueError("Frozen dataset is empty")
    return cases


async def compare_case(
    case: FrozenCase, openai: OpenAIService, typesafe: TypesafeService
) -> dict[str, Any]:
    variants: dict[str, Any] = {}
    for variant in ("A", "B", "C"):
        started = monotonic()
        if variant == "C":
            documents = await typesafe.rerank(case.query, case.documents, rewritten=case.rewritten)
        else:
            query = (
                (case.query + "\nAuxiliary rewrite: " + case.rewritten)
                if variant == "B"
                else (case.rewritten or case.query)
            )
            documents = await openai.rerank(query, case.documents, full_context=variant == "B")
        generated = await openai.generate_response(case.query, documents, case.mode)
        formatted = await openai.format_response(generated, case.mode)
        response = await FormatterAgent().execute(formatted, case.mode)
        ids = [d.id for d in documents]
        expected = set(case.expected_ids)
        variants[variant] = {
            "document_ids": ids,
            "response": response,
            "expected_sources_recall": len(expected.intersection(ids)) / len(expected)
            if expected
            else None,
            "latency_ms": int((monotonic() - started) * 1000),
        }
        if variant == "C":
            started = monotonic()
            result = await typesafe.verify(case.query, response, documents)
            variants["D"] = {
                **variants["C"],
                "verification": result.model_dump(),
                "would_deliver_candidate": result.approved,
                "delivered_response": response
                if result.approved
                else "Encaminhar para revisão de um analista.",
                "latency_ms": variants["C"]["latency_ms"] + int((monotonic() - started) * 1000),
            }
    return {"case_id": case.id, "variants": variants}


async def run(cases: list[FrozenCase], output: Path) -> None:
    config = get_settings()
    if not config.openai_key or not config.typesafe_api_key:
        raise ValueError("OPENAI_API_KEY and TYPESAFE_API_KEY are required")
    if any(len(case.documents) > config.typesafe_max_candidates for case in cases):
        raise ValueError("Frozen candidates exceed shared experimental limit")
    if config.typesafe_max_chunk_chars != 6000:
        raise ValueError("A/B/C/D comparison requires shared 6000-character inputs")
    openai = OpenAIService(
        api_key=config.openai_key,
        model=config.openai_model,
        embedding_model=config.embedding_model,
        timeout=config.openai_timeout_seconds,
        max_retries=config.openai_max_retries,
    )
    typesafe = TypesafeService(config)
    try:
        results = []
        events: list[dict[str, Any]] = []
        for case in cases:
            typesafe.events.clear()
            try:
                result = await compare_case(case, openai, typesafe)
                results.append(result)
            except Exception:
                results.append({"case_id": case.id, "status": "error"})
            events.extend(event.model_dump() for event in typesafe.events)
        report = {
            "model": config.typesafe_model,
            "criteria_version": config.typesafe_criteria_version,
            "quality_validated": False,
            "human_review_required": True,
            "results": results,
            "events": events,
            "observed_input_tokens": sum(e["input_tokens"] for e in events),
            "observed_estimated_cost_usd": sum(e["estimated_cost_usd"] for e in events),
        }
        await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            output.write_text, json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        await openai.aclose()
        await typesafe.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("evals/reports/comparacao-jev.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        cases = load_cases(args.input)
        if args.dry_run:
            print(f"{len(cases)} frozen cases validated; no API calls")
        else:
            asyncio.run(run(cases, args.output))
    except (ValueError, OSError):
        parser.exit(1, "Unable to run comparison; check local input and required configuration.\n")


if __name__ == "__main__":
    main()
