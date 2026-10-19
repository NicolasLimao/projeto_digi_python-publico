# Validação do relatório Digi: custos e implementação do Jev

Data: 30/09/2026. Arquivo local analisado: `relatorio-digi-20260930-1210.md`, mantido fora do Git por conter trechos de conversas. Complementa [VALIDACAO_TYPESAFE_RAG.md](VALIDACAO_TYPESAFE_RAG.md).

Esta análise valida os números e propõe a integração; não implementa nem mede o Jev. O volume temporal foi conferido por consulta somente de leitura à view `v_volume_diario`, exibindo apenas agregados. As estimativas de tokens abaixo são hipóteses, não medições dos prompts do Digi.

## Validação dos números

| Verificação | Resultado |
| --- | --- |
| Feedback | 455 positivos + 44 negativos + 529 sem avaliação = 1.028 |
| Modos | 899 orientação + 119 bug + 10 resposta-cliente = 1.028 |
| Canais | 1.022 dm + 5 desconhecido + 1 verif = 1.028 |
| Soma dos positivos por modo/canal | 455 em ambos |
| Soma dos negativos por modo/canal | 44 em ambos |
| Aprovação entre as avaliadas | 455 / 499 = 91,18%, consistente com 91% arredondados |
| Cobertura de feedback | 499 / 1.028 = 48,54% |
| Negativos entre as avaliadas | 44 / 499 = 8,82% |
| Negativos sobre o total | 44 / 1.028 = 4,28%; não é taxa medida de alucinação |

O relatório está aritmeticamente consistente. Não permite afirmar 91% de acerto em todas as perguntas: mais da metade não recebeu avaliação, e feedback não distingue alucinação de incompletude, formatação, insatisfação ou erro de recuperação.

“Nenhuma dúvida pendente” significa fila de curadoria vazia naquele momento, não ausência de erros. Uma dúvida pode ter sido respondida ou descartada. “Nenhuma rodada encontrada” significa ausência de baseline local disponível para o dashboard, não prova de que nunca houve avaliação em outra instalação.

## A janela de 90 dias não se aplica aos totais exportados

`dashboard/dados.py::gerar_relatorio_md` exporta o resumo geral e as tabelas por modo/canal recebidas. As views em `sql/analytics_views.sql` não aplicam filtro temporal nesses totais. O parâmetro `dias` aparece no cabeçalho, mas a exportação não inclui a série diária nem os totais filtrados da janela. O cabeçalho avisa que o feedback geral é acumulado; é inadequado dividir automaticamente 1.028 por três para estimar o mês.

Consulta à view implantada, filtrando de **03/07/2026 a 30/09/2026**, inclusive:

- Interações: **702**.
- Positivos: **274**.
- Negativos: **31**.
- Sem avaliação, por diferença: **397**.
- Dias com registros: **64**, dentro dos 90 dias corridos.
- Média equivalente por 30 dias: **702 / 90 × 30 = 234 interações**.

A consulta é uma fotografia posterior à geração do arquivo; dados podem mudar. A média de 234 é uma projeção histórica, não a contagem observada especificamente em setembro nem previsão de picos. Não há taxa de pico no relatório. O canal `verif` aparece no export; a definição SQL local não o exclui junto de `eval`, `teste`, `diag` e `diagnostico`, portanto deve ser classificado antes de considerá-lo tráfego real em avaliações futuras.

## Estimativa de custo revisada

