import asyncio
import json

import httpx
import pytest

from src.config import Settings
from src.models.schemas import Document
from src.services.typesafe_service import TypesafeError, TypesafeService


def doc(id="1", content="A documentação permite criar usuários.", **metadata):
    return Document(id=id, content=content, embedding=[], score=0.8, metadata=metadata)


def make_service(handler, **options):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TypesafeService(Settings(typesafe_api_key="test-secret", **options), client=client)


def answer(request, **values):
    payload = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "model": "jev-1.13.0",
            "answers": {
                key: {"type": "noul", "noul": values.get(key, 0.95)} for key in payload["questions"]
            },
            "usage": {"input_tokens": 200, "output_tokens": 10},
        },
    )


@pytest.mark.asyncio
async def test_rerank_maps_real_documents_preserves_scores_and_curation():
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        return answer(
            request,
            relevance=0.2 if payload["state"]["document"]["id"] == "1" else 0.99,
            contradiction=0.01,
            usable=0.95,
        )

    service = make_service(handler)
    curated = doc(tipo="curadoria")
    other = doc("2")
    retired = doc("3", substituido_por="1")
    result = await service.rerank(
        "Como criar usuários?", [curated, other, retired], rewritten="Criar usuário", top_n=2
    )
    assert result == [curated, other]
    assert all(item.score == 0.8 for item in result)
    assert len(seen) == 2
    assert seen[0]["state"]["query"] == "Como criar usuários?"
    assert seen[0]["state"]["rewritten"] == "Criar usuário"
    assert service.events[-1].input_tokens == 400
    await service.aclose()
    assert not service.client.is_closed
    await service.client.aclose()


@pytest.mark.asyncio
async def test_verify_final_text_and_negative_decision():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return answer(request, supported=0.95, contradiction=0.8, respects_curation=0.99)

    service = make_service(handler)
    result = await service.verify("Pergunta", "Resposta final", [doc()])
    assert result.status == "contradicted"
    assert not result.approved
    assert seen[0]["state"]["response"] == "Resposta final"
    await service.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {
            "model": "jev-1.13.0",
            "answers": {"invented": {"type": "noul", "noul": 0.9}},
            "usage": {"input_tokens": 1, "output_tokens": 0},
        },
        {
            "model": "jev-1.13.0",
            "answers": {"supported": {"type": "noul", "noul": 2}},
            "usage": {"input_tokens": 1, "output_tokens": 0},
        },
        {"error": "secret upstream details"},
    ],
)
async def test_invalid_response_is_not_approved(body):
    service = make_service(lambda request: httpx.Response(200, json=body))
    with pytest.raises(TypesafeError) as error:
        await service.verify("Pergunta", "Resposta", [doc()])
    assert "secret" not in str(error.value)
    await service.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 422, 429, 503, 529])
async def test_external_failure_and_bounded_retries(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "0"}, json={"detail": "secret"})

    service = make_service(handler, typesafe_max_retries=1)
    with pytest.raises(TypesafeError):
        await service.verify("Pergunta", "Resposta", [doc()])
    assert len(calls) == (1 if status in (401, 422) else 2)
    await service.client.aclose()


@pytest.mark.asyncio
async def test_deadline_cancels_pending_transport():
    stopped = asyncio.Event()

    async def handler(request):
        try:
            await asyncio.sleep(10)
        finally:
            stopped.set()
        return answer(request)

    service = make_service(handler, typesafe_stage_deadline_seconds=0.1)
    with pytest.raises(TypesafeError):
        await service.verify("Pergunta", "Resposta", [doc()])
    assert stopped.is_set()
    await service.client.aclose()


@pytest.mark.asyncio
async def test_no_evidence_oversize_and_budget_never_call_transport():
    calls = []
    service = make_service(lambda request: calls.append(request), typesafe_budget_usd=0.00000001)
    assert not (await service.verify("Pergunta", "Resposta", [])).approved
    with pytest.raises(TypesafeError):
        await service.verify("Pergunta", "Resposta", [doc()])
    with pytest.raises(TypesafeError):
        await service.verify("Pergunta", "Resposta", [doc(content="x" * 30001)])
    assert not calls
    await service.client.aclose()


