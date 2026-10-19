"""Manual read-only pilot with analyst questions; never invoked by CI."""

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from evals.compare_jev import FrozenCase
from src.agents.formatter_agent import FormatterAgent
from src.agents.rag_agent import RAGAgent
from src.config import Settings, get_settings
from src.models.schemas import Document
from src.services.curadoria import extrair_pergunta, foi_substituido, normalizar_pergunta
from src.services.openai_service import OpenAIService
from src.services.pilot_source_service import PilotSourceService
from src.services.supabase_service import SupabaseService
from src.services.typesafe_service import TypesafeService

EXCLUDED_CHANNELS = {"eval", "teste", "test", "diag", "diagnostico", "diagnóstico", "verif"}
MODES = {"orientacao", "bug", "resposta-cliente"}


def select_cases(
    rows: list[dict[str, Any]], corrections: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 30:
        raise ValueError("Pilot limit must be between 1 and 30")
    references: dict[str, str | None] = {}
    reference_ids: dict[str, str | None] = {}
    for row in sorted(corrections, key=lambda r: str(r.get("criado_em") or ""), reverse=True):
        key = normalizar_pergunta(str(row.get("pergunta") or ""))
        answer = str(row.get("resposta_correta") or "").strip()
        if key not in references:
            reference_ids[key] = str(row["id"]) if row.get("id") is not None else None
            references[key] = (
                answer
                if row.get("ingerida") is True
                and isinstance(row.get("chunks_criados"), int)
                and row["chunks_criados"] > 0
                and 0 < len(answer) <= 40000
                and not answer.lower().startswith("[descartada:")
                else None
            )
    buckets: dict[str | None, list[dict[str, Any]]] = {"negativo": [], "positivo": [], None: []}
    seen: set[str] = set()
    for row in sorted(rows, key=lambda r: str(r.get("timestamp") or ""), reverse=True):
        query = str(row.get("pergunta") or "").strip()
        response = str(row.get("resposta") or "").strip()
        rewritten = str(row.get("pergunta_reescrita") or "").strip()
        mode = row.get("modo") or "orientacao"
        key = normalizar_pergunta(query)
        if (
            not 15 <= len(query) <= 8000
            or not 0 < len(response) <= 40000
            or len(rewritten) > 8000
            or mode not in MODES
            or row.get("feedback") not in buckets
            or str(row.get("canal") or "").lower() in EXCLUDED_CHANNELS
            or key in seen
        ):
            continue
        seen.add(key)
        sources = row.get("fontes")
        source_ids = (
            [str(v) for v in sources if isinstance(v, (str, int)) and len(str(v)) <= 128]
            if isinstance(sources, list)
            else []
        )
        buckets[row.get("feedback")].append(
            {
                "source_id": str(row.get("id") or ""),
                "query": query,
                "rewritten": rewritten,
                "mode": mode,
                "feedback": row.get("feedback"),
                "timestamp": row.get("timestamp"),
                "historical_response": response,
                "historical_source_ids": list(dict.fromkeys(source_ids)),
                "historical_source_ids_valid": isinstance(sources, list)
                and len(source_ids) == len(sources),
                "analyst_reference": references.get(key),
                "analyst_reference_id": reference_ids.get(key) if references.get(key) else None,
            }
        )
    selected: list[dict[str, Any]] = []
    modes: Counter[str] = Counter()
    while len(selected) < limit and any(buckets.values()):
        for bucket in buckets.values():
            if not bucket or len(selected) >= limit:
                continue
            index = min(
                range(len(bucket)),
                key=lambda i: (bucket[i]["analyst_reference"] is None, modes[bucket[i]["mode"]], i),
            )
            case = bucket.pop(index)
            case["id"] = f"analista-{len(selected) + 1:03d}"
            selected.append(case)
            modes[case["mode"]] += 1
    return selected


def require_config(config: Settings) -> None:
    if not all(
        (
            config.supabase_url,
            config.supabase_service_role_key,
            config.openai_key,
            config.typesafe_api_key,
        )
    ):
        raise ValueError("Pilot requires backend Supabase, OpenAI and Jev configuration")
    if config.max_chunks + 5 > min(15, config.typesafe_max_candidates):
        raise ValueError("Pilot candidates exceed Jev limit")
    if config.typesafe_max_chunk_chars != 6000:
        raise ValueError("Pilot requires shared 6000-character reranking inputs")


async def verify_response(
    typesafe: TypesafeService, query: str, response: str, documents: list[Document]
) -> dict[str, Any]:
    if not documents:
        return {
            "transport_status": "not_evaluated",
            "approved": False,
            "reason": "no_documentary_evidence",
        }
    try:
        return {
            "transport_status": "ok",
            **(await typesafe.verify(query, response, documents)).model_dump(),
        }
    except Exception as exc:
        return {"transport_status": "error", "approved": False, "error_type": type(exc).__name__}


async def compare_pilot_case(
    case: FrozenCase, openai: OpenAIService, typesafe: TypesafeService, *, top_n: int = 10
) -> dict[str, Any]:
    variants: dict[str, Any] = {}
    for variant in ("A", "B", "C"):
        started = monotonic()
        try:
            if variant == "C":
                documents = await typesafe.rerank(
                    case.query, case.documents, rewritten=case.rewritten, top_n=top_n
                )
            else:
                query = (
                    case.query + "\nAuxiliary rewrite: " + case.rewritten
                    if variant == "B"
                    else (case.rewritten or case.query)
                )
                documents = await openai.rerank(
                    query, case.documents, top_n=top_n, full_context=variant == "B"
                )
            agent = RAGAgent(openai, SupabaseService())
            generated = await agent.generate(case.query, documents, case.mode)
            response = await FormatterAgent().execute(generated, case.mode)
            elapsed = int((monotonic() - started) * 1000)
            verification_started = monotonic()
            verification = await verify_response(typesafe, case.query, response, documents)
            variants[variant] = {
                "status": "ok",
                "document_ids": [d.id for d in documents],
                "response": response,
                "latency_ms": elapsed,
                "verification": verification,
                "verification_latency_ms": int((monotonic() - verification_started) * 1000),
            }
        except Exception as exc:
            variants[variant] = {"status": "error", "error_type": type(exc).__name__}
    if variants["C"]["status"] == "ok":
        approved = variants["C"]["verification"]["approved"]
        variants["D"] = {
            "status": "ok",
            "would_deliver_candidate": approved,
            "verification": variants["C"]["verification"],
            "delivered_response": variants["C"]["response"]
            if approved
            else "Encaminhar para revisão de um analista.",
            "latency_ms": variants["C"]["latency_ms"] + variants["C"]["verification_latency_ms"],
        }
    else:
        variants["D"] = {"status": "error", "reason": "candidate_unavailable"}
    return variants


async def historical_verification(
    case: dict[str, Any], database: SupabaseService | PilotSourceService, typesafe: TypesafeService
) -> dict[str, Any]:
    ids = case["historical_source_ids"]
    if not ids or len(ids) > 30 or not case.get("historical_source_ids_valid", True):
        return {"transport_status": "not_evaluated", "reason": "missing_or_excessive_source_ids"}
    if any(not id.isdecimal() for id in ids):
        return {
            "transport_status": "not_evaluated",
            "reason": "legacy_source_labels_without_document_ids",
        }
    documents = []
    try:
        for id in ids:
            document = await database.get_document(id)
            if (
                document is None
                or foi_substituido(document.metadata)
                or len(document.content) > 100000
            ):
                return {
                    "transport_status": "not_evaluated",
                    "reason": "missing_retired_or_excessive_source",
                }
            documents.append(document)
    except Exception as exc:
        return {"transport_status": "error", "error_type": type(exc).__name__}
    return await verify_response(typesafe, case["query"], case["historical_response"], documents)


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for variant in ("historical", "A", "B", "C"):
        entries = [
            r.get("historical_verification", {})
            if variant == "historical"
            else r.get("variants", {}).get(variant, {}).get("verification", {})
            for r in results
        ]
        evaluated = [v for v in entries if v.get("transport_status") == "ok"]
        summary[variant] = {
            "evaluated": len(evaluated),
            "approved": sum(bool(v.get("approved")) for v in evaluated),
            "not_evaluated_or_error": len(entries) - len(evaluated),
            "statuses": dict(Counter(v.get("status") for v in evaluated)),
        }
    return summary


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# Piloto Jev com perguntas reais",
        "",
        "Comparação do núcleo RAG, sem histórico conversacional ou escrita no banco.",
        "Aprovação Jev não é acurácia medida. Revisão humana obrigatória; referências podem já estar na base.",
        "",
        "| Variante | Avaliadas | Aprovadas Jev | Não avaliadas/erro |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key, value in report["summary"].items():
        lines.append(
            f"| {key} | {value['evaluated']} | {value['approved']} | {value['not_evaluated_or_error']} |"
        )
    if report.get("reference_summary"):
        lines.extend(
            [
                "",
                "## Confronto com a referência registrada do analista",
                "",
                "A própria referência é verificada como controle. A comparação mede suporte, não completude ou verdade externa.",
                "",
                "| Resposta | Avaliadas | Aprovadas Jev |",
                "| --- | ---: | ---: |",
            ]
        )
        for key, value in report["reference_summary"].items():
            lines.append(f"| {key} | {value['evaluated']} | {value['approved']} |")
    for result in report["results"]:
        lines.extend(
            [
                "",
                f"## {result['id']}",
                "",
                result["query"],
                "",
                f"Modo: {result['mode']}; feedback: {result['feedback']}; referência nos candidatos: {result.get('reference_in_candidates', False)}.",
                "",
                "### Referência registrada do analista",
                "",
                result.get("analyst_reference") or "Sem referência revisada correspondente.",
                "",
                "### Resposta histórica",
                "",
                result["historical_response"],
                "",
                f"Verificação histórica: {json.dumps(result.get('historical_verification', {}), ensure_ascii=False)}",
            ]
        )
        for name, variant in result.get("variants", {}).items():
            lines.extend(
                [
                    "",
                    f"### {name}",
                    "",
                    variant.get("response", variant.get("delivered_response", "Falha técnica")),
                    "",
                    f"Verificação: {json.dumps(variant.get('verification', {}), ensure_ascii=False)}",
                ]
            )
        if result.get("reference_comparison"):
            lines.extend(
                [
                    "",
                    "### Verificação contra a referência do analista",
                    "",
                    f"Controle (a própria referência): {json.dumps(result.get('reference_self_check', {}), ensure_ascii=False)}",
                ]
            )
            for key, value in result["reference_comparison"].items():
                lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False)}")
        lines.extend(
            [
                "",
                "Revisão humana: fidelidade [ ]; completude [ ]; utilidade [ ]; bloqueio indevido [ ].",
            ]
        )
    return "\n".join(lines) + "\n"