O preço publicado em 30/09/2026 é **US$ 0,042 por milhão de tokens de entrada**, com saída gratuita, para `jev-1.13.0`. O mesmo documento informa 40 requisições/s e 100 mil tokens/s, limites sujeitos a mudanças. [Preço e limites oficiais](https://docs.typesafe.ai/models).

Hipóteses de dimensionamento:

- Reranking: até 15 candidatos, com 1.500 tokens por candidato contando pergunta, trecho, critérios e metadados: **22.500 tokens por consulta**.
- Verificação: uma avaliação agrupada da resposta e suas fontes: **10.000 tokens por consulta**.
- Reranking e verificação: **32.500 tokens por consulta**.

Se for necessário dividir a verificação em várias chamadas, repetir fontes, incluir mais histórico ou usar chunks maiores, o consumo aumenta. O número de perguntas agrupadas também adiciona tokens de instruções. Medir `usage.input_tokens` para substituir essas hipóteses.

Fórmula: `consultas × tokens por consulta / 1.000.000 × US$ 0,042`.

| Volume de referência | Só verificação | Só reranking | Reranking + verificação |
| --- | ---: | ---: | ---: |
| 1.028 interações acumuladas do arquivo | US$ 0,43 | US$ 0,97 | US$ 1,40 |
| 702 interações confirmadas em 90 dias | US$ 0,29 | US$ 0,66 | US$ 0,96 |
| 234 interações por 30 dias, média histórica | US$ 0,10 | US$ 0,22 | **US$ 0,32** |
| 1.000 interações por mês, cenário de crescimento | US$ 0,42 | US$ 0,95 | US$ 1,37 |
| 10.000 interações por mês, cenário de crescimento | US$ 4,20 | US$ 9,45 | US$ 13,65 |

No volume médio observado, aplicar uma reserva de planejamento de 20% ao cenário combinado resulta em aproximadamente **US$ 0,38 por 30 dias**. Essa reserva é arbitrada para orçamento, não uma estatística de retries. Um teto inicial de consumo de US$ 1/mês acomodaria essa estimativa; esse valor não representa recarga mínima nem limite imposto pelo fornecedor.

São custos somente do Jev: excluem OpenAI para geração, embeddings, reescrita, classificação, juiz e eventual regeneração; Supabase, OCR, infraestrutura, impostos e câmbio. A economia ao remover o reranker OpenAI depende do consumo real desse componente, que o arquivo não informa. Não é possível calcular o custo líquido ou a economia percentual apenas com este relatório.

A cobrança utiliza créditos. O contrato prevê expiração normalmente em até 12 meses e recarga automática apenas quando habilitada. Não foi confirmado publicamente valor mínimo de recarga ou mensalidade obrigatória. [Condições de cobrança](https://typesafe.ai/legal/mca).

## Proposta de implementação

### Etapa 1: baseline e verificação em observação

Começar verificando respostas sem alterar o resultado entregue. Essa primeira etapa mede o potencial de detectar afirmações sem suporte preservando o comportamento atual enquanto se coleta evidência. A taxa de aprovação relatada não justifica substituir imediatamente um componente sem comparação.

O pipeline proposto, nessa etapa, é: busca e reranker atuais → geração → formatação final → Jev confronta a resposta final com os chunks → registro de métricas. Para medir latência, a validação pode ser aguardada com timeout curto e limitado. Não criar tarefa solta sem controle de ciclo de vida para esconder o custo.

Confrontar a resposta com fontes por decisão atômica, distinguindo suporte, ausência de suporte e contradição. Cobrir também afirmações sem citação. Preservar a prioridade das respostas curadas e tratar pergunta, histórico, resposta e chunks como dados não confiáveis. O modelo não pode conferir autoridade a um documento por seu texto.

### Etapa 2: comparação de rerankers

Comparar as variantes A/B/C/D definidas no relatório anterior. Antes de atribuir ganhos ao Jev, medir o efeito de fornecer ao reranker OpenAI a pergunta original e texto além dos 300 caracteres atuais. Na variante Jev, avaliar candidatos de forma independente com concorrência limitada, preservando IDs e metadados. Uma pergunta `Noul` pode medir evidência para ordenar; limiares precisam de calibração própria.

Não substituir embeddings ou reingerir a base para esse experimento. O Jev usa texto e decisões estruturadas. Há receitas oficiais para [seleção de passagens](https://docs.typesafe.ai/cookbooks/classifying_rag_passages) e [verificação contra citações](https://docs.typesafe.ai/cookbooks/citation_check).

### Etapa 3: ativação gradual

Ativar o reranker Jev somente com ganho demonstrado no conjunto reservado. Habilitar bloqueio de respostas sem suporte em uma fase posterior, calibrando falsos bloqueios e abstenções. Falha do reranker pode usar a ordenação de fallback explicitamente definida; falha de um verificador obrigatório não pode ser registrada como resposta aprovada. Definir encaminhamento/abstenção conforme o modo e permitir rollback por configuração.

Proposta de alterações, ainda não aplicadas:

| Área | Alteração proposta |
| --- | --- |
| `src/services/typesafe_service.py` | Serviço assíncrono com cliente injetável, validação de respostas, reranking e verificação |
| `src/config.py` e `.env.example` | Chave secreta, versão fixa, modos `off`/`shadow`/`enforce`, timeout, retries e limites |
| `src/api/dependencies.py` | Reutilização do cliente pelo application state e fechamento no lifespan |
| `src/agents/rag_agent.py` | Injeção do reranker e uso da pergunta original com contexto necessário |
| `src/pipeline/rag_pipeline.py` | Verificação da resposta final antes de persistir e entregar, conforme configuração |
| `db/migrations/` | Se métricas forem persistidas, migração ordenada com acesso restrito e retenção definida |
| `dashboard/dados.py` e dashboard | Volume efetivo da janela, consumo por etapa, decisões e falhas do Jev |
| `tests/` | Sucesso, entrada inválida, configuração ausente, falha externa, limites e fallback |

Registrar modelo efetivo, tokens, número de chamadas, duração por etapa, falhas, decisões, custo estimado e versão dos critérios. Não guardar bodies sensíveis nos logs. Manter métricas Jev separadas do `score` de recuperação existente. A API retorna uso de tokens; pode ser integrada pelo endpoint HTTP com o cliente já usado pelo projeto. [Referência da API](https://docs.typesafe.ai/api).

Limites iniciais devem incluir candidatos, tamanho do texto, histórico, tokens, concorrência global e prazo total do processamento. Distinguir timeout por chamada de deadline total: várias ondas de candidatos podem somar latência. Não presumir que o volume diário médio representa o pico simultâneo.

## Validação de qualidade necessária

O dataset local tem 32 casos, sendo 31 de orientação e um de resposta-cliente; falta cobertura de bug, que representa 119 interações acumuladas. Os 44 negativos do arquivo merecem classificação por causa antes de virar rubricas. Não estão contidos em detalhe neste export, e os casos existentes não devem ser assumidos equivalentes a todos eles.

Adicionar amostra de positivos e perguntas sem feedback, além de follow-ups, ausência de documentação, fontes conflitantes e instruções adversariais. Reservar casos que não participem do ajuste de critérios. Usar revisão humana nas divergências; o juiz automático atual não deve ser a única referência.

Medir correção factual, fidelidade às fontes, completude, respostas úteis entregues, bloqueios indevidos, abstenções, estabilidade, latência p50/p95 e custo observado. Uma queda em respostas sem suporte com aumento grande de recusas pode ser regressão. Também não confundir a aprovação de feedback com groundedness.

Ao preço e às hipóteses acima, executar 32 casos cinco vezes custa cerca de US$ 0,22 de Jev para a variante combinada; executar separadamente as variantes Jev de reranking e de reranking + verificação custa cerca de US$ 0,37, somadas. Gerador, juiz e variantes OpenAI têm custos adicionais.

## Decisão

**O custo estimado do Jev é pequeno no volume confirmado: cerca de US$ 0,32 por 30 dias para reranking e verificação. O ponto decisivo é comprovar melhora em português sem perda de respostas úteis.**

O arquivo é consistente como resumo acumulado de feedback, mas não basta como baseline de alucinação ou como relatório de consumo de tokens. A consulta temporal adicional permite dimensionar o experimento. A implementação recomendada começa com avaliação offline e verificação em observação, seguida de comparação e ativação gradual. Não há benchmark real do Jev nem implantação realizada nesta análise.
