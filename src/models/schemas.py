from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints

Mode = Literal["orientacao", "resposta-cliente", "bug"]
Feedback = Literal["positivo", "negativo"]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
UserId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IngestRequest(StrictModel):
    content: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500_000)
    ]
    content_type: Literal["pdf", "txt", "text", "markdown"]
    source: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ] = "discord"
    metadata: dict[str, Any] = Field(default_factory=dict)


class Attachment(StrictModel):
    url: AnyHttpUrl
    filename: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=255)] = None
    content_type: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=128)
    ] = Field(
        default=None,
        alias="contentType",
    )


class IngestPayload(StrictModel):
    curated: bool = Field(default=False, strict=True)
    content: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500_000)] = (
        None
    )
    attachments: list[Attachment] = Field(default_factory=list, max_length=20)


class IngestResponse(StrictModel):
    status: str
    chunks_created: int
    total_chars: int
    message: str


class IngestResult(StrictModel):
    chunks_created: int = Field(ge=0)
    total_chars: int = Field(ge=0)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class QueryRequest(StrictModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)]
    mode: Mode | None = None


class QueryResponse(StrictModel):
    response: str
    mode: Mode
    score: float = Field(ge=0.0, le=1.0)
    chunks_used: int = Field(ge=0)
    processing_time_ms: float = Field(ge=0.0)
    interaction_id: str | None = None


class FeedbackRequest(StrictModel):
    interaction_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]
    feedback: Feedback


class HistorySaveRequest(StrictModel):
    user_id: UserId
    pergunta: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)
    ]
    resposta: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40_000)
    ]
    modo: Mode = "orientacao"
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    chunks_used: int = Field(default=0, ge=0, le=100)
    processing_time_ms: int = Field(default=0, ge=0)


class LogEntry(StrictModel):
    timestamp: str
    mode: Mode
    query: str
    score: float
    response_length: int
    processing_time_ms: float
    chunks_used: int


class Document(StrictModel):
    id: str
    content: str
    embedding: list[float]
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float | None = Field(default=None, ge=0.0, le=1.0)


class HistoryEntry(StrictModel):
    id: str | None = None
    user_id: UserId
    pergunta: str
    resposta: str
    modo: Mode = "orientacao"
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    chunks_used: int = Field(default=0, ge=0)
    processing_time_ms: int = Field(default=0, ge=0)
    timestamp: str | None = None


class HistoryContextRequest(StrictModel):
    user_id: UserId
    limit: int = Field(default=5, ge=1, le=20)


class HistoryContextResponse(StrictModel):
    formatted_context: str
    entry_count: int = Field(ge=0)
    oldest_timestamp: str | None = None
