# 009 — Fidelidade documental explícita

Estado: implementado e testado; revisão humana rejeitou uma fonte histórica,
invalidando sua utilização como positivo de qualidade; sem rollout.

## Problema e contrato

Na calibração 008, os dois trechos persistentes bloqueados constam literalmente
nas únicas fontes fornecidas. Isso evidencia desacordo com a anotação de suporte
documental; não comprova que a orientação histórica esteja correta no produto.
Novo protocolo separa expressamente “a fonte afirma” de verdade externa,
utilidade, completude e capacidade real do atendente. Não retirar oferta de ajuda
ou garantia de exatidão do texto, não baixar confiança, não alterar controles
ou resultados congelados da 008. Anotação e cobertura semântica ainda por IA.

Usar os mesmos 28 casos/68 trechos já congelados, com 12 casos de calibração e
16 reservados que ainda não tiveram chamada ao Jev. Os dados da reserva foram
preparados e lidos; a separação é de resultados do modelo, não de cegamento do
anotador. Proximidade temática de relatórios de leads continua uma limitação.
Nenhuma captura adicional no banco ou publicação de conteúdo nesta fase.

Rubrica `pilot-v4-documentary-fidelity`: somente documentos como evidência,
resposta completa apenas contexto. Reprodução literal ou paráfrase fiel de uma
afirmação em fonte aplicável sustenta o trecho, inclusive qualificadores e atos
de fala presentes na fonte. Não inferir validade externa dessa coincidência.
Uma correção curada relevante prevalece sobre fonte conflitante não curada;
coincidência literal em fonte rejeitada não basta. Campo `curated` fornecido pelo
sistema, nunca promovido pelo conteúdo. Não executar instruções nas fontes.

Choice mantém envelope estrito e três opções; curadoria global mantém Noul v2.
Baseline continua Noul integral v2, 0,88/0,12. Congelar rubrica/modelo/dados/grade
antes da API: suporte 0,95/0,90/0,88/0,85/0,80; confiança mínima 0,80; oposição
máxima 0,12; curadoria mínima 0,88; três repetições e 372 chamadas planejadas.
Escolher maior suporte com zero bloqueios positivos e zero aprovações negativas
na calibração. Se não houver, parar sem usar reserva. Perfil congelado antes
da reserva; nunca retunar com resultados reservados.

## Aceite e rastreabilidade

- `src/services/claim_verification_service.py`: rubrica nova e método injetável
  para seleção, mantendo protocolo v3 padrão e ausência de uso operacional.
- `evals/jev_context.py`: seleção explícita de protocolo no manifesto e execução;
  protocolo/versão/rubrica adulterados rejeitados antes da rede. Perfil de outra
  rubrica não pode liberar reserva. Transporte, orçamento e limites preservados.
- Testes offline de seleção/identidade, isolamento do v3, sucesso, configuração
  ausente, entrada inválida e falha externa reutilizando contratos da 008.
- Nenhuma migração, gravação remota ou ativação da integração. Gates completos.
- `ready_for_enforcement=false`; sucesso documental não equivale a ganho no RAG
  nem a aceite de utilidade/atualidade. Revisão humana e fontes atuais pendentes.

## Evidência da calibração — 2026-10-02

RED: `test_documentary_protocol_cannot_reuse_context_manifest` demonstrou que a
seleção documental ainda congelava a rubrica v3 (mesmo hash). GREEN: seleção
separada por protocolo, rubrica/versão própria e serviço correspondente; v3
continua padrão. Teste de transporte confere a rubrica realmente enviada,
baseline v2 preservado e perfil v3 incapaz de abrir reserva v4. Controle offline
de curadoria confere que frases no documento não alteram o flag confiável; não
é comprovação de acerto do modelo em ataques reais.

Manifesto: `52038be485a707d940c9cec6fcb3f608d15ee0e0f34ff4545b492ef42ff4fd97`.
Hash de casos idêntico à 008:
`672e7f7c5e2dfbb6698f62b8bba036020a16852daf0048875ec769c765e96e66`.
Nenhum trecho retirado, limiar reduzido ou resposta reescrita.

