import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from src.api import history_routes, ingest_routes, rag_routes
from src.api.dependencies import close_application_services
from src.config import Settings, get_settings
from src.logger import get_logger

logger = get_logger(__name__)
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _configure_sentry(config: Settings) -> None:
    if not config.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=config.sentry_dsn.get_secret_value(),
        traces_sample_rate=config.sentry_traces_sample_rate,
        profiles_sample_rate=config.sentry_profiles_sample_rate,
        environment=config.environment,
        release=config.release_version,
        send_default_pii=False,
    )


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or get_settings()
    _configure_sentry(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("Application starting")
        yield
        await close_application_services(app)
        logger.info("Application stopped")

    docs_enabled = config.environment != "production"
    app = FastAPI(
        title="Digi RAG API",
        description="RAG-powered support agent for Digisac analysts",
        version="2.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = config
    app.dependency_overrides[get_settings] = lambda: config

    if config.trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.trusted_hosts)

    if config.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_allowed_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
        )

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        supplied_id = request.headers.get("X-Request-ID", "")
        request_id = supplied_id if REQUEST_ID_RE.fullmatch(supplied_id) else uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(history_routes.router)
    app.include_router(rag_routes.router)
    app.include_router(ingest_routes.router)

    @app.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "digi-rag", "version": "2.0.0"}

    @app.get("/ready", tags=["operations"])
    async def ready() -> JSONResponse:
        checks = {
            "openai": bool(config.openai_key),
            "supabase": bool(config.supabase_url and config.database_key),
            "authentication": bool(config.api_auth_token) or config.environment != "production",
        }
        if config.typesafe_active:
            checks["typesafe"] = bool(config.typesafe_api_key)
        ready_state = all(checks.values())
        return JSONResponse(
            status_code=status.HTTP_200_OK if ready_state else status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "ready" if ready_state else "not_ready", "checks": checks},
        )

    @app.get("/", tags=["operations"])
    async def root() -> dict[str, str]:
        body = {"service": "Digi RAG API", "version": "2.0.0"}
        if docs_enabled:
            body["docs"] = "/docs"
        return body

    return app
