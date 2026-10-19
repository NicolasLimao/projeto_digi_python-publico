import asyncio
from typing import Any

from src.agents.base import Agent
from src.config import Settings, get_settings
from src.models.schemas import Document
from src.services.openai_service import OpenAIService
from src.services.server_analysis import is_server_analysis
from src.services.supabase_service import SupabaseService
from src.services.typesafe_service import TypesafeService


class RAGAgent(Agent):
    def __init__(
        self,
        openai_service: OpenAIService,
        supabase_service: SupabaseService,
        config: Settings | None = None,
        *,
        typesafe: TypesafeService | None = None,
    ):
        super().__init__("RAG")
        self.openai = openai_service
        self.supabase = supabase_service
        self.config = config or get_settings()
        self.typesafe = typesafe

    def _needs_rewrite(self, query: str, history_context: str) -> bool:
        """Decide se vale reescrever a query antes de buscar (item 3: pular em pergunta simples)."""
        if history_context:
            return True  # follow-up pode ter referência a resolver
        if len(query) > 120 or "\n" in query:
            return True  # mensagem longa/ruidosa
        q = query.lower()
        return any(k in q for k in ["cliente", "obs.", "obs:"])

    async def _buscar(self, query: str, candidate_k: int) -> list[Document]:
        """Uma passada de busca: embedding -> busca híbrida com threshold."""
        embedding = await self.openai.get_embeddings(query)
        return await self.supabase.search_hybrid(
            embedding=embedding,
            query=query,
            k=candidate_k,
            score_threshold=self.config.score_threshold,
        )

    async def _buscar_fundido(
        self, original: str, reescrita: str, candidate_k: int
    ) -> list[Document]:
        """Busca com a reescrita E a pergunta original, fundindo os candidatos.

        A reescrita às vezes comprime demais e perde a intenção (ex.: dropa
        'solicitar' e vira 'exclusão de conexão'), o que recupera o chunk errado.
        Buscar também com a original ancora o chunk certo mesmo nesse caso.
        Dedup por id mantendo o maior score; ordena por score antes do rerank."""
        pools = await asyncio.gather(
            self._buscar(reescrita, candidate_k),
            self._buscar(original, candidate_k),
        )
        fundido: dict[str, Document] = {}
        for pool in pools:
            for doc in pool:
                atual = fundido.get(doc.id)
                if atual is None or (doc.score or 0.0) > (atual.score or 0.0):
                    fundido[doc.id] = doc
        ordenado = sorted(fundido.values(), key=lambda d: d.score or 0.0, reverse=True)
        return ordenado[:candidate_k]

    async def retrieve(self, query: str, history_context: str = "", k: int = 10) -> dict[str, Any]:
        """Recuperação (não depende do modo): reescreve (condicional) -> embedding -> busca -> rerank."""
        if self._needs_rewrite(query, history_context):
            search_query = await self.openai.rewrite_query(query, history_context)
        else:
            search_query = query
            self.logger.info(f"[{self.name}] Rewrite pulado (pergunta simples)")
        self.logger.info(
            f"[{self.name}] Search query prepared",
            extra={"extras": {"query_chars": len(search_query)}},
        )

        final_n = min(k, self.config.max_chunks)
        candidate_k = max(final_n, self.config.retrieval_candidate_count)

        if search_query != query:
            # Query foi reescrita: busca com as duas (dual-query) para não perder o
            # chunk certo se a reescrita tiver descartado a intenção.
            documents = await self._buscar_fundido(query, search_query, candidate_k)
        else:
            documents = await self._buscar(search_query, candidate_k)
        self.logger.info(f"[{self.name}] Retrieved {len(documents)} candidate documents")

        async def openai_rank() -> list[Document]:
            if self.config.rerank_full_context or is_server_analysis(query, history_context):
                return await self.openai.rerank(
                    query + "\nAuxiliary rewrite: " + search_query,
                    documents,
                    top_n=final_n,
                    full_context=True,
                )
            return await self.openai.rerank(search_query, documents, top_n=final_n)

        async def typesafe_rank() -> list[Document] | None:
            try:
                if self.typesafe is None:
                    raise RuntimeError("TypeSafe unavailable")
                return await self.typesafe.rerank(
                    query, documents, rewritten=search_query, top_n=final_n
                )
            except Exception:
                self.logger.warning("TypeSafe rerank failed; using OpenAI fallback")
                return None

        if self.config.rerank_provider == "typesafe":
            selected = await typesafe_rank()
            documents = selected if selected is not None else await openai_rank()
        elif self.config.typesafe_rerank_shadow:
            baseline, alternative = await asyncio.gather(openai_rank(), typesafe_rank())
            self.logger.info(
                "TypeSafe rerank shadow comparison",
                extra={
                    "extras": {
                        "alternative_available": alternative is not None,
                        "same_order": alternative is not None
                        and [d.id for d in alternative] == [d.id for d in baseline],
                    }
                },
            )
            documents = baseline
        else:
            documents = await openai_rank()
        self.logger.info(f"[{self.name}] After rerank: {len(documents)} documents")

        # Ids reais dos chunks usados na resposta: dá para voltar em `documents` e
        # recuperar conteúdo e `fonte`. Antes daqui ia `metadata["fonte"]`, que é
        # sempre 'discord-upload' e não rastreia nada. Histórico antigo fica como está.
        fontes = [doc.id for doc in documents]
        avg_score = (
            (sum(doc.score or 0.0 for doc in documents) / len(documents)) if documents else 0.0
        )

        return {
            "documents": documents,
            "search_query": search_query,
            "fontes": fontes,
            "score": avg_score,
            "chunks_used": len(documents),
        }

    async def generate(
        self,
        query: str,
        documents: list[Document],
        mode: str = "orientacao",
        history_context: str = "",
    ) -> str:
        """Geração (precisa do modo + documentos recuperados)."""
        if not documents:
            self.logger.warning(f"[{self.name}] No relevant documents found")
            response = (
                "Desculpe, não encontrei informações sobre este tópico na base de conhecimento."
            )
        else:
            response = await self.openai.generate_response(query, documents, mode, history_context)
        return await self.openai.format_response(response, mode)

    async def execute(
        self,
        query: str,
        mode: str = "orientacao",
        k: int = 10,
        history_context: str = "",
    ) -> dict[str, Any]:
        """Compat: recuperação + geração em sequência (usado fora do caminho paralelo)."""
        self.logger.info(
            "RAG execution started",
            extra={"extras": {"query_chars": len(query), "mode": mode, "k": k}},
        )

        try:
            retr = await self.retrieve(query, history_context, k)
            formatted_response = await self.generate(
                query, retr["documents"], mode, history_context
            )

            self.logger.info(f"[{self.name}] Generated response (score={retr['score']:.2f})")
            return {
                "response": formatted_response,
                "mode": mode,
                "score": retr["score"],
                "chunks_used": retr["chunks_used"],
                "documents": retr["documents"],
                "search_query": retr["search_query"],
                "fontes": retr["fontes"],
            }

        except Exception:
            self.logger.exception(f"[{self.name}] RAG execution failed")
            return {
                "response": "Não foi possível consultar a base de conhecimento agora.",
                "mode": mode,
                "score": 0.0,
                "chunks_used": 0,
                "documents": [],
                "search_query": query,
                "fontes": [],
            }
