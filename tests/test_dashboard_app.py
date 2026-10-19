import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import dados
from tests.fakes import FakeSupabaseClient


@pytest.mark.parametrize("token", [None, "test-token"])
@pytest.mark.parametrize("database_failure", [False, True])
def test_ingestion_renders_without_reconciliation_map_or_curation_token(
    monkeypatch, token, database_failure
):
    st.cache_resource.clear()
    st.cache_data.clear()
    env = {"SUPABASE_SERVICE_ROLE_KEY": "test", "OPENAI_API_KEY": "test"}
    if token:
        env["API_AUTH_TOKEN"] = token
    monkeypatch.setattr(dados, "carregar_env", lambda: env)
    monkeypatch.setattr(dados, "criar_cliente_supabase", lambda env: FakeSupabaseClient())
    monkeypatch.setattr(dados, "carregar_mapa_instabilidade", lambda directory: None)
    monkeypatch.setattr(dados, "gerar_relatorio_pdf", lambda text: b"pdf-test")
    monkeypatch.setattr(dados, "ultimo_baseline", lambda directory: None)
    monkeypatch.setattr(dados, "duvidas_eval", lambda *args: [])
    if database_failure:

        def fail(*args):
            raise RuntimeError("secret database error")

        monkeypatch.setattr(dados, "listar_raw", fail)
    app = AppTest.from_file("dashboard/app.py").run(timeout=30)
    assert not app.exception
    assert any(title.value == "Ingestão de documentos (cru)" for title in app.subheader)
    assert len(app.get("file_uploader")) == 1
    assert all("secret" not in message.value for message in app.error)
    if database_failure:
        assert any("Confira o resultado" in message.value for message in app.error)
    st.cache_resource.clear()
    st.cache_data.clear()
