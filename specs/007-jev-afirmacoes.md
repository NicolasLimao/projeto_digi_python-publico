# 007 — Diagnóstico Jev por trechos factuais

Estado: implementado e executado; mais bloqueios na segmentação literal,
revisão humana e novo protocolo pendentes. Sem uso operacional.

## Problema e desenho congelado

O usuário considerou boas quatro respostas integrais que tiveram nove bloqueios
experimentais em doze observações. A paráfrase de saúde foi considerada ruim;
fica fora dos controles positivos desta etapa, sem inventar um motivo ou correção.

Verificar trechos factuais anotados individualmente, usando o cliente, modelo
jev-1.13.0, as mesmas três rubricas v2 e limiares 0,88/0,12. Não ajustar critérios
depois dos resultados. O [cookbook oficial](https://docs.typesafe.ai/cookbooks/citation_check)
motiva verificação por afirmação; aqui mantemos Noul para isolar a mudança de
granularidade. Não implementar Choice nem extração automática nesta etapa.

Diagnóstico de desenvolvimento: quatro referências aprovadas pelo usuário e
suas variantes negativas já vistas. Avaliação adicional: quatro famílias novas
do banco, excluindo perguntas anteriores/piloto/correções entre seus candidatos,
com referência integral, paráfrase, oposição e detalhe ausente. Derivações e
segmentação são revisão IA, não revisão humana. Avaliar integral e trechos
nas mesmas fontes, até três repetições. Todo texto precisa ter os fatos cobertos;
uma afirmação não aprovada impede a aprovação agregada. Isso pode aumentar
bloqueios quando há muitos fatos; medir resultado por resposta e por trecho.

## Contrato e limites

- Runner exclusivamente manual em `evals/jev_claims.py`; nenhuma alteração da API,
  pipeline, cliente de produção, banco ou configuração operacional.
- Segmentos identificam offsets exatos da resposta original, tipo factual ou
  estrutural e relação proposta. Validar IDs, intervalos, sobreposição e cobertura
  de todo caractere não branco. Não aprovar extração parcial como resposta completa.
- Títulos/formatação podem ser estruturais, com justificativa explícita. Validação
  textual não comprova que a anotação factual está correta: revisão humana pendente.
- Até 60 segmentos por resposta, 40 casos, 600 avaliações planejadas por execução;
  resposta/documentos/HTTP/budget/deadlines respeitam o serviço existente.
- Falha técnica não é erro semântico; preservar parcial, não aprovar agregado
  com segmento ausente/erro, retornar falha se houve transporte inválido.
- Manifesto congelado antes das chamadas, com textos, fontes, anotação, modelo,
  limiares e hash das rubricas. Alteração impede execução; não sobrescrever saídas.
- Desenvolvimento/reserva não compartilham pergunta normalizada, família, IDs
  ou conteúdo de fonte. Registro das referências já vistas acompanha a reserva.
- Relatórios por resposta apontam exatamente qual trecho foi bloqueado e suas
  probabilidades. Completude, utilidade e atualidade são avaliações separadas.
- `ready_for_enforcement=false`; todo agregado exige revisão de cobertura antes
  de eventual uso. Os quatro textos aprovados não são considerados fatos atuais
  automaticamente; revisão de qualidade não valida tarifação histórica.

## Aceite e rastreabilidade

`tests/test_jev_claims.py`: cobertura incompleta, intervalos inválidos, afirmação
ruim misturada com boa, falha externa, chave ausente, manifesto alterado, fontes
compartilhadas e resultados efetivamente salvos com transporte injetado.
Não chamar API real na suíte. Fonte read-only: `PilotSourceService` existente.
Sem migração. Guardrails G03, G06, G10, G12 e G13.

## Execução — 02/10/2026

RED: duas falhas de cobertura incompleta e uma de marcador numérico isolado
indevidamente aceito como fato. GREEN: 20 testes dirigidos, incluindo anotação,
limites, manifesto alterado, fonte vista, transporte falho e persistência da
comparação. Nenhum teste normal usa API externa.

Diagnóstico: quatro referências consideradas boas pelo usuário e suas oito
variantes negativas. Reserva: quatro novas referências ingeridas do banco,
excluídas as perguntas/curadorias vistas no piloto e controles anteriores;
referência, paráfrase, oposição e detalhe ausente por família. 28 textos,
125 trechos factuais anotados por IA, três repetições, 459 chamadas reais Jev.
Manifesto final congelado antes das chamadas:
`64636ceaeb5dcdea333b70e814aa61c2a69dc32f3b5132ea5bc369c556141588`.

| Conjunto | Método | Positivas propostas | Bloqueios propostos | Negativas propostas | Aprovações negativas |
| --- | --- | ---: | ---: | ---: | ---: |
| Desenvolvimento | Integral | 12 | 8 | 24 | 0 |
| Desenvolvimento | Todos os trechos | 12 | 12 | 24 | 0 |
| Nova reserva | Integral | 24 | 9 | 24 | 0 |
| Nova reserva | Todos os trechos | 24 | 21 | 24 | 0 |

327 observações de trechos positivos: 191 rejeições, 66 exclusivamente pelo
critério de curadoria. 48 observações de trechos negativos: zero aprovações.
Os três requisitos por fragmento, combinados por aprovação de todos, aumentaram
os bloqueios. Não adotar esse agregado operacionalmente. Frases dependentes de
antecedente e exemplos/listas com múltiplos fatos exigem revisão de segmentação.

Sem falha técnica/truncamento; 698.943 tokens de entrada observados, custo
estimado US$ 0,029355606. Repetições não são exemplos independentes. Rubricas e
limiares não foram ajustados na reserva. Nenhuma geração OpenAI, escrita no
banco, nova política na API ou alteração da configuração operacional.

Artefatos ignorados: `comparacao-afirmacoes-jev-20261002.json`/`.md`,
`afirmacoes-jev-20261002-final.jsonl`, manifesto, revisão dos trechos e
`analise-afirmacoes-jev-20261002.md`. Rascunhos anteriores à execução foram
preservados; o relatório usa somente o manifesto final. A hipótese de avaliar
curadoria global e relação factual local com contexto precisa de protocolo
separado, calibração e reserva novas, sem alegar resultado independente aqui.

Gates: Ruff check/format, mypy src/main e ampliado, Bandit e **378 testes**
aprovados. Auditoria padrão falhou por ensurepip ausente; modo complementar
sem resolução não encontrou vulnerabilidades conhecidas. Gate padrão pendente.
