import pytest

from src.services.server_analysis import is_server_analysis, numeric_labels_in_sources


@pytest.mark.parametrize(
    "query",
    [
        "Faça uma análise de servidor",
        "Servidor 8/12 comporta até quantas conexões?",
        "Servidor atual 2/4, 66.8 K mensagens e 25 usuários; está ideal?",
        "Grafana: RAM esperada 4, vCPUs esperados 4. Precisa de upgrade?",
        "Cliente com servidor topado, preciso avaliar os recursos",
        "CPU Busy 95%, RAM esperada 4, Burstable esperado BASELINE_1_8",
        "Qual o servidor recomendado para 50 conexões WABA?",
    ],
)
def test_server_scope_recognizes_analysis(query):
    assert is_server_analysis(query)


@pytest.mark.parametrize(
    "query",
    [
        "Erro 500 Internal server error: hsm limit exceeded ao enviar template",
        "Como configurar servidor SMTP recomendado para e-mail?",
        "Como exportar contatos sem tags?",
        "Como configurar meu webhook?",
        "",
    ],
)
def test_server_scope_does_not_reclassify_other_topics(query):
    assert not is_server_analysis(query)


@pytest.mark.parametrize(
    ("query", "contents", "expected"),
    [
        ("Servidor 8/12", ["Tabela: 8/16, 2/4"], {"8/12": False}),
        ("Servidor 2/4 ou 8/12?", ["Perfil: 2/4", "Perfil: 8/12"], {"2/4": True, "8/12": True}),
        ("Servidor 8/12", ["Perfil: 18/12; 8/120; 8/12/2026"], {"8/12": False}),
        ("Servidor 2/4", [], {"2/4": False}),
        ("", ["Perfil: 2/4"], {}),
        ("Atualizado em 07/07/2026", ["Perfil: 2/4"], {}),
    ],
)
def test_numeric_labels_require_exact_source_presence(query, contents, expected):
    assert numeric_labels_in_sources(query, contents) == expected


@pytest.mark.parametrize(
    "query",
    [
        "qual recomendado",
        "qual seria o recomendado?",
        "o cliente ja utiliza um 16/16",
        "esse perfil aguenta?",
    ],
)
def test_server_followup_uses_recent_user_topic(query):
    history = (
        "[1] Usuário: Qual servidor recomendado para 11 conexões WhatsApp e 240 usuários?\n"
        "[1] Digi: Não é uma referência de dimensionamento.\n"
        "[2] Usuário: qual recomendado\n[2] Digi: Texto não confiável."
    )
    assert is_server_analysis(query, history)


@pytest.mark.parametrize(
    "query",
    [
        "Como exportar contatos sem tags?",
        "Erro 500 Internal server error",
        "Como configurar SMTP?",
        "Como configurar webhook?",
        "",
    ],
)
def test_explicit_other_topic_does_not_inherit_server_history(query):
    history = "[1] Usuário: Qual servidor recomendado para 11 conexões?\n[1] Digi: ..."
    assert not is_server_analysis(query, history)


@pytest.mark.parametrize(
    "history",
    [
        "",
        "texto sem formato: análise de servidor",
        "[1] Usuário: Como exportar contatos?\n[1] Digi: Qual servidor recomendado?",
        "[1] Usuário: Qual servidor recomendado?\n[1] Digi: ...\n[2] Usuário: Como configurar webhook?\n[2] Digi: ...",
        "[1] Usuário: Qual servidor recomendado?\n[1] Digi: ...\n[2] Usuário: qual recomendado\n[2] Digi: ...\n[3] Usuário: qual recomendado\n[3] Digi: ...\n[4] Usuário: qual recomendado\n[4] Digi: ...\n[5] Usuário: qual recomendado\n[5] Digi: ...",
    ],
)
def test_followup_does_not_infer_topic_from_bot_or_stale_unstructured_history(history):
    assert not is_server_analysis("qual recomendado", history)


def test_long_new_message_is_not_a_contextual_followup():
    history = "[1] Usuário: Qual servidor recomendado?\n[1] Digi: ..."
    assert not is_server_analysis("qual recomendado " + "x" * 240, history)
