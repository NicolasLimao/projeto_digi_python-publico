from fastapi import Depends, FastAPI, Request

from src.config import Settings, get_settings
from src.services.history_service import HistoryService
from src.services.ingestion_service import IngestionService
from src.services.openai_service import OpenAIService
from src.services.supabase_service import SupabaseService
from src.services.typesafe_service import TypesafeService


def get_openai_service(
    request: Request,
    config: Settings = Depends(get_settings),
) -> OpenAIService:
    service = getattr(request.app.state, "openai_service", None)
    if service is None:
        service = OpenAIService(
            api_key=config.openai_key,
            model=config.openai_model,
            embedding_model=config.embedding_model,
            timeout=config.openai_timeout_seconds,
            max_retries=config.openai_max_retries,
        )
        request.app.state.openai_service = service
    return service


def get_supabase_service(
    request: Request,
    config: Settings = Depends(get_settings),
) -> SupabaseService:
    service = getattr(request.app.state, "supabase_service", None)
    if service is None:
        service = SupabaseService(url=config.supabase_url or "", key=config.database_key or "")
        request.app.state.supabase_service = service
    return service


def get_history_service(
    request: Request,
    supabase: SupabaseService = Depends(get_supabase_service),
    config: Settings = Depends(get_settings),
) -> HistoryService:
    service = getattr(request.app.state, "history_service", None)
    if service is None:
        salt = config.user_id_salt.get_secret_value() if config.user_id_salt else ""
        service = HistoryService(supabase.client, salt=salt)
        request.app.state.history_service = service
    return service


def get_ingestion_service(
    request: Request,
    config: Settings = Depends(get_settings),
) -> IngestionService:
    service = getattr(request.app.state, "ingestion_service", None)
    if service is None:
        service = IngestionService(config=config)
        request.app.state.ingestion_service = service
    return service


def get_typesafe_service(
    request: Request, config: Settings = Depends(get_settings)
) -> TypesafeService | None:
    if not config.typesafe_active:
        return None
    service: TypesafeService | None = getattr(request.app.state, "typesafe_service", None)
    if service is None:
        service = TypesafeService(config)
        request.app.state.typesafe_service = service
    return service


async def close_application_services(app: FastAPI) -> None:
    for attribute in ("openai_service", "ingestion_service", "typesafe_service"):
        service = getattr(app.state, attribute, None)
        close = getattr(service, "aclose", None)
        if close is not None:
            await close()
