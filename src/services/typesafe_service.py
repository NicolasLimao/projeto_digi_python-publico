"""Bounded, injectable Jev integration. Never logs prompts or upstream bodies."""

import asyncio
import json
from collections import deque
from collections.abc import Awaitable
from contextlib import suppress
from contextvars import ContextVar
from time import monotonic
from typing import Any, TypeVar

import httpx
from pydantic import ValidationError

from src.config import Settings
from src.logger import get_logger
from src.models.schemas import Document
from src.models.typesafe import EvaluationResponse, RelationResponse, StageEvent, VerificationResult
from src.services.curadoria import eh_documento_curado, foi_substituido
from src.services.typesafe_criteria import ranking_questions, verification_questions

logger = get_logger(__name__)
T = TypeVar("T")
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
INPUT_PRICE = 0.042 / 1_000_000
RETRY_STATUSES = {429, 502, 503, 504, 529}


class TypesafeError(RuntimeError):
    """A sanitized integration error; never contains upstream content."""


class TypesafeService:
    def __init__(self, config: Settings, *, client: httpx.AsyncClient | None = None):
        if not config.typesafe_api_key:
            raise TypesafeError("TypeSafe is not configured")
        self.config = config
        self._key = config.typesafe_api_key.get_secret_value()
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(follow_redirects=False, trust_env=False)
        self._semaphore = asyncio.Semaphore(config.typesafe_max_concurrency)
        self._budget_used = 0.0
        self._budget_started = monotonic()
        self.events: deque[StageEvent] = deque(maxlen=200)
        self._counts: ContextVar[dict[str, int] | None] = ContextVar(
            "typesafe_stage_counts", default=None
        )
        self._decisions: ContextVar[dict[str, float] | None] = ContextVar(
            "typesafe_stage_decisions", default=None
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def _reserve_budget(self, upper_tokens: int) -> float:
        if monotonic() - self._budget_started >= 30 * 86400:
            self._budget_used = 0.0
            self._budget_started = monotonic()
        cost = upper_tokens * INPUT_PRICE
        if self._budget_used + cost > self.config.typesafe_budget_usd:
            raise TypesafeError("TypeSafe local budget exhausted")
        self._budget_used += cost
        return cost

    async def _evaluate(
        self, state: dict[str, Any], questions: dict[str, Any]
    ) -> EvaluationResponse:
        result = await self._evaluate_response(state, questions, EvaluationResponse)
        if not isinstance(result, EvaluationResponse):
            raise TypesafeError("Unexpected TypeSafe answer schema")
        return result

    async def _evaluate_response(
        self,
        state: dict[str, Any],
        questions: dict[str, Any],
        response_schema: type[EvaluationResponse] | type[RelationResponse],
    ) -> EvaluationResponse | RelationResponse:
        payload = {"model": self.config.typesafe_model, "state": state, "questions": questions}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        # UTF-8 bytes conservatively bound byte-level tokens, including all rubrics.
        if len(encoded) > self.config.typesafe_max_request_bytes:
            raise TypesafeError("TypeSafe input budget exceeded")
        async with self._semaphore:
            for attempt in range(self.config.typesafe_max_retries + 1):
                reserved = self._reserve_budget(len(encoded))
                counts = self._counts.get()
                if counts is not None:
                    counts["calls"] += 1
                retry_delay = min(0.25 * 2**attempt, 2.0)
                try:
                    async with self.client.stream(
                        "POST",
                        ENDPOINT,
                        content=encoded,
                        headers={
                            "Authorization": f"Bearer {self._key}",
                            "Content-Type": "application/json",
                        },
                        timeout=self.config.typesafe_http_timeout_seconds,
                        follow_redirects=False,
                    ) as response:
                        if response.status_code in RETRY_STATUSES:
                            with suppress(ValueError):
                                retry_delay = max(
                                    retry_delay,
                                    min(float(response.headers.get("Retry-After", "0")), 2.0),
                                )
                            transient = True
                        elif response.status_code != 200:
                            raise TypesafeError("TypeSafe request rejected")
                        else:
                            content = bytearray()
                            async for part in response.aiter_bytes():
                                content.extend(part)
                                if len(content) > 32768:
                                    raise TypesafeError("TypeSafe response too large")
                            try:
                                result = response_schema.model_validate_json(bytes(content))
                            except ValidationError:
                                raise TypesafeError("Invalid TypeSafe response") from None
                            if result.model != self.config.typesafe_model or set(
                                result.answers
                            ) != set(questions):
                                raise TypesafeError("Unexpected TypeSafe model or answer IDs")
                            if counts is not None:
                                counts["input_tokens"] += result.usage.input_tokens
                                counts["output_tokens"] += result.usage.output_tokens
                            # Unknown/failed attempts retain their conservative reservation.
                            self._budget_used += result.usage.input_tokens * INPUT_PRICE - reserved
                            return result
                except (httpx.TimeoutException, httpx.TransportError):
                    transient = True
                if transient and attempt < self.config.typesafe_max_retries:
                    await asyncio.sleep(retry_delay)
                else:
                    raise TypesafeError("TypeSafe temporarily unavailable")
        raise TypesafeError("TypeSafe evaluation failed")

    async def _stage(self, name: str, operation: Awaitable[T], *, truncated: bool = False) -> T:
        started = monotonic()
        counts = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        decisions: dict[str, float] = {}
        token = self._counts.set(counts)
        decision_token = self._decisions.set(decisions)
        status = "ok"
        try:
            async with asyncio.timeout(self.config.typesafe_stage_deadline_seconds):
                return await operation
        except TimeoutError:
            status = "timeout"
            raise TypesafeError("TypeSafe stage deadline exceeded") from None
        except BaseException:
            status = "error"
            raise
        finally:
            event = StageEvent(
                stage=name,
                status=status,
                model=self.config.typesafe_model,
                criteria_version=self.config.typesafe_criteria_version,
                calls=counts["calls"],
                input_tokens=counts["input_tokens"],
                output_tokens=counts["output_tokens"],
                estimated_cost_usd=counts["input_tokens"] * INPUT_PRICE,
                duration_ms=int((monotonic() - started) * 1000),
                truncated=truncated,
                decisions=decisions,
            )
            self._counts.reset(token)
            self._decisions.reset(decision_token)
            self.events.append(event)
            logger.info("TypeSafe stage completed", extra={"extras": event.model_dump()})

    async def rerank(
        self, query: str, documents: list[Document], *, rewritten: str = "", top_n: int = 10
    ) -> list[Document]:
        if not query.strip() or len(query) > 8000 or len(rewritten) > 8000 or not 1 <= top_n <= 30:
            raise TypesafeError("Invalid reranking input")
        candidates = [d for d in documents if not foi_substituido(d.metadata)][
            : self.config.typesafe_max_candidates
        ]
        if len({d.id for d in candidates}) != len(candidates):
            raise TypesafeError("Duplicate document IDs")

        async def rank() -> list[Document]:
            tasks = []
            async with asyncio.TaskGroup() as group:
                for document in candidates:
                    tasks.append(
                        group.create_task(
                            self._evaluate(
                                {
                                    "query": query,
                                    "rewritten": rewritten,
                                    "document": {
                                        "id": document.id,
                                        "content": document.content[
                                            : self.config.typesafe_max_chunk_chars
                                        ],
                                        "curated": eh_documento_curado(document.metadata),
                                    },
                                },
                                ranking_questions(),
                            )
                        )
                    )
            scored = [(d, task.result().answers) for d, task in zip(candidates, tasks, strict=True)]
            decisions = self._decisions.get()
            if decisions is not None:
                for index, (_, values) in enumerate(scored):
                    decisions.update(
                        {f"candidate_{index}_{key}": value.noul for key, value in values.items()}
                    )
            scored.sort(
                key=lambda pair: (
                    eh_documento_curado(pair[0].metadata),
                    pair[1]["relevance"].noul * pair[1]["usable"].noul,
                ),
                reverse=True,
            )
            return [d for d, _ in scored[:top_n]]

        try:
            return await self._stage(
                "rerank",
                rank(),
                truncated=any(
                    len(d.content) > self.config.typesafe_max_chunk_chars for d in candidates
                )
                or len(documents) > len(candidates),
            )
        except ExceptionGroup:
            raise TypesafeError("TypeSafe reranking failed") from None

    async def verify(
        self, query: str, response: str, documents: list[Document]
    ) -> VerificationResult:
        if not query.strip() or len(query) > 8000 or not response.strip() or len(response) > 40000:
            raise TypesafeError("Invalid verification input")
        if not documents:
            return VerificationResult(status="unsupported")
        if len(documents) > 30 or any(foi_substituido(d.metadata) for d in documents):
            raise TypesafeError("Invalid verification evidence")

        async def evaluate() -> VerificationResult:
            result = await self._evaluate(
                {
                    "query": query,
                    "response": response,
                    "documents": [
                        {
                            "id": d.id,
                            "content": d.content,
                            "curated": eh_documento_curado(d.metadata),
                        }
                        for d in documents
                    ],
                },
                self._verification_questions(),
            )
            probabilities = {key: value.noul for key, value in result.answers.items()}
            decisions = self._decisions.get()
            if decisions is not None:
                decisions.update(probabilities)
            return self._verification_result(probabilities)

        return await self._stage("verify", evaluate())

    def _verification_questions(self) -> dict[str, dict[str, object]]:
        return verification_questions()

    def _verification_result(self, probabilities: dict[str, float]) -> VerificationResult:
        approved = (
            probabilities["supported"] >= self.config.typesafe_support_threshold
            and probabilities["respects_curation"] >= self.config.typesafe_support_threshold
            and probabilities["contradiction"] <= self.config.typesafe_contradiction_threshold
        )
        if approved:
            return VerificationResult(
                status="supported", approved=True, probabilities=probabilities
            )
        # The conservative delivery ceiling is not a semantic yes/no boundary.
        # A Noul above 0.5 favors "yes"; lower values can still block delivery
        # without claiming that the evidence establishes an opposite fact.
        if probabilities["contradiction"] > 0.5:
            return VerificationResult(status="contradicted", probabilities=probabilities)
        if probabilities["supported"] + self.config.typesafe_support_threshold <= 1:
            return VerificationResult(status="unsupported", probabilities=probabilities)
        return VerificationResult(
            status="uncertain",
            probabilities=probabilities,
        )
