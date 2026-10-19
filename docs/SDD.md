# SDD no Digi

SDD significa desenvolvimento orientado por especificação. Mudanças de comportamento começam por um documento que define problema, contrato, limites e evidência de aceite; depois são implementadas e testadas. A especificação deve refletir o comportamento final, incluindo alterações de escopo.

## Organização

- `specs/`: requisitos de comportamento e critérios de aceite, numerados e ligados ao código/testes.
- `docs/`: decisões, planos, operação e relatórios de revisão.
- `db/migrations/`: fonte ordenada e executável de alterações do banco.
- `tests/`: evidência automatizada de contratos e regressões.

A especificação não substitui uma migração de banco nem comprova que algo está implementado. Estado planejado deve ser explícito. Não anunciar uma funcionalidade no README antes de ela existir e ser validada.

## Fluxo

1. Descrever problema, objetivo e escopo com evidência; distinguir fato observado de hipótese.
2. Definir entradas, saídas, autenticação, erros, configuração ausente, limites e efeitos persistentes.
3. Identificar guardrails relevantes e o resultado esperado em falha parcial/indeterminada.
4. Definir casos de aceite observáveis e ligá-los aos testes antes da mudança de comportamento.
5. Implementar usando [TDD](TDD.md); manter responsabilidades das camadas de `AGENTS.md`.
6. Atualizar especificação para a solução final, executar gates e registrar pendências/limitações.

Mudança pequena não precisa de documento extenso. Correção relevante de segurança ou integridade precisa tornar explícito qual estado será preservado em falha. Documentação e remoção de arquivos usam verificação direta quando não mudam comportamento de negócio.

## Modelo de especificação

```markdown
# NNN — Nome do comportamento

Estado: planejado | em implementação | implementado e validado | validado com pendências

## Problema e objetivo
Evidência, usuário afetado e resultado esperado.

## Contrato
Entradas, saídas, limites, configuração, autenticação e falhas.

## Critérios de aceite
Casos de sucesso, inválido, configuração ausente e erro externo.
Efeitos persistentes e estado preservado em falha.

## Rastreabilidade
Código, testes, migrações, guardrails e documentação operacional.

## Validação e pendências
RED/GREEN quando aplicável, resultados e limitações.
```

## Especificações atuais

| Spec | Escopo | Estado |
| --- | --- | --- |
| [001 — Publicação de documentos](../specs/001-publicacao-documentos.md) | Rejeitar publicação vazia e dependências ausentes, preservando a base | Implementado e testado |
| [002 — Integração do Jev](../specs/002-integracao-jev.md) | Reranking, verificação, limites e comparação | Implementado offline; piloto e calibração pendentes |
| [003 — Pré-requisitos Jev](../specs/003-pre-requisitos-jev.md) | Curadoria explícita, confirmação de ingestão, salt, abas independentes e dependências | Implementado e testado |
| [004 — Piloto com histórico](../specs/004-piloto-jev-historico.md) | Comparação somente leitura com perguntas e referências registradas | Executado; revisão humana e calibração pendentes |
| [005 — Critérios e controles Jev](../specs/005-criterios-jev-controles.md) | Rubricas específicas, rejeição e comparação em controles congelados | Executado; rótulos humanos, calibração e reserva pendentes |
| [006 — Calibração experimental Jev](../specs/006-calibracao-jev-experimental.md) | Perfil congelado e reserva com anotação IA explícita | Executado; revisão humana parcial, rollout pendente |
| [007 — Jev por afirmação](../specs/007-jev-afirmacoes.md) | Diagnóstico por trechos e nova reserva independente | Executado; segmentação literal aumentou bloqueios |
| [008 — Contexto e curadoria global](../specs/008-jev-contexto-curadoria.md) | Choice por trecho contextual e Noul global; perfil separado | Calibração sem candidato elegível; reserva sem avaliação |
| [009 — Fidelidade documental](../specs/009-jev-fidelidade-documental.md) | Separar suporte documental de validade externa; preservar trechos/limiares | Revisão humana rejeitou fonte de tags; v4 aprovou 6/6 respostas erradas |
| [010 — Recuperação e evidência](../specs/010-rag-recuperacao-evidencia.md) | Encontrar correções fora dos primeiros 15 candidatos e respeitar restrições documentadas | Regressão funcional conhecida passou; encerramentos genéricos ainda pendentes |
| [011 — Análise de servidor](../specs/011-analise-servidor.md) | Distinguir configuração de consumo, preservar evidência e evitar dimensionamento inventado | Código local e gates aprovados; qualidade real reprovada, revisão documental pendente |
| [012 — Continuação de servidor](../specs/012-servidor-continuacao.md) | Preservar política em follow-up e classificar atualização isolada de perfil como orientação | Continuidade/classificação corrigidas localmente; qualidade integral reprovada |

Pendências de qualidade solicitadas pelo usuário, incluindo revisão posterior
da análise de servidor, estão em [PENDENCIAS_RAG.md](PENDENCIAS_RAG.md).

Para o Jev, usar o [plano detalhado](IMPLEMENTACAO_JEV.md), definir os critérios numéricos antes de ativar enforcement e conservar a distinção entre custo estimado, custo observado e qualidade medida. A preparação de documentação não ativa o fornecedor.
