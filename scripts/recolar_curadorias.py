"""Conserta as correcoes de analista que ja estao na base.

Tres coisas, nesta ordem:

1. **Marca** toda correcao existente com `metadata.tipo = "curadoria"` e
   `metadata.pergunta_norm`. Sem isso o prompt nao tem como saber quais trechos
   sao resposta validada — a autoridade vem do metadata, nao do conteudo.
2. **Recola** correcoes que o chunker partiu: o pedaco 0 fica com o
   "Pergunta: ...", os pedacos seguintes viram texto solto que volta na busca
   como se fosse manual e contradiz a propria correcao de onde saiu.
3. **Aposenta** correcoes duplicadas da mesma pergunta, mantendo a mais nova.

Escreve backup de tudo que toca em dashboard/backups/ antes de alterar.
Sem --apply e simulacao.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402
from openai import OpenAI  # noqa: E402
from supabase import create_client  # noqa: E402

from src.services import curadoria  # noqa: E402

BACKUPS_DIR = REPO_ROOT / "dashboard" / "backups"
EMBEDDING_MODEL = "text-embedding-3-small"
# Pais conhecidos cujas correcoes o chunker partiu (chunk_index 0 do lote).
PAIS_PADRAO = [1711, 2855]


def _cliente_supabase() -> Any:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def _com_embedding(cliente: Any, linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebusca as linhas com o embedding: o backup de uma linha que vai ser
    apagada precisa dele para uma restauracao fiel, sem reembedar.
    """
    ids = [linha["id"] for linha in linhas]
    if not ids:
        return []
    resposta = cliente.table("documents").select("*").in_("id", ids).execute()
    return list(resposta.data or [])


def _backup(linhas: list[dict[str, Any]]) -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    caminho = BACKUPS_DIR / f"curadorias-{datetime.now(UTC).strftime('%Y-%m-%d')}.jsonl"
    with caminho.open("a", encoding="utf-8") as fh:
        for linha in linhas:
            registro = dict(linha)
            registro["backup_em"] = datetime.now(UTC).isoformat()
            fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return caminho


def _curadorias(cliente: Any) -> list[dict[str, Any]]:
    resposta = (
        cliente.table("documents")
        .select("id,content,metadata,created_at")
        .ilike("content", f"%{curadoria.MARCADOR}%")
        .execute()
    )
    return sorted(resposta.data or [], key=lambda linha: int(linha["id"]))


def _irmaos(cliente: Any, pai: dict[str, Any]) -> list[dict[str, Any]]:
    """Pedacos seguintes do mesmo lote de ingestao (mesmo carimbo `data`)."""
    carimbo = (pai.get("metadata") or {}).get("data")
    if not carimbo:
        return []
    resposta = (
        cliente.table("documents")
        .select("id,content,metadata,created_at")
        .eq("metadata->>data", carimbo)
        .execute()
    )
    irmaos = [
        linha
        for linha in (resposta.data or [])
        if int(linha["id"]) != int(pai["id"])
        and int((linha.get("metadata") or {}).get("chunk_index") or 0) > 0
    ]
    return sorted(irmaos, key=lambda linha: int((linha["metadata"] or {}).get("chunk_index") or 0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="grava; sem isso so simula")
    parser.add_argument(
        "--pais",
        type=int,
        nargs="*",
        default=PAIS_PADRAO,
        help="ids das correcoes partidas a recolar",
    )
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    cliente = _cliente_supabase()
    openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    prefixo = "[APLICANDO]" if args.apply else "[SIMULACAO]"

    curadas = _curadorias(cliente)
    print(f"{prefixo} {len(curadas)} correcoes encontradas na base.\n")

    # ---------------------------------------------------------- 1. recolagem
    recolados_ids: set[int] = set()
    for pai_id in args.pais:
        pai = next((linha for linha in curadas if int(linha["id"]) == pai_id), None)
        if pai is None:
            print(f"  ! id {pai_id} nao e uma correcao (ou sumiu) — pulando")
            continue
        irmaos = _irmaos(cliente, pai)
        if not irmaos:
            print(f"  = id {pai_id} nao tem orfaos")
            continue

        inteiro = "\n\n".join([pai["content"].strip(), *(i["content"].strip() for i in irmaos)])
        ids_irmaos = [int(i["id"]) for i in irmaos]
        print(f"  + recolando {pai_id} <- {ids_irmaos} ({len(inteiro)} chars)")
        if args.apply:
            _backup(_com_embedding(cliente, [pai, *irmaos]))
            embedding = (
                openai.embeddings.create(model=EMBEDDING_MODEL, input=inteiro).data[0].embedding
            )
            metadata = {**(pai.get("metadata") or {}), **curadoria.metadata_curadoria(inteiro)}
            metadata["recolado_em"] = datetime.now(UTC).isoformat()
            metadata["recolados"] = ids_irmaos
            cliente.table("documents").update(
                {"content": inteiro, "embedding": embedding, "metadata": metadata}
            ).eq("id", pai_id).execute()
            cliente.table("documents").delete().in_("id", ids_irmaos).execute()
            pai["content"], pai["metadata"] = inteiro, metadata
        recolados_ids.update(ids_irmaos)

    # ------------------------------------------------------------ 2. marcacao
    marcadas = 0
    for linha in curadas:
        if int(linha["id"]) in recolados_ids:
            continue
        metadata = dict(linha.get("metadata") or {})
        extra = curadoria.metadata_curadoria(linha["content"])
        if not extra:
            print(f"  ! id {linha['id']} tem o marcador mas nao casa 'Pergunta:' — pulando")
            continue
        if metadata.get("tipo") == curadoria.TIPO and metadata.get("pergunta_norm"):
            continue
        metadata.update(extra)
        marcadas += 1
        print(f"  + marcando {linha['id']} como curadoria ({extra['pergunta_norm'][:60]})")
        if args.apply:
            cliente.table("documents").update({"metadata": metadata}).eq(
                "id", linha["id"]
            ).execute()
        linha["metadata"] = metadata
    print(f"\n{prefixo} {marcadas} correcoes marcadas.")

    # --------------------------------------------------------- 3. aposentar
    vivas = [linha for linha in curadas if int(linha["id"]) not in recolados_ids]
    por_pergunta: dict[str, list[dict[str, Any]]] = {}
    for linha in vivas:
        chave = (linha.get("metadata") or {}).get("pergunta_norm")
        if chave:
            por_pergunta.setdefault(chave, []).append(linha)

    aposentadas = 0
    for chave, grupo in por_pergunta.items():
        if len(grupo) < 2:
            continue
        grupo.sort(key=lambda linha: int(linha["id"]))
        vigente, antigas = grupo[-1], grupo[:-1]
        for antiga in antigas:
            metadata = dict(antiga.get("metadata") or {})
            if metadata.get("substituido_por"):
                continue
            metadata["substituido_por"] = str(vigente["id"])
            metadata["substituido_em"] = datetime.now(UTC).isoformat()
            aposentadas += 1
            print(f"  + {antiga['id']} substituida por {vigente['id']} ({chave[:60]})")
            if args.apply:
                _backup(_com_embedding(cliente, [antiga]))
                cliente.table("documents").update({"metadata": metadata}).eq(
                    "id", antiga["id"]
                ).execute()
    print(f"{prefixo} {aposentadas} correcoes aposentadas.")

    if not args.apply:
        print("\nNada foi gravado. Rode de novo com --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
