"""Secure document ingestion for text and Discord-hosted attachments."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI
from supabase import create_client

from src.config import Settings, get_settings
from src.logger import get_logger
from src.services import curadoria
from src.services.chunker import chunk_text

logger = get_logger(__name__)

PDF_MIMES = {"application/pdf"}
# Acima disso a correcao volta a ser fatiada: um chunk unico gigante estoura a
# janela do modelo de embedding e recupera mal. Na pratica uma correcao de
# analista fica na casa de 1k chars.
MAX_CURADORIA_CHARS = 6_000
TEXT_MIMES = {"text/plain", "text/markdown"}
EMBED_BATCH = 100
INSERT_BATCH = 100


class IngestionValidationError(ValueError):
    pass


class IngestionService:
    def __init__(
        self,
        config: Settings | None = None,
        *,
        openai_client: AsyncOpenAI | None = None,
        supabase_client: Any = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.config = config or get_settings()
        self._owns_openai_client = openai_client is None
        self.openai = openai_client
        if self.openai is None and self.config.openai_key:
            self.openai = AsyncOpenAI(
                api_key=self.config.openai_key,
                timeout=self.config.openai_timeout_seconds,
                max_retries=self.config.openai_max_retries,
            )

        self.supabase = supabase_client
        if self.supabase is None and self.config.supabase_url and self.config.database_key:
            self.supabase = create_client(self.config.supabase_url, self.config.database_key)
        mistral_secret = self.config.mistral_api_key
        self.mistral_key = mistral_secret.get_secret_value() if mistral_secret else None
        self._owns_http_client = http_client is None
        self.http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.ingest_download_timeout_seconds),
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        if self.openai is not None and self._owns_openai_client:
            await self.openai.close()
        if self._owns_http_client:
            await self.http.aclose()

    async def ingest(
        self,
        content: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        curated: bool = False,
    ) -> dict[str, Any]:
        if self.openai is None or self.supabase is None:
            raise RuntimeError("OpenAI and Supabase must be configured for ingestion")

        attachments = attachments or []
        if curated and (attachments or not content or not curadoria.metadata_curadoria(content)):
            raise IngestionValidationError(
                "Curation requires explicit correction text without attachments"
            )
        if len(attachments) > self.config.ingest_max_attachments:
            raise IngestionValidationError("Too many attachments")

        sources: list[dict[str, Any]] = []
        errors: list[str] = []
        texts: list[tuple[str, str]] = []
        if content and content.strip():
            texts.append((content.strip(), "discord-text"))

        for attachment in attachments:
            url = str(attachment.get("url") or "")
            filename = str(attachment.get("filename") or "attachment")[:255]
            content_type = str(
                attachment.get("contentType") or attachment.get("content_type") or ""
            ).lower()
            try:
                extracted = await self._extract_attachment(url, content_type, filename)
                if extracted.strip():
                    texts.append((extracted, filename))
                else:
                    errors.append(f"{filename}: no extractable text")
            except IngestionValidationError:
                raise
            except Exception:
                logger.exception("Attachment extraction failed")
                errors.append(f"{filename}: extraction failed")

        total_chars = sum(len(text) for text, _ in texts)
        if total_chars > self.config.ingest_max_total_chars:
            raise IngestionValidationError(
                f"Extracted text exceeds {self.config.ingest_max_total_chars} characters"
            )
        if not texts:
            return {
                "chunks_created": 0,
                "total_chars": 0,
                "sources": [],
                "errors": errors or ["Nothing to ingest"],
            }

        chunks: list[str] = []
        chunk_sources: list[str] = []
        chunk_extras: list[dict[str, Any]] = []
        for text, source in texts:
            # Correcao de analista entra inteira: fatiar deixa a segunda metade
            # orfa (sem o "Pergunta:"), e o orfao volta na busca como se fosse
            # manual comum, contradizendo a propria correcao de onde saiu.
            extra = (
                curadoria.metadata_curadoria(text) if curated and source == "discord-text" else {}
            )
            if extra and len(text) <= MAX_CURADORIA_CHARS:
                source_chunks = [text.strip()]
            else:
                source_chunks = chunk_text(text)
            chunks.extend(source_chunks)
            chunk_sources.extend([source] * len(source_chunks))
            chunk_extras.extend([extra] * len(source_chunks))
            sources.append({"source": source, "chars": len(text), "chunks": len(source_chunks)})

        if not chunks:
            return {
                "chunks_created": 0,
                "total_chars": total_chars,
                "sources": sources,
                "errors": [*errors, "No chunks generated"],
            }

        embeddings = await self._embed_batch(chunks)
        if len(embeddings) != len(chunks):
            raise RuntimeError("Embedding response length did not match chunk count")

        timestamp = datetime.now(UTC).isoformat()
        rows: list[dict[str, Any]] = []
        for index, (chunk, embedding, source, extra) in enumerate(
            zip(chunks, embeddings, chunk_sources, chunk_extras, strict=True)
        ):
            metadata: dict[str, Any] = {
                "data": timestamp,
                "fonte": source,
                "tipo_chunk": "semantico",
                "chunk_index": index,
            }
            metadata.update(extra)
            rows.append({"content": chunk, "embedding": embedding, "metadata": metadata})

        inserted = 0
        curadorias_novas: list[tuple[str, str]] = []
        for offset in range(0, len(rows), INSERT_BATCH):
            batch = rows[offset : offset + INSERT_BATCH]
            try:
                response = await asyncio.to_thread(self._insert_documents, batch)
                gravadas = response.data or []
                inserted += len(gravadas)
                for enviada, gravada in zip(batch, gravadas, strict=False):
                    pergunta_norm = enviada["metadata"].get("pergunta_norm")
                    id_gravado = gravada.get("id")
                    if pergunta_norm and id_gravado is not None:
                        curadorias_novas.append((str(pergunta_norm), str(id_gravado)))
            except Exception:
                logger.exception("Document batch insert failed")
                errors.append(f"batch {offset // INSERT_BATCH}: insert failed")

        # A correcao nova aposenta a anterior da mesma pergunta. Sem isso as duas
        # convivem no topo da busca e a geracao concilia versoes que se
        # contradizem — a correcao "quase" pega, mas nao exatamente.
        ids_desta_ingestao = {id_ for _, id_ in curadorias_novas}
        for pergunta_norm, novo_id in curadorias_novas:
            try:
                await self._aposentar_curadorias_anteriores(
                    pergunta_norm, novo_id, ids_desta_ingestao
                )
            except Exception:
                logger.exception("Superseding previous curation failed")
                errors.append(f"supersede {pergunta_norm}: failed")

        return {
            "chunks_created": inserted,
            "total_chars": total_chars,
            "sources": sources,
            "errors": errors,
        }

    def _insert_documents(self, batch: list[dict[str, Any]]) -> Any:
        return self.supabase.table("documents").insert(batch).execute()

    async def _aposentar_curadorias_anteriores(
        self, pergunta_norm: str, novo_id: str, ids_desta_ingestao: set[str]
    ) -> None:
        """Marca as correcoes antigas da mesma pergunta como substituidas.

        Marca em vez de apagar: da para auditar o que o bot respondia antes e
        reverter. Quem tira da busca e o `search_hybrid`.
        """
        anteriores = await asyncio.to_thread(self._buscar_curadorias, pergunta_norm)
        agora = datetime.now(UTC).isoformat()
        for linha in anteriores:
            id_anterior = str(linha.get("id"))
            metadata = dict(linha.get("metadata") or {})
            if id_anterior in ids_desta_ingestao or metadata.get("substituido_por"):
                continue
            metadata["substituido_por"] = str(novo_id)
            metadata["substituido_em"] = agora
            await asyncio.to_thread(self._atualizar_metadata, id_anterior, metadata)
            logger.info(
                "Curation superseded",
                extra={"extras": {"anterior": id_anterior, "nova": novo_id}},
            )

    def _buscar_curadorias(self, pergunta_norm: str) -> list[dict[str, Any]]:
        response = (
            self.supabase.table("documents")
            .select("id,metadata")
            .eq("metadata->>pergunta_norm", pergunta_norm)
            .execute()
        )
        return list(response.data or [])

    def _atualizar_metadata(self, doc_id: str, metadata: dict[str, Any]) -> Any:
        return (
            self.supabase.table("documents")
            .update({"metadata": metadata})
            .eq("id", doc_id)
            .execute()
        )

    def _validate_attachment_url(self, url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        allowed = {item.lower().rstrip(".") for item in self.config.ingest_allowed_hosts}
        if parsed.scheme != "https" or not host or host not in allowed:
            raise IngestionValidationError("Attachment host is not allowed")
        if parsed.username or parsed.password or (parsed.port not in (None, 443)):
            raise IngestionValidationError("Attachment URL contains forbidden authority data")
        return url

    async def _download_attachment(self, url: str) -> tuple[bytes, str]:
        safe_url = self._validate_attachment_url(url)
        downloaded = bytearray()
        async with self.http.stream("GET", safe_url) as response:
            if response.is_redirect:
                raise IngestionValidationError("Attachment redirects are not allowed")
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > self.config.ingest_max_file_bytes:
                raise IngestionValidationError("Attachment is too large")
            async for chunk in response.aiter_bytes():
                downloaded.extend(chunk)
                if len(downloaded) > self.config.ingest_max_file_bytes:
                    raise IngestionValidationError("Attachment is too large")
            response_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        return bytes(downloaded), response_type

    async def _extract_attachment(self, url: str, content_type: str, filename: str) -> str:
        data, response_type = await self._download_attachment(url)
        effective_type = response_type or content_type
        is_pdf = effective_type in PDF_MIMES or filename.lower().endswith(".pdf")
        is_text = effective_type in TEXT_MIMES or filename.lower().endswith((".txt", ".md"))

        if is_pdf:
            text = await asyncio.to_thread(self._extract_pdf_pymupdf, data)
            if text.strip():
                return text
            if self.mistral_key:
                return await self._extract_pdf_mistral(url)
            return ""
        if is_text:
            return data.decode("utf-8", errors="replace")
        raise IngestionValidationError(
            f"Unsupported attachment type: {effective_type or 'unknown'}"
        )

    def _extract_pdf_pymupdf(self, pdf_bytes: bytes) -> str:
        import fitz

        try:
            with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
                if document.page_count > self.config.ingest_max_pdf_pages:
                    raise IngestionValidationError("PDF has too many pages")
                return "\n\n".join(page.get_text() for page in document)
        except IngestionValidationError:
            raise
        except Exception:
            logger.exception("PDF extraction failed")
            return ""

    async def _extract_pdf_mistral(self, url: str) -> str:
        from mistralai import Mistral

        def process() -> str:
            client = Mistral(api_key=self.mistral_key)
            response = client.ocr.process(
                model="mistral-ocr-latest",
                document={"type": "document_url", "document_url": url},
            )
            return "\n\n".join(
                markdown for page in response.pages if (markdown := getattr(page, "markdown", None))
            )

        try:
            return await asyncio.to_thread(process)
        except Exception:
            logger.exception("Mistral OCR failed")
            return ""

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self.openai is None:
            raise RuntimeError("OpenAI is not configured")
        embeddings: list[list[float]] = []
        for offset in range(0, len(texts), EMBED_BATCH):
            response = await self.openai.embeddings.create(
                model=self.config.embedding_model,
                input=texts[offset : offset + EMBED_BATCH],
            )
            embeddings.extend(item.embedding for item in response.data)
        return embeddings
