import asyncio
from time import time
from typing import Any

from src.agents.classifier import ClassifierAgent
from src.agents.formatter_agent import FormatterAgent
from src.agents.rag_agent import RAGAgent
from src.agents.scope_validator import ScopeValidatorAgent
from src.config import Settings, get_settings
from src.logger import get_logger
from src.models.schemas import Mode, QueryResponse
from src.services.history_service import HistoryService
from src.services.typesafe_service import TypesafeService

logger = get_logger(__name__)


class RAGPipeline:
    def __init__(
        self,
        classifier: ClassifierAgent,
        validator: ScopeValidatorAgent,
        rag_agent: RAGAgent,
        formatter: FormatterAgent,
        history_service: HistoryService,
        config: Settings | None = None,
        *,
        typesafe: TypesafeService | None = None,
    ):
        self.classifier = classifier
        self.validator = validator
        self.rag_agent = rag_agent
        self.formatter = formatter
        self.history = history_service
        self.config = config or get_settings()
        self.typesafe = typesafe
        self.logger = logger

    async def process(
        self, query: str, user_id: str, mode: str | None = None, canal: str = "desconhecido"
    ) -> QueryResponse:
        """
        Execute full RAG pipeline:
        1. Classify query
        2. Validate scope
        3. Run RAG if in scope
        4. Format response
        5. Save to history
        6. Return response
        """
        start_time = time()
        self.logger.info("RAG pipeline started")

        try:
            # Histórico primeiro (a reescrita da query o utiliza)
            history_context = ""
            if self.config.history_enabled:
                history_context = await self.history.format_history_for_prompt(
                    user_id, limit=4, within_minutes=60
                )
                if history_context:
                    self.logger.info("Injecting conversation history")

            # Classificar + validar + recuperar — as três EM PARALELO
            # (classificador dedicado é mais preciso; paralelizar esconde o custo sob a recuperação)
            validate_task = asyncio.create_task(self.validator.execute(query, history_context))
            retrieve_task = asyncio.create_task(self.rag_agent.retrieve(query, history_context))
            if mode is None:
                classify_task = asyncio.create_task(self.classifier.execute(query, history_context))
                classification, validation, retr = await asyncio.gather(
                    classify_task, validate_task, retrieve_task
                )
            else:
                validation, retr = await asyncio.gather(validate_task, retrieve_task)
                classification = mode

            # Override por evidência da recuperação: se o validator disse "fora" mas
            # a busca trouxe chunks fortes, é um falso positivo do validator.
            dentro_validator = validation.get("dentro_do_escopo", True)
            chunks_recuperados = retr.get("chunks_used", 0)
            score_recuperacao = retr.get("score", 0.0)
            override_retrieval = (
                not dentro_validator and chunks_recuperados >= 5 and score_recuperacao >= 0.20
            )
            dentro_escopo = dentro_validator or override_retrieval

            if override_retrieval:
                self.logger.info(
                    f"[RAGPipeline] Validator disse fora, mas retrieval trouxe {chunks_recuperados} "
                    f"chunks (score={score_recuperacao:.3f}). Override: tratando como DENTRO."
                )

            self.logger.info(
                f"[RAGPipeline] modo={classification}, escopo={dentro_escopo} (validator={dentro_validator})"
            )

            # Fora do escopo de verdade (validator E retrieval concordam): retorna sem gerar
            if not dentro_escopo:
                response_text = f"Desculpe, sua pergunta está fora do escopo de suporte. Motivo: {validation.get('motivo', 'Não especificado')}"
                response = QueryResponse(
                    response=response_text,
                    mode="orientacao",
                    score=0.0,
                    chunks_used=0,
                    processing_time_ms=int((time() - start_time) * 1000),
                )
                self.logger.info("[RAGPipeline] Query out of scope, returning early")
                return response

            # Geração (precisa do modo + documentos recuperados)
            generated = await self.rag_agent.generate(
                query, retr["documents"], classification, history_context
            )
            formatted = await self.formatter.execute(generated, classification)

            if self.config.typesafe_verify_mode != "off":
                approved = False
                decision = "error"
                try:
                    if self.typesafe is None:
                        raise RuntimeError("TypeSafe unavailable")
                    verification = await self.typesafe.verify(query, formatted, retr["documents"])
                    approved, decision = verification.approved, verification.status
                except Exception:
                    self.logger.warning("TypeSafe verification unavailable")
                self.logger.info(
                    "TypeSafe delivery decision",
                    extra={
                        "extras": {
                            "verification_mode": self.config.typesafe_verify_mode,
                            "verification_status": decision,
                            "approved": approved,
                        }
                    },
                )
                if self.config.typesafe_verify_mode == "enforce" and not approved:
                    formatted = (
                        "Não foi possível confirmar essa informação. Nossa equipe de suporte poderá verificar e orientar você."
                        if classification == "resposta-cliente"
                        else "Não encontrei suporte documental suficiente para confirmar a resposta. Encaminhe a dúvida para revisão de um analista."
                    )

            processing_time_ms = int((time() - start_time) * 1000)

            response = QueryResponse(
                response=formatted,
                mode=classification,
                score=retr.get("score", 0.0),
                chunks_used=retr.get("chunks_used", 0),
                processing_time_ms=processing_time_ms,
            )

            interaction_id = await self._save_history(
                user_id=user_id,
                pergunta=query,
                resposta=formatted,
                modo=classification,
                score=response.score,
                chunks_used=response.chunks_used,
                processing_time_ms=processing_time_ms,
                pergunta_reescrita=retr.get("search_query"),
                fontes=retr.get("fontes"),
                canal=canal,
            )
            response.interaction_id = interaction_id

            self.logger.info(f"[RAGPipeline] Completed pipeline in {processing_time_ms}ms")
            return response

        except Exception:
            self.logger.exception("RAG pipeline failed")
            processing_time_ms = int((time() - start_time) * 1000)

            error_response = QueryResponse(
                response="Não foi possível processar a pergunta agora. Tente novamente em instantes.",
                mode="orientacao",
                score=0.0,
                chunks_used=0,
                processing_time_ms=processing_time_ms,
            )

            await self._save_history(
                user_id=user_id,
                pergunta=query,
                resposta=error_response.response,
                modo="orientacao",
                score=0.0,
                chunks_used=0,
                processing_time_ms=processing_time_ms,
            )

            return error_response

    async def _save_history(
        self,
        user_id: str,
        pergunta: str,
        resposta: str,
        modo: Mode = "orientacao",
        score: float = 0.0,
        chunks_used: int = 0,
        processing_time_ms: int = 0,
        pergunta_reescrita: str | None = None,
        fontes: list[Any] | None = None,
        canal: str | None = None,
    ) -> str | None:
        """History is best-effort and must never replace a valid RAG response."""
        try:
            return await self.history.save_interaction(
                user_id=user_id,
                pergunta=pergunta,
                resposta=resposta,
                modo=modo,
                score=score,
                chunks_used=chunks_used,
                processing_time_ms=processing_time_ms,
                pergunta_reescrita=pergunta_reescrita,
                fontes=fontes,
                canal=canal,
            )
        except Exception:
            self.logger.exception("History persistence failed")
            return None
