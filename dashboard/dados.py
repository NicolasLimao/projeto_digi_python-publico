"""Camada de dados do dashboard do Digi.

Nada de Streamlit aqui: funções puras + wrappers finos de rede, para que os
testes rodem offline e a UI fique só em app.py.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

from src.services.chunker import chunk_contextual_estrutural, construir_indice
from src.services.postman_chunker import chunk_postman

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = REPO_ROOT / "evals" / "dataset.jsonl"
REPORTS_DIR = REPO_ROOT / "evals" / "reports"
DEFAULT_API_BASE = "http://localhost:8000"
TABELA_RESPOSTAS = "duvidas_respondidas"

# Paleta validada (skill dataviz, superfície #1a1a19). O cinza é o neutro
# semântico de "sem avaliação" (midpoint, como em paletas divergentes).
COR_POSITIVO = "#0ca30c"
COR_SEM_AVALIACAO = "#8a8f98"
COR_NEGATIVO = "#d03b3b"
COR_SERIE = "#5c8ff0"


@dataclass
class Duvida:
    chave: str
    origem: str  # "producao" | "eval"
    modo: str
    pergunta: str
    resposta_ruim: str
    score: float | None = None
    veredito: str | None = None
    timestamp: str | None = None


def carregar_env() -> dict[str, str]:
    """Lê o .env da raiz; valores vazios são descartados."""
    return {chave: valor for chave, valor in dotenv_values(REPO_ROOT / ".env").items() if valor}


def criar_cliente_supabase(env: dict[str, str]) -> Any:
    from supabase import create_client

    url = env.get("SUPABASE_URL")
    chave = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_ANON_KEY")
    if not url or not chave:
        raise RuntimeError("SUPABASE_URL e uma chave do Supabase são obrigatórias no .env")
    return create_client(url, chave)


def criar_cliente_openai(env: dict[str, str]) -> Any:
    from openai import OpenAI

    chave = env.get("OPENAI_API_KEY")
    if not chave:
        raise RuntimeError("OPENAI_API_KEY é obrigatória no .env para contextualizar/embutir")
    return OpenAI(api_key=chave)


def duvidas_producao(linhas: list[dict[str, Any]]) -> list[Duvida]:
    """Converte linhas da view v_negativos em dúvidas pendentes."""
    duvidas: list[Duvida] = []
    for linha in linhas:
        ts = str(linha.get("timestamp") or "")
        duvidas.append(
            Duvida(
                chave=f"prod:{ts}",
                origem="producao",
                modo=str(linha.get("modo") or "orientacao"),
                pergunta=str(linha.get("pergunta") or ""),
                resposta_ruim=str(linha.get("resposta") or ""),
                score=float(linha["score"]) if linha.get("score") is not None else None,
                timestamp=ts,
            )
        )
    return duvidas


def duvidas_eval(dataset_path: Path, vereditos: dict[str, str] | None) -> list[Duvida]:
    """Casos do dataset com REVISAR nas notas, anotados com o veredito do baseline."""
    duvidas: list[Duvida] = []
    for linha in dataset_path.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        caso = json.loads(linha)
        if "REVISAR" not in (caso.get("notas") or ""):
            continue
        duvidas.append(
            Duvida(
                chave=f"eval:{caso['id']}",
                origem="eval",
                modo=str(caso.get("modo") or "orientacao"),
                pergunta=str(caso["pergunta"]),
                resposta_ruim=str(caso.get("resposta_anterior") or ""),
                veredito=(vereditos or {}).get(str(caso["id"])),
            )
        )
    return duvidas


def pendentes(producao: list[Duvida], eval_: list[Duvida], respondidas: set[str]) -> list[Duvida]:
    """União das fontes (dedupe por chave) menos as já respondidas."""
    todas: dict[str, Duvida] = {}
    for duvida in [*producao, *eval_]:
        todas.setdefault(duvida.chave, duvida)
    return [duvida for chave, duvida in todas.items() if chave not in respondidas]


def ultimo_baseline(reports_dir: Path) -> dict[str, Any] | None:
    """Último baseline COMPLETO do eval + delta vs o completo anterior."""
    completos: list[dict[str, Any]] = []
    for arquivo in sorted(reports_dir.glob("*.json")):
        try:
            conteudo = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if conteudo.get("parcial") or not isinstance(conteudo.get("vereditos"), dict):
            continue
        completos.append(conteudo)
    if not completos:
        return None

    def aprovados_de(relatorio: dict[str, Any]) -> int:
        return sum(1 for veredito in relatorio["vereditos"].values() if veredito == "aprovado")

    atual = completos[-1]
    resumo: dict[str, Any] = {
        "run": atual.get("run", "?"),
        "aprovados": aprovados_de(atual),
        "total": len(atual["vereditos"]),
        "vereditos": dict(atual["vereditos"]),
    }
    if len(completos) >= 2:
        resumo["delta"] = resumo["aprovados"] - aprovados_de(completos[-2])
    return resumo


def _somar_janela(linhas: list[dict[str, Any]], inicio: date, fim: date) -> dict[str, int]:
    total = {"interacoes": 0, "positivos": 0, "negativos": 0}
    for linha in linhas:
        try:
            dia = date.fromisoformat(str(linha.get("dia"))[:10])
        except ValueError:
            continue
        if inicio <= dia <= fim:
            for campo in total:
                total[campo] += int(linha.get(campo) or 0)
    return total


def janelas_volume(
    linhas: list[dict[str, Any]], dias: int, hoje: date
) -> tuple[dict[str, int], dict[str, int]]:
    """Somatórios da janela atual e da imediatamente anterior (deltas dos cards)."""
    inicio_atual = hoje - timedelta(days=dias - 1)
    inicio_anterior = inicio_atual - timedelta(days=dias)
    atual = _somar_janela(linhas, inicio_atual, hoje)
    anterior = _somar_janela(linhas, inicio_anterior, inicio_atual - timedelta(days=1))
    return atual, anterior


def preparar_volume_grafico(
    linhas: list[dict[str, Any]], dias: int, hoje: date
) -> list[dict[str, Any]]:
    """Formato longo p/ gráfico empilhado: dia x categoria x quantidade (+ordem)."""
    inicio = hoje - timedelta(days=dias - 1)
    saida: list[dict[str, Any]] = []
    for linha in linhas:
        try:
            dia = date.fromisoformat(str(linha.get("dia"))[:10])
        except ValueError:
            continue
        if not inicio <= dia <= hoje:
            continue
        positivos = int(linha.get("positivos") or 0)
        negativos = int(linha.get("negativos") or 0)
        sem = max(int(linha.get("interacoes") or 0) - positivos - negativos, 0)
        for ordem, (categoria, quantidade) in enumerate(
            [("Positivos", positivos), ("Sem avaliação", sem), ("Negativos", negativos)]
        ):
            saida.append(
                {
                    "dia": dia.isoformat(),
                    "categoria": categoria,
                    "quantidade": quantidade,
                    "ordem": ordem,
                }
            )
    return saida


def texto_ingestao(pergunta: str, resposta: str) -> str:
    return (
        f"Pergunta: {pergunta.strip()}\nResposta oficial validada pelo analista: {resposta.strip()}"
    )


def ingerir_resposta(api_base: str, token: str, texto: str) -> dict[str, Any]:
    """Ensina o bot: ingere o texto na base RAG via API de produção."""
    resposta = httpx.post(
        f"{api_base.rstrip('/')}/api/ingest",
        json={"content": texto, "curated": True},
        headers={"X-API-Key": token},
        timeout=120.0,
    )
    resposta.raise_for_status()
    try:
        corpo: dict[str, Any] = resposta.json()
    except ValueError:
        raise ValueError(
            "Ingestão não confirmada; resultado indeterminado, não repetir automaticamente"
        ) from None
    if (
        not isinstance(corpo, dict)
        or type(corpo.get("chunks_created")) is not int
        or corpo["chunks_created"] <= 0
        or corpo.get("errors", [])
    ):
        raise ValueError("Ingestão não confirmada; conferir resultado antes de repetir")
    return corpo


def chaves_respondidas(cliente: Any) -> set[str]:
    resposta = cliente.table(TABELA_RESPOSTAS).select("chave").execute()
    return {str(linha["chave"]) for linha in (resposta.data or [])}


def registrar_resposta(cliente: Any, duvida: Duvida, resposta_correta: str, chunks: int) -> None:
    cliente.table(TABELA_RESPOSTAS).insert(
        {
            "chave": duvida.chave,
            "pergunta": duvida.pergunta,
            "resposta_correta": resposta_correta,
            "ingerida": True,
            "chunks_criados": chunks,
        }
    ).execute()


MOTIVOS_DESCARTE = {
    "correta": "resposta do bot estava correta",
    "fora_escopo": "fora do escopo deste assistente",
    "invalida": "pergunta inválida/incompleta",
}


def descartar_duvida(cliente: Any, duvida: Duvida, motivo: str) -> None:
    """Fecha a dúvida sem ensinar nada ao bot (nada é ingerido na base RAG)."""
    cliente.table(TABELA_RESPOSTAS).insert(
        {
            "chave": duvida.chave,
            "pergunta": duvida.pergunta,
            "resposta_correta": f"[descartada: {motivo}]",
            "ingerida": False,
            "chunks_criados": 0,
        }
    ).execute()


def _dia_do_bucket(bucket: dict[str, Any]) -> str:
    return datetime.fromtimestamp(int(bucket.get("start_time") or 0), tz=UTC).date().isoformat()


def parse_custos(costs_json: dict[str, Any], usage_json: dict[str, Any]) -> dict[str, Any]:
    """Agrega custo (USD) e tokens por dia a partir dos buckets da OpenAI."""
    por_dia: dict[str, dict[str, float | int]] = {}

    def slot(dia: str) -> dict[str, float | int]:
        return por_dia.setdefault(dia, {"custo_usd": 0.0, "tokens_entrada": 0, "tokens_saida": 0})

    for bucket in costs_json.get("data") or []:
        registro = slot(_dia_do_bucket(bucket))
        for resultado in bucket.get("results") or []:
            registro["custo_usd"] = float(registro["custo_usd"]) + float(
                (resultado.get("amount") or {}).get("value") or 0
            )
    for bucket in usage_json.get("data") or []:
        registro = slot(_dia_do_bucket(bucket))
        for resultado in bucket.get("results") or []:
            registro["tokens_entrada"] = int(registro["tokens_entrada"]) + int(
                resultado.get("input_tokens") or 0
            )
            registro["tokens_saida"] = int(registro["tokens_saida"]) + int(
                resultado.get("output_tokens") or 0
            )

    ordenado: list[dict[str, Any]] = [
        {
            "dia": dia,
            "custo_usd": round(float(valores["custo_usd"]), 6),  # evita ruído de float
            "tokens_entrada": int(valores["tokens_entrada"]),
            "tokens_saida": int(valores["tokens_saida"]),
        }
        for dia, valores in sorted(por_dia.items())
    ]
    total = round(sum((float(item["custo_usd"]) for item in ordenado), 0.0), 4)
    return {"por_dia": ordenado, "custo_total_usd": total}


def _buckets_paginados(
    url: str, admin_key: str, inicio: int, limite_pagina: int
) -> list[dict[str, Any]]:
    """GET paginado (segue next_page/has_more) nas APIs de custo/uso da OpenAI."""
    cabecalhos = {"Authorization": f"Bearer {admin_key}"}
    parametros: dict[str, int | str] = {
        "start_time": inicio,
        "bucket_width": "1d",
        "limit": limite_pagina,
    }
    acumulado: list[dict[str, Any]] = []
    for _ in range(12):  # máx. 12 páginas de segurança
        resposta = httpx.get(url, params=parametros, headers=cabecalhos, timeout=30.0)
        resposta.raise_for_status()
        corpo = resposta.json()
        acumulado.extend(corpo.get("data") or [])
        if not corpo.get("has_more"):
            break
        proxima_pagina = corpo.get("next_page")
        if not proxima_pagina:
            break
        parametros = {**parametros, "page": proxima_pagina}
    return acumulado


def custos_openai(admin_key: str, dias: int) -> dict[str, Any]:
    """Consulta as APIs organizacionais de custo/uso da OpenAI (exige Admin key).

    O endpoint de usage limita `limit` a 31 para bucket_width=1d; costs aceita até 180.
    """
    inicio_costs = int(time.time()) - min(dias, 180) * 86_400
    inicio_usage = int(time.time()) - min(dias, 31) * 86_400
    custos = _buckets_paginados(
        "https://api.openai.com/v1/organization/costs", admin_key, inicio_costs, min(dias, 180)
    )
    uso = _buckets_paginados(
        "https://api.openai.com/v1/organization/usage/completions",
        admin_key,
        inicio_usage,
        min(dias, 31),
    )
    return parse_custos({"data": custos}, {"data": uso})


def _tabela_md(linhas: list[dict[str, Any]], campos: list[str]) -> list[str]:
    if not linhas:
        return ["(sem dados)"]
    cabecalho = "| " + " | ".join(campos) + " |"
    separador = "|" + "|".join("---" for _ in campos) + "|"
    corpo = [
        "| " + " | ".join(str(linha.get(campo, "")) for campo in campos) + " |" for linha in linhas
    ]
    return [cabecalho, separador, *corpo]


def gerar_relatorio_md(
    resumo: dict[str, Any],
    por_modo: list[dict[str, Any]],
    por_canal: list[dict[str, Any]],
    baseline: dict[str, Any] | None,
    duvidas: list[Duvida],
    dias: int,
    gerado_em: str,
    *,
    erro_duvidas: str | None = None,
) -> str:
    linhas = [
        "# Relatório Digi",
        "",
        f"Gerado em {gerado_em} — janela de {dias} dias (feedback geral é acumulado).",
        "",
        "## Resumo de feedback",
        "",
        f"- Interações: {resumo.get('total_interacoes', 0)}",
        f"- Positivos: {resumo.get('positivos', 0)}",
        f"- Negativos: {resumo.get('negativos', 0)}",
        f"- Sem avaliação: {resumo.get('sem_feedback', 0)}",
        f"- Taxa de aprovação: {resumo.get('taxa_aprovacao_pct', 0)}%",
        "",
        "## Por modo",
        "",
        *_tabela_md(por_modo, ["modo", "interacoes", "positivos", "negativos"]),
        "",
        "## Por canal",
        "",
        *_tabela_md(por_canal, ["canal", "interacoes", "positivos", "negativos"]),
        "",
        "## Avaliação automática (eval)",
        "",
    ]
    if baseline:
        delta = baseline.get("delta")
        extra = f" (delta {delta:+d} vs rodada anterior)" if isinstance(delta, int) else ""
        linhas.append(
            f"- Último baseline {baseline['run']}: "
            f"{baseline['aprovados']}/{baseline['total']} aprovados{extra}"
        )
    else:
        linhas.append("- Nenhuma rodada de avaliação encontrada (rode evals/run_eval.py).")
    linhas += ["", "## Dúvidas pendentes", ""]
    if erro_duvidas:
        linhas.append("Não foi possível apurar as dúvidas pendentes nesta geração.")
    elif duvidas:
        for duvida in duvidas:
            linhas.append(f"- [{duvida.origem}] {duvida.pergunta}")
    else:
        linhas.append("Nenhuma dúvida pendente. 🎉")
    return "\n".join(linhas) + "\n"


def gerar_relatorio_pdf(texto_md: str) -> bytes:
    """PDF simples (fonte monoespaçada) a partir do relatório em markdown."""
    import textwrap

    import fitz

    linhas_quebradas: list[str] = []
    for linha in texto_md.splitlines():
        linhas_quebradas.extend(textwrap.wrap(linha, width=95) or [""])

    doc = fitz.open()
    por_pagina = 52
    for inicio in range(0, max(len(linhas_quebradas), 1), por_pagina):
        pagina = doc.new_page()  # A4 595x842pt
        y = 50.0
        for linha in linhas_quebradas[inicio : inicio + por_pagina]:
            pagina.insert_text((40, y), linha, fontname="cour", fontsize=9)
            y += 14
    conteudo = doc.tobytes()
    doc.close()
    return bytes(conteudo)


BACKUPS_DIR = REPO_ROOT / "dashboard" / "backups"
EMBEDDING_MODEL = "text-embedding-3-small"
CONTEXT_MODEL = "gpt-4o-mini"
INSERT_BATCH = 100  # linhas por INSERT (embeddings são grandes; evita estourar payload)
EMBED_BATCH = 128  # textos por chamada de embedding (evita estourar teto de tokens/req)
LOTES_ANTIGOS: dict[str, dict[str, Any]] = {
    "manual": {"id_min": 977, "id_max": 1677, "data_prefixo": "2026-05-28"},
    "api": {"id_min": 6, "id_max": 365, "data_prefixo": "2026-04-14"},
}


def carregar_mapa_instabilidade(reports_dir: Path) -> dict[str, Any] | None:
    arquivos = sorted(reports_dir.glob("instabilidade-*.json"))
    if not arquivos:
        return None
    try:
        conteudo: dict[str, Any] = json.loads(arquivos[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return conteudo


def chunks_suspeitos(mapa: dict[str, Any]) -> list[dict[str, Any]]:
    """Chunks dos casos instáveis (indice > 0), deduplicados por trecho."""
    vistos: set[str] = set()
    suspeitos: list[dict[str, Any]] = []
    for caso in mapa.get("casos") or []:
        if float(caso.get("indice") or 0) <= 0:
            continue
        for chunk in caso.get("chunks") or []:
            trecho = str(chunk.get("trecho") or "")
            if not trecho or trecho in vistos:
                continue
            vistos.add(trecho)
            suspeitos.append(
                {
                    "caso_id": str(caso.get("id")),
                    "ref": str(chunk.get("ref") or ""),
                    "data": str(chunk.get("data") or ""),
                    "trecho": trecho,
                    "score_busca": chunk.get("score_busca"),
                }
            )
    return suspeitos


def mapa_sem_ref(suspeitos: list[dict[str, Any]]) -> bool:
    """True quando o mapa veio de uma versão antiga do detector (chunks sem `ref`).

    Sem `ref` não há como localizar o chunk em documents — o mapa precisa ser
    regerado rodando evals/detectar_instabilidade.py.
    """
    return bool(suspeitos) and all(not str(s.get("ref") or "").strip() for s in suspeitos)


def classificar_idade(data_iso: str) -> str:
    """Rótulo visual: chunks de jul/2026 em diante são 'curado', o resto 'manual'."""
    try:
        dia = date.fromisoformat(str(data_iso)[:10])
    except ValueError:
        return "manual"
    return "curado" if dia >= date(2026, 7, 1) else "manual"


def _trecho_normalizado(content: str) -> str:
    """Reproduz o trecho do detector: primeiros 120 chars com espaços colapsados."""
    return " ".join(str(content)[:120].split())


def _redigir_email(texto: str) -> str:
    """Mascara emails, igual ao detector faz ao montar o trecho do mapa."""
    return re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", texto)


def resolver_chunk(cliente: Any, ref: str, trecho: str) -> list[dict[str, Any]]:
    """Acha a(s) linha(s) de documents do chunk: narrowa por fonte+chunk_index e
    desempata pelo trecho normalizado (o ref sozinho não é único)."""
    fonte, _, indice = ref.rpartition("#")
    if not fonte:
        return []
    resposta = (
        cliente.table("documents")
        .select("id,content,metadata")
        .eq("metadata->>fonte", fonte)
        .eq("metadata->>chunk_index", indice)
        .execute()
    )
    achados: list[dict[str, Any]] = []
    for linha in resposta.data or []:
        if _redigir_email(_trecho_normalizado(str(linha.get("content") or ""))) == trecho:
            achados.append(
                {
                    "id": linha["id"],
                    "content": str(linha.get("content") or ""),
                    "metadata": linha.get("metadata") or {},
                }
            )
    return achados


def buscar_documento(cliente: Any, chunk_id: int) -> dict[str, Any] | None:
    resposta = cliente.table("documents").select("*").eq("id", chunk_id).execute()
    linhas = resposta.data or []
    return dict(linhas[0]) if linhas else None


def montar_backup(linha: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": linha.get("id"),
        "content": linha.get("content"),
        "embedding": linha.get("embedding"),
        "metadata": linha.get("metadata"),
        "backup_em": datetime.now(UTC).isoformat(),
    }


def salvar_backup(caminho: Path, backup: dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(backup, ensure_ascii=False) + "\n")


def reembed(openai_client: Any, texto: str) -> list[float]:
    resposta = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=texto)
    return list(resposta.data[0].embedding)


def parse_ocr_response(payload: dict[str, Any]) -> str:
    """Junta o markdown das páginas do retorno do Mistral OCR."""
    paginas = payload.get("pages") or []
    return "\n\n".join(str(p.get("markdown") or "") for p in paginas).strip()


def montar_raw(nome: str, fonte_alvo: str, tipo: str, texto: str) -> dict[str, Any]:
    """Monta a linha de raw_documents (status inicial 'cru')."""
    return {
        "nome": nome.strip(),
        "fonte_alvo": fonte_alvo.strip(),
        "tipo": tipo,
        "texto": texto,
        "n_chars": len(texto),
        "status": "cru",
    }


def extrair_texto(
    cliente: Any, mistral_key: str, arquivo_bytes: bytes, tipo: str, nome_arquivo: str
) -> str:
    """Texto cru do arquivo. 'texto' decodifica; 'pdf' faz OCR via Mistral pela Files
    API: sobe o arquivo (multipart, aguenta grande), pega uma URL assinada, e o OCR só
    referencia essa URL (o Mistral busca o próprio arquivo — rápido, requisição pequena).
    `cliente` fica na assinatura por simetria com a camada; não é usado aqui."""
    if tipo in ("texto", "api"):
        return arquivo_bytes.decode("utf-8", errors="replace")

    cabecalho = {"Authorization": f"Bearer {mistral_key}"}
    envio = httpx.post(
        "https://api.mistral.ai/v1/files",
        headers=cabecalho,
        files={"file": (nome_arquivo, arquivo_bytes, "application/pdf")},
        data={"purpose": "ocr"},
        timeout=300.0,
    )
    envio.raise_for_status()
    file_id = envio.json()["id"]

    assinada = httpx.get(
        f"https://api.mistral.ai/v1/files/{file_id}/url",
        headers=cabecalho,
        params={"expiry": 1},
        timeout=60.0,
    )
    assinada.raise_for_status()
    url = assinada.json()["url"]

    ocr = httpx.post(
        "https://api.mistral.ai/v1/ocr",
        headers=cabecalho,
        json={
            "model": "mistral-ocr-latest",
            "document": {"type": "document_url", "document_url": url},
        },
        timeout=300.0,
    )
    ocr.raise_for_status()
    return parse_ocr_response(ocr.json())


def salvar_raw(cliente: Any, linha: dict[str, Any]) -> None:
    cliente.table("raw_documents").insert(linha).execute()


def listar_raw(cliente: Any) -> list[dict[str, Any]]:
    resposta = (
        cliente.table("raw_documents")
        .select("id, nome, fonte_alvo, tipo, n_chars, status, criado_em")
        .order("criado_em", desc=True)
        .execute()
    )
    return list(resposta.data or [])


def buscar_raw(cliente: Any, raw_id: int) -> dict[str, Any]:
    resposta = cliente.table("raw_documents").select("*").eq("id", raw_id).execute()
    linhas = resposta.data or []
    if not linhas:
        raise RuntimeError(f"raw_documents id={raw_id} não encontrado")
    return dict(linhas[0])


def lote_para_backup(cliente: Any, id_min: int, id_max: int) -> list[dict[str, Any]]:
    resposta = (
        cliente.table("documents")
        .select("id,content,embedding,metadata")
        .gte("id", id_min)
        .lte("id", id_max)
        .execute()
    )
    return list(resposta.data or [])


def reembed_lote(
    openai_client: Any, textos: list[str], *, batch: int = EMBED_BATCH
) -> list[list[float]]:
    """Embute em lotes para não estourar o teto de tokens por requisição da API."""
    vetores: list[list[float]] = []
    for offset in range(0, len(textos), batch):
        resposta = openai_client.embeddings.create(
            model=EMBEDDING_MODEL, input=textos[offset : offset + batch]
        )
        vetores.extend(list(dado.embedding) for dado in resposta.data)
    return vetores


def marcar_chunkado(cliente: Any, raw_id: int) -> None:
    cliente.table("raw_documents").update({"status": "chunkado"}).eq("id", raw_id).execute()


PROMPT_CONTEXTO = """Você indexa um manual do sistema Digisac para busca (RAG).
ÍNDICE DO MANUAL (headings): {outline}

