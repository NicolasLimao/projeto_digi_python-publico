# API RAG Digi — Relatório Completo de Auditoria e Melhorias

**Data da auditoria:** 13/07/2026  
**Arquivo auditado:** `projeto_digi_python-main.zip`  
**Versão do Python:** 3.12  
**Resultado:** projeto corrigido e validado localmente. O deploy em produção ainda depende da aplicação da migração do banco e das configurações descritas neste relatório.

## 1. Resumo executivo

O projeto original apresenta uma boa proposta de produto e uma arquitetura RAG reconhecível, mas não estava suficientemente seguro, reproduzível e estável para uso em produção.

Os problemas mais graves encontrados foram:

- código Python inválido que impedia a compilação do projeto;
- endpoints sem autenticação capazes de gerar custos de IA e expor históricos;
- permissões excessivas no Supabase;
- ingestão remota vulnerável a SSRF e consumo excessivo de recursos;
- chamadas síncronas bloqueando rotas assíncronas;
- geração de dados fictícios quando integrações falhavam;
- entradas, downloads e documentos sem limites adequados;
- dependências sem travamento completo e ausência de validação contínua.

A implementação foi reestruturada com uma factory do FastAPI, injeção de dependências, gerenciamento do ciclo de vida dos clientes, configurações e contratos estritos, autenticação por chave, CORS e hosts controlados, ingestão segura, acesso ao banco apenas pelo backend, tratamento seguro de erros, dependências travadas, CI e uma suíte de testes ampliada.

### Resultado comparativo

| Verificação | Situação original | Resultado após as correções |
|---|---:|---:|
| Compilação Python | Falhava por sintaxe inválida em `chunker.py` | Aprovada |
| Testes | 45 aprovados, 31 falhas e 3 erros | 97 aprovados |
| Ruff | 38 ocorrências e falha de análise | Aprovado, 0 ocorrências |
| Formatação | Bloqueada pelo erro de sintaxe | Aprovada |
| Mypy estrito | Bloqueado por erros de sintaxe e tipagem | Aprovado em 28 arquivos-fonte |
| Bandit | 1 ocorrência média relacionada a `0.0.0.0` | 0 ocorrências; bind de deploy documentado |
| Dependências | Ambiente de ferramenta com 6 alertas no `pip` 25.0.1 | 0 vulnerabilidades conhecidas no `requirements.lock`; `pip` 26.1.2 |
| Verificação de segredos | Exemplos com formatos semelhantes a credenciais | Nenhum segredo detectado; somente placeholders explícitos |

Não foram utilizadas credenciais reais da OpenAI, Supabase, Mistral, Discord ou SquareCloud. Portanto, compatibilidade com os provedores, migração dos dados existentes, latência, consumo e qualidade do RAG ainda precisam ser validados em homologação.

## 2. Escopo e metodologia

A auditoria contemplou:

- estrutura do repositório e conteúdo do arquivo ZIP;
- sintaxe, imports, configuração, contratos HTTP e comportamento assíncrono;
- autenticação, autorização, CORS, validação de hosts e proteção de dados;
- logs, divulgação de erros, prompt injection, SSRF e limites de download;
- políticas RLS, tabelas, views e migrações do Supabase;
- classificação, validação de escopo, busca, reranking, geração e formatação;
- histórico, feedback, ingestão de documentos e OCR;
- testes unitários, testes de API e integrações locais;
- dependências de produção e desenvolvimento;
- análise estática, tipagem, vulnerabilidades e possíveis segredos;
- CI, endpoints operacionais, deploy e documentação.

Os repositórios de referência fornecidos foram tratados como catálogos externos não confiáveis. Nenhuma skill, prompt, hook ou código desses catálogos foi instalado automaticamente. As práticas relevantes foram adaptadas para controles nativos do projeto e verificadas localmente.

## 3. Problemas encontrados e correções aplicadas

### Crítico — o código não compilava

**Problema:** o arquivo `src/services/chunker.py` utilizava uma expressão regular com sintaxe JavaScript dentro do Python:

```text
text.split(/.../m)
```

Isso impedia a coleta dos testes, a análise de tipos e a inicialização em produção.

**Correção:** o código foi substituído por um chunker semântico em Python, com suporte a títulos, parágrafos, divisão por frases, tamanho máximo e sobreposição controlada. Também foram adicionados testes específicos.

