# 008 — Afirmação com contexto e curadoria global

Estado: implementado e testado; calibração real falhou no critério definido,
sem avaliação da reserva e sem rollout.

## Contrato

Na spec 007, avaliar curadoria em cada fragmento aumentou bloqueios. Testar
relação factual local com a resposta completa disponível somente como contexto,
e verificar respeito à curadoria uma vez na resposta inteira. Fonte, query e
resposta são dados não confiáveis; só documentos fornecem evidência. Resposta
completa resolve referências como “nessa tela”, mas não prova a própria afirmação.

Usar Choice com `supports`, `contradicts`, `says_nothing` e Noul global para
curadoria. Contrato oficial: [API](https://docs.typesafe.ai/api),
[Choice](https://docs.typesafe.ai/primitives/choice) e
[cookbook](https://docs.typesafe.ai/cookbooks/citation_check). Validar modelo,
IDs/tipos, opções, probabilidades finitas que somem um, escolha máxima e confiança.
Não confundir confiança Choice com probabilidade da opção.

Novo serviço experimental reutiliza transporte, clientes, limites, orçamento,
retries e deadlines existentes. O parser Noul de produção continua estrito:
Choice inesperado não pode aprovar `verify` ou `rerank`. Nenhuma rota/pipeline
chama o novo protocolo; versão experimental separada da configuração operacional.

Trechos mantêm cobertura de offsets da spec 007 e estão anotados por IA. Usar
as quatro respostas aceitas pelo usuário e oito negativas já vistas para
calibração; reservar quatro famílias inéditas, excluindo todo piloto/correções
visíveis e controles das specs 005–007. Anotações/cobertura humanas pendentes.

Antes de avaliar a reserva: confiança Choice mínima fixa 0,80; teto de oposição
Choice 0,12 e curadoria global mínima 0,88. Grade de probabilidade de `supports`
0,95, 0,90, 0,88, 0,85, 0,80. Selecionar maior limiar com zero falsos bloqueios
e zero aprovações negativas nas repetições da calibração. Se nenhum atingir o
objetivo, parar sem perfil operacional; registrar a falha experimental.
Rubricas/dados/grade congelados antes da calibração; perfil resultante congelado
antes da reserva. Não retunar usando reserva.

Comparar com Noul integral v2 0,88/0,12 nas mesmas respostas/fontes. O agregado
novo exige curadoria global aprovada e todas as afirmações `supports` dentro dos
limites. Uma única afirmação incerta/negativa, faltante ou falha técnica impede
aprovação; falha técnica não conta como erro semântico. Custos e parcial explícitos.
Máximo 40 casos, 60 segmentos/caso, três repetições, 600 avaliações planejadas.
Saídas em `evals/reports/`; não sobrescrever entradas/relatórios/perfis existentes.

## Aceite e rastreabilidade

- `src/models/typesafe.py`: envelope Choice estrito, sem enfraquecer Noul.
- `src/services/typesafe_service.py`: parser parametrizado com mesmos limites.
- `src/services/claim_verification_service.py`: contexto e curadoria global.
- `evals/jev_context.py`: congelamento, calibração separada, comparação e relatório.
- Testes offline de sucesso, chave ausente, input/Choice inválido, timeout/budget,
  upstream, falha por afirmação, perfis alterados e reserva vazada.
- Sem migração ou gravação remota. G03/G06/G10/G12/G13 preservados.
- `ready_for_enforcement=false`, nenhum aceite humano presumido ou ganho no RAG
  alegado a partir de transporte/offline. Atualidade de fontes/completude não medidas.

## Evidência e pendências — 2026-10-02

RED: o primeiro teste Choice falhou porque o decoder Noul rejeitava o envelope
Choice. O teste de curadoria global reproduziu aprovação indevida com fatos
sustentados e curadoria 0,20. GREEN: decoder separado e agregado exige curadoria
global >=0,88, além de cada fato. A suíte usa transporte injetado, sem rede.
`tests/services/test_claim_verification_service.py` cobre contexto literal,
configuração ausente, validação, falhas/budget e regressão Noul;
`tests/test_jev_context.py` cobre fases, perfil alterado, vazamento, persistência
de falhas e calibração inelegível. Proteções já existentes tiveram cobertura de
regressão; suas execuções não foram contadas como RED.

Manifesto `b6c3fe9276bdd6c1860267ed9307c57e5d8ab8c5089cfb657a968ef2b233c8f7`:
28 casos, 68 trechos factuais, três repetições, 372 avaliações planejadas
(198 calibração + 174 reserva). Uma candidata foi excluída manualmente por
repetir a intenção de templates consecutivos da spec 007. Reserva com quatro
famílias novas por pergunta/fonte/conteúdo; independência temática limitada
na família de relatórios de leads. Exemplos/listas agrupados não são fatos
puramente atômicos. Saúde do número foi excluída dos positivos desta fase.

Calibração: quatro referências aceitas pelo usuário, repetidas três vezes
(12 observações positivas), e oito controles negativos (24 observações).
Baseline integral v2 bloqueou 10/12 positivas e aprovou 0/24 negativas.
Contexto/curadoria global bloqueou 9/12 em 0,95 e 6/12 em cada limiar de
0,90 a 0,80; aprovou 0/24 negativas em toda a grade. Nenhum candidato
atingiu zero bloqueios/zero aprovações negativas. Perfil congelado
`e90ed3c99f2a896821afef8771f09d714fc2f7ebccd6ef584734a3cf5dd73449`
tem `selected_support_floor=null` e `ready_for_reserved=false`.
Reserva congelada, sem chamadas; não ajustar critério para liberar reserva.

198 chamadas HTTP, sem erro técnico/truncamento, 261.330 tokens de entrada,
US$ 0,01097586 estimados. Os dois trechos persistentes foram oferta de ajuda
e precisão de “levantamento exato” de contatos novos. Classificação de ato
conversacional versus fato é hipótese para revisão; não alterar anotações
congeladas ou chamar a oferta de ajuda de informação incorreta sem revisão.
Não é validação independente nem ganho comprovado de qualidade do RAG.

Artefatos locais ignorados: `evals/reports/contexto-jev-20261002.jsonl`,
`manifesto-contexto-jev-20261002.json`, `calibracao-contexto-jev-20261002.json`,
`perfil-contexto-jev-20261002.json`, `revisao-contexto-jev-20261002.md` e
`analise-contexto-jev-20261002.md`. Nenhuma gravação remota ou mudança de
configuração operacional. Revisão humana de trechos/rótulos, atualidade das
fontes e rollout continuam pendentes.

Gates: Ruff check/format, mypy (`src main.py evals dashboard`) e Bandit passaram.
Pytest completo: 412 testes passaram. `pip-audit` padrão falhou porque falta
`ensurepip`; a auditoria complementar dos pins com `--disable-pip --no-deps`
não encontrou vulnerabilidades conhecidas. O gate padrão continua pendente.

Atualização posterior do ambiente, autorizada pelo usuário em 02/10: Python
3.12.15 com `ensurepip` instalado no usuário e configurado no `.venv`, sem
alterar as versões dos pacotes do projeto. A auditoria padrão foi repetida e
passou sem vulnerabilidades conhecidas; os 412 testes e demais gates passaram
novamente. A pendência de auditoria foi resolvida. Isso não altera os resultados
da calibração, o perfil congelado ou as pendências de revisão humana/rollout.
