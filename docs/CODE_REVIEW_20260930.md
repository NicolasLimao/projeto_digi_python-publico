# Code review do Digi — 30/09/2026

## Escopo e resultado

Atualização após implementação Jev: os achados sobre curadoria por marcador, encerramento sem confirmação, salt de produção, pins vulneráveis e interrupção de abas foram corrigidos. A exposição direta de exceções no dashboard foi substituída por mensagens genéricas e logs sem conteúdo externo. Os detalhes da primeira revisão abaixo registram o comportamento anterior; o acompanhamento final ao fim do documento prevalece para o estado atual.

Revisão da configuração, contratos e autenticação HTTP, pipeline RAG, recuperação e geração, ingestão, curadoria, dashboard, migrações, dependências, execução e documentação. Foram lidos os caminhos principais e executadas reproduções offline com clientes falsos de teste; nenhum dado real foi alterado por essas reproduções.

O dashboard é exclusivamente local e não terá login, conforme definição do usuário. A ausência de login não é um achado. A configuração do Streamlit foi fixada em `127.0.0.1`.

Esta entrega remove os arquivos Docker, atualiza instruções de execução, cria o [plano do Jev](IMPLEMENTACAO_JEV.md) e estabelece [guardrails](GUARDRAILS.md), [TDD](TDD.md) e [SDD](SDD.md). A publicação vazia foi corrigida com especificação e testes; os demais achados abaixo permanecem pendentes e devem preceder a integração quando indicado.

## Achados por prioridade

### P1 — Publicação vazia remove a base antiga — corrigido nesta entrega

