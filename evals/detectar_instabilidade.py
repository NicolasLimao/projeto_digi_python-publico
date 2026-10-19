"""Detector de instabilidade da base RAG do Digi.

Roda cada caso do dataset N vezes contra a API, julga cada resposta com a
mesma rubrica do eval e mede a divergência dos vereditos. Captura os chunks
da busca híbrida para apontar conteúdo conflitante por data (insumo da
Fase 2: reconciliação). 100% leitura — nada é escrito no banco.

Uso:
    python evals/detectar_instabilidade.py                  # 5x por caso
    python evals/detectar_instabilidade.py --repeticoes 3
    python evals/detectar_instabilidade.py --filter neg --limit 5
    python evals/detectar_instabilidade.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values
from openai import AsyncOpenAI

EVALS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS_DIR))
import run_eval  # noqa: E402

DEFAULT_REPETICOES = 5
LIMIAR_CONFLITO_DIAS = 30
EMBEDDING_MODEL = "text-embedding-3-small"
MAX_CONCURRENCY = 3
RPC_BUSCA = "match_documents_hybrid"


@dataclass
class ResultadoCaso:
    case_id: str
    pergunta: str
    vereditos: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    chunks: list[dict[str, Any]] = field(default_factory=list)


def _redigir(texto: str) -> str:
    """Mascara e-mails em texto livre antes de gravar em relatório (repo é público)."""
    return re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", texto)


def indice_instabilidade(vereditos: list[str]) -> float:
    """1 - freq(majoritário)/N sobre vereditos válidos; erros de infra ficam fora."""
    validos = [v for v in vereditos if v in ("aprovado", "reprovado")]
    if not validos:
        return 0.0
    majoritario = Counter(validos).most_common(1)[0][1]
    return round(1 - majoritario / len(validos), 3)


def contar_erros(vereditos: list[str]) -> int:
    return sum(1 for v in vereditos if v not in ("aprovado", "reprovado"))


def conflito_potencial(
    chunks: list[dict[str, Any]], limiar_dias: int = LIMIAR_CONFLITO_DIAS
) -> bool:
    """True quando os chunks recuperados misturam datas com diferença > limiar."""
    datas: list[date] = []
    for chunk in chunks:
        try:
            datas.append(date.fromisoformat(str(chunk.get("data"))[:10]))
        except ValueError:
            continue
    if len(datas) < 2:
        return False
    return (max(datas) - min(datas)).days > limiar_dias


def montar_relatorio(
    resultados: list[ResultadoCaso], repeticoes: int, run_id: str
) -> tuple[str, dict[str, Any]]:
    """Relatório md (humano) + estrutura json (Fase 2), ordenados por instabilidade."""
    ordenados = sorted(resultados, key=lambda r: indice_instabilidade(r.vereditos), reverse=True)
    instaveis = [r for r in ordenados if indice_instabilidade(r.vereditos) > 0]
    com_conflito = [r for r in ordenados if conflito_potencial(r.chunks)]

    linhas = [
        f"# Instabilidade {run_id}",
        "",
        f"**{len(instaveis)} casos instáveis de {len(resultados)}** "
        f"({repeticoes} repetições por caso) · "
        f"{len(com_conflito)} com conflito potencial de datas",
        "",
    ]
    for resultado in ordenados:
        indice = indice_instabilidade(resultado.vereditos)
        if indice == 0:
            continue
        aviso = " ⚠️ CONFLITO DE DATAS" if conflito_potencial(resultado.chunks) else ""
        linhas += [
            f"## {resultado.case_id} — índice {indice}{aviso}",
            "",
            f"Pergunta: {resultado.pergunta}",
            f"Vereditos: {', '.join(resultado.vereditos)}",
        ]
        if resultado.scores:
            linhas.append(f"Score da API: {min(resultado.scores):.2f}-{max(resultado.scores):.2f}")
        if resultado.chunks:
            linhas.append("Chunks recuperados (ref · data · trecho):")
            linhas += [
                f"- `{chunk.get('ref')}` · {chunk.get('data') or 'sem data'} · "
                f"{chunk.get('trecho', '')}"
                for chunk in resultado.chunks
            ]
        linhas.append("")
    estaveis = [r.case_id for r in ordenados if indice_instabilidade(r.vereditos) == 0]
    linhas += [f"Estáveis ({len(estaveis)}): {', '.join(estaveis) or 'nenhum'}", ""]

    estrutura = {
        "run": run_id,
        "repeticoes": repeticoes,
        "casos": [
            {
                "id": r.case_id,
                "indice": indice_instabilidade(r.vereditos),
                "vereditos": r.vereditos,
                "erros": contar_erros(r.vereditos),
                "conflito_potencial": conflito_potencial(r.chunks),
                "chunks": r.chunks,
            }
            for r in ordenados
        ],
    }
    return "\n".join(linhas), estrutura


async def _julgar(juiz: AsyncOpenAI, caso: run_eval.EvalCase, resposta: str) -> str:
    try:
        conclusao = await juiz.chat.completions.create(
            model=run_eval.JUDGE_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": run_eval.JUDGE_SYSTEM},
                {"role": "user", "content": run_eval.build_judge_prompt(caso, resposta)},
            ],
        )
    except Exception:
        return "erro"
    veredito, _ = run_eval.parse_judge_response(conclusao.choices[0].message.content or "")
    return str(veredito)


def _user_id_da_execucao(prefixo_run: str, case_id: str, repeticao: int) -> str:
    """user_id isolado por repetição: cada execução lê histórico vazio, então a
    instabilidade medida é variância de geração real, não histórico embaralhado."""
    return f"{prefixo_run}_{case_id}_{repeticao}"


async def _uma_execucao(
    caso: run_eval.EvalCase,
    http_client: httpx.AsyncClient,
    juiz: AsyncOpenAI,
    api_url: str,
    api_token: str,
    user_id: str,
    limite: asyncio.Semaphore,
) -> tuple[str, float | None]:
    async with limite:
        try:
            resposta_http = await http_client.post(
                api_url,
                params={"user_id": user_id, "canal": "eval"},
                json={"query": caso.pergunta, "mode": caso.modo},
                headers={"X-API-Key": api_token},
            )
            resposta_http.raise_for_status()
            corpo = resposta_http.json()
        except (httpx.HTTPError, ValueError):
            return "erro", None
        veredito = await _julgar(juiz, caso, str(corpo.get("response") or ""))
        score = corpo.get("score")
        return veredito, float(score) if score is not None else None


async def _chunks_do_caso(
    openai_client: AsyncOpenAI, supabase_client: Any, pergunta: str
) -> list[dict[str, Any]]:
    """Reproduz a busca híbrida da API para capturar os chunks (somente leitura)."""
    try:
        embedding = await openai_client.embeddings.create(model=EMBEDDING_MODEL, input=pergunta)
        vetor = embedding.data[0].embedding

        def consulta() -> Any:
            return supabase_client.rpc(
                RPC_BUSCA,
                {
                    "query_text": pergunta,
                    "query_embedding": str(vetor),
                    "match_count": 10,
                    "full_text_weight": 0.5,
                    "semantic_weight": 0.5,
                },
            ).execute()

        resposta = await asyncio.to_thread(consulta)
    except Exception:
        return []
    chunks: list[dict[str, Any]] = []
    for item in resposta.data or []:
        conteudo = _redigir(" ".join(str(item.get("content") or "")[:120].split()))
        metadados = item.get("metadata") or {}
        # `ref` (fonte#chunk_index) não é único — chunk_index reinicia a cada batch de
        # upload. O `id` (migração 004) é o localizador confiável; `ref` fica para
        # leitura humana e para o mapa continuar compatível com o dashboard.
        fonte = str(metadados.get("fonte") or "?")
        indice = metadados.get("chunk_index")
        ref = f"{fonte}#{indice}"
        id_bruto = item.get("id")
        chunks.append(
            {
                "id": str(id_bruto) if id_bruto is not None else "",
                "ref": ref,
                "data": (str(metadados.get("data") or "")[:10] or None),
                "trecho": conteudo,
                "score_busca": round(float(item.get("score") or 0.0), 3),
            }
        )
    return chunks


async def _rodar_caso(
    caso: run_eval.EvalCase,
    http_client: httpx.AsyncClient,
    juiz: AsyncOpenAI,
    supabase_client: Any,
    api_url: str,
    api_token: str,
    prefixo_run: str,
    repeticoes: int,
    limite: asyncio.Semaphore,
) -> ResultadoCaso:
    execucoes = await asyncio.gather(
        *(
            _uma_execucao(
                caso,
                http_client,
                juiz,
                api_url,
                api_token,
                _user_id_da_execucao(prefixo_run, caso.id, i),
                limite,
            )
            for i in range(repeticoes)
        )
    )
    async with limite:
        chunks = await _chunks_do_caso(juiz, supabase_client, caso.pergunta)
    return ResultadoCaso(
        case_id=caso.id,
        pergunta=caso.pergunta,
        vereditos=[veredito for veredito, _ in execucoes],
        scores=[score for _, score in execucoes if score is not None],
        chunks=chunks,
    )


def _criar_supabase(env: dict[str, str | None]) -> Any:
    from supabase import create_client

    url = env.get("SUPABASE_URL")
    chave = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_ANON_KEY")
    if not url or not chave:
        raise SystemExit("SUPABASE_URL e uma chave do Supabase são obrigatórias no .env")
    return create_client(url, chave)


async def _main_async(args: argparse.Namespace) -> int:
    casos = run_eval.load_dataset(run_eval.DATASET_PATH)
    if args.filter:
        casos = [caso for caso in casos if args.filter in caso.id]
    if args.limit is not None:
        casos = casos[: args.limit]
    if not casos:
        print("Nenhum caso após filtros.")
        return 1

    if args.dry_run:
        for caso in casos:
            print(f"{caso.id} [{caso.modo}] {caso.pergunta[:80]}")
        print(f"\n{len(casos)} casos x {args.repeticoes} repetições (dry-run).")
        return 0

    env = dotenv_values(EVALS_DIR.parent / ".env")
    api_token = env.get("API_AUTH_TOKEN") or ""
    openai_key = env.get("OPENAI_API_KEY") or ""
    if not api_token or not openai_key:
        print("API_AUTH_TOKEN e OPENAI_API_KEY são obrigatórios no .env")
        return 1
    api_url = (
        args.api_url
        or os.environ.get("EVAL_API_URL")
        or env.get("EVAL_API_URL")
        or (run_eval.DEFAULT_API_URL)
    )
    supabase_client = _criar_supabase(dict(env))

    run_id = time.strftime("%Y-%m-%d-%H%M")
    prefixo_run = f"stab_{time.strftime('%Y%m%d%H%M%S')}"
    limite = asyncio.Semaphore(MAX_CONCURRENCY)
    juiz = AsyncOpenAI(api_key=openai_key)

    async with httpx.AsyncClient(timeout=90.0) as http_client:
        resultados = list(
            await asyncio.gather(
                *(
                    _rodar_caso(
                        caso,
                        http_client,
                        juiz,
                        supabase_client,
                        api_url,
                        api_token,
                        prefixo_run,
                        args.repeticoes,
                        limite,
                    )
                    for caso in casos
                )
            )
        )
    await juiz.close()

    md, estrutura = montar_relatorio(resultados, args.repeticoes, run_id)
    run_eval.REPORTS_DIR.mkdir(exist_ok=True)
    md_path = run_eval.REPORTS_DIR / f"instabilidade-{run_id}.md"
    md_path.write_text(md, encoding="utf-8")
    (run_eval.REPORTS_DIR / f"instabilidade-{run_id}.json").write_text(
        json.dumps(estrutura, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    instaveis = [r for r in resultados if indice_instabilidade(r.vereditos) > 0]
    conflitos = [r for r in resultados if conflito_potencial(r.chunks)]
    print(
        f"\n{len(instaveis)} casos instáveis de {len(resultados)} · "
        f"{len(conflitos)} com conflito potencial de datas — relatório: {md_path}"
    )
    for resultado in sorted(
        instaveis, key=lambda r: indice_instabilidade(r.vereditos), reverse=True
    ):
        print(
            f"  {resultado.case_id}: índice {indice_instabilidade(resultado.vereditos)} "
            f"({', '.join(resultado.vereditos)})"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detector de instabilidade da base RAG (somente leitura)"
    )
    parser.add_argument(
        "--repeticoes", type=int, default=DEFAULT_REPETICOES, help="execuções por caso"
    )
    parser.add_argument("--filter", help="roda só casos cujo id contém a substring")
    parser.add_argument("--limit", type=int, help="roda só os N primeiros casos")
    parser.add_argument("--dry-run", action="store_true", help="lista casos sem chamar nada")
    parser.add_argument("--api-url", help="endpoint /api/rag/query (default produção)")
    return asyncio.run(_main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
