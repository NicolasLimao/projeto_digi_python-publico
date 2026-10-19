import pytest

from src.services.chunker import (
    ChunkerService,
    chunk_contextual_estrutural,
    chunk_text,
    construir_indice,
    limpar_ocr,
    rechunk_manual,
)


def test_empty_text_returns_no_chunks():
    assert chunk_text("   ") == []


def test_headings_and_paragraphs_are_preserved():
    text = (
        "# Instalação\n\n"
        + "Primeiro parágrafo. " * 10
        + "\n\n## Uso\n\n"
        + "Segundo parágrafo. " * 10
    )
    chunks = chunk_text(text, max_chars=300)
    assert len(chunks) >= 2
    assert any("Instalação" in chunk for chunk in chunks)
    assert any("Uso" in chunk for chunk in chunks)


def test_every_chunk_respects_maximum_size():
    chunks = chunk_text("Sentença longa. " * 300, max_chars=180, overlap_chars=20)
    assert chunks
    assert all(len(chunk) <= 180 for chunk in chunks)


def test_tiny_text_is_not_lost():
    assert chunk_text("curto", min_chars=30) == ["curto"]


def test_invalid_overlap_is_rejected():
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("texto", max_chars=100, overlap_chars=100)


def test_service_wrapper_uses_valid_python_implementation():
    assert ChunkerService.chunk_semantic("Um texto simples e suficientemente longo para um chunk.")


def test_defaults_inalterados_regressao():
    # com os defaults, a saída não muda (parâmetros novos são neutros)
    texto = "# A\n\n" + "Frase um. " * 20 + "\n\n## B\n\n" + "Frase dois. " * 20
    esperado = chunk_text(texto, max_chars=300)
    assert chunk_text(texto, max_chars=300, inter_overlap_chars=0, merge_min_chars=0) == esperado


def test_inter_overlap_semeia_inicio_do_proximo_chunk():
    p1 = "Alfa " * 40  # ~200 chars
    p2 = "Beta " * 40
    texto = p1.strip() + "\n\n" + p2.strip()
    chunks = chunk_text(texto, max_chars=220, inter_overlap_chars=40)
    assert len(chunks) >= 2
    # o início do 2º chunk contém a cauda do 1º (overlap presente)
    cauda_do_primeiro = chunks[0][-30:].split(" ", 1)[-1]
    assert cauda_do_primeiro.split()[0] in chunks[1][:60]
    # overlap cortado em espaço: nenhuma palavra partida no começo do 2º
    assert not chunks[1].startswith(" ")


def test_inter_overlap_invalido_rejeitado():
    with pytest.raises(ValueError, match="inter_overlap"):
        chunk_text("texto", max_chars=100, overlap_chars=10, inter_overlap_chars=100)


def test_merge_min_funde_chunk_final_pequeno_no_anterior():
    # dois blocos grandes (mas < max_chars) + um bloco final minúsculo
    grande = "Palavra " * 125  # 999 chars, um chunk cada
    texto = grande.strip() + "\n\n" + grande.strip() + "\n\nFim."
    chunks = chunk_text(texto, max_chars=1000, merge_min_chars=400)
    assert all(len(c) >= 400 for c in chunks)  # nada pequeno sobra
    assert "Fim." in chunks[-1]  # o final minúsculo foi fundido, não descartado


def test_limpar_ocr_remove_furniture_e_imagens():
    texto = (
        "# Novidades\n\n"
        "Conteúdo real da seção.\n\n"
        "20\n\n"
        "31/07/2026, 17:08\n\n"
        "Manual Digisac\n\n"
        "Site: https://digisac.com.br/\n\n"
        "![img-1.jpeg](img-1.jpeg)\n\n"
        "---\n\n"
        "Mais conteúdo real."
    )
    limpo = limpar_ocr(texto)
    assert "31/07/2026" not in limpo
    assert "Manual Digisac" not in limpo
    assert "Site:" not in limpo
    assert "img-1.jpeg" not in limpo
    assert "---" not in limpo
    assert "\n20\n" not in f"\n{limpo}\n"  # número de página solto sumiu
    assert "Conteúdo real da seção." in limpo
    assert "Mais conteúdo real." in limpo
    assert "# Novidades" in limpo


def test_construir_indice_lista_headings():
    texto = "# A\n\ncorpo\n\n## B\n\ncorpo\n\n### C\n\ncorpo"
    indice = construir_indice(texto)
    assert indice == "# A | ## B | ### C"


def test_chunk_contextual_todo_chunk_tem_breadcrumb():
    texto = (
        "# GUIA\n\n## Seção Longa\n\n"
        + "Frase de conteúdo. " * 120  # força mais de um chunk
        + "\n\n## Vazia\n\n## Com Corpo\n\nTexto curto final."
    )
    chunks = chunk_contextual_estrutural(texto)
    assert len(chunks) >= 2
    # todo chunk começa com o breadcrumb da sua seção
    assert all(c["texto"].startswith(c["breadcrumb"]) for c in chunks)
    assert all(c["breadcrumb"].startswith("#") for c in chunks)
    # a seção "## Vazia" (sem corpo) NÃO virou chunk
    assert not any(c["breadcrumb"].endswith("## Vazia") for c in chunks)
    # a seção longa aparece com breadcrumb hierárquico
    assert any(c["breadcrumb"] == "# GUIA > ## Seção Longa" for c in chunks)
    # o corpo final curto foi emitido sob sua própria seção
    assert any("Texto curto final." in c["corpo"] for c in chunks)


def test_rechunk_manual_funde_cacos_e_remove_separadores():
    # simula a fragmentação: título sozinho, parágrafos curtos, separador de página
    texto = (
        "# Webhooks — Eventos de Mensagem\n\n"
        "A Digisac suporta disparos de webhook.\n\n"
        "---\n\n"
        "## Eventos disponíveis\n\n"
        "- message.created dispara quando uma mensagem chega.\n\n"
        "## Configuração\n\n"
        "Endpoint: POST /api/v1/me/webhooks para criar um webhook novo.\n\n"
        "## Importante\n\n"
        "Os eventos cobrem mensagens enviadas pelo atendente e recebidas do lead."
    )
    resultado = rechunk_manual(texto)
    # os cacos viraram poucos chunks coerentes
    assert len(resultado) <= 3
    # nenhum separador solto sobrou
    assert all("---" not in c for c in resultado)
    # o título ficou junto do conteúdo (não é um chunk só de título)
    assert any(c.startswith("# Webhooks") and len(c) > 60 for c in resultado)
