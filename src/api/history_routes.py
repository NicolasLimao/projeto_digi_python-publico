from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from src.api.auth import require_api_key
from src.api.dependencies import get_history_service
from src.logger import get_logger
from src.models.schemas import (
    HistoryContextRequest,
    HistoryContextResponse,
    HistoryEntry,
    HistorySaveRequest,
)
from src.services.history_service import HistoryService

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/history",
    tags=["history"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/save", status_code=status.HTTP_201_CREATED)
async def save_interaction(
    request: HistorySaveRequest,
    service: HistoryService = Depends(get_history_service),
) -> dict[str, str]:
    entry_id = await service.save_interaction(**request.model_dump())
    if not entry_id:
        raise HTTPException(status_code=503, detail="History storage unavailable")
    return {"id": entry_id, "status": "saved"}


@router.post("/context", response_model=HistoryContextResponse)
async def get_history_context(
    request: HistoryContextRequest,
    service: HistoryService = Depends(get_history_service),
) -> HistoryContextResponse:
    formatted = await service.format_history_for_prompt(request.user_id, request.limit)
    history = await service.get_recent_history(request.user_id, request.limit)
    return HistoryContextResponse(
        formatted_context=formatted,
        entry_count=len(history),
        oldest_timestamp=history[-1].timestamp if history else None,
    )


@router.get("/user/{user_id}", response_model=list[HistoryEntry])
async def get_user_history(
    user_id: Annotated[str, Path(min_length=1, max_length=128)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    service: HistoryService = Depends(get_history_service),
) -> list[HistoryEntry]:
    return await service.get_recent_history(user_id=user_id, limit=limit)


@router.delete("/cleanup")
async def cleanup_old_history(
    days_to_keep: Annotated[int, Query(ge=1, le=3_650)] = 90,
    service: HistoryService = Depends(get_history_service),
) -> dict[str, int | str]:
    deleted = await service.clear_old_history(days_to_keep=days_to_keep)
    return {"deleted_count": deleted, "status": "completed"}
