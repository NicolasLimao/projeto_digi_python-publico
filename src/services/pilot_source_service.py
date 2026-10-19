"""Read-only, bounded source capture for the manual Jev pilot."""

import asyncio
from typing import Any

from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

from src.config import Settings
from src.models.schemas import Document


class PilotSourceError(RuntimeError):
    pass


class PilotSourceService:
    def __init__(self, config: Settings, *, client: Any = None):
        if not config.supabase_url or not config.supabase_service_role_key:
            raise PilotSourceError("Pilot requires Supabase backend configuration")
        self._owns_client = client is None
        self.client = client or create_client(
            config.supabase_url,
            config.supabase_service_role_key.get_secret_value(),
            options=SyncClientOptions(
                postgrest_client_timeout=10, persist_session=False, auto_refresh_token=False
            ),
        )

    async def capture(self) -> dict[str, list[dict[str, Any]]]:
        async def history(feedback: str | None) -> list[dict[str, Any]]:
            def read() -> list[dict[str, Any]]:
                query = self.client.table("historico_digi").select(
                    "id,pergunta,resposta,modo,feedback,canal,timestamp,pergunta_reescrita,fontes"
                )
                query = (
                    query.is_("feedback", "null")
                    if feedback is None
                    else query.eq("feedback", feedback)
                )
                return list(query.order("timestamp", desc=True).limit(100).execute().data or [])

            return await asyncio.to_thread(read)

        async def corrections() -> list[dict[str, Any]]:
            return await asyncio.to_thread(
                lambda: list(
                    self.client.table("duvidas_respondidas")
                    .select("id,pergunta,resposta_correta,ingerida,chunks_criados,criado_em")
                    .order("criado_em", desc=True)
                    .limit(100)
                    .execute()
                    .data
                    or []
                )
            )

        try:
            results = await asyncio.gather(
                history("negativo"),
                history("positivo"),
                history(None),
                corrections(),
                return_exceptions=True,
            )
            completed = [result for result in results if isinstance(result, list)]
            if len(completed) != 4:
                raise PilotSourceError("Unable to read pilot sources")
            negative, positive, unrated, reviewed = completed
        except Exception:
            raise PilotSourceError("Unable to read pilot sources") from None
        return {"history": [*negative, *positive, *unrated], "corrections": reviewed}

    async def get_document(self, doc_id: str) -> Document | None:
        # The deployed documents table uses bigint IDs. Legacy source labels
        # such as discord-upload cannot identify a document.
        if not doc_id.isdecimal() or len(doc_id) > 19 or int(doc_id) > 2**63 - 1:
            return None
        try:
            result = await asyncio.to_thread(
                lambda: (
                    self.client.table("documents")
                    .select("id,content,metadata")
                    .eq("id", doc_id)
                    .limit(1)
                    .execute()
                )
            )
            if not result.data:
                return None
            row = result.data[0]
            if not isinstance(row, dict):
                raise ValueError("Invalid historical document")
            # Verification needs text only; do not deserialize pgvector strings
            # or invent vectors. This projection never enters vector retrieval.
            return Document.model_validate(
                {
                    "id": str(row["id"]),
                    "content": row["content"],
                    "metadata": row.get("metadata") or {},
                    "embedding": [],
                }
            )
        except Exception:
            raise PilotSourceError("Unable to read historical source") from None

    async def aclose(self) -> None:
        if self._owns_client:
            try:
                await asyncio.to_thread(self.client.postgrest.aclose)
            finally:
                await asyncio.to_thread(self.client.auth.close)
