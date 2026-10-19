"""Testes offline do runner de avaliação (sem rede, sem OpenAI)."""

import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_eval", Path(__file__).resolve().parents[1] / "evals" / "run_eval.py"
)
run_eval = importlib.util.module_from_spec(_SPEC)
sys.modules["run_eval"] = run_eval
_SPEC.loader.exec_module(run_eval)


def test_load_dataset_le_o_dataset_publico():
    casos = run_eval.load_dataset(run_eval.DATASET_PATH)
    assert len(casos) >= 25
    assert all(caso.fatos_esperados for caso in casos)


def test_runner_usa_api_local_por_padrao():
    assert run_eval.DEFAULT_API_URL == "http://localhost:8000/api/rag/query"


def test_load_dataset_rejeita_ids_duplicados(tmp_path):
    linha = json.dumps(
        {
            "id": "x-001",
            "origem": "feedback_positivo",
            "modo": "orientacao",
            "pergunta": "p?",
            "fatos_esperados": ["f"],
        }
    )
    arquivo = tmp_path / "d.jsonl"
    arquivo.write_text(linha + "\n" + linha + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicado"):
        run_eval.load_dataset(arquivo)


def test_build_judge_prompt_inclui_rubrica():
    caso = run_eval.EvalCase(
        id="neg-001",
        origem="feedback_negativo",
        modo="orientacao",
        pergunta="Tem limite de arquivos?",
        fatos_esperados=["cita o limite por arquivo"],
        erros_proibidos=["afirmar que não há limite"],
    )
    prompt = run_eval.build_judge_prompt(caso, "resposta do bot")
    assert "cita o limite por arquivo" in prompt
    assert "afirmar que não há limite" in prompt
    assert "resposta do bot" in prompt


def test_parse_judge_response_feliz():
    veredito, motivo = run_eval.parse_judge_response(
        '{"veredito": "aprovado", "motivo": "cobre os fatos"}'
    )
    assert veredito == "aprovado"
    assert motivo == "cobre os fatos"


def test_parse_judge_response_invalida_vira_erro():
    veredito, motivo = run_eval.parse_judge_response("não sou json")
    assert veredito == "erro"
    assert "parseável" in motivo


def test_calcular_delta_sem_anteriores_retorna_none():
    resultados = [run_eval.CaseResult("neg-001", "aprovado", "ok")]
    assert run_eval._calcular_delta(resultados, None) is None


def test_calcular_delta_identifica_regressoes_e_correcoes():
    resultados = [
        run_eval.CaseResult("neg-001", "reprovado", "piorou"),
        run_eval.CaseResult("neg-002", "aprovado", "melhorou"),
        run_eval.CaseResult("neg-003", "aprovado", "manteve"),
    ]
    anteriores = {"neg-001": "aprovado", "neg-002": "reprovado", "neg-003": "aprovado"}
    regressoes, correcoes = run_eval._calcular_delta(resultados, anteriores)
    assert regressoes == ["neg-001"]
    assert correcoes == ["neg-002"]


def test_sanitizar_md_celula_escapa_pipe_e_remove_quebras():
    texto = "motivo com | pipe\ne quebra\r\nde linha"
    resultado = run_eval._sanitizar_md_celula(texto)
    assert "\n" not in resultado
    assert "\r" not in resultado
    assert "\\|" in resultado


def test_vereditos_anteriores_ignora_rodadas_parciais(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "REPORTS_DIR", tmp_path)
    (tmp_path / "2026-01-01-0000.json").write_text(
        json.dumps({"run": "a", "parcial": False, "vereditos": {"neg-001": "aprovado"}}),
        encoding="utf-8",
    )
    (tmp_path / "2026-01-02-0000.json").write_text(
        json.dumps({"run": "b", "parcial": True, "vereditos": {"neg-001": "reprovado"}}),
        encoding="utf-8",
    )
    anteriores = run_eval._vereditos_anteriores()
    assert anteriores == {"neg-001": "aprovado"}


def test_user_id_do_caso_e_distinto_por_repeticao_e_nao_numerico():
    a = run_eval._user_id_do_caso("eval_20260101", "neg-001", 0)
    b = run_eval._user_id_do_caso("eval_20260101", "neg-001", 1)
    assert a == "eval_20260101_neg-001_0"
    assert a != b
    # analytics exclui só ids puramente numéricos; o formato não pode virar numérico
    assert not re.fullmatch(r"[0-9]+", a)


@pytest.mark.asyncio
async def test_rodar_caso_agrega_repeticoes_e_isola_user_id():
    postados: list[str] = []
    # 3 respostas do bot; o juiz aprova as 2 primeiras e reprova a 3ª
    respostas = iter(["ok1", "ok2", "ruim"])
    vereditos_juiz = iter(
        [
            '{"veredito": "aprovado", "motivo": "cobre"}',
            '{"veredito": "aprovado", "motivo": "cobre"}',
            '{"veredito": "reprovado", "motivo": "faltou"}',
        ]
    )

    async def fake_post(url, **kwargs):
        postados.append(kwargs["params"]["user_id"])
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"response": next(respostas), "score": 0.5, "processing_time_ms": 10},
        )

    http = MagicMock()
    http.post = fake_post
    juiz = MagicMock()

    async def fake_juiz(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(vereditos_juiz)))]
        )

    juiz.chat.completions.create = fake_juiz
    caso = run_eval.EvalCase(
        id="neg-042",
        origem="feedback_negativo",
        modo="orientacao",
        pergunta="p?",
        fatos_esperados=["f"],
    )
    resultado = await run_eval._rodar_caso(
        caso, http, juiz, "http://x", "tok", "eval_RUN", 3, asyncio.Semaphore(1)
    )
    assert resultado.veredito == "aprovado"  # 2 de 3 -> maioria
    assert resultado.aprovados == 2
    assert resultado.execucoes == 3
    assert set(postados) == {"eval_RUN_neg-042_0", "eval_RUN_neg-042_1", "eval_RUN_neg-042_2"}


