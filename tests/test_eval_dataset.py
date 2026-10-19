"""Valida o schema do dataset de avaliação. Offline e grátis — roda no CI."""

import json
from pathlib import Path

DATASET = Path(__file__).resolve().parents[1] / "evals" / "dataset.jsonl"
ORIGENS_VALIDAS = {"feedback_negativo", "feedback_positivo", "sintetico"}
MODOS_VALIDOS = {"orientacao", "resposta-cliente", "bug"}
CAMPOS_PERMITIDOS = {
    "id",
    "origem",
    "modo",
    "pergunta",
    "fatos_esperados",
    "erros_proibidos",
    "resposta_anterior",
    "notas",
}


def _casos() -> list[dict]:
    linhas = DATASET.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(linha) for linha in linhas]


def test_dataset_existe_e_tem_volume_minimo():
    assert DATASET.exists(), "evals/dataset.jsonl não encontrado"
    assert len(_casos()) >= 25


def test_campos_obrigatorios_e_valores_validos():
    for caso in _casos():
        assert set(caso) <= CAMPOS_PERMITIDOS, f"{caso['id']}: campo desconhecido"
        assert caso["id"].strip()
        assert caso["origem"] in ORIGENS_VALIDAS
        assert caso["modo"] in MODOS_VALIDOS
        assert caso["pergunta"].strip()
        assert isinstance(caso["fatos_esperados"], list) and caso["fatos_esperados"]
        assert all(isinstance(f, str) and f.strip() for f in caso["fatos_esperados"])
        assert isinstance(caso.get("erros_proibidos", []), list)


def test_ids_unicos():
    ids = [caso["id"] for caso in _casos()]
    assert len(ids) == len(set(ids))


def test_negativos_carregam_resposta_anterior():
    for caso in _casos():
        if caso["origem"] == "feedback_negativo":
            assert caso.get("resposta_anterior", "").strip(), f"{caso['id']} sem resposta_anterior"
