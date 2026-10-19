# 011 — Análise de servidor baseada em evidências

Estado: implementado localmente; validação real de qualidade reprovada.

## Problema e evidência

Usuário reportou análise de servidor ruim. Rastreio somente leitura confirmou
documentação ingerida “Servidores e consumo”, Grafana, lentidão e AWX, além de
perguntas reais de analistas. A reprodução atual classificou recursos esperados
como configuração real, quantidade de usuários como usuários ativos e avaliou
o ambiente como adequado sem medições de consumo. Outra resposta sugeriu plano
4/8 sem dimensionamento documentado. Feedback histórico positivo não comprova
correção; um caso negativo antigo confundia servidor com visualização por conexão.

Há limites nas fontes: alguns gráficos só aparecem como referências a imagens;
não foi confirmado original cru desse treinamento. Um trecho define load como
utilização CPU/RAM; essa definição precisa de revisão, não promoção automática
a curadoria. Sem publicar correção nem substituir documentos nesta etapa.

## Contrato

- Reconhecer intenção de dimensionamento, consumo ou diagnóstico de servidor
  pela pergunta. Erro genérico “Internal server error”, SMTP e perguntas de
  exportação não recebem a política de análise de infraestrutura.
- Reranking OpenAI desses casos usa pergunta original e texto até 6000
  caracteres por candidato; preserva 30 candidatos e limite final existentes.
  Rewrite conserva tema técnico. Não fixar IDs nem forçar fonte irrelevante.
- Geração distingue configuração esperada/contratada de medição de uso real,
  snapshot de série temporal, usuários cadastrados de simultâneos. Não inventar
  CPU/RAM consumidos, ocupação moderada, saturação ou capacidade garantida com
  base apenas em volume de mensagens/conexões/usuários.
- Sem critério de dimensionamento confiável, não escolher um plano numérico ou
  garantir número máximo de conexões. Informar o que os dados permitem concluir
  e quais medições específicas faltam; usar verificações documentadas de
  Grafana/AWX, containers/filas, período de pico e sintomas. Não pedir novamente
  dados já fornecidos nem recusar toda análise por falta de uma tabela de sizing.
- Conhecimento técnico geral verificado não vira regra comercial da Digisac.
  Load bruto é contagem média, não percentual CPU/RAM; painel pode normalizá-lo,
  então confirmar unidade/consulta. Baseline é capacidade configurada, não uso
  atual. CPU steal isolado não comprova a causa nem esgotamento de burst.
- `resposta-cliente` mantém proibição de termos/processos internos; análise não
  executa reboot ou alteração de infraestrutura. Jev continua off.
- Documentos ficam em JSON na mensagem de dados; regras, política e índices de
  curadoria fornecidos pelo sistema ficam na mensagem `system`. Marcadores no
  conteúdo não promovem fonte. Alteração compartilhada exige regressão de tags
  e procedimentos gerais, sem mudar o limite final nem os dados congelados.
- A análise de servidor usa política específica e curta, sem a persona genérica
  que presume conhecer capacidades não documentadas. Rótulos de perfis não
  autorizam inferir vCPUs/OCPUs/GB nem copiar a linha de um perfil parecido.
- A presença literal de rótulos numéricos X/Y é conferida em código contra o
  texto das fontes, sem contar a pergunta como evidência. Ausência não permite
  afirmar que o perfil está documentado. Presença comprova somente grafia,
  nunca unidades, capacidade, pertencimento à tabela ou autoridade. Não aceitar
  prefixos, substrings de outros perfis ou fragmentos de datas como confirmação.
- A geração geral também abandona a presunção de conhecimento total do produto,
  recurso nativo e ação da equipe em andamento. Conserva o contrato da spec 010
  de evidência suficiente para todas as condições do procedimento solicitado.
- Contratos HTTP, autenticação, limites, erros genéricos e ciclo de vida dos
  clientes preservados. Sem mudança de schema, migração ou gravação remota.

