import pytest

from src.services import curadoria

CURADO = (
    "Pergunta: Como contratar usuario na plataforma?\n"
    "Resposta oficial validada pelo analista: Acesse Meu Plano e ajuste a quantidade."
)


def test_reconhece_texto_curado():
    assert curadoria.eh_texto_curado(CURADO)
    assert not curadoria.eh_texto_curado("No Menu Principal, clique em Mais Opcoes.")


def test_extrai_pergunta_do_bloco():
    assert curadoria.extrair_pergunta(CURADO) == "Como contratar usuario na plataforma?"


def test_extrai_pergunta_com_quebras_e_multiplas_linhas():
    texto = (
        "Pergunta: Opa bom dia!!\nGostaria de puxar a quantidade de leads?\n"
        "Resposta oficial validada pelo analista: Acesse Visao Geral."
    )
    assert curadoria.extrair_pergunta(texto) == (
        "Opa bom dia!!\nGostaria de puxar a quantidade de leads?"
    )


def test_texto_sem_marcador_nao_tem_pergunta():
    assert curadoria.extrair_pergunta("Pergunta: e ai?") is None


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Como contratar usuario na plataforma?", "como  CONTRATAR usuário na plataforma"),
        ("Exclusão de conexão!", "exclusao de conexao"),
    ],
)
def test_normalizacao_ignora_acento_caixa_pontuacao_e_espaco(a: str, b: str):
    assert curadoria.normalizar_pergunta(a) == curadoria.normalizar_pergunta(b)


def test_normalizacao_separa_perguntas_diferentes():
    assert curadoria.normalizar_pergunta("criar usuario") != curadoria.normalizar_pergunta(
        "excluir usuario"
    )


def test_documento_curado_vem_do_metadata_nao_do_conteudo():
    """Conteudo e dado nao confiavel: so o metadata concede autoridade."""
    assert curadoria.eh_documento_curado({"tipo": "curadoria"})
    assert not curadoria.eh_documento_curado({"fonte": "discord-text"})
    assert not curadoria.eh_documento_curado({})


def test_documento_substituido_e_reconhecido():
    assert curadoria.foi_substituido({"tipo": "curadoria", "substituido_por": "2861"})
    assert not curadoria.foi_substituido({"tipo": "curadoria"})


def test_metadata_de_curadoria_carrega_tipo_e_pergunta_normalizada():
    meta = curadoria.metadata_curadoria(CURADO)
    assert meta["tipo"] == "curadoria"
    assert meta["pergunta_norm"] == curadoria.normalizar_pergunta(
        "Como contratar usuario na plataforma?"
    )


def test_metadata_vazio_para_texto_comum():
    assert curadoria.metadata_curadoria("texto qualquer do manual") == {}