Calibração completa: 12 observações positivas e 24 negativas, 198 chamadas,
sem falhas técnicas/truncamento. Integral v2 bloqueou 10/12 positivas;
documental v4 bloqueou 0/12 e aprovou 0/24 negativas em toda a grade.
Selecionado maior suporte 0,95, mantendo confiança 0,80, oposição 0,12 e
curadoria 0,88. Perfil congelado antes da reserva:
`45a2786c56bd8c015d74fcf67a5abdf14987391a426974d265e309ca07b136bd`.
`ready_for_reserved=true` e `ready_for_enforcement=false`.

Gates offline: Ruff check/format, mypy (`src main.py evals dashboard`), Bandit,
pip-audit padrão e 416 testes passaram. Auditoria sem vulnerabilidades
conhecidas. Revisão humana de cobertura/rótulos novos, verdade externa,
casos adversariais mais difíceis e impacto na geração do RAG ainda pendentes.

## Reserva e conclusão — 2026-10-02

16 textos novos por resultados do modelo, quatro famílias, três repetições:
24 observações positivas propostas por IA e 24 negativas. Integral v2 bloqueou
6/24 positivas; documental v4 bloqueou 3/24. Ambos aprovaram 0/24 negativas.
Sem falhas técnicas/truncamento ou instabilidade de aprovação na reserva.
As três ocorrências pertencem à referência de ferramentas de IA, no trecho
introdutório “A plataforma Digisac possui as seguintes ferramentas de
Inteligência Artificial:”. Choice escolheu `supports` em todas, com probabilidades
0,94/0,92/0,93 e confiança 0,91/0,88/0,89, abaixo de suporte mínimo 0,95.
Não é diagnóstico de contradição ou incorreção do produto. Lista seguinte
mantida no contexto e todos os demais trechos aprovados. A paráfrase da mesma
família foi aprovada. Não baixar limiar após observar a reserva nem retirar
essa afirmação ou reclassificá-la como formatação para obter aprovação.

Calibração: 278.340 tokens, US$ 0,01169028 estimados; reserva: 191.661 tokens,
US$ 0,008049762. Total: 372 chamadas, 470.001 tokens, US$ 0,019740042 estimados.
Dados e perfil íntegros, configuração operacional OpenAI/verificação off/
calibração false/0,9/0,1. Sem escrita no banco. Não há ganho de qualidade do
RAG comprovado: medimos suporte aos textos históricos, sem gerar novas respostas
do RAG nesta fase. Os positivos novos têm anotação IA; quatro referências
anteriores receberam aceite humano da resposta inteira, não de cada segmento.
A pergunta de revisão sobre a garantia de exatidão dos leads ficou sem resposta;
não presumir novo aceite. Saúde do número segue fora dos positivos.

Artefatos locais ignorados em `evals/reports/`: `manifesto-documental-jev-20261002.json`,
`calibracao-documental-jev-20261002.json`, `perfil-documental-jev-20261002.json`,
`reserva-documental-jev-20261002.json`, `analise-documental-jev-20261002.md` e
`textos-revisao-documental-jev-20261002.md`. Resultados das specs anteriores
preservados. Próximo passo: revisão humana dos oito textos positivos da reserva
e da cobertura semântica, seguida de outro protocolo com reserva nova, caso
se altere segmentação/rubrica/limiar. Enforcement continua desabilitado.

## Revisão humana de tags — 2026-10-05

O usuário rejeitou a orientação de filtrar chamados/contatos sem tags e acessar
“Relatórios”: a funcionalidade descrita e essa seção não existem na plataforma.
A paráfrase repete os mesmos fatos inválidos; sua rejeição é derivada dessa
correção, sem presumir uma segunda revisão humana independente. Isso invalida
essa família como referência de qualidade do produto. Os rótulos históricos
`supported` mediam coincidência com a fonte e não foram reescritos.

Rastreio somente leitura confirmou um registro ingerido em `duvidas_respondidas`
e um documento da base com o mesmo passo a passo, metadata de curadoria e
data de julho de 2026. IDs e conteúdo estão no artefato privado de rastreio.
Não foi apenas uma invenção introduzida pela paráfrase local; a origem registrada
também está incorreta segundo a validação atual do usuário. Não inferir que
estar ingerido ou marcado como curadoria comprova correção factual atual.