### Crítico — operações sensíveis e pagas sem autenticação

**Problema:** as rotas de RAG, ingestão, histórico, limpeza e feedback podiam ser chamadas sem autenticação. Isso permitia acesso a conversas e abuso de recursos pagos, como embeddings, geração de respostas, OCR e armazenamento.

**Correção:** todas as rotas `/api/*` agora exigem o cabeçalho:

```http
X-API-Key: <API_AUTH_TOKEN>
```

A comparação da chave utiliza tempo constante. Quando `ENVIRONMENT=production`, a aplicação não inicia sem `API_AUTH_TOKEN`. Apenas `/`, `/health` e `/ready` permanecem públicos.

O bot do Discord ou outro serviço consumidor deve enviar a chave em cada solicitação. Essa chave nunca deve ser colocada em um frontend público.

### Crítico — acesso excessivo ao banco de dados

**Problema:** a política original do histórico permitia operações anônimas, mesmo armazenando perguntas, respostas, fontes, feedbacks, canal e dados de recuperação.

**Correção:** as migrações agora:

- habilitam RLS nas tabelas protegidas;
- removem políticas anônimas conhecidas;
- revogam acesso dos papéis `anon` e `authenticated`;
- protegem as views de analytics;
- adicionam as colunas efetivamente utilizadas pela API;
- validam os valores de modo e feedback;
- mantêm o acesso pelo backend usando `service_role`.

**Ação necessária no deploy:** faça backup do banco, verifique registros incompatíveis e execute `db/migrations/002_harden_api_data.sql` como administrador antes de ativar a API corrigida.

### Crítico — risco de SSRF e esgotamento de recursos na ingestão

**Problema:** anexos remotos não possuíam controles suficientes de URL, redirecionamento, tamanho, páginas, quantidade de arquivos e volume de texto extraído.

**Correção:** a ingestão agora possui:

- HTTPS obrigatório;
- allowlist exata de host;
- bloqueio de usuário e senha na URL;
- somente porta HTTPS padrão;
- redirecionamentos desativados e rejeitados;
- download em streaming;
- limite de bytes por arquivo;
- timeout configurável;
- limite de anexos;
- limite de páginas do PDF;
- limite total de texto extraído;
- lista estrita de formatos suportados.

Por padrão, apenas os CDNs oficiais usados pelo Discord são aceitos. Foram incluídos testes para redirecionamentos e vetores de SSRF.

### Alto — dados fictícios escondiam falhas reais

**Problema:** quando OpenAI ou Supabase não estavam configurados, alguns caminhos retornavam embeddings, documentos ou identificadores artificiais. Isso fazia integrações quebradas parecerem funcionais e contaminava métricas.

**Correção:** operações de geração, embedding, banco e histórico agora falham de forma explícita quando o provedor necessário não está disponível. Heurísticas locais determinísticas permanecem apenas para classificação e escopo em desenvolvimento; elas não criam respostas de IA, embeddings, documentos ou IDs falsos.

### Alto — chamadas bloqueantes em rotas assíncronas

**Problema:** SDKs síncronos do Supabase e OCR eram executados diretamente em fluxos assíncronos, bloqueando o event loop e reduzindo a capacidade de atendimento simultâneo.

**Correção:** operações síncronas de banco e OCR agora utilizam `asyncio.to_thread`. Classificação, validação e recuperação continuam concorrentes. Quando o modo já é informado pelo cliente, a classificação é ignorada, economizando latência e tokens.

### Alto — configuração e clientes difíceis de testar

**Problema:** configurações globais carregadas no import e criação dispersa de clientes dificultavam testes isolados, encerramento correto e validação dos ambientes.

**Correção:** foram implementados:

- `Settings` validado pelo Pydantic;
- validação obrigatória de segredos em produção;
- parsing de allowlists separadas por vírgula;
- limites de timeout, retry, arquivos e chunks;
- factory da aplicação FastAPI;
- injeção de dependências;
- reutilização de clientes pelo estado da aplicação;
- encerramento dos clientes no lifespan;
- configuração injetada nos agentes e no pipeline.

### Alto — contratos de entrada permissivos

**Problema:** strings, listas, modos, feedbacks, URLs, identificadores e números não eram limitados adequadamente. Também havia valores mutáveis compartilhados.

