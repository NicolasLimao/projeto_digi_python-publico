from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NoulAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["noul"]
    noul: float = Field(ge=0, le=1, allow_inf_nan=False)


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input_tokens: int = Field(ge=0, le=64000)
    output_tokens: int = Field(ge=0, le=64000)


class EvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1, max_length=64)
    answers: dict[str, NoulAnswer]
    usage: TokenUsage


class RelationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["choice"]
    choice: Literal["supports", "contradicts", "says_nothing"]
    probabilities: dict[str, float]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_distribution(self) -> "RelationAnswer":
        import math

        if set(self.probabilities) != {"supports", "contradicts", "says_nothing"} or any(
            not math.isfinite(p) or not 0 <= p <= 1 for p in self.probabilities.values()
        ):
            raise ValueError("Invalid relation options or probabilities")
        if abs(sum(self.probabilities.values()) - 1) > 0.001:
            raise ValueError("Relation probabilities must sum to one")
        if self.probabilities[self.choice] != max(self.probabilities.values()):
            raise ValueError("Relation choice must have maximum probability")
        return self


class RelationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1, max_length=64)
    answers: dict[str, RelationAnswer]
    usage: TokenUsage


class VerificationResult(BaseModel):
    status: Literal["supported", "unsupported", "contradicted", "uncertain"]
    approved: bool = False
    probabilities: dict[str, float] = Field(default_factory=dict)


class StageEvent(BaseModel):
    stage: str
    status: str
    model: str
    criteria_version: str
    calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    duration_ms: int
    truncated: bool = False
    decisions: dict[str, float] = Field(default_factory=dict)
