import json

from src.services.postman_chunker import (
    _body_fields,
    _path_params,
    _query_params,
    chunk_postman,
)


def test_path_params_ignora_URL_e_pega_tokens():
    url = "{{URL}}/api/v1/contacts/{{contactId}}/tags/{{tagId}}"
    assert _path_params(url) == ["contactId", "tagId"]


def test_query_params_extrai_chaves():
    url = "{{URL}}/api/v1/schedule?perPage=40&page={{p}}"
    assert _query_params(url) == ["perPage", "page"]
    assert _query_params("{{URL}}/api/v1/schedule") == []


def test_body_fields_json_valido_e_invalido():
    body_ok = {"mode": "raw", "raw": '{"tagIds": ["x"], "name": "y"}'}
    assert _body_fields(body_ok) == ["tagIds", "name"]
    assert _body_fields({"mode": "raw", "raw": "não é json"}) == []
    assert _body_fields({"mode": "formdata"}) == []
    assert _body_fields(None) == []


def _collection_fixture() -> str:
    return json.dumps(
        {
            "info": {"name": "col", "schema": "v2.1"},
            "item": [
                {
                    "name": "⚙️ Gerais",
                    "item": [
                        {
                            "name": "Contatos",
                            "item": [
                                {
                                    "name": "Editar tag do contato",
                                    "request": {
                                        "method": "PUT",
                                        "url": {"raw": "{{URL}}/api/v1/contacts/{{contactId}}"},
                                        "body": {"mode": "raw", "raw": '{"tagIds": []}'},
                                    },
                                },
                                {
                                    "name": "Listar contatos",
                                    "request": {
                                        "method": "GET",
                                        "url": {"raw": "{{URL}}/api/v1/contacts?perPage=40"},
                                    },
                                },
                            ],
                        },
                        {
                            "name": "Tags",
                            "item": [
                                {
                                    "name": "Criar tag",
                                    "request": {
                                        "method": "POST",
                                        "url": {"raw": "{{URL}}/api/v1/tags"},
                                        "body": {"mode": "raw", "raw": '{"name": "x"}'},
                                    },
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": "🛠️ Populares",
                    "item": [
                        {
                            "name": "Contatos",
                            "item": [
                                {
                                    "name": "Listar contatos",
                                    "request": {
                                        "method": "GET",
                                        "url": {"raw": "{{URL}}/api/v1/contacts"},
                                    },
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        ensure_ascii=False,
    )


def test_chunk_postman_exclui_populares_e_monta_endpoints():
    chunks = chunk_postman(_collection_fixture())
    # 3 endpoints de Gerais; o duplicado em Populares foi excluído
    assert len(chunks) == 3
    nomes = {c["nome"] for c in chunks}
    assert nomes == {"Editar tag do contato", "Listar contatos", "Criar tag"}
    # recurso = pasta imediata sob o container de topo
    editar = next(c for c in chunks if c["nome"] == "Editar tag do contato")
    assert editar["recurso"] == "Contatos"
    assert editar["metodo"] == "PUT"
    # texto determinístico com método/URL/params/body
    assert "Recurso: Contatos" in editar["texto"]
    assert "PUT {{URL}}/api/v1/contacts/{{contactId}}" in editar["texto"]
    assert "Parâmetros de caminho: contactId" in editar["texto"]
    assert "Corpo (campos): tagIds" in editar["texto"]
    # GET com query, sem body
    listar = next(c for c in chunks if c["nome"] == "Listar contatos")
    assert "Parâmetros de query: perPage" in listar["texto"]
    assert "Corpo (campos)" not in listar["texto"]
