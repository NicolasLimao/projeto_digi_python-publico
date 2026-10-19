# 004 — Piloto Jev com perguntas reais dos analistas

Estado: implementado e executado; avaliação humana e calibração pendentes.

## Objetivo e contrato

Comparar respostas registradas no `historico_digi` com A (reranker OpenAI atual),
B (OpenAI com entrada ampliada), C (reranker Jev) e D (simulação de verificação de C).
Congelar os mesmos candidatos reais antes do reranking. A geração continua OpenAI.
O runner manual não chama a rota de produção, não escreve no banco e não ativa Jev.

Ler somente com service-role, sem fallback anônimo. Amostrar até 30 perguntas,
deduplicadas por pergunta normalizada e distribuídas por feedback e modo, de até
100 linhas por estrato. Excluir canais de avaliação/diagnóstico e perguntas inválidas.
Ler até 100 revisões recentes de `duvidas_respondidas`: apenas ingestão confirmada,
chunks positivos e resposta não descartada podem servir de referência registrada.
Uma correção posterior prevalece para a mesma pergunta; descarte posterior remove
a referência. Feedback positivo e resposta antiga do bot não viram gabarito.

As respostas históricas só são verificadas com seus próprios IDs de fonte; fontes
faltantes/aposentadas impedem essa verificação. O conteúdo recuperado é o atual,
não um snapshot da época. As variantes novas usam candidatos congelados da base
atual. Sem histórico conversacional, o piloto compara o núcleo RAG para perguntas
isoladas; não equivale à reprodução completa do pipeline em produção.

## Aceite e rastreabilidade

- Seleção diversa, limites, duplicatas e referências: `tests/test_pilot_jev.py`.
- Falta de configuração rejeitada antes de construir clientes; falha de leitura
  encerra captura sem anunciar sucesso; falha de uma variante preserva as demais.
- Consulta somente leitura, via `asyncio.to_thread`, cliente injetável:
  `src/services/pilot_source_service.py` e testes offline.
- Runner: `evals/pilot_jev.py`, usando os serviços reais, sem embeddings sintéticos.
- Verificação de A/B/C e histórico distingue aprovação, rejeição e falha técnica.
- Relatório incremental JSON e Markdown em `evals/reports/`, ignorados pelo Git,
  sem user_id/chaves. Conteúdo interno não é exibido nos logs.
- Revisões humanas exigidas, inclusão da referência na recuperação sinalizada,
  sem alegar ganho de qualidade a partir da taxa de aprovação do próprio Jev.

## Limites e efeitos

Deadline de 180 segundos por caso; limites existentes de OpenAI/Jev, concorrência
compartilhada Jev e orçamento local de US$ 1 preservados. Fontes históricas limitadas
a 30 IDs e documento a 100 mil caracteres; conteúdo excessivo não é truncado para
aprovar verificação. Falha não repete escrita, pois não há nenhuma escrita remota.
Sem migrações ou mudanças nas rotas. Guardrails G03/G04/G06/G10/G12/G13.

## Primeira rodada — 02/10/2026

RED: quatro testes de seleção falharam antes da implementação (função ainda
sem comportamento). GREEN: seleção, referências, falhas independentes,
configuração ausente e fonte somente textual cobertas offline.

Piloto com 12 perguntas: quatro negativas, quatro positivas, quatro sem feedback;
cinco de orientação, cinco de bug e duas de resposta-cliente. Seis referências
registradas de analistas, todas presentes nos candidatos. Uma execução de A/B/C
por pergunta e D simulado, sem escrita remota. São 36 respostas novas, não 48:
D reutiliza C. Foram recuperadas fontes identificáveis para oito respostas
históricas; duas tinham documentos ausentes/aposentados e duas apenas rótulos
genéricos, impedindo confrontação com suas fontes originais.

Os limiares provisórios não aprovaram nenhuma resposta nova contra o conjunto
selecionado de fontes. Uma checagem complementar contra as seis referências
registradas aprovou somente duas das próprias referências idênticas ao conteúdo
fornecido. Esse controle indica risco de bloqueio indevido e impede usar a taxa
Jev como medida de acurácia ou habilitar enforcement. O confronto textual
mostra correções já utilizadas pelo RAG atual, também preservadas pela variante
Jev; não há ganho de qualidade comprovado.

Artefatos locais ignorados: `evals/reports/piloto-jev-20261002.json`, `.md`,
`.frozen.jsonl` e `piloto-jev-20261002-analise.md`. A checagem complementar ficou
registrada nesses artefatos e em `evals/reports/recheck_jev.py`; não repete a
geração OpenAI. Conteúdo interno permanece fora do Git.

Achados restantes: referências não reservadas e algumas perguntas dependentes
de contexto anterior; nenhuma revisão humana assinada; histórico sem snapshot
do corpus; `SupabaseService.get_document` continua assumindo embeddings em lista,
incompatível com vetores serializados como texto observados no piloto. O leitor
do piloto projeta só texto/metadados; esse achado no serviço geral não foi alterado.

Gates finais: Ruff check e format, mypy (incluindo evals/dashboard), Bandit e
306 testes aprovados. A auditoria padrão não conseguiu criar ambiente temporário
por falta de `ensurepip`; o modo complementar `--disable-pip --no-deps` não
encontrou vulnerabilidades conhecidas. O gate padrão permanece pendente.
