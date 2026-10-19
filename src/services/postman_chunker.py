"""Chunker determinístico da Postman Collection: 1 endpoint = 1 chunk.
Nada de LLM — tudo derivado da collection, sem inferir comportamento de API."""

import json
import re
from typing import Any
from urllib.parse import parse_qsl


def _url_raw(url: Any) -> str:
    if isinstance(url, dict):
        return url.get("raw", "") or ""
    return url or ""


def _path_params(url_raw: str) -> list[str]:
    return [tok for tok in re.findall(r"\{\{(\w+)\}\}", url_raw) if tok != "URL"]


def _query_params(url_raw: str) -> list[str]:
    if "?" not in url_raw:
        return []
    querystring = url_raw.split("?", 1)[1]
    return [chave for chave, _ in parse_qsl(querystring, keep_blank_values=True)]


def _body_fields(body: Any) -> list[str]:
    if not isinstance(body, dict) or body.get("mode") != "raw":
        return []
    try:
        obj = json.loads(body.get("raw") or "")
    except (ValueError, TypeError):
        return []
    return list(obj.keys()) if isinstance(obj, dict) else []


def _montar_texto(
    recurso: str,
    nome: str,
    metodo: str,
    url_raw: str,
    path_params: list[str],
    query_params: list[str],
    body_fields: list[str],
) -> str:
    linhas = [
        f"Documentação da API Digisac — Recurso: {recurso}",
        f"Endpoint: {nome}",
        f"{metodo} {url_raw}".strip(),
    ]
    if path_params:
        linhas.append("Parâmetros de caminho: " + ", ".join(path_params))
    if query_params:
        linhas.append("Parâmetros de query: " + ", ".join(query_params))
    if body_fields:
        linhas.append("Corpo (campos): " + ", ".join(body_fields))
    return "\n".join(linhas)


def chunk_postman(json_text: str, *, excluir_topo: tuple[str, ...] = ("Populares",)) -> list[dict]:
    """Um chunk por endpoint. Pula containers de topo cujo nome contenha algum
    termo de `excluir_topo` (ex.: 'Populares', duplicatas). `recurso` = caminho de
    pastas ABAIXO do container de topo."""
    col = json.loads(json_text)
    chunks: list[dict] = []

    def anda(itens: list[dict], trilha: list[str]) -> None:
        for item in itens or []:
            nome = (item.get("name") or "").strip()
            if "item" in item:
                anda(item["item"], [*trilha, nome])
                continue
            req = item.get("request") or {}
            recurso = " > ".join(trilha) if trilha else "(raiz)"
            metodo = (req.get("method") or "").strip()
            url_raw = _url_raw(req.get("url"))
            texto = _montar_texto(
                recurso,
                nome,
                metodo,
                url_raw,
                _path_params(url_raw),
                _query_params(url_raw),
                _body_fields(req.get("body")),
            )
            chunks.append({"recurso": recurso, "metodo": metodo, "nome": nome, "texto": texto})

    for topo in col.get("item", []):
        nome_topo = (topo.get("name") or "").strip()
        if any(termo in nome_topo for termo in excluir_topo):
            continue
        if "item" in topo:
            anda(topo["item"], [])
    return chunks
