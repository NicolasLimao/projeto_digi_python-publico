"""Curadoria: respostas revisadas por analista têm autoridade sobre o manual.

Uma correção entra na base como um bloco `Pergunta: … / Resposta oficial
validada pelo analista: …`. Sem marcação, esse bloco vira só mais um trecho
entre dez e a geração concilia versões que se contradizem — foi assim que uma
correção ficou "perto, mas não exata". Aqui ficam as regras que identificam a
curadoria e a chave que liga uma correção nova à que ela substitui.

A autoridade vem SEMPRE do metadata, nunca do conteúdo: conteúdo é dado não
confiável e um texto ingerido não pode se autopromover escrevendo o marcador.
"""

import re
import unicodedata
from typing import Any

MARCADOR = "Resposta oficial validada pelo analista:"
TIPO = "curadoria"

_BLOCO_RE = re.compile(
    rf"^\s*Pergunta:\s*(?P<pergunta>.+?)\s*{re.escape(MARCADOR)}",
    re.DOTALL | re.IGNORECASE,
)
_PONTUACAO_RE = re.compile(r"[^\w\s]", re.UNICODE)
_ESPACO_RE = re.compile(r"\s+")


def eh_texto_curado(texto: str) -> bool:
    """O texto bruto que chega na ingestão é uma correção de analista?"""
    return MARCADOR.lower() in (texto or "").lower()


def extrair_pergunta(texto: str) -> str | None:
    """A pergunta que a correção responde, ou None se o texto não for curadoria."""
    if not eh_texto_curado(texto):
        return None
    encontrado = _BLOCO_RE.search(texto)
    return encontrado.group("pergunta").strip() if encontrado else None


def normalizar_pergunta(pergunta: str) -> str:
    """Chave estável para casar duas correções da MESMA pergunta.

    Ignora acento, caixa, pontuação e espaço: quem responde de novo raramente
    recola a pergunta byte a byte igual à da vez anterior.
    """
    sem_acento = "".join(
        letra
        for letra in unicodedata.normalize("NFKD", pergunta or "")
        if not unicodedata.combining(letra)
    )
    return _ESPACO_RE.sub(" ", _PONTUACAO_RE.sub(" ", sem_acento.lower())).strip()


def metadata_curadoria(texto: str) -> dict[str, Any]:
    """Metadata que marca a linha como curadoria; vazio para texto comum."""
    pergunta = extrair_pergunta(texto)
    if pergunta is None:
        return {}
    return {"tipo": TIPO, "pergunta_norm": normalizar_pergunta(pergunta)}


def eh_documento_curado(metadata: Any) -> bool:
    """Documento recuperado tem autoridade de curadoria?"""
    return isinstance(metadata, dict) and metadata.get("tipo") == TIPO


def foi_substituido(metadata: Any) -> bool:
    """Correção antiga que já perdeu para uma resposta mais nova."""
    return isinstance(metadata, dict) and bool(metadata.get("substituido_por"))
