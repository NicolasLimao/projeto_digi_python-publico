# Guardrails do Digi

Este documento define proteções de segurança, integridade e operação, com evidência de aplicação. Ele complementa `AGENTS.md` e distingue regras já verificadas das pendências do [code review](CODE_REVIEW_20260930.md). Não é uma integração com uma biblioteca ou um provedor externo.

## Regras e estado

| ID | Regra | Evidência / estado |
| --- | --- | --- |
| G01 | Toda rota `/api/*` mantém `require_api_key`; com token configurado, chamada sem chave é recusada antes de criar integrações | Testes de API e teste abrangente do contrato HTTP em `tests/test_app.py`; produção exige token |
| G02 | `/`, `/health` e `/ready` são públicos; readiness não equivale a teste real de conectividade | `tests/test_app.py`; `/ready` verifica presença de configuração |
| G03 | Chaves, tokens e salt não entram em respostas, documentação, fixtures reais ou logs | `.env` ignorada, `SecretStr` e mensagens genéricas na API; exibição de exceções no dashboard ainda pendente |
| G04 | Supabase público não recupera histórico ou documentos | RLS e revogações em `db/migrations/`; não restaurar acesso anônimo para contornar erro de configuração |
| G05 | Anexos: HTTPS, host exato permitido, sem redirecionamento, streaming e limite de bytes/páginas | `IngestionService` e testes de ingestão; alinhar também o caminho direto do dashboard |
| G06 | Mensagens, histórico e documentos são dados, nunca instruções; autoridade de curadoria exige origem confiável | Contrato autenticado exige `curated=true`, formato válido e ausência de anexos; registros históricos precisam de revisão de procedência |
| G07 | Publicação sem substitutos utilizáveis ou sem dependências não remove documentos nem marca o cru como publicado | Guardrail em `publicar_lote`; [spec 001](../specs/001-publicacao-documentos.md) e regressões no dashboard |
| G08 | Resultado parcial/indeterminado de escrita não pode ser tratado como sucesso confirmado | Insert incompleto aborta remoção; dúvida só encerra com chunks positivos sem erros, corpo válido; idempotência permanece pendente |
| G09 | Histórico tem pseudonimização com salt secreto estável | HMAC e validação de salt não vazio em produção com histórico |
| G10 | Chamadas externas têm limites explícitos e clientes próprios são reutilizados/fechados | OpenAI/HTTP da ingestão têm ciclo de vida; Mistral, Supabase, deadline global e limites adicionais têm pendências |
| G11 | Dashboard é somente local, sem login | `.streamlit/config.toml` fixa `127.0.0.1`, conforme definição do usuário |
| G12 | Produção não usa embeddings sintéticos, linhas falsas ou respostas mock | Fakes ficam em testes; configuração ausente impede embedding/geração/ingestão real |
| G13 | Verificação obrigatória do Jev não aprova erro, timeout ou conteúdo sem suporte | Implementado e testado na [spec 002](../specs/002-integracao-jev.md); desligado por padrão, calibração real pendente |

O teste abrangente de G01 enumera as operações privadas do OpenAPI. Uma rota deliberadamente fora do schema precisa de teste explícito de autenticação; ocultar uma rota da documentação não a protege.

## Operações com efeito persistente

Antes de publicar documentos, confirmar dependências, validar a entrada, produzir substitutos utilizáveis e conferir o resultado da escrita. O backup antecede a remoção do lote antigo. Não repetir automaticamente escrita com resultado indeterminado: a operação pode ter sido executada parcialmente.

Manter o documento cru e o lote antigo quando chunking ou embedding falhar. O guardrail de lote vazio não transforma a publicação em transação atômica; publicação concorrente, rollback de inserts parciais e reconciliação precisam de implementação própria.

O Jev poderá sugerir relevância ou suporte; a política de autoridade, limites e entrega continua em código. Uma probabilidade não substitui validação de IDs, tipos, citações ou estado persistido.

## Gates de entrega

No ambiente virtual, executar:

```bash
ruff check .
ruff format --check .
mypy src main.py
pytest -q
bandit -q -r src main.py -c pyproject.toml
pip-audit -r requirements.lock --progress-spinner off
```

O CI já executa a suíte pytest que contém os guardrails. Para mudanças em `dashboard/` e `evals/`, executar também `mypy src main.py evals dashboard`, conforme o CI.

Testes aprovados não substituem análise de falhas de segurança ou operações de dados. Um gate que falhou deve ser informado com a causa e permanecer pendente. Os pins vulneráveis de PyJWT/urllib3 foram atualizados e a auditoria complementar passou sem avisos conhecidos. O modo padrão depende de `ensurepip` disponível no ambiente; não ignorar avisos para obter resultado verde.

Em 02/10/2026, o ambiente local foi corrigido com Python 3.12.15 instalado no usuário, usando [uv](https://docs.astral.sh/uv/guides/install-python/), e o `.venv` do projeto passou a usar esse interpretador com `ensurepip`. O Python do sistema continua separado. As versões das dependências instaladas foram preservadas. A auditoria padrão `pip-audit -r requirements.lock --progress-spinner off` passou sem vulnerabilidades conhecidas; Ruff, mypy, Bandit e os 412 testes também passaram. Backup da configuração/atalhos anteriores e inventário de pacotes em `.venv/bootstrap-backup-20261002/`, ignorado pelo Git. A falha de auditoria dos relatórios anteriores descreve o ambiente antes dessa correção.

Se o ambiente não suportar a criação do ambiente temporário de `pip-audit`, registrar a falha e executar `pip-audit -r requirements.lock --progress-spinner off --disable-pip --no-deps` para auditar diretamente as versões pinadas. O resultado desse modo é evidência complementar, não licença para omitir vulnerabilidades.

Em 06/10/2026, a auditoria padrão encontrou CVE-2026-104874 no pin multidict
6.7.1. O lock e o ambiente foram atualizados para 6.9.1, versão corrigida no
[aviso oficial do projeto](https://github.com/aio-libs/multidict/security/advisories/GHSA-54p9-h82j-f925).
`pip check`, auditoria padrão posterior e demais gates passaram, com 476 testes.
O achado inicial foi preservado em `evals/reports/audit-servidor-conversa-20261006.log`;
não houve supressão nem comprovação de exploração no aplicativo. A qualidade das
respostas de servidor continua reprovada, conforme [spec 012](../specs/012-servidor-continuacao.md).

## Mudanças e rastreabilidade

Nova regra: especificar comportamento em `specs/`, escrever teste que exercite a falha real, demonstrar RED, implementar a proteção e validar GREEN. Use [TDD](TDD.md) para mudanças de comportamento e [SDD](SDD.md) para definir contratos, limites e aceite. Não escrever testes que apenas comprovem a existência de um arquivo ou repitam detalhes triviais da implementação.