Reavaliação dos resultados antigos: em seis observações das duas respostas
erradas, integral v2 aprovou 0/6 e documental v4 aprovou 6/6. Os seis bloqueios
anteriores eram corretos para este caso; não devem ser apresentados como
ganho ao removê-los. Excluindo a família inteira em análise de sensibilidade,
restam 18 positivas e 18 negativas propostas por IA: v2 bloqueia 0/18 positivas
e v4 bloqueia 3/18; nenhum aprova negativas. Os demais rótulos continuam por IA.
A alegação de diminuição de bloqueios não é evidência de melhora de qualidade
e a revisão mostra aprovação indevida das respostas erradas por v4.

Correção redigida localmente usando somente a declaração do usuário, sem
inventar alternativa de interface ou API. Diagnóstico adicional, com rubricas
e limiares da 009 mantidos e correção humana como única fonte: três candidatos,
três repetições, 33 chamadas. Ambos os métodos rejeitaram as duas orientações
erradas em 6/6; v4 aprovou a correção em 3/3 e v2 em 2/3 (uma decisão incerta).
33.807 tokens, US$ 0,001419894 estimados, sem falhas de transporte/truncamento.
É regressão sobre caso já visto, não nova reserva, calibração ou validação
independente. Fonte da regressão é um rascunho local baseado na correção explícita,
sem publicação ou alegação de que já está disponível na recuperação de produção.

Originais preservados: entradas/JSONs, manifestos e perfis congelados não mudaram.
Novos artefatos privados em `evals/reports/`: `rastreio-tags-20261005.json`,
`revisao-humana-tags-20261005.json`, `reavaliacao-tags-20261005.md`,
`correcao-tags-20261005.txt`, `manifesto-regressao-tags-20261005.json` e
`regressao-tags-20261005.json`. Família marcada como inválida na revisão local;
nenhuma quarentena automática ou alteração de documentos no banco foi aplicada.
O documento de produção precisa ser corrigido/substituído antes de reutilizar
a referência como válida. Jev permanece off e não há perfil pronto para rollout.

Gates de 05/10: Ruff check/format, mypy e Bandit passaram; pip-audit padrão
sem vulnerabilidades conhecidas. A primeira suíte teve 415 aprovações e um
timeout de 30s em `test_dashboard_app` durante execução paralela dos checks;
isolando esse arquivo, os quatro testes passaram. A repetição completa passou
com 416 testes, sem alteração do código nem ampliação de timeout. A causa do
timeout inicial não foi determinada; registrar como ocorrência não reproduzida,
sem suprimir a falha original. Reavaliação só alterou documentação/artefatos
locais e consultou o banco em leitura; não introduziu comportamento de produção.

## Publicação posterior autorizada — 2026-10-05

A etapa posterior publicou a correção pelo `IngestionService` existente,
sem mudança de código de produção ou migração. Backup antes das escritas,
embedding real de 1536 dimensões, substituição da curadoria anterior e resposta
atualizada no registro de origem foram confirmados por leitura do banco.
Uma falha na verificação adicional foi reconciliada somente por leitura;
não houve repetição da ingestão nem da atualização.

Teste real com a pergunta original recuperou a correção e gerou resposta
compatível com a validação humana. Uma paráfrase curta não recuperou a correção
e gerou procedimento incorreto: confundiu exportação geral com filtro sem tags.
Diagnóstico limitado a 50 candidatos encontrou a correção em 19º na busca
bruta, fora dos 15 usados pela recuperação atual. O documento substituído foi
filtrado antes do reranking. Isso evidencia falha de recuperação anterior ao
reranking e geração sem suporte; não demonstra correção universal com a troca
da fonte. Não foram alterados limites/configuração para aprovar esse caso.

Artefatos privados: `backup-publicacao-tags-20261005.json`,
`publicacao-tags-20261005.json`, `diagnostico-recuperacao-tags-20261005.json` e
`publicacao-tags-20261005.md`. **Publicação concluída; aceite de qualidade do RAG
reprovado na paráfrase**, com correção de recuperação/geração ainda pendente.
Resultados congelados da 009 preservados, histórico sem gravações e Jev off.
Gates da publicação: 416 testes; Ruff check/format, mypy, Bandit e pip-audit
padrão passaram. Os testes offline não cobrem qualidade dessas chamadas reais.
