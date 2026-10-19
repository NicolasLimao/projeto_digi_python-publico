"""Testes offline da camada de dados do dashboard (sem rede, sem Streamlit)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dashboard import dados
from tests.fakes import FakeSupabaseClient


def _escrever_jsonl(caminho: Path, casos: list[dict]) -> None:
    caminho.write_text(
        "\n".join(json.dumps(caso, ensure_ascii=False) for caso in casos) + "\n",
        encoding="utf-8",
    )


def test_duvidas_producao_converte_view():
    linhas = [
        {
            "timestamp": "2026-07-03T16:22:00+00:00",
            "canal": "dm",
            "modo": "orientacao",
            "score": 0.33,
            "pergunta": "P?",
            "resposta": "R ruim",
        }
    ]
    duvidas = dados.duvidas_producao(linhas)
    assert len(duvidas) == 1
    assert duvidas[0].chave == "prod:2026-07-03T16:22:00+00:00"
    assert duvidas[0].origem == "producao"
    assert duvidas[0].resposta_ruim == "R ruim"


def test_duvidas_eval_filtra_revisar_e_anota_veredito(tmp_path):
    _escrever_jsonl(
        tmp_path / "d.jsonl",
        [
            {
                "id": "neg-001",
                "origem": "feedback_negativo",
                "modo": "orientacao",
                "pergunta": "P1?",
                "fatos_esperados": ["f"],
                "resposta_anterior": "ruim",
                "notas": "REVISAR: confirmar",
            },
            {
                "id": "pos-001",
                "origem": "feedback_positivo",
                "modo": "orientacao",
                "pergunta": "P2?",
                "fatos_esperados": ["f"],
                "notas": "ok",
            },
        ],
    )
    duvidas = dados.duvidas_eval(tmp_path / "d.jsonl", {"neg-001": "reprovado"})
    assert [d.chave for d in duvidas] == ["eval:neg-001"]
    assert duvidas[0].veredito == "reprovado"


def test_pendentes_subtrai_respondidas_e_deduplica():
    a = dados.Duvida("prod:1", "producao", "orientacao", "P", "R")
    b = dados.Duvida("eval:x", "eval", "orientacao", "P", "R")
    duplicada = dados.Duvida("prod:1", "producao", "orientacao", "P", "R")
    resultado = dados.pendentes([a, duplicada], [b], {"eval:x"})
    assert [d.chave for d in resultado] == ["prod:1"]


def test_ultimo_baseline_ignora_parciais_e_calcula_delta(tmp_path):
    (tmp_path / "a.json").write_text(
        json.dumps({"run": "r1", "vereditos": {"x": "aprovado", "y": "reprovado"}}),
        encoding="utf-8",
    )
    (tmp_path / "b.json").write_text(
        json.dumps({"run": "r2", "parcial": True, "vereditos": {"x": "reprovado"}}),
        encoding="utf-8",
    )
    (tmp_path / "c.json").write_text(
        json.dumps(
            {"run": "r3", "parcial": False, "vereditos": {"x": "aprovado", "y": "aprovado"}}
        ),
        encoding="utf-8",
    )
    baseline = dados.ultimo_baseline(tmp_path)
    assert baseline is not None
    assert (baseline["run"], baseline["aprovados"], baseline["total"]) == ("r3", 2, 2)
    assert baseline["delta"] == 1  # r3 (2 aprovados) vs r1 (1 aprovado); parcial ignorado
    assert baseline["vereditos"] == {"x": "aprovado", "y": "aprovado"}


def test_ultimo_baseline_sem_relatorios(tmp_path):
    assert dados.ultimo_baseline(tmp_path) is None


def test_janelas_volume_soma_janela_atual_e_anterior():
    linhas = [
        {"dia": "2026-07-15", "interacoes": 10, "positivos": 4, "negativos": 1},
        {"dia": "2026-07-10", "interacoes": 6, "positivos": 2, "negativos": 0},
        {"dia": "2026-07-05", "interacoes": 8, "positivos": 3, "negativos": 2},
    ]
    # janela atual (7d, 09-15/07): linhas de 15/07 e 10/07; anterior (02-08/07): linha de 05/07
    atual, anterior = dados.janelas_volume(linhas, dias=7, hoje=date(2026, 7, 15))
    assert atual == {"interacoes": 16, "positivos": 6, "negativos": 1}
    assert anterior == {"interacoes": 8, "positivos": 3, "negativos": 2}


def test_preparar_volume_grafico_formato_longo_com_sem_avaliacao():
    linhas = [{"dia": "2026-07-15", "interacoes": 10, "positivos": 4, "negativos": 1}]
    longo = dados.preparar_volume_grafico(linhas, dias=7, hoje=date(2026, 7, 15))
    categorias = {(item["categoria"], item["quantidade"]) for item in longo}
    assert categorias == {("Positivos", 4), ("Sem avaliação", 5), ("Negativos", 1)}


def test_texto_ingestao_estrutura():
    texto = dados.texto_ingestao("  Como faço X?  ", "  Passo a passo Y.  ")
    assert texto == (
        "Pergunta: Como faço X?\nResposta oficial validada pelo analista: Passo a passo Y."
    )


def test_parse_custos_agrega_buckets_diarios():
    costs = {
        "data": [
            {
                "start_time": 1784246400,  # 2026-07-17 UTC? valor exato não importa, ver dia
                "results": [{"amount": {"value": 0.12}}, {"amount": {"value": 0.03}}],
            }
        ]
    }
    usage = {
        "data": [
            {
                "start_time": 1784246400,
                "results": [
                    {"input_tokens": 1000, "output_tokens": 200},
                    {"input_tokens": 500, "output_tokens": 100},
                ],
            }
        ]
    }
    resultado = dados.parse_custos(costs, usage)
    assert len(resultado["por_dia"]) == 1
    dia = resultado["por_dia"][0]
    assert dia["custo_usd"] == 0.15
    assert dia["tokens_entrada"] == 1500
    assert dia["tokens_saida"] == 300
    assert resultado["custo_total_usd"] == 0.15


def test_buckets_paginados_segue_next_page(monkeypatch):
    paginas = [
        {"data": [{"start_time": 1, "results": []}], "has_more": True, "next_page": "p2"},
        {"data": [{"start_time": 2, "results": []}], "has_more": False},
    ]
    chamadas: list[dict] = []

    class _Resposta:
        def __init__(self, corpo):
            self._corpo = corpo

        def raise_for_status(self):
            pass

        def json(self):
            return self._corpo

    def _fake_get(url, params, headers, timeout):
        chamadas.append(dict(params))
        return _Resposta(paginas[len(chamadas) - 1])

    monkeypatch.setattr(dados.httpx, "get", _fake_get)
    buckets = dados._buckets_paginados("https://exemplo", "sk-admin", 0, 31)
    assert len(buckets) == 2
    assert len(chamadas) == 2
    assert "page" not in chamadas[0]
    assert chamadas[1]["page"] == "p2"


def test_buckets_paginados_respeita_teto_de_seguranca(monkeypatch):
    def _sempre_tem_mais(url, params, headers, timeout):
        class _Resposta:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": [{}], "has_more": True, "next_page": "x"}

        return _Resposta()

    monkeypatch.setattr(dados.httpx, "get", _sempre_tem_mais)
    buckets = dados._buckets_paginados("https://exemplo", "sk-admin", 0, 31)
    assert len(buckets) == 12  # máx. 12 páginas de segurança


def test_custos_openai_usa_limites_distintos_para_costs_e_usage(monkeypatch):
    urls_e_limites: list[tuple[str, int]] = []

    def _fake_buckets(url, admin_key, inicio, limite_pagina):
        urls_e_limites.append((url, limite_pagina))
        return []

    monkeypatch.setattr(dados, "_buckets_paginados", _fake_buckets)
    resultado = dados.custos_openai("sk-admin", dias=90)
    assert resultado == {"por_dia": [], "custo_total_usd": 0.0}
    limites = dict((url.rsplit("/", 1)[-1], limite) for url, limite in urls_e_limites)
    assert limites["costs"] == 90
    assert limites["completions"] == 31  # usage é limitado a 31 mesmo com dias=90


def test_ingerir_resposta_corpo_2xx_nao_json(monkeypatch):
    class _Resposta:
        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(dados.httpx, "post", lambda *a, **k: _Resposta())
    with pytest.raises(ValueError, match="confirmada"):
        dados.ingerir_resposta("https://api", "token", "texto")


@pytest.mark.parametrize(
    "body",
    [{"chunks_created": 0}, {"chunks_created": 1, "errors": ["failed"]}, {"chunks_created": "1"}],
)
def test_ingerir_resposta_rejeita_resultado_sem_confirmacao(monkeypatch, body):
    response = MagicMock()
    response.json.return_value = body
    monkeypatch.setattr(dados.httpx, "post", lambda *a, **k: response)
    with pytest.raises(ValueError, match="confirmada"):
        dados.ingerir_resposta("https://api", "token", "texto")


def test_ingerir_resposta_confirma_chunks_e_envia_curadoria_explicita(monkeypatch):
    response = MagicMock()
    response.json.return_value = {"chunks_created": 1, "errors": []}
    post = MagicMock(return_value=response)
    monkeypatch.setattr(dados.httpx, "post", post)
    assert dados.ingerir_resposta("https://api", "token", "texto")["chunks_created"] == 1
    assert post.call_args.kwargs["json"] == {"content": "texto", "curated": True}


def _relatorio_exemplo() -> str:
    resumo = {
        "total_interacoes": 384,
        "positivos": 209,
        "negativos": 14,
        "sem_feedback": 161,
        "taxa_aprovacao_pct": 94,
    }
    por_modo = [{"modo": "orientacao", "interacoes": 332, "positivos": 178, "negativos": 11}]
    por_canal = [{"canal": "dm", "interacoes": 383, "positivos": 209, "negativos": 14}]
    baseline = {"run": "2026-07-15-2357", "aprovados": 17, "total": 32}
    duvida = dados.Duvida("prod:1", "producao", "orientacao", "Como exportar?", "R ruim")
    return dados.gerar_relatorio_md(
        resumo, por_modo, por_canal, baseline, [duvida], dias=30, gerado_em="2026-07-16 10:00"
    )


def test_relatorio_md_contem_secoes_e_dados():
    texto = _relatorio_exemplo()
    assert "# Relatório Digi" in texto
    assert "2026-07-16 10:00" in texto
    assert "384" in texto and "94" in texto
    assert "orientacao" in texto and "dm" in texto
    assert "17/32" in texto
    assert "Como exportar?" in texto


def test_relatorio_md_sem_baseline_e_sem_duvidas():
    texto = dados.gerar_relatorio_md(
        {"total_interacoes": 0}, [], [], None, [], dias=7, gerado_em="2026-07-16 10:00"
    )
    assert "Nenhuma rodada de avaliação encontrada" in texto
    assert "Nenhuma dúvida pendente" in texto


def test_relatorio_md_com_delta_do_baseline():
    baseline = {"run": "r", "aprovados": 20, "total": 32, "delta": 3}
    texto = dados.gerar_relatorio_md(
        {"total_interacoes": 0}, [], [], baseline, [], dias=7, gerado_em="2026-07-16 10:00"
    )
    assert "20/32" in texto
    assert "(delta +3" in texto


def test_relatorio_md_com_erro_duvidas_e_honesto():
    duvida = dados.Duvida("prod:1", "producao", "orientacao", "Como exportar?", "R ruim")
    texto = dados.gerar_relatorio_md(
        {"total_interacoes": 0},
        [],
        [],
        None,
        [duvida],
        dias=7,
        gerado_em="2026-07-16 10:00",
        erro_duvidas="Falha ao carregar as fontes de dúvidas: RuntimeError",
    )
    assert "Não foi possível apurar as dúvidas pendentes nesta geração." in texto
    assert "Como exportar?" not in texto
    assert "Nenhuma dúvida pendente" not in texto


def test_relatorio_pdf_gera_bytes_legiveis():
    import fitz

    conteudo = dados.gerar_relatorio_pdf(_relatorio_exemplo())
    assert conteudo[:5] == b"%PDF-"
    with fitz.open(stream=conteudo, filetype="pdf") as doc:
        assert doc.page_count >= 1
        texto = "".join(page.get_text() for page in doc)
    assert "Digi" in texto and "384" in texto


class _StubSupabase:
    def __init__(self):
        self.inserido: dict | None = None
        self.tabela: str | None = None

    def table(self, nome: str):
        self.tabela = nome
        return self

    def insert(self, payload: dict):
        self.inserido = payload
        return self

    def execute(self):
        return self


def test_descartar_duvida_registra_sem_ingerir():
    stub = _StubSupabase()
    duvida = dados.Duvida("prod:1", "producao", "orientacao", "comob", "resposta do bot")
    dados.descartar_duvida(stub, duvida, dados.MOTIVOS_DESCARTE["invalida"])
    assert stub.tabela == dados.TABELA_RESPOSTAS
    assert stub.inserido is not None
    assert stub.inserido["chave"] == "prod:1"
    assert stub.inserido["ingerida"] is False
    assert stub.inserido["chunks_criados"] == 0
    assert "descartada" in stub.inserido["resposta_correta"]
    assert dados.MOTIVOS_DESCARTE["invalida"] in stub.inserido["resposta_correta"]


class _StubDocs:
    """Stub do cliente Supabase para a tabela documents (resolução/backup/update)."""

    def __init__(self, linhas: list[dict] | None = None):
        self.linhas = linhas or []
        self.filtros: list[tuple[str, str]] = []
        self._modo = "select"
        self._payload: dict | None = None
        self._id_alvo = None
        self.updates: list[dict] = []

    def table(self, nome: str):
        self.tabela = nome
        return self

    def select(self, *_):
        self._modo = "select"
        return self

    def update(self, payload: dict):
        self._modo = "update"
        self._payload = payload
        return self

    def eq(self, coluna: str, valor):
        if coluna == "id":
            self._id_alvo = valor
        else:
            self.filtros.append((coluna, str(valor)))
        return self

    def execute(self):
        if self._modo == "update":
            existe = any(linha.get("id") == self._id_alvo for linha in self.linhas)
            self.updates.append({"id": self._id_alvo, **(self._payload or {})})
            dados_ret = [{"id": self._id_alvo}] if existe else []
            self._id_alvo = None
            return type("R", (), {"data": dados_ret})()
        linhas = self.linhas
        for coluna, valor in self.filtros:
            chave = coluna.split("->>")[-1]
            linhas = [
                linha for linha in linhas if str((linha.get("metadata") or {}).get(chave)) == valor
            ]
        if self._id_alvo is not None:
            linhas = [linha for linha in linhas if linha.get("id") == self._id_alvo]
        self.filtros = []
        self._id_alvo = None
        return type("R", (), {"data": [dict(linha) for linha in linhas]})()


def test_chunks_suspeitos_achata_instaveis_e_deduplica():
    mapa = {
        "casos": [
            {
                "id": "neg-008",
                "indice": 0.4,
                "chunks": [
                    {
                        "ref": "discord-upload#37",
                        "data": "2026-05-28",
                        "trecho": "A",
                        "score_busca": 0.4,
                    },
                    {
                        "ref": "discord-upload#41",
                        "data": "2026-05-28",
                        "trecho": "B",
                        "score_busca": 0.3,
                    },
                ],
            },
            {
                "id": "pos-002",
                "indice": 0.0,
                "chunks": [{"ref": "x#1", "data": "2026-05-28", "trecho": "Z", "score_busca": 0.6}],
            },
            {
                "id": "neg-013",
                "indice": 0.4,
                "chunks": [
                    {
                        "ref": "discord-upload#37",
                        "data": "2026-05-28",
                        "trecho": "A",
                        "score_busca": 0.4,
                    }
                ],
            },
        ]
    }
    suspeitos = dados.chunks_suspeitos(mapa)
    trechos = [s["trecho"] for s in suspeitos]
    assert trechos == ["A", "B"]  # dedupe por trecho; pos-002 (estável) fora
    assert suspeitos[0]["caso_id"] == "neg-008"


def test_mapa_sem_ref_detecta_formato_antigo():
    antigos = [{"caso_id": "neg-008", "ref": "", "trecho": "A"}]
    novos = [{"caso_id": "neg-008", "ref": "discord-upload#37", "trecho": "A"}]
    misto = [{"ref": ""}, {"ref": "discord-upload#37"}]
    assert dados.mapa_sem_ref(antigos) is True
    assert dados.mapa_sem_ref(novos) is False
    assert dados.mapa_sem_ref(misto) is False
    assert dados.mapa_sem_ref([]) is False


def test_classificar_idade():
    assert dados.classificar_idade("2026-07-16T00:00:00Z") == "curado"
    assert dados.classificar_idade("2026-05-28T22:14:23.192Z") == "manual"
    assert dados.classificar_idade("2026-04-14") == "manual"
    assert dados.classificar_idade("data-invalida") == "manual"


def test_resolver_chunk_desempata_por_conteudo_normalizado():
    linhas = [
        {
            "id": 977,
            "content": "Agente   Inteligente\ncontratado",
            "metadata": {"fonte": "discord-upload", "chunk_index": 37},
        },
        {
            "id": 45,
            "content": "Outro chunk qualquer",
            "metadata": {"fonte": "discord-upload", "chunk_index": 37},
        },
    ]
    stub = _StubDocs(linhas)
    trecho = dados._trecho_normalizado("Agente   Inteligente\ncontratado")
    achados = dados.resolver_chunk(stub, "discord-upload#37", trecho)
    assert [a["id"] for a in achados] == [977]


def test_resolver_chunk_sem_match_retorna_vazio():
    stub = _StubDocs(
        [
            {
                "id": 1,
                "content": "nada a ver",
                "metadata": {"fonte": "discord-upload", "chunk_index": 37},
            }
        ]
    )
    assert dados.resolver_chunk(stub, "discord-upload#37", "trecho inexistente") == []


def test_montar_backup_preserva_campos_do_original():
    linha = {"id": 977, "content": "velho", "embedding": [0.1, 0.2], "metadata": {"fonte": "x"}}
    backup = dados.montar_backup(linha)
    assert backup["id"] == 977
    assert backup["content"] == "velho"
    assert backup["embedding"] == [0.1, 0.2]
    assert backup["metadata"] == {"fonte": "x"}
    assert "backup_em" in backup


def test_salvar_backup_faz_append_jsonl(tmp_path):
    caminho = tmp_path / "documents-2026-07-19.jsonl"
    dados.salvar_backup(caminho, {"id": 1, "content": "a"})
    dados.salvar_backup(caminho, {"id": 2, "content": "b"})
    linhas = caminho.read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 2
    assert json.loads(linhas[1])["id"] == 2


def test_atualizar_chunk_envia_content_e_embedding():
    stub = _StubDocs([{"id": 977, "content": "velho", "metadata": {}}])
    dados.atualizar_chunk(stub, 977, "novo texto", [0.5, 0.6])
    assert stub.updates == [{"id": 977, "content": "novo texto", "embedding": [0.5, 0.6]}]


def test_resolver_chunk_casa_trecho_com_email_redigido():
    linhas = [
        {
            "id": 5,
            "content": "contate joao@exemplo.com no suporte",
            "metadata": {"fonte": "discord-upload", "chunk_index": 9},
        },
    ]
    stub = _StubDocs(linhas)
    # o mapa guarda o trecho JÁ com o email mascarado
    achados = dados.resolver_chunk(stub, "discord-upload#9", "contate [email] no suporte")
    assert [a["id"] for a in achados] == [5]


class _StubOpenAI:
    def __init__(self, vetor: list[float]):
        self._vetor = vetor
        self.chamada: dict | None = None
        self.embeddings = self

    def create(self, model: str, input: str):
        self.chamada = {"model": model, "input": input}
        dado = type("D", (), {"embedding": self._vetor})()
        return type("R", (), {"data": [dado]})()


def test_reembed_usa_modelo_correto_e_retorna_vetor():
    stub = _StubOpenAI([0.1, 0.2, 0.3])
    vetor = dados.reembed(stub, "texto novo")
    assert vetor == [0.1, 0.2, 0.3]
    assert stub.chamada == {"model": dados.EMBEDDING_MODEL, "input": "texto novo"}


def test_buscar_documento_retorna_linha_ou_none():
    stub = _StubDocs([{"id": 7, "content": "x", "embedding": [0.1], "metadata": {}}])
    assert dados.buscar_documento(stub, 7)["content"] == "x"
    assert dados.buscar_documento(_StubDocs([]), 99) is None


def test_atualizar_chunk_sem_linha_afetada_levanta():
    import pytest

    with pytest.raises(RuntimeError, match="nenhuma linha"):
        dados.atualizar_chunk(_StubDocs([]), 999, "novo", [0.1])


def test_parse_ocr_response_junta_paginas():
    payload = {"pages": [{"markdown": "pagina um"}, {"markdown": "pagina dois"}]}
    assert dados.parse_ocr_response(payload) == "pagina um\n\npagina dois"


def test_parse_ocr_response_vazio():
    assert dados.parse_ocr_response({}) == ""
    assert dados.parse_ocr_response({"pages": []}) == ""


def test_montar_raw_shape_e_contagem():
    linha = dados.montar_raw("Manual", "manual", "pdf", "abc def")
    assert linha["nome"] == "Manual"
    assert linha["fonte_alvo"] == "manual"
    assert linha["tipo"] == "pdf"
    assert linha["texto"] == "abc def"
    assert linha["n_chars"] == 7
    assert linha["status"] == "cru"


def test_extrair_texto_arquivo_de_texto_nao_faz_ocr():
    # tipo 'texto' apenas decodifica os bytes; não usa cliente nem rede
    resultado = dados.extrair_texto(
        cliente=MagicMock(),
        mistral_key="k",
        arquivo_bytes=b"ola mundo",
        tipo="texto",
        nome_arquivo="n.txt",
    )
    assert resultado == "ola mundo"


def test_extrair_texto_pdf_via_files_api(monkeypatch):
    visto = {"posts": []}

    def _resp(payload):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    def fake_post(url, **kwargs):
        visto["posts"].append(url)
        if url.endswith("/v1/files"):
            # upload multipart do arquivo
            assert "file" in kwargs["files"]
            return _resp({"id": "file-123"})
        if url.endswith("/v1/ocr"):
            visto["ocr_url"] = kwargs["json"]["document"]["document_url"]
            return _resp({"pages": [{"markdown": "texto do pdf"}]})
        raise AssertionError(f"POST inesperado: {url}")

    def fake_get(url, **kwargs):
        visto["get"] = url
        return _resp({"url": "https://sig/mistral"})

    monkeypatch.setattr(dados.httpx, "post", fake_post)
    monkeypatch.setattr(dados.httpx, "get", fake_get)

    resultado = dados.extrair_texto(
        cliente=MagicMock(),
        mistral_key="k",
        arquivo_bytes=b"%PDF-conteudo",
        tipo="pdf",
        nome_arquivo="manual.pdf",
    )
    assert resultado == "texto do pdf"
    # subiu o arquivo, pegou a signed URL do file, e o OCR referenciou essa URL
    assert visto["posts"][0].endswith("/v1/files")
    assert visto["get"] == "https://api.mistral.ai/v1/files/file-123/url"
    assert visto["ocr_url"] == "https://sig/mistral"


def test_salvar_raw_insere_a_linha():
    cliente = MagicMock()
    linha = {
        "nome": "M",
        "fonte_alvo": "manual",
        "tipo": "pdf",
        "texto": "x",
        "n_chars": 1,
        "status": "cru",
    }
    dados.salvar_raw(cliente, linha)
    cliente.table.assert_called_with("raw_documents")
    cliente.table.return_value.insert.assert_called_with(linha)


def test_listar_raw_retorna_linhas():
    cliente = MagicMock()
    cliente.table.return_value.select.return_value.order.return_value.execute.return_value = (
        SimpleNamespace(data=[{"id": 1, "nome": "M"}])
    )
    assert dados.listar_raw(cliente) == [{"id": 1, "nome": "M"}]


# ---- Fatia 2: re-chunk contextual (Tasks 4-6) ----


class _StubEmbedLote:
    def __init__(self, vetores):
        self._vetores = vetores
        self.embeddings = self
        self.chamada = None

    def create(self, model, input):
        self.chamada = {"model": model, "input": input}
        dados_ = [type("D", (), {"embedding": v})() for v in self._vetores]
        return type("R", (), {"data": dados_})()


class _StubChat:
    """Stub do cliente OpenAI para chat.completions.create."""

    def __init__(self, respostas):
        self._respostas = respostas
        self.chamadas = []
        self.chat = self
        self.completions = self

    def create(self, model, temperature, max_tokens, messages):
        self.chamadas.append({"model": model, "messages": messages})
        conteudo = self._respostas[len(self.chamadas) - 1]
        msg = type("M", (), {"content": conteudo})()
        escolha = type("C", (), {"message": msg})()
        return type("R", (), {"choices": [escolha]})()


def test_buscar_raw_retorna_linha_e_levanta_se_ausente():
    import pytest

    cliente = FakeSupabaseClient()
    cliente.tables["raw_documents"] = [{"id": 1, "texto": "conteudo", "status": "cru"}]
    assert dados.buscar_raw(cliente, 1)["texto"] == "conteudo"
    with pytest.raises(RuntimeError, match="não encontrado"):
        dados.buscar_raw(cliente, 99)


def test_lote_para_backup_pega_faixa_de_ids():
    cliente = FakeSupabaseClient()
    cliente.tables["documents"] = [
        {"id": 977, "content": "a", "embedding": [0.1], "metadata": {}},
        {"id": 1677, "content": "b", "embedding": [0.2], "metadata": {}},
        {"id": 2000, "content": "fora", "embedding": [0.3], "metadata": {}},
    ]
    lote = dados.lote_para_backup(cliente, 977, 1677)
    assert sorted(item["id"] for item in lote) == [977, 1677]


def test_reembed_lote_manda_lista_e_retorna_vetores():
    stub = _StubEmbedLote([[0.1], [0.2]])
    out = dados.reembed_lote(stub, ["a", "b"])
    assert out == [[0.1], [0.2]]
    assert stub.chamada == {"model": dados.EMBEDDING_MODEL, "input": ["a", "b"]}


def test_marcar_chunkado_atualiza_status():
    cliente = FakeSupabaseClient()
    cliente.tables["raw_documents"] = [{"id": 1, "status": "cru"}]
    dados.marcar_chunkado(cliente, 1)
    assert cliente.tables["raw_documents"][0]["status"] == "chunkado"


def test_lotes_antigos_tem_o_manual():
    assert dados.LOTES_ANTIGOS["manual"] == {
        "id_min": 977,
        "id_max": 1677,
        "data_prefixo": "2026-05-28",
    }


def test_montar_linhas_documents_metadata_e_indice():
    linhas = dados.montar_linhas_documents(
        ["texto0", "texto1"], [[0.1], [0.2]], "manual", 1, "2026-08-01T00:00:00+00:00"
    )
    assert len(linhas) == 2
    assert linhas[0]["content"] == "texto0"
    assert linhas[0]["embedding"] == [0.1]
    md = linhas[0]["metadata"]
    assert md["fonte_alvo"] == "manual"
    assert md["raw_id"] == 1
    assert md["chunk_index"] == 0
    assert md["fonte"] == "discord-upload"
    assert md["tipo_chunk"] == "semantico"
    assert linhas[1]["metadata"]["chunk_index"] == 1


def test_montar_linhas_documents_exige_tamanhos_iguais():
    import pytest

    with pytest.raises(ValueError):
        dados.montar_linhas_documents(["a", "b"], [[0.1]], "manual", 1, "2026-08-01")


def test_contextualizar_prepend_contexto_por_chunk():
    stub = _StubChat(["contexto A", "contexto B"])
    chunks = [
        {"breadcrumb": "# X", "secao": "sec1", "corpo": "corpo1", "texto": "# X\n\ncorpo1"},
        {"breadcrumb": "# Y", "secao": "sec2", "corpo": "corpo2", "texto": "# Y\n\ncorpo2"},
    ]
    finais = dados.contextualizar_chunks(stub, chunks, "indice", model="gpt-4o")
    assert finais[0] == "contexto A\n\n# X\n\ncorpo1"
    assert finais[1] == "contexto B\n\n# Y\n\ncorpo2"
    assert stub.chamadas[0]["model"] == "gpt-4o"


def _prep_publicacao(monkeypatch):
    """Monkeypatcha os passos caros (chunking/LLM/embedding) por stubs determinísticos."""
    monkeypatch.setattr(
        dados,
        "chunk_contextual_estrutural",
        lambda t: [
            {"breadcrumb": "# A", "secao": "s", "corpo": "c1", "texto": "# A\n\nc1"},
            {"breadcrumb": "# A", "secao": "s", "corpo": "c2", "texto": "# A\n\nc2"},
        ],
    )
    monkeypatch.setattr(dados, "construir_indice", lambda t: "# A")
    monkeypatch.setattr(
        dados,
        "contextualizar_chunks",
        lambda oa, chunks, outline: [f"ctx\n\n{c['texto']}" for c in chunks],
    )
    monkeypatch.setattr(dados, "reembed_lote", lambda oa, textos: [[0.9]] * len(textos))


def test_publicar_lote_insere_faz_backup_apaga_e_marca(tmp_path, monkeypatch):
    _prep_publicacao(monkeypatch)
    cliente = FakeSupabaseClient()
    cliente.tables["raw_documents"] = [{"id": 1, "texto": "cru", "status": "cru"}]
    cliente.tables["documents"] = [
        {"id": 977, "content": "velho1", "embedding": [0.1], "metadata": {"data": "2026-05-28"}},
        {"id": 1677, "content": "velho2", "embedding": [0.2], "metadata": {"data": "2026-05-28"}},
    ]
    res = dados.publicar_lote(cliente, object(), 1, "manual", tmp_path)

    docs = cliente.tables["documents"]
    assert all(r["id"] not in (977, 1677) for r in docs)  # antigos apagados
    assert len(docs) == 2  # só os 2 novos
    assert res["inseridos"] == 2
    assert res["apagados"] == 2
    assert res["aviso"] is None
    bkp = tmp_path / f"documents-manual-{datetime.now(UTC).isoformat()[:10]}.jsonl"
    assert len(bkp.read_text(encoding="utf-8").strip().splitlines()) == 2
    assert cliente.tables["raw_documents"][0]["status"] == "chunkado"


class _ClienteInsertCurto(FakeSupabaseClient):
    """Faz o INSERT em documents retornar uma linha a menos (simula falha parcial)."""

    def table(self, name):
        query = super().table(name)
        if name == "documents":
            original = query.execute

            def executar_curto():
                res = original()
                if query.operation == "insert" and res.data:
                    res.data = res.data[:-1]
                return res

            query.execute = executar_curto
        return query


def test_publicar_lote_aborta_sem_apagar_se_insert_incompleto(tmp_path, monkeypatch):
    import pytest

    _prep_publicacao(monkeypatch)
    cliente = _ClienteInsertCurto()
    cliente.tables["raw_documents"] = [{"id": 1, "texto": "cru", "status": "cru"}]
    cliente.tables["documents"] = [
        {"id": 977, "content": "velho1", "embedding": [0.1], "metadata": {"data": "2026-05-28"}},
    ]
    with pytest.raises(RuntimeError, match="abortad"):
        dados.publicar_lote(cliente, object(), 1, "manual", tmp_path)

    assert any(r["id"] == 977 for r in cliente.tables["documents"])  # antigo intacto
    assert cliente.tables["raw_documents"][0]["status"] == "cru"  # não marcado
    bkp = tmp_path / f"documents-manual-{datetime.now(UTC).isoformat()[:10]}.jsonl"
    assert not bkp.exists()  # backup não escrito


def test_publicar_lote_insere_em_varios_lotes(tmp_path, monkeypatch):
    # com INSERT_BATCH pequeno, os 2 chunks entram em 2 inserts separados,
    # e ainda assim todos são inseridos e contados (sem estourar payload).
    _prep_publicacao(monkeypatch)
    monkeypatch.setattr(dados, "INSERT_BATCH", 1)
    inserts = {"n": 0}
    cliente = FakeSupabaseClient()
    cliente.tables["raw_documents"] = [{"id": 1, "texto": "cru", "status": "cru"}]
    cliente.tables["documents"] = [
        {"id": 977, "content": "v", "embedding": [0.1], "metadata": {"data": "2026-05-28"}},
    ]
    original_table = cliente.table

    def _contar(name):
        query = original_table(name)
        if name == "documents":
            orig = query.execute

            def exec_conta():
                if query.operation == "insert":
                    inserts["n"] += 1
                return orig()

            query.execute = exec_conta
        return query

    cliente.table = _contar
    res = dados.publicar_lote(cliente, object(), 1, "manual", tmp_path)
    assert res["inseridos"] == 2
    assert inserts["n"] == 2  # dois inserts (batch=1), não um só
    assert len([r for r in cliente.tables["documents"] if r["id"] == 977]) == 0


class _StubEmbedEco:
    """Retorna um vetor por input recebido (permite verificar batching)."""

    def __init__(self):
        self.tamanhos = []
        self.embeddings = self

    def create(self, model, input):
        self.tamanhos.append(len(input))
        dados_ = [type("D", (), {"embedding": [float(len(t))]})() for t in input]
        return type("R", (), {"data": dados_})()


def test_reembed_lote_batcha_e_preserva_ordem():
    stub = _StubEmbedEco()
    textos = ["a", "bb", "ccc", "dddd", "eeeee"]
    out = dados.reembed_lote(stub, textos, batch=2)
    assert out == [[1.0], [2.0], [3.0], [4.0], [5.0]]  # ordem preservada
    assert stub.tamanhos == [2, 2, 1]  # 5 itens em lotes de 2


def test_contextualizar_retenta_no_rate_limit(monkeypatch):
    monkeypatch.setattr(dados.time, "sleep", lambda s: None)

    class RateLimitError(Exception):
        pass

    class _StubFlaky:
        def __init__(self):
            self.n = 0
            self.chat = self
            self.completions = self

        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                raise RateLimitError("429 tokens per min")
            msg = type("M", (), {"content": "ctx"})()
            ch = type("C", (), {"message": msg})()
            return type("R", (), {"choices": [ch]})()

    stub = _StubFlaky()
    chunks = [{"breadcrumb": "# X", "secao": "s", "corpo": "c", "texto": "# X\n\nc"}]
    finais = dados.contextualizar_chunks(stub, chunks, "idx")
    assert finais == ["ctx\n\n# X\n\nc"]
    assert stub.n == 2  # falhou 1x com rate limit e retentou


def test_context_model_e_mini():
    assert dados.CONTEXT_MODEL == "gpt-4o-mini"


def test_montar_linhas_documents_metadata_extra_e_fonte():
    linhas = dados.montar_linhas_documents(
        ["t0", "t1"],
        [[0.1], [0.2]],
        "api",
        9,
        "2026-08-01T00:00:00+00:00",
        fonte="postman",
        tipo_chunk="endpoint",
        metadados_extra=[
            {"recurso": "Contatos", "metodo": "PUT"},
            {"recurso": "Tags", "metodo": "POST"},
        ],
    )
    md0 = linhas[0]["metadata"]
    assert md0["fonte"] == "postman"
    assert md0["tipo_chunk"] == "endpoint"
    assert md0["recurso"] == "Contatos"
    assert md0["metodo"] == "PUT"
    assert md0["fonte_alvo"] == "api"
    assert linhas[1]["metadata"]["recurso"] == "Tags"


def test_montar_linhas_documents_default_manual_inalterado():
    linhas = dados.montar_linhas_documents(["t"], [[0.1]], "manual", 1, "2026-08-01T00:00:00+00:00")
    md = linhas[0]["metadata"]
    assert md["fonte"] == "discord-upload"
    assert md["tipo_chunk"] == "semantico"
    assert "recurso" not in md


def test_publicar_lote_api_usa_postman_e_troca(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dados,
        "chunk_postman",
        lambda txt: [
            {"recurso": "Contatos", "metodo": "PUT", "nome": "Editar", "texto": "T1"},
            {"recurso": "Tags", "metodo": "POST", "nome": "Criar", "texto": "T2"},
        ],
    )
    monkeypatch.setattr(dados, "reembed_lote", lambda oa, textos: [[0.5]] * len(textos))
    cliente = FakeSupabaseClient()
    cliente.tables["raw_documents"] = [{"id": 9, "texto": "{json}", "tipo": "api", "status": "cru"}]
    cliente.tables["documents"] = [
        {"id": 6, "content": "velho", "embedding": [0.1], "metadata": {"data": "2026-04-14"}},
        {"id": 365, "content": "velho2", "embedding": [0.2], "metadata": {"data": "2026-04-14"}},
    ]
    res = dados.publicar_lote(cliente, object(), 9, "api", tmp_path)
    docs = cliente.tables["documents"]
    assert res["inseridos"] == 2
    assert res["apagados"] == 2
    assert all(r["id"] not in (6, 365) for r in docs)  # lote antigo apagado
    novos = [r for r in docs if r.get("metadata", {}).get("fonte_alvo") == "api"]
    assert len(novos) == 2
    assert novos[0]["metadata"]["fonte"] == "postman"
    assert novos[0]["metadata"]["recurso"] == "Contatos"
    assert novos[0]["metadata"]["tipo_chunk"] == "endpoint"
    assert cliente.tables["raw_documents"][0]["status"] == "chunkado"


@pytest.mark.parametrize(
    ("tipo", "texto", "fonte"),
    [("texto", "", "manual"), ("api", '{"item": []}', "api")],
)
def test_publicar_lote_vazio_preserva_base_e_status(tmp_path, tipo, texto, fonte):
    cliente = FakeSupabaseClient()
    cliente.tables["raw_documents"] = [{"id": 1, "texto": texto, "tipo": tipo, "status": "cru"}]
    antigo = {
        "id": dados.LOTES_ANTIGOS[fonte]["id_min"],
        "content": "Documento existente",
        "embedding": [0.1],
        "metadata": {},
    }
    cliente.tables["documents"] = [antigo.copy()]

    with pytest.raises(ValueError, match="Nenhum chunk"):
        dados.publicar_lote(cliente, object(), 1, fonte, tmp_path)

    assert cliente.tables["documents"] == [antigo]
    assert cliente.tables["raw_documents"][0]["status"] == "cru"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("dependencia_ausente", ["supabase", "openai"])
def test_publicar_lote_exige_dependencias(tmp_path, dependencia_ausente):
    cliente = FakeSupabaseClient()
    cliente.tables["raw_documents"] = [{"id": 1, "texto": "cru", "status": "cru"}]
    cliente.tables["documents"] = [{"id": 977, "content": "Existente"}]

    with pytest.raises(RuntimeError, match="Supabase e OpenAI"):
        dados.publicar_lote(
            None if dependencia_ausente == "supabase" else cliente,
            None if dependencia_ausente == "openai" else object(),
            1,
            "manual",
            tmp_path,
        )

    assert cliente.tables["documents"] == [{"id": 977, "content": "Existente"}]
    assert cliente.tables["raw_documents"][0]["status"] == "cru"


def test_publicar_lote_api_invalida_preserva_base(tmp_path):
    cliente = FakeSupabaseClient()
    cliente.tables["raw_documents"] = [
        {"id": 1, "texto": "{invalid", "tipo": "api", "status": "cru"}
    ]
    cliente.tables["documents"] = [{"id": 6, "content": "Existente"}]

    with pytest.raises(ValueError):
        dados.publicar_lote(cliente, object(), 1, "api", tmp_path)

    assert cliente.tables["documents"] == [{"id": 6, "content": "Existente"}]
    assert cliente.tables["raw_documents"][0]["status"] == "cru"
    assert list(tmp_path.iterdir()) == []


def test_publicar_lote_falha_externa_preserva_base(tmp_path, monkeypatch):
    _prep_publicacao(monkeypatch)

    def falhar_embedding(*args, **kwargs):
        raise RuntimeError("Embedding indisponível")

    monkeypatch.setattr(dados, "reembed_lote", falhar_embedding)
    cliente = FakeSupabaseClient()
    cliente.tables["raw_documents"] = [{"id": 1, "texto": "cru", "status": "cru"}]
    cliente.tables["documents"] = [{"id": 977, "content": "Existente"}]

    with pytest.raises(RuntimeError, match="Embedding indisponível"):
        dados.publicar_lote(cliente, object(), 1, "manual", tmp_path)

    assert cliente.tables["documents"] == [{"id": 977, "content": "Existente"}]
    assert cliente.tables["raw_documents"][0]["status"] == "cru"
    assert list(tmp_path.iterdir()) == []


def test_extrair_texto_api_decodifica_sem_ocr():
    conteudo = dados.extrair_texto(
        cliente=MagicMock(),
        mistral_key="",
        arquivo_bytes=b'{"info": {}}',
        tipo="api",
        nome_arquivo="col.json",
    )
    assert conteudo == '{"info": {}}'


def test_dashboard_usa_api_local_por_padrao():
    from dashboard import dados

    assert dados.DEFAULT_API_BASE == "http://localhost:8000"