Referência: [dashboard/dados.py:764](../dashboard/dados.py#L764), função `publicar_lote`, especialmente a validação de contagem e a remoção do lote.

Uma collection Postman válida, mas sem endpoints (`{"item": []}`), produz zero chunks. Como o código compara `n_inseridos == len(linhas)`, zero inserções satisfazem a conferência. O fluxo salva backup, remove o lote antigo e marca o documento cru como `chunkado`, mesmo sem publicar substitutos.

Reprodução offline com `FakeSupabaseClient`, uma linha antiga no lote e collection vazia: `inseridos=0`, `apagados=1`, `documentos_restantes=0`, `raw_status=chunkado`.

Correção aplicada: rejeitar dependências ausentes e lote sem conteúdo utilizável antes das mutações. A [spec 001](../specs/001-publicacao-documentos.md) registra o contrato. Novos testes demonstraram quatro falhas antes da correção; depois dela, os dez casos de publicação passaram, incluindo sucesso, entrada inválida, falha externa e insert incompleto. O backup permite recuperação manual. A sequência continua sem transação atômica; inserts parciais podem ficar no banco em caso de falha e precisam de estratégia de reconciliação.

### P1 — Conteúdo de anexo pode promover a si mesmo a curadoria

Referências: [src/services/ingestion_service.py:125](../src/services/ingestion_service.py#L125), [src/services/curadoria.py](../src/services/curadoria.py).

O serviço aplica `metadata_curadoria(text)` a todos os textos, inclusive textos extraídos de anexos. Um documento que contenha o padrão `Pergunta: ... / Resposta oficial validada pelo analista: ...` recebe `tipo=curadoria`, embora a decisão venha do conteúdo não confiável. Na geração, esse metadado atribui prioridade de resposta oficial e pode suplantar documentação legítima.

Reprodução offline confirmou que o marcador produz `tipo=curadoria`. A autenticação da API limita quem chama a ingestão, mas não transforma o conteúdo dos documentos em instrução ou confirmação de revisão humana.

Correção recomendada: tornar a ação de curadoria explícita no contrato autenticado, com origem confiável, e impedir que anexos comuns obtenham autoridade por marcador textual. Manter textos históricos e compatibilidade da curadoria legítima com migração/estratégia definida. Testar especialmente documento adversarial com esse marcador.

### P1 — Dashboard pode encerrar uma dúvida sem confirmação de ingestão

Referências: [dashboard/dados.py:211](../dashboard/dados.py#L211), [dashboard/app.py:312](../dashboard/app.py#L312), [src/services/ingestion_service.py](../src/services/ingestion_service.py).

`ingerir_resposta` trata HTTP 2xx com corpo não JSON como `{"chunks_created": 0}`. O dashboard registra a dúvida como respondida e mostra sucesso mesmo quando há zero chunks ou `errors` no resultado. O serviço de ingestão pode retornar HTTP 200 com falhas por lote; o código da UI não valida esses erros.

Reprodução offline confirmou o retorno de zero chunks para uma resposta 2xx não JSON. Há um teste atual que fixa esse comportamento. Uma alteração exige revisar esse teste e separar confirmação de ingestão de resultado indeterminado.

Correção recomendada: validar schema, número de chunks e erros antes de encerrar a dúvida. Para resultado indeterminado/parcial, mostrar estado próprio e permitir reconciliação; não repetir automaticamente uma operação que possa ter gravado parte do conteúdo. Idempotência deve ser planejada antes de retries de escrita.

### P1 — Configuração de produção aceita salt de pseudonimização ausente

Referências: [src/config.py:42](../src/config.py#L42), [src/services/history_service.py](../src/services/history_service.py).

`USER_ID_SALT` não participa das credenciais exigidas na validação de produção. O serviço usa string vazia quando ausente; o HMAC continua determinístico, mas perde a proteção secreta contra enumeração de IDs conhecidos. Uma nova implantação pode entrar em produção com essa configuração.

Reprodução offline: `Settings(environment="production", ... user_id_salt=None)` aceita a configuração quando as demais credenciais estão presentes. A `.env` local já foi validada com salt configurado anteriormente; o achado é a ausência da proteção de configuração, não uma afirmação de que o ambiente atual esteja sem salt.

Correção recomendada: exigir salt não vazio ao persistir histórico em produção e rejeitar whitespace. Revisar testes e documentação. Manter salt estável; trocar arbitrariamente altera as chaves do histórico existente e exige estratégia de migração.

### P1 — Dependência vulnerável bloqueia a auditoria

Referências: [requirements.lock](../requirements.lock), [requirements-dev.lock](../requirements-dev.lock), [uv.lock](../uv.lock).

A auditoria final das versões pinadas identifica 14 vulnerabilidades conhecidas: 11 em `PyJWT 2.13.0` (correção indicada em `2.14.0`) e três em `urllib3 2.7.0` (correção indicada em `2.8.0`). A consulta anterior identificava dez no PyJWT; o diagnóstico final usa a base de avisos atualizada. O projeto não satisfaz o gate de auditoria enquanto esses pins persistirem.

Correção recomendada: atualizar de maneira consistente todos os locks afetados e o ambiente de teste, verificar compatibilidade das dependências Supabase e executar a auditoria novamente. Não ignorar os avisos para aprovar a entrega. Esta revisão não altera dependências.

### P2 — Ausência do mapa de reconciliação impede carregar a ingestão

Referência: [dashboard/app.py:364](../dashboard/app.py#L364); também os `st.stop()` das condições das abas anteriores.

Streamlit executa o script inteiro das abas. `st.stop()` na aba Reconciliação interrompe a execução antes da aba Ingestão. Sem mapa de instabilidade, a aba Ingestão aparece na navegação, mas não recebe seu conteúdo. Falta de token ou erro nas dúvidas também pode interromper abas posteriores.

Reprodução com `AppTest`, Supabase falso e mapa ausente: quatro abas criadas, nenhuma exceção, zero file uploaders e ausência do título de ingestão. Isso explica por que uma checagem baseada apenas em exceções parecia aprovar o dashboard anteriormente.

Correção recomendada: renderizar cada aba em função própria e retornar localmente quando seus requisitos estiverem ausentes. Manter `st.stop()` apenas para falhas globais. Testar renderização da ingestão sem mapa, sem token de curadoria e com falha em uma aba independente.

### P2 — Exceções externas são exibidas diretamente no dashboard

Referências: [dashboard/app.py:202](../dashboard/app.py#L202), [dashboard/app.py:310](../dashboard/app.py#L310), [dashboard/app.py:342](../dashboard/app.py#L342), [dashboard/app.py:383](../dashboard/app.py#L383), [dashboard/app.py:419](../dashboard/app.py#L419).

Vários handlers interpolam `{erro}` em mensagens da interface. Exceções de rede/SDK podem incluir URLs, detalhes internos e conteúdo de resposta. Isso não segue a regra do repositório de logging no servidor e retorno de mensagem genérica ao usuário, mesmo considerando uso local.

Correção recomendada: mensagens curtas e genéricas na UI, com logging sanitizado e identificação de operação no servidor. A ingestão direta e a publicação também precisam de tratamento de falha para evitar traceback renderizado pelo Streamlit.

### P2 — Reranker não avalia todo o conteúdo disponível nem a intenção original

Referências: [src/services/openai_service.py:264](../src/services/openai_service.py#L264), [src/agents/rag_agent.py:87](../src/agents/rag_agent.py#L87).

O reranker recebe apenas 300 caracteres por candidato e a pergunta reescrita, embora a recuperação também use a original. Uma resposta correta depois desse limite não pode influenciar a ordenação. Uma reescrita que perdeu “solicitar”, por exemplo, pode privilegiar instruções para executar em vez de solicitar uma ação.

Correção recomendada: comparar a variante OpenAI com entrada melhorada antes de atribuir qualquer ganho ao Jev. Incluir pergunta original e contexto necessário, preservar metadados confiáveis e limitar o texto por política explícita. Não alterar silenciosamente o benchmark de referência.

### P2 — Exportação não permite inferir consumo nem volume da janela

Referências: [dashboard/dados.py:360](../dashboard/dados.py#L360), [sql/analytics_views.sql](../sql/analytics_views.sql).

O cabeçalho informa uma janela, mas os totais exportados são acumulados. Não há tokens por etapa, chamadas, latência por componente ou custo líquido. Dividir esses totais pelo tamanho da janela produz orçamento incorreto. O problema foi confirmado na [validação do relatório](VALIDACAO_RELATORIO_JEV_20260930.md): 1.028 acumuladas versus 702 na janela consultada.

Correção recomendada: exportar totais filtrados e acumulados com rótulos claros, período efetivo e denominadores de feedback. Para o Jev, registrar uso real por etapa e não confundir score de recuperação com probabilidade de correção.

## Melhorias adicionais a planejar

- `Mistral` é criado por chamada no fallback OCR, sem aplicar explicitamente a política de timeout/retry da aplicação nem fechar o cliente no lifespan. Consolidar em integração injetável e com ciclo de vida controlado; o offload com `asyncio.to_thread` já está presente.
- A aba Ingestão cria outro cliente Supabase a cada execução do script. Consolidar sua reutilização com o recurso já cacheado e definir fechamento dos clientes próprios.
- Consultas de listagem do dashboard usam `.select(...).execute()` sem paginação; a contagem de chaves respondidas/documentos pode ficar incompleta ao atingir o limite do servidor. Definir paginação limitada e filtros.
- Ingestão do dashboard chama OCR e gravação diretamente, sem todos os limites de páginas, texto e operações aplicados pelo caminho da API. Unificar políticas de limite e testar entradas grandes antes de ampliar seu uso.
- Não há deadline global do pipeline nem limite explícito de chunks na ingestão: timeouts por chamada e limites de caracteres não estabelecem prazo/custo total. Definir orçamento por operação antes de adicionar fan-out Jev.
- As views analíticas estão em `sql/`, embora `db/migrations/` seja a fonte ordenada de alterações do banco. Versionar a implantação das views em migração futura e revisar o filtro de canais de diagnóstico.

## Alterações aplicadas nesta entrega

- Removidos `Dockerfile`, `Dockerfile.dashboard`, `docker-compose.yml` e `.dockerignore`, conforme solicitação.
- README e guia RAG atualizados para ambiente virtual, execução Python e Streamlit local. Corrigidas as afirmações de OAuth inexistente, swap atômico e configurações de exemplo sem credenciais reais para o RAG.
- Corrigido o valor padrão documentado de `score_threshold`: 0,30.
- `.streamlit/config.toml` fixa `server.address = "127.0.0.1"`.
- Segurança operacional documenta salt estável e dashboard local sem login.
- Criado [IMPLEMENTACAO_JEV.md](IMPLEMENTACAO_JEV.md), com arquitetura, contratos, configurações, rollout, custos, testes e pré-requisitos.
- Adicionados guias de guardrails, TDD e SDD, especificações numeradas e regras correspondentes em `AGENTS.md`.
- Implementada rejeição de publicação vazia/dependências ausentes, com testes de preservação da base; adicionada regressão abrangente de autenticação das operações privadas do OpenAPI.

O comportamento de publicação foi alterado para abortar entradas inseguras. Não foram alterados contratos HTTP, lógica do RAG, dados no Supabase ou credenciais. A configuração SquareCloud permanece aplicável à API Python. O Jev continua planejado, sem chamadas ou ativação nesta entrega.

## Validação da entrega

Resultados dos gates executados no ambiente virtual:

| Gate | Resultado |
| --- | --- |
| `ruff check .` | Aprovado |
| `ruff format --check .` | Aprovado; 66 arquivos |
| `mypy src main.py evals dashboard` | Aprovado; 37 arquivos |
| `pytest -q` | 237 testes aprovados |
| `bandit -q -r src main.py -c pyproject.toml` | Aprovado |
| `pip-audit -r requirements.lock --progress-spinner off` | Falhou por ausência de `ensurepip` no ambiente temporário |
| Auditoria complementar com `--disable-pip --no-deps` | Reprovada: 14 vulnerabilidades em dois pacotes |

Os quatro arquivos Docker foram removidos e as instruções operacionais atualizadas. Streamlit está configurado para loopback e permanece em execução local. A reprodução dos achados é evidência adicional; testes aprovados não descartam os problemas demonstrados.

Limitação do ambiente: a ausência de `ensurepip` impede o modo padrão da auditoria. O modo complementar audita diretamente as versões já pinadas e reporta as vulnerabilidades citadas; não foi usada exclusão de avisos. A entrega tem validação funcional aprovada e pendências de segurança abertas.


## Acompanhamento — integração Jev

Implementados cliente HTTP assíncrono injetável, modelo fixo, reranker selecionável com fallback, ordenação em observação e verificação da resposta final em off/shadow/enforce. Limites cobrem candidatos, conteúdo, payload, resposta externa, chamadas/retries, concorrência compartilhada, prazo por etapa e orçamento volátil por processo. Probabilidades e uso não sobrescrevem score de recuperação. O histórico recebe apenas a resposta entregue.

Pré-requisitos corrigidos com testes: curadoria requer campo explícito autenticado e proíbe anexos; ingestão sem confirmação não encerra dúvida; histórico em produção exige salt não vazio; abas retornam localmente; falhas de documentos têm mensagens genéricas. Locks e ambiente passaram a PyJWT 2.15.1 e urllib3 2.8.0. Metadados históricos não foram alterados.

Validação final: Ruff e formatação aprovados (73 arquivos), mypy aprovado (40 arquivos incluindo dashboard/evals), 291 testes aprovados e Bandit aprovado. Auditoria complementar das versões fixadas, sem exclusões, não encontrou vulnerabilidades conhecidas. O comando padrão de pip-audit foi executado e continua limitado pela falta de ensurepip no sistema. O CI executa o comando padrão em Python provisionado.

Runner A/B/C/D disponível com candidatos congelados, controle de entrada, decisões e consumo observado. Não houve chamada real ao Jev porque TYPESAFE_API_KEY está ausente; qualidade em português, custo e latência reais, revisão humana e calibração permanecem pendentes. O booleano de calibração representa declaração operacional, não prova estatística. A configuração local/produção não foi alterada para ativar chamadas.

Pendências restantes: exportação acumulada versus janela, paginação de listagens, OCR/limites unificados do dashboard, ciclo de vida Mistral/Supabase, deadline global do pipeline, limite global de chunks de ingestão, idempotência/rollback/concorrência da publicação, versionamento de views analíticas e revisão de procedência da curadoria histórica. A integração desligada não depende desses novos serviços; rollout obrigatório requer resolver as pendências relevantes e comprovar ganho no piloto.

Operação e rollback: [JEV_OPERACAO.md](JEV_OPERACAO.md). Rastreabilidade: specs 001–003, testes de serviço, agentes, pipeline, wiring, dashboard e comparação. Os relatórios operacionais com conteúdo de conversas e a .env permanecem locais e ignorados pelo Git.
