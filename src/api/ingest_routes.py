from fastapi import APIRouter, Depends, HTTPException, status

from src.api.auth import require_api_key
from src.api.dependencies import get_ingestion_service
from src.config import Settings, get_settings
from src.logger import get_logger
from src.models.schemas import IngestPayload, IngestResult
from src.services.ingestion_service import IngestionService, IngestionValidationError

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["ingest"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/ingest", response_model=IngestResult)
async def ingest(
    payload: IngestPayload,
    service: IngestionService = Depends(get_ingestion_service),
    config: Settings = Depends(get_settings),
) -> IngestResult:
    if not payload.content and not payload.attachments:
        raise HTTPException(status_code=400, detail="content or attachments is required")
    if len(payload.attachments) > config.ingest_max_attachments:
        raise HTTPException(
            status_code=413,
            detail=f"At most {config.ingest_max_attachments} attachments are allowed",
        )

    try:
        result = await service.ingest(
            curated=payload.curated,
            content=payload.content,
            attachments=[
                attachment.model_dump(mode="json", by_alias=True)
                for attachment in payload.attachments
            ],
        )
        return IngestResult(**result)
    except IngestionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        logger.exception("Ingestion failed")
        raise HTTPException(status_code=503, detail="Ingestion service unavailable") from None
