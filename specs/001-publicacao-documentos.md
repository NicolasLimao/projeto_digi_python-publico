# 001 — Guardrail de publicação de documentos

Estado: implementado e validado funcionalmente; dependências corrigidas na etapa Jev, com auditoria complementar aprovada.

## Problema

`dashboard.dados.publicar_lote` aceita um conjunto vazio de novos chunks como publicação completa e remove os documentos antigos. A operação deve preservar a base quando não há substitutos ou quando dependências/serviços falham.

## Comportamento requerido

1. Supabase e OpenAI devem ser fornecidos; ausência de dependência causa erro antes de acessar ou alterar o banco.
2. Documento que não produz chunks utilizáveis causa erro antes de inserir, gravar backup, remover documentos ou atualizar o status do cru.
3. JSON inválido causa erro de entrada, preservando lote e status.
4. Falha externa ao gerar embeddings preserva lote e status.
5. Sucesso continua inserindo novos chunks, conferindo contagem, salvando backup, removendo antigos e marcando o cru.
6. Insert incompleto continua abortando antes de remover o lote antigo.

A publicação continua sendo um processo em etapas, não uma transação atômica. Rollback de inserção parcial, concorrência entre publicações e idempotência ficam para uma especificação futura.

## Aceite e rastreabilidade

| Caso | Evidência |
| --- | --- |
| Texto e collection sem conteúdo | Teste parametrizado: lote e cru inalterados; sem backup |
| Dependência ausente | Teste parametrizado para Supabase/OpenAI |
| Collection inválida | Teste de erro de parsing sem mutação |
| Embedding indisponível | Teste com falha externa controlada sem mutação |
| Publicação válida | Testes existentes para manual e API |
| Insert incompleto | Teste existente de abortar sem apagar |

Código: `dashboard/dados.py::publicar_lote`. Testes: `tests/test_dashboard_dados.py`. Achado original: [code review](../docs/CODE_REVIEW_20260930.md).

## Validação

Registrar RED dos novos testes, implementar o guardrail mínimo, registrar GREEN da suíte dirigida e executar os gates de `AGENTS.md`. Dependências vulneráveis são uma pendência distinta e não devem ser ocultadas por uma suíte verde.

Evidência dirigida: RED com quatro falhas esperadas (dois casos vazios e duas dependências ausentes); JSON inválido e falha externa já preservavam a base. Depois da implementação, os dez casos de publicação passaram. Resultados finais são registrados no code review.