Referências técnicas primárias verificadas em 05/10/2026:
[Linux /proc](https://www.kernel.org/doc/html/latest/filesystems/proc.html),
[load average](https://www.kernel.org/pub/linux/docs/man-pages/book/man-pages-6.17.pdf),
[Oracle Burstable](https://docs.oracle.com/en-us/iaas/Content/Compute/References/burstable-instances.htm).
Não transportar a afirmação errada do treinamento para o sistema; revisão do
documento original permanece separada desta correção de comportamento.

## Aceite e rastreabilidade

| Critério | Evidência planejada |
| --- | --- |
| Texto completo relevante e pergunta original chegam ao reranker no caso Grafana | Regressão do `RAGAgent`, fake injetado offline |
| Rewrite e geração recebem política de evidência, não a regra genérica de recusa de procedimentos | Captura dos requests em `tests/services/test_openai_service.py` |
| Intenção de servidor detectada sem atingir erro de template, SMTP ou tags | Testes parametrizados do helper puro |
| Configuração ausente, erro externo e entrada inválida preservam falhas seguras | Suíte existente de serviços/API, regressões dirigidas |
| Não recomendar tamanho nem carga adequada sem métricas; orientar investigação útil | Regressão real com seis perguntas históricas e dois controles congelados, três repetições finais |
| Saída para cliente não contém AWX/Pipefy/N2 | Regressão real adicional desse modo; contrato de transporte |
| Tags continuam negando o recurso e erros de template conservam assunto | Controles reais e testes de seleção |

## Validação e limitações

Baseline e expectativas congelados antes da mudança. Captura/read-only em
`evals/reports/rastreio-servidor-20261005.json`, protocolo em
`manifesto-servidor-20261005.json`. Não usar respostas históricas como prova
de correção. Revisão final pelo assistente contra fontes e critérios; novo
aceite humano das respostas ainda necessário. Casos conhecidos, sem reserva
independente ou alegação de ganho geral do RAG/Jev.

Baseline sofreu erro de DNS temporário na consulta de expansão; resultados
parciais e falha preservados. Retomada somente de leitura, sem repetir escritas.
Registrar completude e falhas restantes antes de anunciar aprovação.

## RED/GREEN e tentativas preservadas

Três regressões offline falharam pelo requisito: reranker não recebeu pergunta
original/texto completo, política de evidências ausente e rewrite sem intenção
de análise. Depois, a regressão de fronteira demonstrou que texto do documento
ainda era enviado como instrução `system`. GREEN: documentos serializados em
mensagem de dados, índices de curadoria gerados exclusivamente de metadata e
política técnica separada. Teste com marcador falso confere que ele não altera
a classificação confiável. É prova de contrato, não imunidade a prompt injection.

Primeira tentativa real com política anexada à persona genérica ainda supôs
adequação. Foi interrompida com 11 respostas preservadas, não considerada
aprovada. Separar dados e instruções, sozinho, também não resolveu: segunda
tentativa preservada com falhas de conteúdo e transporte. Sondagem de uma
geração com política específica removeu a conclusão sem evidência; não foi
contada como avaliação de qualidade.

Terceira rodada específica ainda atribuiu características de um perfil parecido
ao perfil 8/12 e inferiu unidades do rótulo 2/4. A iteração seguinte exige
correspondência literal do perfil e explicitação de unidades. Todas são rodadas
de desenvolvimento em casos conhecidos; não reservar resultados ruins nem
retunar os estudos Jev anteriores. Não anunciar que todos os critérios passaram
antes da revisão completa e da contabilização das falhas externas.

A regressão compartilhada demonstrou três respostas incorretas com fonte
parcial de tags. A simplificação da política geral preservou exportação/importação
documentadas e voltou a reconhecer a lacuna sem inventar o filtro. O teste de
transporte da presunção de conhecimento também apresentou RED; é evidência
de contrato, sem substituir o resultado das gerações reais.

Somente instruções adicionais não resolveram a referência falsa ao perfil
ausente. RED verificou ausência da conferência no request; GREEN acrescentou
a comparação literal em `server_analysis.numeric_labels_in_sources`, com casos
de presença, ausência, fonte vazia, prefixos, rótulos maiores e datas. Não houve
alteração de tabelas nem promoção de conteúdo a curadoria. A proposta documental
está em [REVISAO_DOCUMENTACAO_SERVIDOR.md](../docs/REVISAO_DOCUMENTACAO_SERVIDOR.md).

## Resultado final desta revisão — 05/10/2026

Rodada v7 completa: 36 respostas (12 casos × 3), sem falhas externas; snapshot
dos 20 documentos 919–938 permaneceu igual. A comparação literal resolveu a
referência falsa ao perfil 8/12 em 3/3. Entretanto, persistem inferências de
adequação/insuficiência, unidades do perfil 2/4, recursos esperados como atuais
em texto externo e interpretações excessivas do snapshot. As definições erradas
das fontes ainda são reproduzidas ou conciliadas. **Aceite de servidor reprovado.**

Controle de tags com correção aplicável: 3/3 funcionalmente corretos; controles
gerais e de fonte parcial na versão final: 9/9 aprovados contra as fontes.
Erro de template conserva o tema em 3/3, sem aprovação do procedimento HSM.
452 testes passaram; Ruff, formatação, mypy (incluindo evals/dashboard), Bandit
e pip-audit padrão passaram. Auditoria inicial e consultas anteriores tiveram
falhas de DNS/transporte, preservadas; as execuções finais foram completas.

Manifesto, código exato e respostas finais em `evals/reports/`, versões v7 de
servidor e v3 dos controles. Relatório simples: `analise-servidor-20261005.md`.
Sem deploy ou gravação remota. Não anunciar correção integral, calibrar Jev com
aprovações falsas nem publicar estas respostas como curadoria. Próximo trabalho:
revisar as fontes técnicas e confirmar informações do produto, depois repetir
a avaliação. O rascunho documental não é aceite humano ou publicação.
