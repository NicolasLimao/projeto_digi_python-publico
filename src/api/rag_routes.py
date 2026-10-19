from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from src.agents.classifier import ClassifierAgent
from src.agents.formatter_agent import FormatterAgent
from src.agents.rag_agent import RAGAgent
from src.agents.scope_validator import ScopeValidatorAgent
from src.api.auth import require_api_key
from src.api.dependencies import (
    get_history_service,
    get_openai_service,
    get_supabase_service,
    get_typesafe_service,
)
from src.config import Settings, get_settings
from src.logger import get_logger
from src.models.schemas import FeedbackRequest, QueryRequest, QueryResponse
from src.pipeline.rag_pipeline import RAGPipeline
from src.services.history_service import HistoryService
from src.services.openai_service import OpenAIService
from src.services.supabase_service import SupabaseService
from src.services.typesafe_service import TypesafeService

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/rag",
    tags=["rag"],
    dependencies=[Depends(require_api_key)],
)


def get_rag_pipeline(
    openai: OpenAIService = Depends(get_openai_service),
    supabase: SupabaseService = Depends(get_supabase_service),
    history: HistoryService = Depends(get_history_service),
    config: Settings = Depends(get_settings),
    typesafe: TypesafeService | None = Depends(get_typesafe_service),
) -> RAGPipeline:
    return RAGPipeline(
        ClassifierAgent(openai),
        ScopeValidatorAgent(openai),
        RAGAgent(openai, supabase, config, typesafe=typesafe),
        FormatterAgent(),
        history,
        config,
        typesafe=typesafe,
    )


@router.post("/query", response_model=QueryResponse)
async def query_rag(
    request: QueryRequest,
    user_id: Annotated[str, Query(min_length=1, max_length=128)],
    canal: Annotated[str, Query(min_length=1, max_length=64)] = "desconhecido",
    pipeline: RAGPipeline = Depends(get_rag_pipeline),
) -> QueryResponse:
    logger.info(
        "RAG request received",
        extra={"extras": {"query_chars": len(request.query), "channel": canal}},
    )
    try:
        return await pipeline.process(request.query, user_id, request.mode, canal)
    except Exception:
        logger.exception("RAG query failed")
        raise HTTPException(status_code=503, detail="RAG service unavailable") from None


@router.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    history: HistoryService = Depends(get_history_service),
) -> dict[str, str]:
    ok = await history.update_feedback(request.interaction_id, request.feedback)
    if not ok:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return {
        "status": "ok",
        "interaction_id": request.interaction_id,
        "feedback": request.feedback,
    }
