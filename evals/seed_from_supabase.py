"""Extrai casos reais do Supabase para o rascunho do dataset de avaliação.

Uso (uma vez, ou para re-semear):
    .venv/Scripts/python.exe evals/seed_from_supabase.py

Gera evals/dataset.draft.jsonl com rubricas vazias; a curadoria
(fatos_esperados/erros_proibidos) é manual e vira evals/dataset.jsonl.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from dotenv import dotenv_values
from supabase import create_client

EVALS_DIR = Path(__file__).resolve().parent
DRAFT_PATH = EVALS_DIR / "dataset.draft.jsonl"
POSITIVOS_ALVO = 20
DISCORD_ID_RE = re.compile(r"^[0-9]+$")


def _caso(
    caso_id: str,
    origem: str,
    row: dict[str, Any],
    incluir_resposta_anterior: bool,
) -> dict[str, Any]:
    caso: dict[str, Any] = {
        "id": caso_id,
        "origem": origem,
        "modo": row.get("modo") or "orientacao",
        "pergunta": (row.get("pergunta") or "").strip(),
        "fatos_esperados": [],
        "erros_proibidos": [],
        "notas": f"seed: timestamp={row.get('timestamp', '')[:16]} score={row.get('score')}",
    }
    if incluir_resposta_anterior:
        caso["resposta_anterior"] = (row.get("resposta") or "").strip()
    else:
        # Positivo: a resposta aprovada é a referência para extrair fatos.
        caso["resposta_aprovada_referencia"] = (row.get("resposta") or "").strip()
    return caso


def _amostrar_positivos(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Espalha a amostra pelo período: ordena por timestamp e pega passos regulares."""
    reais = [
        r
        for r in rows
        if DISCORD_ID_RE.match(str(r.get("user_id") or ""))
        and len((r.get("pergunta") or "").strip()) >= 15
    ]
    vistos: set[str] = set()
    unicos = []
    for r in sorted(reais, key=lambda r: r.get("timestamp") or ""):
        chave = (r.get("pergunta") or "").strip().lower()
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(r)
    if len(unicos) <= POSITIVOS_ALVO:
        return unicos
    passo = len(unicos) / POSITIVOS_ALVO
    return [unicos[int(i * passo)] for i in range(POSITIVOS_ALVO)]


def main() -> None:
    env = dotenv_values(EVALS_DIR.parent / ".env")
    url, key = env.get("SUPABASE_URL"), env.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL/SUPABASE_ANON_KEY ausentes no .env")
    client = create_client(url, key)

    negativos = cast(
        "list[dict[str, Any]]", client.table("v_negativos").select("*").execute().data or []
    )
    positivos = cast(
        "list[dict[str, Any]]",
        client.table("historico_digi")
        .select("user_id,pergunta,resposta,modo,score,timestamp")
        .eq("feedback", "positivo")
        .execute()
        .data
        or [],
    )

    casos = [
        _caso(f"neg-{i:03d}", "feedback_negativo", row, incluir_resposta_anterior=True)
        for i, row in enumerate(negativos, 1)
    ]
    casos += [
        _caso(f"pos-{i:03d}", "feedback_positivo", row, incluir_resposta_anterior=False)
        for i, row in enumerate(_amostrar_positivos(positivos), 1)
    ]

    with DRAFT_PATH.open("w", encoding="utf-8") as fh:
        for caso in casos:
            fh.write(json.dumps(caso, ensure_ascii=False) + "\n")
    print(f"{len(casos)} casos escritos em {DRAFT_PATH}")


if __name__ == "__main__":
    main()
