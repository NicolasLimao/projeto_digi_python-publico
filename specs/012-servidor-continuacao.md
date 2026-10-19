# 012 — Continuação da análise de servidor

Estado: continuidade e classificação corrigidas localmente; qualidade integral reprovada.

## Evidência e escopo

Em 06/10/2026, o usuário forneceu uma conversa anterior aos ajustes. A primeira
pergunta (11 conexões WhatsApp convencional, 350 mil mensagens/mês e 240 usuários)
já pertence à família conhecida da spec 011. A sequência acrescenta
“qual recomendado” e “o cliente ja utiliza um 16/16”. As respostas antigas
repetem mínimos 4 CPU/8 GB, presumem simultaneidade e traduzem o perfil 16/16
para recursos, concluindo suficiência sem consumo medido. Pedem também canais
já informados e pressupõem lentidão não relatada.

Inspeção confirmou uma falha de implementação: as políticas de infraestrutura
na reescrita, seleção e geração eram ativadas apenas pela pergunta atual.
Continuações sem a palavra servidor perdiam a política mesmo com histórico.
As respostas antigas são evidência do defeito, não referência correta ou fonte
de capacidades. Não usar esse exemplo como reserva independente.

## Contrato

- Pergunta explícita de servidor continua sendo reconhecida como na spec 011.
- Continuação curta e dependente do contexto (recomendação, referência ou
  atualização de perfil) herda o assunto de uma pergunta anterior de servidor.
  Examinar no máximo as quatro interações recentes do formato do HistoryService.
  Identificação do tema examina até 64 mil caracteres; continuação tem até 240
  caracteres. Esses limites não ampliam o contrato HTTP ou o histórico enviado.
- Somente perguntas anteriores do usuário identificam o assunto. Texto de
  respostas do Digi não ativa infraestrutura nem comprova dimensões/capacidade.
- Nova pergunta explícita de outro assunto interrompe a herança. Não aplicar
  política de servidor a tags, SMTP, templates ou configurações de webhook.
  Sem histórico reconhecível, não adivinhar o assunto de “qual recomendado”.
- Reescrita, seleção de texto completo e geração usam a mesma decisão de escopo.
  Não permitir que um resumo reescrito seja promovido a curadoria.
- Classificador recebe o histórico factual. Uma atualização isolada de perfil,
  reconhecida como continuação de servidor, é orientação, não relato de bug.
  Essa decisão local dispensa inferência externa e vale também sem configuração
  do fornecedor. Mensagem que acrescenta sintomas não recebe essa regra; modo
  explicitamente solicitado na API continua prevalecendo. Calls independentes
  de classificação/validação/recuperação permanecem concorrentes.
- Preservar 16/16 como perfil informado pelo usuário; não completar unidades
  nem afirmar adequação. Não reaproveitar o mínimo 4/8 das respostas antigas.
  Conservar quantidades e canais informados; distinguir cadastro/simultaneidade;
  não inventar sintomas nem repetir perguntas já respondidas.
- Histórico continua na mensagem de dados, não nas instruções. Autoridade
  continua exclusivamente no metadata autorizado; Jev permanece desligado.
- Nenhuma migração, alteração de autenticação, gravação remota ou deploy.

## Aceite e rastreabilidade

| Critério | Evidência |
| --- | --- |
| Continuação mantém escopo e troca explícita de assunto o encerra | Helper puro e casos de fonte vazia, histórico sem formato e resposta antiga isolada |
| Política e conferência literal do 16/16 chegam à geração | Cliente injetado; histórico fora de system |
| Reescrita e reranking preservam tema e conteúdo completo | Serviços e agente com transporte injetado |
| Entrada inválida, falta de configuração e falha externa conservam comportamento seguro | Contratos existentes e testes dirigidos de continuação |
| Nenhum mínimo inventado, tradução do perfil, suficiência sem consumo ou sintomas presumidos | Reprodução real da sequência fornecida, contexto anterior congelado, três repetições finais |

## Validação

Registrar RED antes da mudança e GREEN offline separadamente da revisão das
respostas reais. Baseline usa o código local anterior a esta correção, não é a
versão de produção que gerou o texto antigo. Não reclassificar resultados ruins
como aprovados. Falhas de transporte e achados da spec 011 permanecem explícitos.

## RED/GREEN e resultado — 06/10/2026

Três testes reproduziram ausência de política na geração/reescrita e conteúdo
completo no reranking. GREEN usa a mesma decisão contextual nos três pontos.
Casos do helper verificam continuações, troca de assunto, limites, ausência de
histórico, formato não reconhecido e proibição de usar a resposta do bot como
âncora. Histórico permanece em dados, fora de `system`.

Depois, duas regressões de pipeline reproduziram modo `bug` com classificador
injetado e `resposta-cliente` com configuração ausente, para a mesma atualização
isolada. GREEN: `is_server_profile_update` decide orientação em contexto de
servidor; `ClassifierAgent` e `RAGPipeline` encaminham o histórico. Resultado
entregue e modo persistido conferidos. Sintomas/novo assunto/ausência de contexto
não recebem essa regra; modo explícito mantém prioridade. Sem cliente novo.

Baseline local: três respostas, “qual recomendado” reproduziu mínimo 4 CPU/8 GB.
Continuidade corrigida: nove respostas, três por turno com histórico antigo
congelado. Em 3/3 do último turno não houve tradução de 16/16 ou suficiência
garantida. Cadeias adicionais com respostas novas têm três turnos cada; com
classificador real anterior, o último modo foi bug; com regra corrigida, os
três modos foram orientação e o último turno preservou perfil e quantidades.
Protocolos são distintos e conhecidos, não uma reserva independente.

Qualidade integral ainda reprovada: hipóteses de insuficiência/maior capacidade
sem consumo, legitimação do mínimo antigo como sugestão geral e teste de carga
sem suporte específico verificado. Não marcar o dataset inteiro como aprovado.
Rodadas completas sem erros externos; 20 documentos monitorados inalterados.
Relatório privado: `evals/reports/exemplo-servidor-20261006.md`.

476 testes e gates passaram. A primeira auditoria padrão encontrou
CVE-2026-104874 em multidict 6.7.1; atualização do pin e do ambiente para 6.9.1
seguiu o [aviso oficial](https://github.com/aio-libs/multidict/security/advisories/GHSA-54p9-h82j-f925).
`pip check` e a auditoria padrão posterior passaram, sem supressão do achado.
Falha original preservada; sem alegação de exploração demonstrada no aplicativo.