SEÇÃO onde o trecho está ({breadcrumb}):
\"\"\"{secao}\"\"\"

TRECHO a situar:
\"\"\"{chunk}\"\"\"

Escreva UMA frase curta (máx 25 palavras), em português, que situe o trecho no manual \
para melhorar a recuperação: de que recurso/tela ele fala e em que contexto. NÃO invente \
nenhum fato novo; apenas localize. Responda só a frase, sem aspas."""


def montar_linhas_documents(
    chunks_texto: list[str],
    embeddings: list[list[float]],
    fonte_alvo: str,
    raw_id: int,
    data_iso: str,
    *,
    fonte: str = "discord-upload",
    tipo_chunk: str = "semantico",
    metadados_extra: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if len(chunks_texto) != len(embeddings):
        raise ValueError("chunks_texto e embeddings precisam ter o mesmo tamanho")
    if metadados_extra is not None and len(metadados_extra) != len(chunks_texto):
        raise ValueError("metadados_extra precisa ter o mesmo tamanho que chunks_texto")
    linhas: list[dict[str, Any]] = []
    for indice, (texto, embedding) in enumerate(zip(chunks_texto, embeddings, strict=True)):
        metadata = {
            "data": data_iso,
            "fonte": fonte,
            "fonte_alvo": fonte_alvo,
            "raw_id": raw_id,
            "tipo_chunk": tipo_chunk,
            "chunk_index": indice,
        }
        if metadados_extra is not None:
            metadata.update(metadados_extra[indice])
        linhas.append({"content": texto, "embedding": embedding, "metadata": metadata})
    return linhas


def _e_rate_limit(erro: Exception) -> bool:
    return type(erro).__name__ == "RateLimitError" or getattr(erro, "status_code", None) == 429


def contextualizar_chunks(
    openai_client: Any,
    chunks: list[dict[str, Any]],
    outline: str,
    *,
    model: str = CONTEXT_MODEL,
    max_tentativas: int = 6,
) -> list[str]:
    """Prepend de UMA frase de contexto (gerada por LLM) a cada chunk, antes do embedding.
    Retenta com backoff exponencial em rate limit (429) para não quebrar no meio do lote."""
    finais: list[str] = []
    for chunk in chunks:
        mensagem = PROMPT_CONTEXTO.format(
            outline=outline,
            breadcrumb=chunk["breadcrumb"],
            secao=chunk["secao"][:2500],
            chunk=chunk["corpo"],
        )
        resposta = None
        for tentativa in range(max_tentativas):
            try:
                resposta = openai_client.chat.completions.create(
                    model=model,
                    temperature=0,
                    max_tokens=80,
                    messages=[{"role": "user", "content": mensagem}],
                )
                break
            except Exception as erro:
                if _e_rate_limit(erro) and tentativa < max_tentativas - 1:
                    time.sleep(min(2**tentativa, 30))
                    continue
                raise
        assert resposta is not None  # o loop acima atribui `resposta` ou levanta
        contexto = (resposta.choices[0].message.content or "").strip()
        finais.append(f"{contexto}\n\n{chunk['texto']}" if contexto else chunk["texto"])
    return finais


def publicar_lote(
    cliente: Any, openai_client: Any, raw_id: int, fonte_alvo: str, backups_dir: Path
) -> dict[str, Any]:
    """Troca segura: publica o manual re-chunkado e substitui o lote antigo.
    Ordem que nunca deixa o manual ausente: captura antigo → insere novo →
    confere → backup → apaga antigo → marca raw."""
    if cliente is None or openai_client is None:
        raise RuntimeError("Supabase e OpenAI devem estar configurados para publicar")

    lote = LOTES_ANTIGOS[fonte_alvo]
    raw = buscar_raw(cliente, raw_id)
    texto = raw["texto"]

    # 0) captura o lote antigo (só leitura) antes de mexer em qualquer coisa
    antigos = lote_para_backup(cliente, lote["id_min"], lote["id_max"])

    # 1) constrói os chunks novos — ramo por tipo do cru
    data_iso = datetime.now(UTC).isoformat()
    if raw.get("tipo") == "api":
        endpoints = chunk_postman(texto)
        finais = [e["texto"] for e in endpoints]
        embeddings = reembed_lote(openai_client, finais)
        extras = [{"recurso": e["recurso"], "metodo": e["metodo"]} for e in endpoints]
        linhas = montar_linhas_documents(
            finais,
            embeddings,
            fonte_alvo,
            raw_id,
            data_iso,
            fonte="postman",
            tipo_chunk="endpoint",
            metadados_extra=extras,
        )
    else:
        chunks = chunk_contextual_estrutural(texto)
        outline = construir_indice(texto)
        finais = contextualizar_chunks(openai_client, chunks, outline)
        embeddings = reembed_lote(openai_client, finais)
        linhas = montar_linhas_documents(finais, embeddings, fonte_alvo, raw_id, data_iso)

    if not linhas or any(not linha["content"].strip() for linha in linhas):
        raise ValueError("Nenhum chunk utilizável — publicação abortada antes de alterar a base")

    # 2) insere em lotes (embeddings são grandes) e confere ANTES de apagar nada
    n_inseridos = 0
    for offset in range(0, len(linhas), INSERT_BATCH):
        lote_linhas = linhas[offset : offset + INSERT_BATCH]
        inseridos = cliente.table("documents").insert(lote_linhas).execute()
        n_inseridos += len(inseridos.data or [])
    if n_inseridos != len(linhas):
        raise RuntimeError(
            f"INSERT afetou {n_inseridos} de {len(linhas)} — abortado antes de apagar o lote antigo"
        )

    # 3) backup dos antigos
    backup_path = Path(backups_dir) / f"documents-{fonte_alvo}-{data_iso[:10]}.jsonl"
    for row in antigos:
        salvar_backup(backup_path, montar_backup(row))

    # 4) apaga os antigos pelos ids exatos
    ids = [row["id"] for row in antigos]
    aviso: str | None = None
    if ids:
        apagados = cliente.table("documents").delete().in_("id", ids).execute()
        n_apagados = len(apagados.data or [])
        if n_apagados != len(ids):
            aviso = f"Apagados {n_apagados} de {len(ids)} chunks antigos — verifique duplicados."

    # 5) marca o cru como chunkado
    marcar_chunkado(cliente, raw_id)

    return {
        "inseridos": n_inseridos,
        "apagados": len(ids),
        "backup_path": str(backup_path),
        "aviso": aviso,
    }


def atualizar_chunk(
    cliente: Any, chunk_id: int, novo_conteudo: str, novo_embedding: list[float]
) -> None:
    resposta = (
        cliente.table("documents")
        .update({"content": novo_conteudo, "embedding": novo_embedding})
        .eq("id", chunk_id)
        .execute()
    )
    if not (resposta.data or []):
        raise RuntimeError(f"UPDATE nao afetou nenhuma linha (id {chunk_id} sumiu?)")