@pytest.mark.asyncio
async def test_shared_concurrency_bound():
    running = peak = 0

    async def handler(request):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return answer(request, contradiction=0.01)

    service = make_service(handler, typesafe_max_concurrency=2)
    await asyncio.gather(*(service.rerank("Pergunta", [doc(str(i))], top_n=1) for i in range(5)))
    assert peak == 2
    assert len(service.events) == 5
    assert all(event.calls == 1 and event.input_tokens == 200 for event in service.events)
    await service.client.aclose()


@pytest.mark.asyncio
async def test_owned_client_is_closed():
    service = TypesafeService(Settings(typesafe_api_key="test"))
    await service.aclose()
    assert service.client.is_closed


@pytest.mark.asyncio
async def test_cancellation_propagates_and_stops_candidate_tasks():
    active = 0
    started = asyncio.Event()

    async def handler(request):
        nonlocal active
        active += 1
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            active -= 1
        return answer(request)

    service = make_service(handler)
    task = asyncio.create_task(service.rerank("Pergunta", [doc("1"), doc("2")]))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert active == 0
    await service.client.aclose()


def test_missing_key_rejected_before_client_creation():
    with pytest.raises(TypesafeError):
        TypesafeService(Settings())


@pytest.mark.asyncio
async def test_verification_http_contract_has_independent_yes_no_meanings():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return answer(request, supported=0.97, contradiction=0.01, respects_curation=0.98)

    service = make_service(handler)
    result = await service.verify("Pergunta", "Resposta apoiada", [doc(tipo="curadoria")])
    assert result.approved
    questions = seen[0]["questions"]
    assert len({q["criteria"]["true"] for q in questions.values()}) == 3
    assert len({q["criteria"]["false"] for q in questions.values()}) == 3
    # The provider does not send question IDs to inference: each prompt must
    # identify the evaluated response and its documentary evidence explicitly.
    assert all(
        "response" in q["instructions"] and "documents" in q["instructions"]
        for q in questions.values()
    )
    await service.client.aclose()


@pytest.mark.asyncio
async def test_ranking_http_contract_does_not_equate_missing_evidence_and_opposite_premise():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return answer(request, relevance=0.98, usable=0.97, contradiction=0.01)

    service = make_service(handler)
    document = doc()
    assert await service.rerank("Como criar usuários?", [document], top_n=1) == [document]
    questions = seen[0]["questions"]
    assert len({q["criteria"]["true"] for q in questions.values()}) == 3
    assert len({q["criteria"]["false"] for q in questions.values()}) == 3
    assert all(
        "document" in q["instructions"] and "query" in q["instructions"] for q in questions.values()
    )
    await service.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "support,contradiction,curation,status",
    [
        (0.04, 0.25, 0.98, "unsupported"),
        (0.97, 0.25, 0.98, "uncertain"),
        (0.97, 0.01, 0.60, "uncertain"),
        (0.02, 0.96, 0.10, "contradicted"),
    ],
)
async def test_rejection_reason_distinguishes_unsupported_uncertain_and_opposed(
    support, contradiction, curation, status
):
    service = make_service(
        lambda request: answer(
            request, supported=support, contradiction=contradiction, respects_curation=curation
        )
    )
    result = await service.verify("Pergunta", "Detalhe avaliado", [doc()])
    assert result.status == status
    assert not result.approved
    await service.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "support_threshold,contradiction_threshold", [(0.9, 0.1), (0.8, 0.2), (0.4, 0.7)]
)
async def test_rejection_labels_do_not_change_configured_delivery_requirements(
    support_threshold, contradiction_threshold
):
    probabilities = [
        (0.98, 0.01, 0.98),
        (0.89, 0.05, 0.98),
        (0.97, 0.25, 0.98),
        (0.97, 0.01, 0.60),
        (0.45, 0.60, 0.45),
        (0.04, 0.25, 0.98),
    ]
    responses = iter(probabilities)

    def handler(request):
        support, contradiction, curation = next(responses)
        return answer(
            request, supported=support, contradiction=contradiction, respects_curation=curation
        )

    service = make_service(
        handler,
        typesafe_support_threshold=support_threshold,
        typesafe_contradiction_threshold=contradiction_threshold,
    )
    for support, contradiction, curation in probabilities:
        result = await service.verify("Pergunta", "Texto", [doc()])
        expected = (
            support >= support_threshold
            and curation >= support_threshold
            and contradiction <= contradiction_threshold
        )
        assert result.approved == expected
    await service.client.aclose()
