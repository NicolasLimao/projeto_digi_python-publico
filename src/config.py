from functools import lru_cache
from typing import Annotated, Any, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from src.services.typesafe_criteria import CRITERIA_VERSION


def _csv_list(value: Any) -> Any:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    Development may start without external credentials so health checks and unit
    tests remain usable. Production deliberately fails fast unless every secret
    needed by the API is configured.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = Field(default=45.0, ge=5.0, le=120.0)
    openai_max_retries: int = Field(default=2, ge=0, le=5)

    supabase_url: str | None = None
    supabase_anon_key: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None

    mistral_api_key: SecretStr | None = None
    cohere_api_key: SecretStr | None = None

    typesafe_api_key: SecretStr | None = None
    typesafe_model: Literal["jev-1.13.0"] = "jev-1.13.0"
    rerank_provider: Literal["openai", "typesafe"] = "openai"
    rerank_full_context: bool = False
    typesafe_rerank_shadow: bool = False
    typesafe_verify_mode: Literal["off", "shadow", "enforce"] = "off"
    typesafe_http_timeout_seconds: float = Field(default=3, ge=0.1, le=30)
    typesafe_stage_deadline_seconds: float = Field(default=10, ge=0.1, le=60)
    typesafe_max_retries: int = Field(default=1, ge=0, le=2)
    typesafe_max_concurrency: int = Field(default=4, ge=1, le=8)
    typesafe_max_candidates: int = Field(default=15, ge=1, le=35)
    typesafe_max_chunk_chars: int = Field(default=6000, ge=100, le=6000)
    typesafe_max_request_bytes: int = Field(default=24000, ge=1000, le=30000)
    typesafe_budget_usd: float = Field(default=1, gt=0, le=100)
    typesafe_support_threshold: float = Field(default=0.9, gt=0, le=1)
    typesafe_contradiction_threshold: float = Field(default=0.1, ge=0, lt=1)
    typesafe_criteria_version: str = Field(default=CRITERIA_VERSION, min_length=1, max_length=64)
    typesafe_criteria_calibrated: bool = False

    api_auth_token: SecretStr | None = None
    user_id_salt: SecretStr | None = None
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    trusted_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )

    ingest_allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["cdn.discordapp.com", "media.discordapp.net"]
    )
    ingest_max_attachments: int = Field(default=5, ge=1, le=20)
    ingest_max_file_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)
    ingest_max_total_chars: int = Field(default=2_000_000, ge=1_000)
    ingest_download_timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)
    ingest_max_pdf_pages: int = Field(default=1_000, ge=1, le=5_000)

    history_enabled: bool = True
    history_retention_days: int = Field(default=90, ge=1, le=3_650)
    rag_api_url: str = "http://localhost:8000/api/rag/query"

    log_level: str = "INFO"
    environment: str = "development"
    score_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    max_chunks: int = Field(default=10, ge=1, le=30)
    retrieval_candidate_count: int = Field(default=30, ge=1, le=60)
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65_535)

    sentry_dsn: SecretStr | None = None
    release_version: str | None = None
    sentry_traces_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    sentry_profiles_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("cors_allowed_origins", "trusted_hosts", "ingest_allowed_hosts", mode="before")
    @classmethod
    def parse_csv_lists(cls, value: Any) -> Any:
        return _csv_list(value)

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, value: Any) -> str:
        return str(value or "development").strip().lower()

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: Any) -> str:
        return str(value or "INFO").strip().upper()

    @field_validator(
        "openai_api_key",
        "supabase_url",
        "supabase_anon_key",
        "supabase_service_role_key",
        "mistral_api_key",
        "cohere_api_key",
        "api_auth_token",
        "user_id_salt",
        "typesafe_api_key",
        "sentry_dsn",
        mode="before",
    )
    @classmethod
    def empty_values_are_unset(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Self:
        if self.typesafe_active and not self.typesafe_api_key:
            raise ValueError("Missing configuration: TYPESAFE_API_KEY")
        if self.typesafe_verify_mode == "enforce" and not self.typesafe_criteria_calibrated:
            raise ValueError("Enforcement requires calibrated criteria")
        if self.typesafe_active and self.typesafe_criteria_version != CRITERIA_VERSION:
            raise ValueError("Active TypeSafe requires the current criteria version")
        if self.environment != "production":
            return self

        required = {
            "OPENAI_API_KEY": self.openai_api_key,
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
            "API_AUTH_TOKEN": self.api_auth_token,
        }
        if self.history_enabled:
            required["USER_ID_SALT"] = self.user_id_salt
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError("Missing production configuration: " + ", ".join(sorted(missing)))
        return self

    @property
    def typesafe_active(self) -> bool:
        return (
            self.rerank_provider == "typesafe"
            or self.typesafe_rerank_shadow
            or self.typesafe_verify_mode != "off"
        )

    @property
    def database_key(self) -> str | None:
        secret = self.supabase_service_role_key or self.supabase_anon_key
        return secret.get_secret_value() if secret else None

    @property
    def openai_key(self) -> str | None:
        return self.openai_api_key.get_secret_value() if self.openai_api_key else None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