**Correção:** os contratos Pydantic agora:

- rejeitam campos desconhecidos;
- limitam strings e listas;
- validam URLs e valores numéricos;
- utilizam valores literais para modos e feedback;
- criam listas e dicionários independentes para cada objeto.

### Alto — risco de exposição em logs e mensagens de erro

**Problema:** alguns logs incluíam trechos das perguntas, identificadores de usuários, objetos de resposta ou erros internos dos provedores.

**Correção:** os logs passaram a ser estruturados em JSON e utilizar timestamps UTC. Em vez do conteúdo das conversas, são registrados tamanhos, status e dimensões seguras. Erros detalhados ficam no servidor, enquanto o cliente recebe mensagens genéricas. O Sentry é configurado com `send_default_pii=False`.

Também foi adicionado um identificador de requisição para correlação de problemas sem utilizar a pergunta do usuário como identificador.

### Alto — histórico e documentos como vetores de prompt injection

**Problema:** documentos recuperados e mensagens anteriores eram inseridos no prompt sem uma fronteira de confiança suficientemente clara.

**Correção:** o prompt agora:

- identifica documentos e histórico como conteúdo não confiável;
- orienta o modelo a ignorar comandos inseridos nesses dados;
- bloqueia instruções de revelação de segredos ou mudança das regras;
- separa histórico, classificação, pergunta e contexto com delimitadores.

Essa proteção reduz o risco, mas não garante segurança absoluta. Testes adversariais contínuos ainda são recomendados.

### Médio — proteções HTTP incompletas

**Problema:** CORS e hosts eram permissivos, e os comportamentos de desenvolvimento e produção não estavam suficientemente separados.

**Correção:** CORS permanece desabilitado por padrão e aceita apenas origens exatas configuradas. Também foram adicionados:

- validação de hosts confiáveis;
- `X-Request-ID`;
- `X-Content-Type-Options: nosniff`;
- bloqueio de frames;
- política de referrer;
- política de permissões;
- `Cache-Control: no-store` nas rotas da API;
- desativação do OpenAPI em produção.

### Médio — dependências não reproduzíveis

**Problema:** as dependências não estavam completamente travadas, e não havia um fluxo automatizado de qualidade e segurança.

**Correção:** foram adicionados:

- versões exatas das dependências diretas;
- `requirements.lock` para produção;
- `requirements-dev.lock` para desenvolvimento e CI;
- `uv.lock`;
- `.python-version`;
- `pyproject.toml`;
- Ruff;
- mypy estrito;
- Bandit;
- pip-audit;
- Dependabot;
- GitHub Actions com permissões mínimas.

### Médio — documentação operacional insuficiente

**Problema:** o repositório não registrava de maneira durável as regras de segurança, arquitetura e validação necessárias para futuros desenvolvedores e agentes de código.

**Correção:** foram adicionados ou atualizados:

- `AGENTS.md`;
- `SECURITY.md`;
- `.env.example` sanitizado;
- início rápido no `README.md`;
- ordem das migrações;
- comandos de validação;
- checklist de deploy;
- este relatório completo.

## 4. Nova organização do projeto

```text
main.py                         entrada mínima da aplicação
src/app.py                      factory, lifespan, middlewares e health checks
src/api/auth.py                 autenticação por chave
src/api/dependencies.py         criação, reutilização e encerramento dos serviços
src/api/                        contratos HTTP validados
src/pipeline/                   orquestração do fluxo RAG
src/agents/                     agentes pequenos e especializados
src/services/                   integrações, histórico, chunking e ingestão
src/models/                     contratos Pydantic estritos
db/migrations/                  fonte ordenada das alterações do banco
tests/                          testes de agentes, API, serviços e integração local
.github/workflows/ci.yml        verificações automáticas de qualidade e segurança
AGENTS.md / SECURITY.md         regras de manutenção e produção
requirements*.lock / uv.lock   ambientes reproduzíveis
AUDIT_REPORT.md                 este relatório
```

Ambientes virtuais, caches, bytecode, `.env` local e arquivos temporários não foram incluídos no ZIP final.

## 5. Melhorias de desempenho e confiabilidade

