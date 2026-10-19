# 006 — Calibração experimental e avaliação reservada do Jev

Estado: implementado e executado; bloqueios indevidos ainda altos,
aceite humano e uso operacional pendentes.

## Problema e contrato

A spec 005 mediu oito bloqueios propostos de textos apoiados em 36 observações
v2. O usuário autorizou continuar os experimentos. Revisão assistida por IA
é permitida para exploração, identificada como `ai_reviewed`, distinta de
`reviewed` por humano. Não aprova curadoria nem valida verdade atual do produto.

Congelar um perfil experimental usando somente o relatório v2 de calibração,
com todas as repetições bem-sucedidas e sem truncamento. Exigir fontes/textos
idênticos aos casos anotados, versão, modelo e hash das rubricas correspondentes.
Nenhuma geração OpenAI ou escrita no banco. Configuração da aplicação preservada.

Antes dos resultados da reserva: grade de suporte/curadoria 0,90, 0,89, 0,88,
0,87 e 0,85; teto de oposição 0,10, 0,12, 0,15 e 0,20. Objetivo exploratório:
zero aprovações negativas e zero bloqueios positivos nas repetições da calibração.
Selecionar o maior suporte viável e, depois, o menor teto de oposição. Não ajustar
o perfil após a reserva. Se nenhum candidato atingir o objetivo, encerrar sem perfil.

O perfil registra hash dos casos de calibração e reserva, relatório, rubricas,
grade, revisão e limiares. Referências, famílias e perguntas normalizadas não
podem atravessar as divisões. Reserva exige controles de referência, paráfrase,
oposição e detalhe ausente por família, revisados por IA ou humano antes da chamada.

Um runner separado permite somente avaliação **experimental** da reserva com o
perfil congelado. A trava do runner operacional/anterior permanece. Comparar
limiares originais e experimentais nas mesmas probabilidades v2; até cinco
repetições, máximo 120 controles, orçamento e limites do cliente existente.
Falhas técnicas não são rejeições semânticas; salvar resultados parciais e
retornar falha. Saídas restritas a `evals/reports/`, sem sobrescrever perfil ou
relatório existente. Perfil adulterado/incompatível é rejeitado antes da rede.

## Aceite e rastreabilidade

- Anotação IA não conta como revisão humana: `tests/test_jev_controls.py`.
- Congelamento, vazamento, adulteração, falhas, configuração ausente e comparação
  com transporte injetado: `tests/test_jev_calibration.py`.
- Implementação: `evals/jev_calibration.py`, `evals/jev_controls.py`.
- Sem migração. G03, G06, G10, G12 e G13 preservados.
- Relatórios: `human_review_required=true`, `ready_for_enforcement=false` e
  `production_changed=false`; resultados exploratórios não autorizam rollout.

## Limitações

Controles derivados de referências registradas medem suporte documental, não
atualidade da referência nem completude/utilidade da resposta. Repetições não são
amostras independentes. Oito famílias são uma reserva pequena; follow-ups e
tráfego real ainda exigem avaliação. A etapa humana da spec 005 continua pendente;
esta spec acrescenta uma via exploratória, sem substituí-la.

## Execução — 02/10/2026

RED: duas falhas na anotação IA; uma na rejeição de cópia de fonte com outro ID;
uma no registro das duas decisões por repetição. GREEN: 40 testes dirigidos,
incluindo configuração ausente, transporte falho, perfil alterado e sobreposição.

24 controles de seis famílias foram revisados por IA com justificativas, sem
alterar textos/fontes/relações usados na avaliação anterior. A seleção usou apenas
72 observações v2 gravadas. O primeiro candidato viável foi suporte/curadoria
0,88 e teto de oposição 0,12: zero bloqueios positivos/zero aprovações negativas
na calibração, ante oito/zero com 0,9/0,1. O perfil foi gravado antes das chamadas
reservadas, com hash `877f86505f63196f022993ee014024ab86b4271ca07788719a68a2c2af9f55e5`.

32 controles de oito famílias novas, quatro tipos por família, foram derivados
das referências reais anteriormente reservadas. Anotação `ai_reviewed`, nenhum
aceite humano. Três repetições, 96 chamadas reais Jev, rubricas/modelo congelados.

| Política na reserva | Positivas | Bloqueios positivos propostos | Negativas | Aprovações negativas propostas | Falhas técnicas |
| --- | ---: | ---: | ---: | ---: | ---: |
| Limiares originais 0,90/0,10 | 48 | 22 | 48 | 0 | 0 |
| Perfil experimental 0,88/0,12 | 48 | 12 | 48 | 0 | 0 |

Bloqueios ainda atingem 25% das observações positivas; cinco dos 16 textos
positivos foram bloqueados ao menos uma vez. Dois controles tiveram decisões
experimentais instáveis. Nove bloqueios afetam cópias integrais das próprias
fontes e três uma paráfrase apoiada sobre saúde do número. Não ajustar limiares
na reserva: o perfil permanece congelado e sem autorização operacional.

Não houve erro de transporte ou truncamento. 124.974 tokens de entrada observados,
custo estimado pelo preço configurado US$ 0,005248908, sem OpenAI. Probabilidades
originais preservadas; decisões de ambas as políticas registradas por repetição,
derivadas offline sem chamadas adicionais. Nada foi gravado no banco ou ativado
na aplicação. O padrão continua OpenAI/off/não calibrado, limiares 0,9/0,1.

As 96 observações são repetições de 32 textos/oito famílias. A ausência de
aprovações negativas nesses controles não comprova ausência de alucinação.
O objetivo de falso bloqueio zero observado na calibração falhou na reserva.
Revisar os casos com analistas; tratar qualquer revisão futura de rubricas ou
verificação por afirmação como outro experimento, com nova reserva independente.

Artefatos ignorados em `evals/reports/`: controles `*-ia-20261002.jsonl`,
`perfil-jev-experimental-20261002.json`, `reserva-jev-experimental-20261002.json`/`.md`,
`revisao-ia-jev-20261002.md` e `analise-reserva-jev-20261002.md`.

Gates: Ruff check/format, mypy src/main e ampliado, Bandit e **358 testes
aprovados**. A auditoria padrão falhou por ausência de `ensurepip` para o ambiente
temporário; o modo complementar sem resolução não encontrou vulnerabilidades
conhecidas. O gate padrão permanece pendente. Nenhuma dependência foi alterada.

## Revisão humana parcial posterior — 02/10/2026

O usuário revisou os cinco textos que tiveram bloqueio experimental: considerou
boas as referências 002/003/004/008 e ruim a paráfrase 007 sobre saúde. O feedback
é de qualidade; não determina separadamente suporte, atualidade ou contradição.
Não reclassificar a paráfrase como alucinação sem justificativa. Os demais 27
textos não receberam revisão humana nesta etapa.

As quatro respostas consideradas boas sofreram nove bloqueios em doze avaliações.
As três rejeições da paráfrase contestada deixam de ser tratadas automaticamente
como bloqueio de resposta boa. O agregado original 12/48 continua preservado.
Em análise de sensibilidade pós-avaliação, excluindo esse controle, restam nove
bloqueios em 45 observações positivas propostas; não é uma nova avaliação reservada
nem confirmação humana de todas as positivas. As 48 negativas permanecem sem
aprovação sob rótulos IA.

Registro complementar local: `revisao-humana-parcial-jev-20261002.json`/`.md`, com
fala do usuário, hashes e decisões por caso. Não altera perfil congelado, textos
testados, resultados do modelo, banco ou configuração. Motivo e correção da
paráfrase aguardam esclarecimento. Nenhuma nova chamada externa.
