# 010 — Recuperação e evidência de procedimentos

Estado: validado com pendências de redação e de avaliação geral.

## Problema

Após corrigir a fonte de tags, a pergunta original recebeu resposta correta,
mas uma paráfrase curta não recuperou a correção. Diagnóstico real encontrou a
curadoria em 19º na busca híbrida, fora dos 15 candidatos. A geração combinou
exportação geral com um filtro inexistente. Não é falha de publicação.

## Contrato

- Buscar 30 candidatos por padrão, com `retrieval_candidate_count` configurável
  entre 1 e 60. O conjunto comporta ao menos o limite final, que continua
  limitado por `max_chunks`. Busca original e reescrita continuam concorrentes;
  união deduplicada e limitada antes do reranking.
- Reranking OpenAI preserva até 6000 caracteres de cada curadoria confiável,
  inclusive a resposta após o cabeçalho da pergunta. Trechos comuns continuam
  com 300 caracteres, salvo `rerank_full_context=true`. Autoridade vem somente
  de metadata; curadoria irrelevante não ganha prioridade automática.
- Geração só fornece procedimentos que atendem às restrições da pergunta com
  suporte específico nas fontes. Evidência parcial não autoriza inventar
  filtros, menus ou uma alternativa condicional. Ausência de suporte não
  equivale a prova de inexistência; correção relevante explícita prevalece.
  Com curadoria aplicável, trechos comuns não acrescentam alternativas; a
  geração usa temperatura zero para reduzir variação, sem promessa determinista.
- Documentos substituídos continuam descartados. Sem credenciais ou em falha
  externa, preservar os erros genéricos existentes; não fornecer resposta fake.
- Sem nova publicação, migração, alteração de histórico ou ativação do Jev.
  Integração alternativa conserva seus limites; validação real desta etapa
  mede somente o RAG OpenAI atual, não melhoria de qualidade do Jev.

## Aceite e rastreabilidade

| Critério | Código / testes |
| --- | --- |
| Correção em 19º pode chegar às fontes finais, respeitando limite final | `RAGAgent.retrieve`; regressão em `tests/agents/test_rag_agent.py` |
| Configuração inválida recusada; limites injetados e dual-query preservados | `Settings`; `tests/test_config.py`, testes do agente |
| Resposta curada após caractere 300 visível; texto comum não se autopromove | `OpenAIService.rerank`; `tests/services/test_openai_service.py` |
| Contrato de geração exige suporte às restrições sem inventar alternativa | Prompt de `generate_response`; captura de transporte offline e teste real |
| Configuração ausente e erro externo sem resposta inventada | Testes existentes dos serviços e agente, mais regressão de falha do reranking |
| Pergunta original e variações negam somente a função corrigida; exportação geral continua permitida quando documentada | Piloto real, repetido, somente leitura, artefato privado com perguntas/fontes/respostas |

## Validação e limites

Registrar RED antes da implementação. Testes offline comprovam recuperação,
contratos e limites; não comprovam qualidade de respostas de IA. Piloto real
é regressão de caso conhecido, sem nova reserva nem retuning dos relatórios Jev.
A ampliação é limitada, não garante encontrar toda correção do banco; custo de
reranking pode crescer. Não misturar sucesso deste caso com validação global.

RED offline: a correção em 19º não chegava às fontes; a resposta curada depois
do caractere 300 não era enviada; contrato de restrições ausente e configuração
fora dos limites aceita. Execução dirigida: cinco falhas esperadas, três casos
existentes passaram. GREEN inicial: 73 testes dirigidos e 424 na suíte completa.

Primeira regressão real: 18 respostas em seis perguntas, três repetições, mais
três respostas com somente o documento de exportação geral. Recuperação passou
(12/12 correções selecionadas nos casos de tags; 6/6 controles gerais sem ela),
mas geração reprovou: duas respostas sugeriram filtrar uma planilha externamente
sem evidência dos atributos exportados, e 3/3 respostas com fonte parcial ainda
inventaram filtro ou conteúdo do arquivo. Artefatos originais preservados em
`teste-correcao-rag-20261005.json` e `manifesto-correcao-rag-20261005.json`.

A falha real motivou uma regra final explícita: curadoria relevante encerra a
resposta em seu conteúdo; fonte parcial não fornece um procedimento geral como
solução específica. Nova rodada usa os mesmos casos conhecidos, com código
congelado antes das chamadas em outro manifesto, sem alterar a rodada falha.
Isso é iteração de regressão conhecida, não ajuste em reserva ou evidência de
generalização. Validar também que o suporte ausente não vira negação universal.

## Resultado final — 05/10/2026

Segunda rodada eliminou o filtro inventado e as alternativas de planilha nos
casos testados, mas uma resposta ainda sugeriu outros relatórios sem suporte.
Removida a permissão de complementar curadoria relevante com trechos comuns;
temperatura de geração passou de 0,5 para zero. Rodada v2 preservada.

Rodada v3, congelada antes das chamadas: seis perguntas, três repetições,
18 respostas do RAG, mais três gerações com o documento real de exportação
geral como única fonte. Revisão do assistente contra a correção humana explícita
e os documentos recuperados, sem novo aceite humano das respostas inteiras:

- 12/12 respostas de tags selecionaram a correção e negaram a operação descrita,
  sem inventar menu/filtro ou solução externa. Documento substituído não voltou.
- 6/6 controles gerais não selecionaram a correção de tags e mantiveram os
  procedimentos documentados de exportação/importação.
- 3/3 respostas com fonte parcial reconheceram ausência de orientação específica,
  sem passos inventados nem concluir inexistência só por falta de documentação.
- Estado dos documentos e registro de origem conferido antes/depois e preservado;
  nenhuma escrita, histórico ou ativação do Jev nesta etapa.

**O aceite funcional do caso passou; a regra de não acrescentar encerramentos
não foi plenamente obedecida.** Cinco das 12 respostas de tags ainda acrescentam
oferta genérica de ajuda ou encaminhamento ao N2. Não apresentam um procedimento
inventado, mas são pendência de redação e impedem anunciar aderência literal
integral à curadoria. Temperatura zero também não garante respostas idênticas.

Artefatos privados: `manifesto-correcao-rag-v3-20261005.json`,
`teste-correcao-rag-v3-20261005.json` e `correcao-rag-20261005.md`. Rodadas v1/v2
com falhas preservadas; entradas/resultados Jev anteriores não foram alterados.
21 observações sobre casos conhecidos, não 21 perguntas independentes. Testado
em `orientacao`, sem histórico, com OpenAI; outros modos, assuntos e fornecedores
não ganharam validação de qualidade. O limite 30 pode ainda perder outras fontes;
não é garantia de encontrar toda curadoria relevante.

RED/GREEN e refatoração registrados acima. Gates finais: 424 testes, Ruff
check/format, mypy (`src main.py evals dashboard`), Bandit e pip-audit padrão
passaram; auditoria sem vulnerabilidades conhecidas. Sem migração ou deploy.
API já em execução precisa recarregar o código para usar a mudança.
Revisão posterior de análise de servidor registrada em
[PENDENCIAS_RAG.md](../docs/PENDENCIAS_RAG.md), sem investigação antecipada.
