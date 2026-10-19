import re

from src.logger import get_logger

logger = get_logger(__name__)
HEADING_RE = re.compile(r"(?=^#{1,3}\s)", re.MULTILINE)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _split_oversized(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    sentences = [sentence.strip() for sentence in SENTENCE_RE.split(text) if sentence.strip()]
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            step = max(1, max_chars - overlap_chars)
            chunks.extend(
                sentence[start : start + max_chars].strip()
                for start in range(0, len(sentence), step)
                if sentence[start : start + max_chars].strip()
            )
            continue

        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            overlap = current[-overlap_chars:].lstrip() if overlap_chars else ""
            current = f"{overlap} {sentence}".strip()
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks


def chunk_text(
    text: str,
    *,
    max_chars: int = 1_000,
    min_chars: int = 30,
    overlap_chars: int = 120,
    inter_overlap_chars: int = 0,
    merge_min_chars: int = 0,
) -> list[str]:
    """Split text by headings and paragraphs while bounding every chunk.

    The previous implementation accidentally contained JavaScript regex syntax,
    which made this entire module impossible to import.
    """

    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    if max_chars <= 0 or min_chars < 0 or overlap_chars < 0:
        raise ValueError("Chunk sizes must be non-negative and max_chars must be positive")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")
    if inter_overlap_chars < 0 or inter_overlap_chars >= max_chars:
        raise ValueError("inter_overlap_chars must be >= 0 and smaller than max_chars")
    if merge_min_chars < 0:
        raise ValueError("merge_min_chars must be non-negative")

    sections = [section.strip() for section in HEADING_RE.split(normalized) if section.strip()]
    units: list[str] = []
    for section in sections:
        units.extend(part.strip() for part in re.split(r"\n\s*\n", section) if part.strip())

    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for unit in units:
        if len(unit) > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current, current_size = [], 0
            chunks.extend(_split_oversized(unit, max_chars, overlap_chars))
            continue

        additional = len(unit) + (2 if current else 0)
        if current and current_size + additional > max_chars:
            flushed = "\n\n".join(current)
            chunks.append(flushed)
            tail = ""
            if inter_overlap_chars:
                tail = flushed[-inter_overlap_chars:]
                space = tail.find(" ")
                tail = (tail[space + 1 :] if space != -1 else tail).strip()
            if tail:
                current, current_size = [tail, unit], len(tail) + len(unit) + 2
            else:
                current, current_size = [unit], len(unit)
        else:
            current.append(unit)
            current_size += additional

    if current:
        chunks.append("\n\n".join(current))

    if merge_min_chars and len(chunks) >= 2 and len(chunks[-1]) < merge_min_chars:
        chunks[-2] = chunks[-2] + "\n\n" + chunks[-1]
        chunks.pop()

    result = [chunk for chunk in chunks if len(chunk) >= min_chars]
    if not result and len(normalized) < min_chars:
        result = [normalized]
    logger.info("Chunking completed", extra={"extras": {"chars": len(text), "chunks": len(result)}})
    return result


def rechunk_manual(texto: str) -> list[str]:
    """Chunking para re-ingestão do manual: agrupa até ~1000 chars com overlap de 150
    e funde um final < 400 no anterior. Remove separadores de página soltos ('---'
    que o 'Extrair texto' do n8n insere entre páginas)."""
    sem_separadores = re.sub(r"(?m)^\s*-{3,}\s*$", "", texto)
    return chunk_text(
        sem_separadores,
        max_chars=1_000,
        min_chars=1,
        overlap_chars=150,
        inter_overlap_chars=150,
        merge_min_chars=400,
    )


def limpar_ocr(texto: str) -> str:
    """Remove 'furniture' de OCR: nº de página solto, data/hora de impressão,
    rodapé 'Manual Digisac' e 'Site: http…', imagens ![..](..) e separadores '---'."""
    linhas = []
    for linha in texto.split("\n"):
        despido = linha.strip()
        if re.fullmatch(r"\d{1,4}", despido):
            continue
        if re.fullmatch(r"\d{2}/\d{2}/\d{4},?\s*\d{2}:\d{2}", despido):
            continue
        if despido == "Manual Digisac":
            continue
        if re.fullmatch(r"Site:\s*https?://\S+", despido):
            continue
        linhas.append(linha)
    texto = "\n".join(linhas)
    texto = re.sub(r"(?m)^\s*-{3,}\s*$", "", texto)
    texto = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def construir_indice(texto: str, *, max_chars: int = 3_000) -> str:
    """Índice do documento a partir dos headings (grátis, sem LLM)."""
    limpo = limpar_ocr(texto)
    heads = re.findall(r"(?m)^(#{1,3})\s+(.*)$", limpo)
    return " | ".join(f"{marca} {titulo.strip()}" for marca, titulo in heads)[:max_chars]


def chunk_contextual_estrutural(
    texto: str, *, max_chars: int = 1_000, overlap_chars: int = 150, merge_min_chars: int = 400
) -> list[dict]:
    """Chunka respeitando seções; prepend do breadcrumb (H1 > H2 > H3) em CADA chunk.
    Heading sem corpo não vira chunk — é dobrado no breadcrumb do próximo (mata cacos)."""
    limpo = limpar_ocr(texto)
    partes = re.split(r"(?m)^(#{1,3}\s+.*)$", limpo)
    secoes: list[tuple[str | None, int, str]] = []
    if partes[0].strip():
        secoes.append((None, 0, partes[0].strip()))
    for i in range(1, len(partes), 2):
        head = partes[i].strip()
        corpo = (partes[i + 1] if i + 1 < len(partes) else "").strip()
        nivel = len(head) - len(head.lstrip("#"))
        secoes.append((head, nivel, corpo))

    trilha: dict[int, str] = {}
    saida: list[dict] = []
    for head, nivel, corpo in secoes:
        if head:
            trilha[nivel] = head
            for maior in [n for n in trilha if n > nivel]:
                del trilha[maior]
        breadcrumb = " > ".join(trilha[n] for n in sorted(trilha)) if trilha else ""
        if not corpo:
            continue
        reserva = len(breadcrumb) + 2
        sub = chunk_text(
            corpo,
            max_chars=max(200, max_chars - reserva),
            min_chars=1,
            overlap_chars=overlap_chars,
            inter_overlap_chars=overlap_chars,
            merge_min_chars=merge_min_chars,
        )
        for pedaco in sub:
            final = f"{breadcrumb}\n\n{pedaco}" if breadcrumb else pedaco
            saida.append(
                {"breadcrumb": breadcrumb, "secao": corpo, "corpo": pedaco, "texto": final}
            )
    return saida


class ChunkerService:
    MAX_CHUNK_SIZE = 1_000
    MIN_CHUNK_SIZE = 30

    @staticmethod
    def chunk_semantic(text: str) -> list[str]:
        return chunk_text(
            text,
            max_chars=ChunkerService.MAX_CHUNK_SIZE,
            min_chars=ChunkerService.MIN_CHUNK_SIZE,
        )