- Clientes OpenAI e HTTP são reutilizados e encerrados corretamente.
- Operações bloqueantes do Supabase e OCR são executadas fora do event loop.
- A classificação é ignorada quando o modo já foi informado.
- Classificação, validação de escopo e recuperação continuam concorrentes.
- Embeddings e inserts utilizam lotes limitados.
- Chamadas externas possuem timeout e retries controlados.
- Downloads são realizados em streaming e limitados antes da leitura do PDF.
- Quantidade e tamanho dos chunks, candidatos, páginas e textos são limitados.
- Falhas ao salvar histórico não substituem uma resposta RAG válida.
- `/health` verifica o processo e `/ready` confirma a presença da configuração necessária.

Os números de aproximadamente 10 segundos de latência e 90% de aprovação presentes no README original não foram verificados de forma independente. Eles agora estão identificados como métricas históricas declaradas.

## 6. Evidências da validação

Comandos executados sobre o código corrigido:

```text
ruff check .                                        APROVADO — 0 ocorrências
ruff format --check .                               APROVADO — 48 arquivos
mypy src main.py                                    APROVADO — 28 arquivos-fonte
pytest -q                                           APROVADO — 97 testes
python -m compileall -q src main.py                 APROVADO
bandit -r src main.py -c pyproject.toml             APROVADO — 0 ocorrências
pip-audit -r requirements.lock                      APROVADO — 0 vulnerabilidades
teste de parsing das configurações                  APROVADO
verificação de padrões de segredos                  APROVADO — somente placeholders
instalação limpa com requirements-dev.lock          APROVADO — 97 testes
teste do projeto extraído do ZIP final              APROVADO — 97 testes
```

A regra `B104` do Bandit foi excluída porque uma aplicação ASGI hospedada precisa aceitar bind em `0.0.0.0`. O endereço é configurável e não substitui autenticação, firewall ou controles da hospedagem.

## 7. Referências utilizadas

- <https://github.com/awesome-gptx/awesome-gpt> foi utilizado como referência ampla do ecossistema de GPTs. Trata-se de um catálogo, não de um padrão executável de qualidade.
- <https://github.com/hesreallyhim/awesome-claude-code> contribuiu para a ênfase em engenharia de contexto, segurança explícita e resultados verificáveis.
- <https://github.com/RoggeOhta/awesome-codex-cli> contribuiu para as orientações duráveis em `AGENTS.md`, automações, CI e segurança.
- <https://github.com/ComposioHQ/awesome-codex-skills> contribuiu para o planejamento em etapas, testes de fluxos críticos e quality gates reutilizáveis. As práticas foram adaptadas, sem instalar skills externas.
- <https://github.com/sindresorhus/awesome-chatgpt> retornou `404 Not Found` por meio da integração do GitHub durante a auditoria. Por isso, seu conteúdo não foi utilizado nem presumido.

Nenhum desses catálogos recebeu acesso à aplicação ou foi incorporado como dependência de produção.

## 8. Procedimento obrigatório para produção

1. Faça backup completo do Supabase.
2. Verifique valores existentes nas colunas `modo` e `feedback`.
3. Execute `db/migrations/002_harden_api_data.sql` como administrador.
4. Defina `ENVIRONMENT=production`.
5. Configure `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` e `API_AUTH_TOKEN`.
6. Gere uma nova chave longa e aleatória para `API_AUTH_TOKEN`.
7. Configure o bot para enviar essa chave no cabeçalho `X-API-Key`.
8. Mantenha a `SUPABASE_SERVICE_ROLE_KEY` somente no backend.
9. Configure exatamente os hosts confiáveis e mantenha CORS vazio se não houver frontend web.
10. Faça o deploy em homologação e teste RAG, ingestão, feedback, limpeza e histórico.
11. Confirme que `VERSION=recommended` na SquareCloud utiliza uma versão compatível do Python 3.12.
12. Meça o pico de memória durante o processamento do maior PDF permitido. Os 512 MB atuais podem ser insuficientes.
13. Confirme que `/ready` retorna HTTP 200.
14. Execute uma solicitação RAG autenticada antes da liberação.

O rollback da aplicação não deve restaurar políticas anônimas no banco. Problemas de migração ou dados devem ser revertidos pelo backup.

## 9. Métricas essenciais recomendadas

As métricas não devem conter perguntas, respostas, documentos ou IDs reais como labels.

### API e disponibilidade

