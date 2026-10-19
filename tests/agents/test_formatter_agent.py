import pytest

from src.agents.formatter_agent import FormatterAgent


@pytest.fixture
def formatter() -> FormatterAgent:
    return FormatterAgent()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["orientacao", "resposta-cliente", "bug"])
async def test_formatter_preserves_model_formatting(formatter: FormatterAgent, mode: str):
    response = "1. Primeiro passo\n\n- detalhe importante"
    assert await formatter.execute(response, mode) == response


@pytest.mark.asyncio
async def test_formatter_trims_outer_whitespace(formatter: FormatterAgent):
    assert await formatter.execute("  resposta pronta \n", "orientacao") == "resposta pronta"


@pytest.mark.asyncio
async def test_formatter_handles_empty_response(formatter: FormatterAgent):
    assert await formatter.execute("", "bug") == ""
