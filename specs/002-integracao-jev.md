# 002 — Integração do Jev

Estado: implementação concluída com testes offline; piloto real e calibração pendentes. Integração desativada por padrão.

## Objetivo

Avaliar suporte documental e comparar reranking no Digi, com política explícita de entrega e medição em português. O contrato completo, configurações, arquitetura, custos e rollout estão no [plano de implementação](../docs/IMPLEMENTACAO_JEV.md).

## Critérios obrigatórios

- Integração desligada preserva o comportamento atual e não faz chamadas Jev.
- Cliente assíncrono injetável, reutilizado e fechado pelo lifespan quando próprio.
- Chave ausente com modo ativo falha na configuração, sem vazar valores.
- IDs, tipos e probabilidades externos são validados; documentos inventados não entram no contexto.
- Fontes curadas mantêm autoridade por origem confiável; texto não promove a si mesmo.
- Verificação em observação mede e registra sem alterar a resposta entregue.
- Verificação obrigatória não aprova timeout, erro externo ou ausência de suporte.
- Chamadas, tokens, retries, concorrência e deadline são limitados.
- Métricas separadas do score de busca, com RLS e retenção para qualquer persistência nova.
- Avaliação A/B/C/D separa melhoria de entrada de melhoria do modelo; critérios numéricos são definidos antes do rollout.

## Pré-requisitos e validação

Resolver os achados pendentes indicados no code review e no plano. Ampliar dataset, reservar casos e revisar divergências com analista humano. Aplicar [TDD](../docs/TDD.md), [SDD](../docs/SDD.md) e [guardrails](../docs/GUARDRAILS.md).

Rastreabilidade:

- Configuração e chave/critério ausentes: `tests/test_config.py`.
- Contrato, respostas inválidas, deadline, retries, orçamento, concorrência e cancelamento: `tests/services/test_typesafe_service.py`.
- Seleção, observação e fallback: `tests/agents/test_rag_agent.py`.
- Verificação após formatação, bloqueio e histórico da resposta entregue: `tests/integration/test_rag_pipeline.py`.
- Reutilização, fechamento e autenticação: `tests/test_typesafe_wiring.py`.
- Comparação congelada A/B/C/D e limites de entrada: `tests/test_compare_jev.py`.
- Pré-requisitos de integridade: [spec 003](003-pre-requisitos-jev.md).

Métricas ficam em logs e no runner local; não há tabela nova ou acesso anônimo a criar. O orçamento é por processo e volátil, não um teto financeiro de conta. Limites de bytes conservadores não substituem o uso informado pelo fornecedor. O [guia operacional](../docs/JEV_OPERACAO.md) detalha a configuração efetiva e suas limitações.

RED: configuração e pré-requisitos tiveram 13 falhas reais antes da correção. Os testes do serviço foram escritos antes da criação do módulo (RED de coleção por módulo ausente). Os testes de integração complementam essa evidência. Não houve chamada real ao Jev nem experimento de qualidade por falta de chave. Ativar enforcement depende de calibração e revisão humana, não apenas de testes offline.