- total de requisições por rota e status;
- taxa de erros 4xx e 5xx;
- disponibilidade da aplicação;
- falhas do endpoint de prontidão;
- quantidade de reinicializações.

### Latência

- p50, p95 e p99 do pipeline completo;
- tempo de classificação;
- tempo de validação de escopo;
- tempo de embedding;
- tempo de busca no Supabase;
- tempo de reranking;
- tempo de geração;
- tempo de OCR e ingestão.

### Custos de IA

- tokens de entrada e saída;
- custo estimado por solicitação;
- custo diário e mensal;
- consumo do orçamento;
- retries, timeouts e rate limits por provedor.

### Qualidade do RAG

- quantidade de candidatos recuperados;
- chunks utilizados;
- taxa de respostas sem documentos;
- distribuição dos scores;
- taxa de override da validação de escopo;
- distribuição dos modos;
- taxa de perguntas fora do escopo;
- cobertura de feedback;
- taxa de aprovação e reprovação.

### Ingestão

- arquivos, bytes e páginas processados;
- chunks gerados;
- downloads rejeitados;
- falhas de extração;
- falhas de OCR;
- falhas de insert no banco.

### Infraestrutura

- uso e pico de memória;
- uso de CPU;
- event-loop lag;
- saturação de workers;
- conexões e erros dos provedores.

Alertas iniciais sugeridos:

- taxa de 5xx acima de 2% de forma sustentada;
- p95 acima do SLO por 10 minutos;
- erros de um provedor acima de 5%;
- aumento relevante na taxa de respostas sem documentos;
- gasto diário acima do orçamento;
- falha do `/ready`;
- memória acima de 85%.

## 10. Próximas melhorias recomendadas

### Prioridade 0 — antes de receber tráfego de produção

- concluir o procedimento de deploy descrito acima;
- trocar qualquer segredo que possa ter aparecido em commits, logs, prints ou chats antigos;
- confirmar que o bot trata corretamente respostas HTTP 401 e 503;
- confirmar que o bot nunca registra `API_AUTH_TOKEN` nos logs.

### Prioridade 1 — próxima versão

- adicionar rate limiting no gateway;
- limitar concorrência e tamanho total do corpo HTTP;
- criar monitoramento de abuso e custos;
- montar um dataset RAG versionado;
- medir correção, fundamentação, relevância, recusas e prompt injection;
- criar testes em homologação com recursos descartáveis da OpenAI e Supabase;
- testar as migrações contra uma cópia semelhante ao banco de produção;
- criar verificações sintéticas de conectividade;
- executar a retenção de histórico por tarefa agendada e auditável;
- documentar o processo de exclusão de dados de usuários.

### Prioridade 2 — qualidade, custo e desempenho

- avaliar um reranker dedicado ou cross-encoder;
- comparar qualquer mudança utilizando o dataset versionado;
- estudar cache de queries e embeddings com expiração e isolamento;
- adicionar OpenTelemetry sem PII;
- contabilizar custos por etapa e provedor;
- avaliar respostas em streaming somente após definir cancelamentos e falhas parciais;
- versionar prompts, modelos e configurações;
- executar canary antes de trocar modelo ou dimensão dos embeddings.

## 11. Riscos residuais

- As proteções contra prompt injection reduzem o risco, mas não garantem o comportamento do modelo.
- A chave `service_role` possui permissões amplas. Uma API comprometida ainda pode acessar dados protegidos.
- O endpoint `/ready` verifica configuração, não conectividade real com os provedores.
- A migração não foi executada no banco de produção do usuário.
- Qualidade, compatibilidade, latência, custo e memória não foram medidos com credenciais reais.
- `squarecloud.app` utiliza `VERSION=recommended`; a versão resolvida pelo provedor deve ser confirmada.

## 12. Avaliação final

O projeto agora é um candidato de deploy significativamente mais seguro, testável e sustentável. Os quality gates locais e de segurança estão aprovados, as dependências estão travadas, os fluxos críticos possuem testes e as principais fronteiras de segurança foram corrigidas.

Ainda assim, o projeto não deve ser enviado diretamente para produção sem:

1. aplicar a migração do banco;
2. configurar a autenticação no bot;
3. executar testes integrados em homologação;
4. medir memória e desempenho;
5. ativar métricas, alertas e controle de custos.
