"""Dashboard do Digi — rode com: streamlit run dashboard/app.py"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import altair as alt
import httpx
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard import dados
from src.logger import get_logger

logger = get_logger(__name__)

st.set_page_config(page_title="Digi Dashboard", page_icon="🤖", layout="wide")

ENV = dados.carregar_env()
API_BASE = os.environ.get("DIGI_API_BASE") or ENV.get("DIGI_API_BASE") or dados.DEFAULT_API_BASE


@st.cache_resource(show_spinner=False)
def _cliente() -> Any:
    return dados.criar_cliente_supabase(ENV)


@st.cache_resource(show_spinner=False)
def _openai() -> Any:
    from openai import OpenAI

    return OpenAI(api_key=ENV.get("OPENAI_API_KEY", ""))


@st.cache_data(ttl=300, show_spinner="Consultando Supabase...")
def _view(nome: str) -> list[dict[str, Any]]:
    resposta = _cliente().table(nome).select("*").execute()
    return list(resposta.data or [])


def _limpar_caches() -> None:
    _view.clear()
    for chave in [k for k in st.session_state if k.startswith("custos_")]:
        del st.session_state[chave]


st.title("🤖 Digi — Dashboard")
st.caption(f"API: {API_BASE} • dados do Supabase • atualizados a cada 5 min")

try:
    resumo_rows = _view("v_feedback_resumo")
except Exception:
    st.error(
        "Não consegui consultar o Supabase. Confira SUPABASE_URL e a chave no .env "
        "e sua conexão, depois recarregue."
    )
    st.stop()

resumo: dict[str, Any] = resumo_rows[0] if resumo_rows else {}
volume = _view("v_volume_diario")
por_modo = _view("v_por_modo")
por_canal = _view("v_por_canal")
baseline = dados.ultimo_baseline(dados.REPORTS_DIR)

# Dúvidas pendentes calculadas ANTES das abas: o export (aba 1) também as usa.
erro_duvidas: str | None = None
lista_pendentes: list[dados.Duvida] = []
producao: list[dados.Duvida] = []
eval_: list[dados.Duvida] = []

try:
    respondidas = dados.chaves_respondidas(_cliente())
except Exception:
    erro_duvidas = (
        "Não consegui ler a tabela duvidas_respondidas. "
        "Rode sql/duvidas_respondidas.sql no Supabase SQL Editor."
    )
    respondidas = set()

try:
    producao = dados.duvidas_producao(_view("v_negativos"))
    eval_ = dados.duvidas_eval(dados.DATASET_PATH, baseline["vereditos"] if baseline else None)
    lista_pendentes = dados.pendentes(producao, eval_, respondidas)
except Exception:
    logger.warning("Unable to load pending questions")
    erro_duvidas = "Não foi possível carregar as fontes de dúvidas agora."

aba_metricas, aba_duvidas, aba_reconciliacao, aba_ingestao = st.tabs(
    ["📊 Métricas", "❓ Dúvidas pendentes", "🧩 Reconciliação", "📥 Ingestão"]
)

# ---------------------------------------------------------------- Métricas
with aba_metricas:
    dias = st.radio(
        "Período", [7, 30, 90], index=1, horizontal=True, format_func=lambda d: f"{d} dias"
    )
    hoje = datetime.now(UTC).date()
    atual, anterior = dados.janelas_volume(volume, dias, hoje)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric(
        "Interações (janela)",
        atual["interacoes"],
        delta=atual["interacoes"] - anterior["interacoes"],
    )
    col2.metric(
        "Positivos (janela)",
        atual["positivos"],
        delta=atual["positivos"] - anterior["positivos"],
    )
    col3.metric(
        "Negativos (janela)",
        atual["negativos"],
        delta=atual["negativos"] - anterior["negativos"],
        delta_color="inverse",
    )
    col4.metric("Taxa de aprovação (geral)", f"{resumo.get('taxa_aprovacao_pct', 0)}%")
    if baseline:
        delta_eval = baseline.get("delta")
        col5.metric(
            "Eval (último baseline)",
            f"{baseline['aprovados']}/{baseline['total']}",
            delta=delta_eval if isinstance(delta_eval, int) else None,
        )
    else:
        col5.metric("Eval", "—")
        col5.caption("Rode `evals/run_eval.py` para gerar o baseline.")

    st.subheader("Volume diário")
    longo = dados.preparar_volume_grafico(volume, dias, hoje)
    if longo:
        grafico = (
            alt.Chart(pd.DataFrame(longo))
            .mark_bar(stroke="#1a1a19", strokeWidth=2)
            .encode(
                x=alt.X("dia:T", title=None),
                y=alt.Y("sum(quantidade):Q", title="Interações"),
                color=alt.Color(
                    "categoria:N",
                    scale=alt.Scale(
                        domain=["Positivos", "Sem avaliação", "Negativos"],
                        range=[
                            dados.COR_POSITIVO,
                            dados.COR_SEM_AVALIACAO,
                            dados.COR_NEGATIVO,
                        ],
                    ),
                    legend=alt.Legend(title=None, orient="top"),
                ),
                order=alt.Order("ordem:Q"),
                tooltip=[
                    alt.Tooltip("dia:T", title="Dia"),
                    alt.Tooltip("categoria:N", title="Categoria"),
                    alt.Tooltip("quantidade:Q", title="Quantidade"),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(grafico, use_container_width=True)
    else:
        st.info("Sem interações no período selecionado.")

    col_modo, col_canal = st.columns(2)

    def _barras(titulo: str, linhas: list[dict[str, Any]], dimensao: str) -> Any:
        return (
            alt.Chart(pd.DataFrame(linhas))
            .mark_bar(color=dados.COR_SERIE, stroke="#1a1a19", strokeWidth=2)
            .encode(
                x=alt.X("interacoes:Q", title="Interações"),
                y=alt.Y(f"{dimensao}:N", sort="-x", title=None),
                tooltip=[dimensao, "interacoes", "positivos", "negativos"],
            )
            .properties(height=180, title=titulo)
        )

    with col_modo:
        if por_modo:
            st.altair_chart(_barras("Por modo", por_modo, "modo"), use_container_width=True)
            st.dataframe(pd.DataFrame(por_modo), use_container_width=True, hide_index=True)
    with col_canal:
        if por_canal:
            st.altair_chart(_barras("Por canal", por_canal, "canal"), use_container_width=True)
            st.dataframe(pd.DataFrame(por_canal), use_container_width=True, hide_index=True)

    st.subheader("Custos de IA (OpenAI)")
    chave_admin = ENV.get("OPENAI_ADMIN_KEY")
    if not chave_admin:
        st.info(
            "Para ver custo e tokens por dia, crie uma Admin API key em "
            "platform.openai.com → Settings → Organization → Admin keys e adicione "
            "`OPENAI_ADMIN_KEY=...` ao .env."
        )
    else:
        try:
            custos = st.session_state.get(f"custos_{dias}")
            if custos is None:
                custos = dados.custos_openai(chave_admin, dias)
                st.session_state[f"custos_{dias}"] = custos
        except (httpx.HTTPError, ValueError):
            st.warning("Não consegui consultar a API de custos da OpenAI: serviço indisponível")
        else:
            if custos and custos["por_dia"]:
                col_a, col_b = st.columns([1, 3])
                col_a.metric("Custo no período", f"US$ {custos['custo_total_usd']:.2f}")
                grafico_custos = (
                    alt.Chart(pd.DataFrame(custos["por_dia"]))
                    .mark_bar(color=dados.COR_SERIE, stroke="#1a1a19", strokeWidth=2)
                    .encode(
                        x=alt.X("dia:T", title=None),
                        y=alt.Y("custo_usd:Q", title="US$/dia"),
                        tooltip=["dia", "custo_usd", "tokens_entrada", "tokens_saida"],
                    )
                    .properties(height=200)
                )
                col_b.altair_chart(grafico_custos, use_container_width=True)
            else:
                st.info("Sem consumo registrado no período.")

    st.divider()
    st.subheader("Exportar relatório")
    relatorio_md = dados.gerar_relatorio_md(
        resumo,
        por_modo,
        por_canal,
        baseline,
        lista_pendentes,
        dias,
        datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        erro_duvidas=erro_duvidas,
    )
    formato = st.radio("Formato", ["TXT/Markdown", "PDF"], horizontal=True)
    carimbo = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    if formato == "TXT/Markdown":
        st.download_button(
            "⬇️ Baixar relatório (.md)",
            relatorio_md.encode("utf-8"),
            file_name=f"relatorio-digi-{carimbo}.md",
            mime="text/markdown",
        )
    else:
        st.download_button(
            "⬇️ Baixar relatório (.pdf)",
            dados.gerar_relatorio_pdf(relatorio_md),
            file_name=f"relatorio-digi-{carimbo}.pdf",
            mime="application/pdf",
        )


# --------------------------------------------------------- Dúvidas pendentes
def _render_aba_duvidas() -> None:
    token = ENV.get("API_AUTH_TOKEN")
    if not token:
        st.error("API_AUTH_TOKEN ausente no .env — necessário para ensinar o bot.")
        return
    if erro_duvidas:
        st.error(erro_duvidas)
        return

    lista = lista_pendentes

    topo_a, topo_b = st.columns([4, 1])
    topo_a.caption(
        f"{len(lista)} pendentes • {len(producao)} negativos de produção • "
        f"{len(eval_)} dúvidas do eval • {len(respondidas)} já respondidas"
    )
    if topo_b.button("🔄 Recarregar"):
        _limpar_caches()
        st.rerun()

    if not lista:
        st.success("🎉 Nenhuma dúvida pendente — tudo respondido!")

    for duvida in lista:
        rotulo_origem = "🔴 produção" if duvida.origem == "producao" else "🧪 eval"
        with st.expander(f"{rotulo_origem} · {duvida.pergunta[:100]}"):
            st.markdown(f"**Pergunta completa:**\n\n> {duvida.pergunta}")
            if duvida.resposta_ruim:
                st.markdown("**Resposta que o bot deu (avaliada como ruim):**")
                st.code(duvida.resposta_ruim, language=None, wrap_lines=True)
            detalhes = [f"modo: {duvida.modo}"]
            if duvida.score is not None:
                detalhes.append(f"score: {duvida.score:.2f}")
            if duvida.veredito:
                detalhes.append(f"veredito do juiz: {duvida.veredito}")
            if duvida.timestamp:
                detalhes.append(f"em: {duvida.timestamp[:16]}")
            st.caption(" • ".join(detalhes))

            with st.form(key=f"form_{duvida.chave}"):
                resposta = st.text_area(
                    "Resposta correta (será ensinada ao bot)",
                    key=f"resp_{duvida.chave}",
                    height=160,
                    placeholder="Escreva a resposta oficial, como um analista experiente…",
                )
                enviado = st.form_submit_button("✅ Responder e ensinar ao bot")

            if enviado:
                if len(resposta.strip()) < 20:
                    st.error("Escreva uma resposta com pelo menos 20 caracteres.")
                else:
                    try:
                        resultado = dados.ingerir_resposta(
                            API_BASE,
                            token,
                            dados.texto_ingestao(duvida.pergunta, resposta),
                        )
                    except (httpx.HTTPError, ValueError):
                        logger.warning("Curation ingestion not confirmed")
                        st.error(
                            "Ingestão não confirmada. A dúvida continua pendente; confira a operação antes de repetir."
                        )
                    else:
                        chunks = int(resultado.get("chunks_created") or 0)
                        try:
                            dados.registrar_resposta(_cliente(), duvida, resposta, chunks)
                        except Exception:
                            st.warning(
                                "A resposta FOI ingerida no RAG, mas falhou ao registrar "
                                "na tabela duvidas_respondidas. NÃO responda de novo — "
                                "insira o registro manualmente para não duplicar."
                            )
                        else:
                            st.toast(f"Bot ensinado! {chunks} chunks criados.", icon="🎓")
                            _limpar_caches()
                            st.rerun()

            st.caption("Ou, se a resposta do bot estava certa / a pergunta não vale correção:")
            with st.form(key=f"desc_{duvida.chave}"):
                col_motivo, col_botao = st.columns([3, 1])
                motivo_id = col_motivo.selectbox(
                    "Motivo do descarte",
                    options=list(dados.MOTIVOS_DESCARTE),
                    format_func=lambda item: dados.MOTIVOS_DESCARTE[item],
                    key=f"motivo_{duvida.chave}",
                    label_visibility="collapsed",
                )
                descartado = col_botao.form_submit_button("🗑️ Descartar")

            if descartado:
                try:
                    dados.descartar_duvida(_cliente(), duvida, dados.MOTIVOS_DESCARTE[motivo_id])
                except Exception:
                    logger.warning("Discard failed")
                    st.error("Falha ao descartar — a dúvida continua pendente.")
                else:
                    st.toast("Dúvida descartada (nada foi ensinado ao bot).", icon="🗑️")
                    _limpar_caches()
                    st.rerun()


# ------------------------------------------------------------- Reconciliação

with aba_duvidas:
    _render_aba_duvidas()


def _render_aba_reconciliacao() -> None:
    st.caption(
        "Edite chunks conflitantes apontados pelo mapa de instabilidade. "
        "O original vai para backup local antes de qualquer alteração."
    )
    if not ENV.get("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY ausente no .env — necessário para re-embedar o texto editado.")
        return

    mapa = dados.carregar_mapa_instabilidade(dados.REPORTS_DIR)
    if not mapa:
        st.info(
            "Nenhum mapa de instabilidade encontrado. Rode "
            "`evals/detectar_instabilidade.py` para gerar."
        )
        return

    suspeitos = dados.chunks_suspeitos(mapa)
    if dados.mapa_sem_ref(suspeitos):
        st.warning(
            "O mapa carregado foi gerado por uma versão anterior do detector e não "
            "traz a referência dos chunks (`ref`), então eles não podem ser localizados. "
            "Rode `evals/detectar_instabilidade.py` para gerar um mapa novo."
        )
        return

    st.caption(
        f"{len(suspeitos)} chunks suspeitos (dos casos instáveis do mapa {mapa.get('run', '?')})."
    )

    for suspeito in suspeitos:
        try:
            resolvidos = dados.resolver_chunk(_cliente(), suspeito["ref"], suspeito["trecho"])
        except Exception:  # falha de rede não derruba a aba
            logger.warning("Chunk resolution failed")
            st.warning("Não foi possível consultar o chunk agora.")
            continue

        if not resolvidos:
            st.caption(f"⚠️ `{suspeito['ref']}` não encontrado (já editado/removido?).")
            continue

        for linha in resolvidos:
            rotulo = dados.classificar_idade(suspeito["data"])
            emoji = "🟢 curado" if rotulo == "curado" else "📄 manual"
            with st.expander(f"{emoji} · id {linha['id']} · caso {suspeito['caso_id']}"):
                novo = st.text_area(
                    "Conteúdo do chunk (edite para corrigir o conflito)",
                    value=linha["content"],
                    key=f"cont_{linha['id']}",
                    height=280,
                )
                if st.button("💾 Salvar correção", key=f"salvar_{linha['id']}"):
                    if novo.strip() == linha["content"].strip():
                        st.info("Nenhuma alteração no texto.")
                    elif len(novo.strip()) < 20:
                        st.error("O conteúdo precisa ter pelo menos 20 caracteres.")
                    else:
                        try:
                            original = dados.buscar_documento(_cliente(), linha["id"])
                            if original is None:
                                st.error("Chunk sumiu do banco; recarregue a aba.")
                            else:
                                caminho = (
                                    dados.BACKUPS_DIR
                                    / f"documents-{datetime.now(UTC).strftime('%Y-%m-%d')}.jsonl"
                                )
                                dados.salvar_backup(caminho, dados.montar_backup(original))
                                embedding = dados.reembed(_openai(), novo)
                                dados.atualizar_chunk(_cliente(), linha["id"], novo, embedding)
                        except Exception:
                            logger.warning("Chunk correction not confirmed")
                            st.error(
                                "Não foi possível confirmar a correção. Confira a operação antes de repetir."
                            )
                        else:
                            st.toast(f"Chunk {linha['id']} corrigido e re-embedado.", icon="🧩")
                            _limpar_caches()
                            st.rerun()


# ---------------------------------------------------------------- Ingestão

with aba_reconciliacao:
    _render_aba_reconciliacao()


def _render_aba_ingestao() -> None:
    st.subheader("Ingestão de documentos (cru)")
    env = dados.carregar_env()
    mistral_key = env.get("MISTRAL_API_KEY", "")
    if not env.get("SUPABASE_SERVICE_ROLE_KEY"):
        st.info("Configure SUPABASE_SERVICE_ROLE_KEY no .env para usar a ingestão.")
    else:
        cliente_sb = _cliente()
        arquivo = st.file_uploader(
            "Arquivo (PDF, TXT, MD ou JSON)", type=["pdf", "txt", "md", "json"]
        )
        nome = st.text_input("Nome do documento", value=arquivo.name if arquivo else "")
        fonte_alvo = st.text_input("fonte_alvo (ex.: manual, api)", value="")
        if st.button("Salvar cru", disabled=not (arquivo and nome and fonte_alvo)):
            assert arquivo is not None  # botão desabilitado quando não há arquivo
            ext = arquivo.name.lower()
            tipo = "pdf" if ext.endswith(".pdf") else ("api" if ext.endswith(".json") else "texto")
            if tipo == "pdf" and not mistral_key:
                st.error("PDF exige MISTRAL_API_KEY no .env.")
            else:
                with st.spinner("Extraindo texto..."):
                    texto = dados.extrair_texto(
                        cliente_sb, mistral_key, arquivo.getvalue(), tipo, arquivo.name
                    )
                    dados.salvar_raw(cliente_sb, dados.montar_raw(nome, fonte_alvo, tipo, texto))
                st.success(f"Salvo: {len(texto)} caracteres extraídos.")

        st.divider()
        st.markdown("**Documentos crus**")
        for linha in dados.listar_raw(cliente_sb):
            rotulo = (
                f"{linha['nome']} · {linha['tipo']} · {linha['n_chars']} chars · {linha['status']}"
            )
            with st.expander(rotulo):
                completo = (
                    cliente_sb.table("raw_documents")
                    .select("texto")
                    .eq("id", linha["id"])
                    .execute()
                )
                st.text((completo.data or [{}])[0].get("texto", "")[:5000])

                fonte = linha["fonte_alvo"]
                if linha["status"] == "cru" and fonte in dados.LOTES_ANTIGOS:
                    lote = dados.LOTES_ANTIGOS[fonte]
                    n_antigos = lote["id_max"] - lote["id_min"] + 1
                    chave = f"previa_{linha['id']}"
                    if st.button("Gerar prévia do re-chunk", key=f"btn_previa_{linha['id']}"):
                        texto_cru = (completo.data or [{}])[0].get("texto", "")
                        if linha["tipo"] == "api":
                            chunks_previa = dados.chunk_postman(texto_cru)
                        else:
                            chunks_previa = dados.chunk_contextual_estrutural(texto_cru)
                        tamanhos = [len(c["texto"]) for c in chunks_previa]
                        st.session_state[chave] = {"n": len(chunks_previa), "tam": tamanhos}
                    if chave in st.session_state:
                        prev = st.session_state[chave]
                        tam = prev["tam"]
                        media = sum(tam) // len(tam) if tam else 0
                        st.info(
                            f"{prev['n']} chunks novos (médio {media}, "
                            f"máx {max(tam) if tam else 0} chars) — "
                            f"substituem ~{n_antigos} chunks antigos do lote {lote['data_prefixo']}. "
                            f"Custo estimado: contexto LLM ~US$3 + embedding ~US$0,02."
                        )
                        st.warning(
                            "Confirmar publica os novos e APAGA o lote antigo (com backup). "
                            "Roda o passo de contexto por LLM (lento)."
                        )
                        if st.button("Confirmar publicação", key=f"btn_conf_{linha['id']}"):
                            openai_client = dados.criar_cliente_openai(env)
                            with st.spinner("Contextualizando, embutindo e publicando..."):
                                res = dados.publicar_lote(
                                    cliente_sb, openai_client, linha["id"], fonte, dados.BACKUPS_DIR
                                )
                            del st.session_state[chave]
                            aviso = f" ⚠️ {res['aviso']}" if res["aviso"] else ""
                            st.success(
                                f"Publicado: {res['inseridos']} novos, "
                                f"{res['apagados']} antigos apagados. "
                                f"Backup: {res['backup_path']}.{aviso}"
                            )


with aba_ingestao:
    try:
        _render_aba_ingestao()
    except Exception:
        logger.warning("Document ingestion operation not confirmed")
        st.error(
            "Não foi possível concluir a operação de documentos. Confira o resultado antes de repetir."
        )
