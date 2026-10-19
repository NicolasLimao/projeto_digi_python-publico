import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from evals.compare_jev import FrozenCase, compare_case, load_cases
from src.models.schemas import Document
from src.models.typesafe import VerificationResult


@pytest.mark.asyncio
async def test_frozen_comparison_reuses_candidates_and_d_verifies_c_final_response():
    document = Document(id="real-1", content="Document", embedding=[], score=0.8)
    case = FrozenCase(
        id="case",
        query="Question",
        rewritten="Rewrite",
        documents=[document],
        expected_ids=["real-1"],
    )
    openai = MagicMock()
    openai.rerank = AsyncMock(return_value=[document])
    openai.generate_response = AsyncMock(return_value="Generated answer")
    openai.format_response = AsyncMock(return_value="Final answer")
    typesafe = MagicMock()
    typesafe.rerank = AsyncMock(return_value=[document])
    typesafe.verify = AsyncMock(return_value=VerificationResult(status="uncertain"))
    report = await compare_case(case, openai, typesafe)
    assert set(report["variants"]) == {"A", "B", "C", "D"}
    assert openai.rerank.await_args_list[0].kwargs["full_context"] is False
    assert openai.rerank.await_args_list[1].kwargs["full_context"] is True
    assert report["variants"]["C"]["response"] == typesafe.verify.await_args.args[1]
    assert not report["variants"]["D"]["would_deliver_candidate"]
    assert report["variants"]["D"]["delivered_response"] != report["variants"]["C"]["response"]
    assert report["variants"]["A"]["expected_sources_recall"] == 1


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not-json",
        json.dumps({"id": "test", "query": "test", "documents": [], "unexpected": True}),
    ],
)
def test_invalid_frozen_dataset_rejected(tmp_path, content):
    path = tmp_path / "cases.jsonl"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_cases(path)
