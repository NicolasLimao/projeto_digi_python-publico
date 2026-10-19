"""Testes offline do detector de instabilidade (lógica pura, sem rede)."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_EVALS = Path(__file__).resolve().parents[1] / "evals"


def _carregar(nome: str):
    modulo_existente = sys.modules.get(nome)
    if modulo_existente is not None:
        return modulo_existente
    spec = importlib.util.spec_from_file_location(nome, _EVALS / f"{nome}.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo
    spec.loader.exec_module(modulo)
    return modulo


_carregar("run_eval")  # o detector faz `import run_eval`; registrar antes
det = _carregar("detectar_instabilidade")


def test_indice_zero_quando_unanime():
    assert det.indice_instabilidade(["aprovado"] * 5) == 0.0
    assert det.indice_instabilidade(["reprovado"] * 3) == 0.0


def test_indice_mede_divergencia():
    vereditos = ["aprovado", "reprovado", "aprovado", "reprovado", "aprovado"]
    assert det.indice_instabilidade(vereditos) == 0.4


def test_indice_ignora_erros_de_infra():
    assert det.indice_instabilidade(["aprovado", "erro", "erro", "aprovado"]) == 0.0
    assert det.indice_instabilidade(["aprovado", "reprovado", "erro"]) == 0.5
    assert det.indice_instabilidade(["erro", "erro"]) == 0.0


def test_contar_erros():
    assert det.contar_erros(["aprovado", "erro", "reprovado", "erro"]) == 2
    assert det.contar_erros(["aprovado"]) == 0


def test_conflito_potencial_por_datas():
    antigos_e_novos = [{"data": "2026-04-14"}, {"data": "2026-07-16"}]
    proximos = [{"data": "2026-05-01"}, {"data": "2026-05-20"}]
    sem_data = [{"data": None}, {"trecho": "x"}]
    um_so = [{"data": "2026-05-01"}]
    assert det.conflito_potencial(antigos_e_novos) is True
    assert det.conflito_potencial(proximos) is False
    assert det.conflito_potencial(sem_data) is False
    assert det.conflito_potencial(um_so) is False


def test_redigir_mascara_email_e_preserva_texto_normal():
    assert det._redigir("contate fulano.tal@exemplo.com para suporte") == (
        "contate [email] para suporte"
    )
    assert det._redigir("texto sem nenhum e-mail aqui") == "texto sem nenhum e-mail aqui"


def _resultados_sinteticos():
    instavel = det.ResultadoCaso(
        case_id="neg-008",
        pergunta="Quais IAs a plataforma digisac possui?",
        vereditos=["aprovado", "reprovado", "aprovado", "reprovado", "aprovado"],
        scores=[0.31, 0.38, 0.35, 0.33, 0.36],
        chunks=[
            {
                "ref": "discord-upload#1",
                "data": "2026-04-14",
                "trecho": "manual antigo",
                "score_busca": 0.4,
            },
            {
                "ref": "discord-upload#2",
                "data": "2026-07-16",
                "trecho": "material novo",
                "score_busca": 0.5,
            },
        ],
    )
    estavel = det.ResultadoCaso(
        case_id="pos-002",
        pergunta="o que são tags?",
        vereditos=["aprovado"] * 5,
        scores=[0.4] * 5,
        chunks=[
            {"ref": "discord-upload#3", "data": "2026-05-28", "trecho": "tags", "score_busca": 0.6}
        ],
    )
    return [estavel, instavel]


def test_relatorio_md_destaca_instaveis_e_conflito():
    md, _ = det.montar_relatorio(_resultados_sinteticos(), repeticoes=5, run_id="teste")
    assert "1 casos instáveis de 2" in md
    assert "neg-008" in md and "0.4" in md
    assert "CONFLITO DE DATAS" in md
    assert "pos-002" not in md.split("Estáveis")[0]  # estável não ganha seção própria
    assert "pos-002" in md.split("Estáveis")[1]


def test_relatorio_json_ordenado_e_sem_chave_vereditos_no_topo():
    _, estrutura = det.montar_relatorio(_resultados_sinteticos(), repeticoes=5, run_id="teste")
    assert "vereditos" not in estrutura  # invariante: não confundir o delta do run_eval
    assert estrutura["repeticoes"] == 5
    ids = [caso["id"] for caso in estrutura["casos"]]
    assert ids == ["neg-008", "pos-002"]  # mais instável primeiro
    assert estrutura["casos"][0]["conflito_potencial"] is True
    assert estrutura["casos"][0]["erros"] == 0


def _clientes_stub(itens: list[dict]):
    """Stubs do OpenAI (async) e do Supabase (sync, chamado via to_thread)."""
    openai_client = MagicMock()
    openai_client.embeddings.create = AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * 4)])
    )
    supabase_client = MagicMock()
    supabase_client.rpc.return_value.execute.return_value = SimpleNamespace(data=itens)
    return openai_client, supabase_client


@pytest.mark.asyncio
async def test_chunks_registram_o_id_real_do_documento():
    openai_client, supabase_client = _clientes_stub(
        [
            {
                "id": 1700,
                "content": "texto do chunk",
                "metadata": {
                    "fonte": "discord-upload",
                    "chunk_index": 37,
                    "data": "2026-05-02",
                },
                "score": 0.31,
            }
        ]
    )
    chunks = await det._chunks_do_caso(openai_client, supabase_client, "backup")
    assert chunks[0]["id"] == "1700"
    assert chunks[0]["ref"] == "discord-upload#37"  # `ref` continua no mapa


@pytest.mark.asyncio
async def test_chunk_sem_id_fica_com_string_vazia():
    openai_client, supabase_client = _clientes_stub(
        [{"content": "texto", "metadata": {"fonte": "discord-upload", "chunk_index": 1}}]
    )
    chunks = await det._chunks_do_caso(openai_client, supabase_client, "backup")
    assert chunks[0]["id"] == ""


def test_user_id_da_execucao_e_distinto_por_repeticao():
    a = det._user_id_da_execucao("stab_X", "neg-008", 0)
    b = det._user_id_da_execucao("stab_X", "neg-008", 1)
    assert a == "stab_X_neg-008_0"
    assert a != b


@pytest.mark.asyncio
async def test_rodar_caso_gera_user_id_distinto_por_repeticao():
    postados: list[str] = []

    async def fake_post(url, **kwargs):
        postados.append(kwargs["params"]["user_id"])
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"response": "r", "score": 0.5},
        )

    http = MagicMock()
    http.post = fake_post
    juiz = MagicMock()
    juiz.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"veredito": "aprovado", "motivo": "ok"}')
                )
            ]
        )
    )
    juiz.embeddings.create = AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * 4)])
    )
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value = SimpleNamespace(data=[])
    caso = det.run_eval.EvalCase(
        id="neg-008",
        origem="feedback_negativo",
        modo="orientacao",
        pergunta="p?",
        fatos_esperados=["f"],
    )
    await det._rodar_caso(
        caso, http, juiz, sb, "http://x", "tok", "stab_RUN", 3, asyncio.Semaphore(5)
    )
    assert len(postados) == 3
    assert set(postados) == {"stab_RUN_neg-008_0", "stab_RUN_neg-008_1", "stab_RUN_neg-008_2"}