def test_agregar_vereditos_maioria_estrita():
    assert run_eval._agregar_vereditos(
        ["aprovado", "aprovado", "aprovado", "reprovado", "reprovado"]
    ) == (
        "aprovado",
        3,
        5,
    )
    assert run_eval._agregar_vereditos(
        ["aprovado", "aprovado", "reprovado", "reprovado", "reprovado"]
    ) == (
        "reprovado",
        2,
        5,
    )


def test_agregar_vereditos_empate_reprova():
    # 2 aprovado / 2 reprovado: 2*2 > 4 é falso -> reprovado
    assert run_eval._agregar_vereditos(["aprovado", "aprovado", "reprovado", "reprovado"]) == (
        "reprovado",
        2,
        4,
    )


def test_agregar_vereditos_ignora_erros_na_contagem():
    # erro não conta em execucoes; maioria é sobre os válidos (2 de 2 válidos)
    assert run_eval._agregar_vereditos(["aprovado", "aprovado", "erro"]) == ("aprovado", 2, 2)


def test_agregar_vereditos_tudo_erro_vira_erro():
    assert run_eval._agregar_vereditos(["erro", "erro"]) == ("erro", 0, 0)


def test_classificar_estabilidade():
    assert run_eval._classificar(5, 5) == "estavel_aprova"
    assert run_eval._classificar(0, 5) == "estavel_reprova"
    assert run_eval._classificar(3, 5) == "instavel"
    # sem execução válida não é "estável"
    assert run_eval._classificar(0, 0) == "instavel"


def test_relatorio_traz_maioria_classes_e_taxas(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "REPORTS_DIR", tmp_path)
    resultados = [
        run_eval.CaseResult(
            "a", "aprovado", "cobre", score=0.5, tempo_ms=10, aprovados=5, execucoes=5
        ),
        run_eval.CaseResult(
            "b", "reprovado", "faltou", score=0.4, tempo_ms=12, aprovados=0, execucoes=5
        ),
        run_eval.CaseResult(
            "c", "aprovado", "cobre", score=0.3, tempo_ms=8, aprovados=3, execucoes=5
        ),
    ]
    caminho = run_eval._escrever_relatorio(resultados, "2026-07-24-0000", None, parcial=False)
    md = caminho.read_text(encoding="utf-8")
    assert "2/3 aprovados por maioria" in md
    # classes: a=estavel_aprova, b=estavel_reprova, c=instavel
    assert "estável-aprova: 1" in md
    assert "instável: 1" in md
    assert "estável-reprova: 1" in md
    assert "3/5" in md  # taxa do caso c aparece na tabela
    dados = json.loads((tmp_path / "2026-07-24-0000.json").read_text(encoding="utf-8"))
    assert dados["vereditos"] == {"a": "aprovado", "b": "reprovado", "c": "aprovado"}
    assert dados["taxas"] == {"a": "5/5", "b": "0/5", "c": "3/5"}