async def save_report(report: dict[str, Any], output: Path) -> None:
    report["summary"] = summarize(report["results"])
    await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(
        output.write_text, json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    await asyncio.to_thread(
        output.with_suffix(".md").write_text, render_report(report), encoding="utf-8"
    )


async def run_pilot(config: Settings, output: Path, *, limit: int, capture_only: bool) -> None:
    require_config(config)
    if not 1 <= limit <= 30:
        raise ValueError("Pilot limit must be between 1 and 30")
    # Internal artifacts must stay in the ignored report directory.
    valid_output = await asyncio.to_thread(
        lambda: output.resolve().is_relative_to(Path("evals/reports").resolve())
    )
    if not valid_output or output.suffix != ".json":
        raise ValueError("Pilot output must be a JSON file in evals/reports")
    source = PilotSourceService(config)
    openai = OpenAIService(
        api_key=config.openai_key,
        model=config.openai_model,
        embedding_model=config.embedding_model,
        timeout=config.openai_timeout_seconds,
        max_retries=config.openai_max_retries,
    )
    typesafe = TypesafeService(config)
    database = SupabaseService(client=source.client)
    agent = RAGAgent(openai, database, config)
    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "model": config.typesafe_model,
        "openai_model": config.openai_model,
        "criteria_version": config.typesafe_criteria_version,
        "support_threshold": config.typesafe_support_threshold,
        "contradiction_threshold": config.typesafe_contradiction_threshold,
        "quality_validated": False,
        "human_review_required": True,
        "historical_sources_are_current_content": True,
        "conversation_history_replayed": False,
        "production_changed": False,
        "results": [],
        "events": [],
        "capture_only": capture_only,
    }
    try:
        raw = await source.capture()
        cases = select_cases(raw["history"], raw["corrections"], limit)
        if not cases:
            raise ValueError("No eligible analyst questions")
        report["sample"] = {
            "selected": len(cases),
            "feedback": dict(Counter(str(c["feedback"]) for c in cases)),
            "modes": dict(Counter(c["mode"] for c in cases)),
            "with_analyst_reference": sum(c["analyst_reference"] is not None for c in cases),
        }
        frozen = []
        for case in cases:
            typesafe.events.clear()
            result = dict(case)
            try:
                async with asyncio.timeout(180):
                    search_query = case["rewritten"] or (
                        await openai.rewrite_query(case["query"])
                        if agent._needs_rewrite(case["query"], "")
                        else case["query"]
                    )
                    count = config.max_chunks + 5
                    documents = (
                        await agent._buscar_fundido(case["query"], search_query, count)
                        if search_query != case["query"]
                        else await agent._buscar(search_query, count)
                    )
                    if any(d.id.startswith("chunk_") or len(d.content) > 100000 for d in documents):
                        raise ValueError("Invalid frozen document")
                    frozen_case = FrozenCase(
                        id=case["id"],
                        query=case["query"],
                        rewritten=search_query,
                        mode=case["mode"],
                        documents=documents,
                    )
                    frozen.append(frozen_case.model_dump())
                    result["candidate_ids"] = [d.id for d in documents]
                    result["reference_in_candidates"] = (
                        any(
                            normalizar_pergunta(extrair_pergunta(d.content) or "")
                            == normalizar_pergunta(case["query"])
                            for d in documents
                        )
                        if case["analyst_reference"]
                        else False
                    )
                    result["historical_verification"] = (
                        await historical_verification(case, source, typesafe)
                        if not capture_only
                        else {"transport_status": "not_evaluated", "reason": "capture_only"}
                    )
                    if not capture_only:
                        result["variants"] = await compare_pilot_case(
                            frozen_case, openai, typesafe, top_n=config.max_chunks
                        )
            except Exception as exc:
                result["status"] = "error"
                result["error_type"] = type(exc).__name__
            report["results"].append(result)
            report["events"].extend(e.model_dump() for e in typesafe.events)
            report["observed_input_tokens"] = sum(e["input_tokens"] for e in report["events"])
            report["observed_estimated_cost_usd"] = sum(
                e["estimated_cost_usd"] for e in report["events"]
            )
            await save_report(report, output)
            await asyncio.to_thread(
                output.with_suffix(".frozen.jsonl").write_text,
                "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in frozen),
                encoding="utf-8",
            )
            print(
                f"{case['id']}: {'captured' if capture_only else 'compared'}; cases {len(report['results'])}/{len(cases)}",
                flush=True,
            )
        print(
            json.dumps(
                {
                    "sample": report["sample"],
                    "summary": report["summary"],
                    "observed_input_tokens": report["observed_input_tokens"],
                    "observed_estimated_cost_usd": report["observed_estimated_cost_usd"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    finally:
        await asyncio.gather(openai.aclose(), typesafe.aclose(), source.aclose())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--output", type=Path, default=Path("evals/reports/piloto-jev.json"))
    parser.add_argument("--capture-only", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(
            run_pilot(get_settings(), args.output, limit=args.limit, capture_only=args.capture_only)
        )
    except Exception as exc:
        parser.exit(
            1,
            f"Unable to run pilot ({type(exc).__name__}); check configuration and source access.\n",
        )


if __name__ == "__main__":
    main()
