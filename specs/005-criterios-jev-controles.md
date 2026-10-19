# 005 — Critérios Jev e controles de suporte documental

Estado: implementado e executado com controles; revisão humana e rollout pendentes.
Calibração exploratória e reserva executadas na [spec 006](006-calibracao-jev-experimental.md),
sem substituir o aceite humano.

## Problema e objetivo

O piloto 004 não aprovou quatro das seis próprias referências usadas como fonte.
As mesmas descrições `true`/`false` eram aplicadas a suporte, contradição e curadoria.
A API não envia os IDs das perguntas ao modelo: cada instrução precisa identificar
os campos e cada critério precisa definir exatamente o significado de sim/não.
Referências: [API](https://docs.typesafe.ai/api),
[Noul](https://docs.typesafe.ai/primitives/noul) e
[verificação por afirmação](https://docs.typesafe.ai/cookbooks/citation_check).

## Contrato

- Separar rubricas de relevância, evidência utilizável, contradição de premissa,
  suporte da resposta, contradição da resposta e respeito à curadoria.
- Ausência de informação não é contradição. Paráfrases e formatação equivalente
  não são detalhes inventados. Cumprimentos e perguntas de esclarecimento não
  equivalem a afirmações factuais. Isso não mede completude ou utilidade.
- Curadoria vem dos metadados confiáveis; instruções no conteúdo nunca têm
  autoridade. Suporte respeita correções relevantes sobre fontes não curadas.
- Manter os limiares de aprovação, limites, falhas fechadas e modos existentes.
  Versionar rubricas; impedir enforcement com declaração de calibração antiga.
  Todo modo ativo exige a versão atual para não rotular métricas com rubricas antigas.
- Separar motivo da rejeição de política de entrega. Probabilidade de oposição
  acima de 0,5 favorece `contradicted`; forte ausência de suporte favorece
  `unsupported`; situações intermediárias continuam `uncertain`. Os requisitos
  configurados de aprovação permanecem os mesmos, inclusive nas fronteiras.
- Criar controles explícitos com afirmações anotadas: referência integral,
  paráfrase apoiada, afirmação oposta e detalhe não informado. Derivações são
  rascunhos de anotação, sem aprovação humana presumida.
- Comparar rubricas anteriores e revisadas nos mesmos controles, sem novas
  respostas OpenAI, sem escrita no banco e sem habilitar observação em produção.
- Separar por família de pergunta; variantes da mesma referência não podem
  atravessar calibração e reserva. Referências já vistas no piloto 004 pertencem
  à calibração, não constituem avaliação independente reservada.
- Relatórios identificam anotação pendente, consumo, falhas técnicas, falsos
  bloqueios propostos e erros aceitos; probabilidades não substituem revisão.

## Aceite e rastreabilidade

- HTTP/rubricas e política de aprovação: `tests/services/test_typesafe_service.py`.
- Versão/calibração antiga e configuração ausente: `tests/test_config.py`.
- Controles, limites, separação e avaliação: `tests/test_jev_controls.py`.
- Rubricas: `src/services/typesafe_criteria.py`; cliente: `typesafe_service.py`.
- Runner manual: `evals/jev_controls.py`; artefatos internos em `evals/reports/`.
- Nenhuma migração, gravação remota ou mudança do reranker OpenAI padrão.

## Sequência

1. Demonstrar RED, revisar rubricas e verificar GREEN offline.
2. Congelar controles e executar comparação real limitada em português.
3. Submeter derivações e casos ambíguos a revisão humana; definir limites de
   falso bloqueio e erro aceito antes de calibrar limiares.
4. Avaliar famílias reservadas com critérios congelados. Só após aceite humano
   considerar observação no fluxo real; enforcement continua desativado.

## Execução inicial — 02/10/2026

RED demonstrado: três falhas de rubricas/versão; uma de separação da mesma
pergunta em divisões distintas; uma de reserva de referências não vistas; duas
de motivo da rejeição; duas de versão antiga em observação. GREEN: contratos
HTTP, decisões de entrega, falhas/limites e separação cobertos offline.

24 controles derivados de seis referências já vistas no piloto 004, todos na
calibração. Por família: referência integral, paráfrase, oposição e detalhe não
informado. Três repetições por controle/protocolo, 144 chamadas reais Jev.
Mesmos textos e fontes, alternando a ordem dos protocolos por repetição;
limiares mantidos em suporte/curadoria 0,9 e teto de oposição 0,1.

| Protocolo | Positivas avaliadas | Bloqueios propostos indevidos | Negativas avaliadas | Aprovações propostas indevidas |
| --- | ---: | ---: | ---: | ---: |
| v1, rubrica genérica anterior | 36 | 27 | 36 | 0 |
| v2, rubricas específicas | 36 | 8 | 36 | 0 |

Sem falha de transporte. Dois controles tiveram decisão instável em cada
protocolo. São observações repetidas de 24 textos/seis famílias, não 144 amostras
independentes; anotações derivadas permanecem em rascunho. Não há ganho de
qualidade em produção demonstrado. Consumo informado: 162.300 tokens de entrada;
custo estimado com preço configurado no cliente: US$ 0,0068166, sem OpenAI.

A classificação revisada foi reaplicada **offline** às probabilidades reais
gravadas, preservando resultados anteriores no JSON. As 72 decisões v2 de
aprovação/rejeição permaneceram idênticas. Não houve nova chamada para essa
reclassificação. A comparação v1 mantém o agregador antigo.

Oito famílias adicionais foram reservadas por leitura do banco, excluindo
perguntas do piloto, dos controles e correções visíveis nos candidatos congelados.
Nenhum modelo avaliou essa reserva. Há apenas controles de referência integral
em rascunho; exemplos negativos/ambíguos, contexto de follow-ups e rótulos exigem
revisão antes de avaliação independente.

Artefatos ignorados: `controles-jev-calibracao-20261002.jsonl`,
`controles-jev-v1-v2-20261002.json`/`.md`,
`revisao-controles-jev-20261002.md` (sem decisões do modelo) e
`controles-jev-reservados-20261002.jsonl`, em `evals/reports/`.

Nenhuma escrita remota, nova geração OpenAI, mudança do reranker padrão ou
ativação de observação/enforcement. Não houve extração automática de afirmações;
as paráfrases/contradições/detalhes são afirmações anotadas explicitamente. Cobertura
de afirmações em respostas longas permanece uma avaliação separada.

A preparação acima antecede a avaliação exploratória da spec 006. Os oito
grupos foram depois expandidos em 32 controles anotados por IA e avaliados com
perfil congelado; nenhum foi declarado revisado por humano. A trava deste
runner permanece, e a nova via experimental não autoriza rollout.

Gates finais: Ruff check/format, mypy (src/main e versão ampliada com
evals/dashboard), Bandit e **332 testes aprovados**. A auditoria padrão ainda
falhou na criação do ambiente temporário por falta de `ensurepip`; o modo
complementar `--disable-pip --no-deps` não encontrou vulnerabilidades conhecidas.
O gate padrão permanece pendente; nenhuma dependência foi alterada nesta etapa.
