# Jev: configuração e validação

Estado: cliente e integração implementados; primeira rodada real em português
executada em 02/10/2026, com revisão humana e calibração pendentes. A integração
vem desligada. A chave local foi validada com chamadas reais; nenhuma chave é
versionada. Resultados e limites do piloto: [spec 004](../specs/004-piloto-jev-historico.md).

O Jev avalia relevância documental e suporte da resposta. OpenAI continua responsável pela geração. O contrato HTTP segue a [API oficial](https://docs.typesafe.ai/api), com `Noul` e versão fixa `jev-1.13.0`. Preço usado nas métricas: US$ 0,042 por milhão de tokens de entrada; saída gratuita. [Modelos e preços](https://docs.typesafe.ai/models).

## Começar em observação

Configure a chave somente na `.env` local e confirme as condições de tratamento dos dados da conta antes de enviar conteúdo interno. Nunca envie a chave em mensagens ou versionamento.

```dotenv
TYPESAFE_API_KEY=<configurar-localmente>
RERANK_PROVIDER=openai
TYPESAFE_RERANK_SHADOW=true
TYPESAFE_VERIFY_MODE=shadow
```

Reinicie a API para aplicar as variáveis. O reranker OpenAI continua escolhendo os documentos; a ordenação alternativa e a verificação são medidas sem alterar a resposta. A chave ausente com qualquer modo ativo impede inicialização. O dashboard permanece local e sem login.

## Selecionar reranker e política

- `RERANK_PROVIDER=typesafe`: usa Jev; falha da etapa retorna ao reranker OpenAI. A probabilidade Jev não sobrescreve `Document.score`.
- `RERANK_FULL_CONTEXT=true`: variante de controle OpenAI com pergunta original, reescrita auxiliar e até 6.000 caracteres por documento. O padrão preserva a entrada anterior de 300 caracteres.
- `TYPESAFE_VERIFY_MODE=off`: nenhuma verificação.
- `shadow`: mede suporte, contradição e respeito à curadoria após toda formatação; entrega a resposta atual.
- `enforce`: resposta só é entregue após aprovação. Erro, timeout, entrada excessiva e ausência de documentos encaminham para revisão; o histórico recebe apenas a mensagem entregue.

Para `enforce`, é obrigatório declarar `TYPESAFE_CRITERIA_CALIBRATED=true`, definir `TYPESAFE_CRITERIA_VERSION` e configurar os limiares após avaliação humana com casos reservados. O booleano é uma declaração operacional, não uma calibração automática. Os padrões 0,9/0,1 são provisórios para observação; não há evidência de redução de alucinação em português nesta entrega.

A versão atual das rubricas é `pilot-v2-specific-rubrics`. Qualquer modo ativo
exige essa versão para evitar métricas rotuladas incorretamente; uma calibração
de `pilot-v1` não habilita a revisão atual. O teto de oposição usado na entrega
continua conservador, mas não transforma qualquer probabilidade acima de 0,1
em oposição confirmada: o motivo pode ser `unsupported` ou `uncertain`.

## Limites e telemetria

Os valores completos estão em [`.env.example`](../.env.example). Timeout por tentativa: três segundos; deadline por etapa: dez segundos, incluindo fila e retries. Concorrência compartilhada por processo: quatro. Até 15 candidatos e um retry para 429/502/503/504/529 ou transporte transitório. Redirects são recusados. Resposta externa é limitada a 32 KiB e tem schema, modelo, IDs e probabilidades validados.

O payload completo, incluindo perguntas e critérios, é limitado a 24.000 bytes UTF-8, uma proteção conservadora de tamanho. Não se conhece o tokenizer proprietário do fornecedor; consumo real vem de `usage`. Reranking pode limitar candidatos/conteúdo, registrando truncamento. Verificação usa todo o conteúdo selecionado e recusa excesso; não verifica silenciosamente uma versão truncada.

`TYPESAFE_BUDGET_USD` é uma proteção em memória por processo, em janela móvel de 30 dias. Reservas conservadoras são feitas antes de cada tentativa; sucesso ajusta pelo uso informado, falha mantém a reserva. Reiniciar perde o contador. Vários workers multiplicam o orçamento disponível. Um teto financeiro global exige limite na conta ou armazenamento/limitador compartilhado.

Logs JSON `TypeSafe stage completed` incluem etapa, modelo, versão de critérios, chamadas, tokens, custo estimado de chamadas com usage conhecido, duração, truncamento, probabilidades e status de transporte. `TypeSafe delivery decision` registra a política aplicada. Custos de tentativas sem usage permanecem desconhecidos; não interpretar zero tokens observados como consumo grátis. Probabilidades e score de busca têm significado distinto. Não há persistência de métricas no Supabase nesta etapa.

## Experimento A/B/C/D

Use o runner [compare_jev.py](../evals/compare_jev.py) com candidatos congelados em JSONL local. Cada linha contém `id`, `query`, `rewritten` opcional, `mode`, `documents` (objetos `Document` reais) e `expected_ids` anotados. IDs esperados servem à recuperação; não substituem revisão das afirmações geradas. O runner não cria embeddings nem consulta/altera o banco.

```bash
python -m evals.compare_jev --input evals/reports/candidatos-congelados.jsonl --dry-run
python -m evals.compare_jev --input evals/reports/candidatos-congelados.jsonl --output evals/reports/comparacao-jev.json
```

A: OpenAI atual; B: OpenAI com entrada ampliada; C: Jev com pergunta original e contexto ampliado; D: mesma resposta de C com verificação. O relatório distingue resposta candidata, decisão e resposta que seria entregue por enforcement; D é uma simulação, não ativa produção. Métricas agregam presença de fontes esperadas, tempo e consumo Jev observado. Revisão humana de fidelidade, completude, respostas úteis e bloqueios indevidos é obrigatória, com calibração separada de avaliação. Os artefatos contêm conteúdo interno e permanecem ignorados pelo Git.

Rollback: `RERANK_PROVIDER=openai`, `TYPESAFE_RERANK_SHADOW=false`, `TYPESAFE_VERIFY_MODE=off`, reiniciando a API. O caminho padrão não constrói cliente Jev nem faz chamadas.

## Curadoria explícita

`POST /api/ingest` autenticado aceita `curated=true` somente para conteúdo textual no formato `Pergunta: ... / Resposta oficial validada pelo analista: ...`, sem anexos. O dashboard envia esse campo após revisão humana. Consumidores que publicavam correções pelo marcador devem passar a enviar o campo explícito. Texto e anexos comuns não obtêm autoridade pelo conteúdo.

Registros históricos não foram reclassificados. Revisar a origem de curadorias existentes antes do piloto; autoridade antiga sem procedência confiável não é corrigida automaticamente pelo Jev. Resultado de ingestão parcial/indeterminado mantém a dúvida pendente; conferir gravações antes de tentar novamente.

## Piloto com perguntas do banco

O runner manual [pilot_jev.py](../evals/pilot_jev.py) lê até 100 linhas recentes por
feedback e até 100 revisões de analistas, sempre com service-role. Não usa a rota
de produção e não grava no banco. A amostra padrão tem até 12 perguntas únicas,
com distribuição entre feedback e modos; referências ingeridas e não descartadas
têm prioridade. Sem replay do histórico conversacional, a comparação cobre o
núcleo RAG para perguntas isoladas, não o pipeline inteiro.

```bash
python -m evals.pilot_jev --limit 12 --output evals/reports/piloto-jev.json
python -m evals.pilot_jev --limit 12 --capture-only --output evals/reports/captura-jev.json
```

O segundo comando só captura candidatos (ainda usa OpenAI para busca/reescrita),
sem geração ou chamadas Jev. JSON, Markdown e candidatos congelados ficam em
`evals/reports/`, ignorados pelo Git. Falhas permanecem explícitas no relatório.
Limites e aceite: [spec 004](../specs/004-piloto-jev-historico.md).

As fontes antigas podem conter nomes genéricos como `discord-upload`; isso não
identifica o documento e impede a verificação histórica. O leitor do piloto
projeta somente ID/texto/metadados, sem desserializar vetores ou consultar com
embeddings artificiais. Fontes recuperadas hoje não comprovam o conteúdo na data
da resposta. Uma correção já incluída nos candidatos é sinalizada: concordância
com essa referência não equivale a desempenho em perguntas reservadas.

## Controles e revisão dos critérios

O runner [jev_controls.py](../evals/jev_controls.py) compara a rubrica anterior
com a atual nos mesmos textos/fontes, com orçamento compartilhado e até cinco
repetições. Não gera respostas novas e não escreve no banco. Cada controle traz
família, divisão, relação esperada e estado da anotação; derivações não são
consideradas aprovadas por analista automaticamente. O runner rejeita mistura
de perguntas, famílias ou fontes entre calibração e reserva. A execução do
conjunto reservado permanece bloqueada até revisão e calibração congelada.

```bash
python -m evals.jev_controls --input evals/reports/controles-jev-calibracao-20261002.jsonl --dry-run
python -m evals.jev_controls --input evals/reports/controles-jev-calibracao-20261002.jsonl --output evals/reports/nova-comparacao-controles.json --repetitions 3
python -m evals.jev_controls --input evals/reports/controles-jev-calibracao-20261002.jsonl --prepare-reserved --pilot-candidates evals/reports/piloto-jev-20261002.frozen.jsonl --output evals/reports/nova-reserva.jsonl --reserved-limit 8
```

A primeira comparação teve 27 bloqueios propostos indevidos em 36 positivas
com v1 e oito com v2, sem aprovação dos 36 negativos em nenhuma versão. Rótulos
ainda pendentes de revisão, controles fáceis não reservados e repetições
correlacionadas impedem usar isso como comprovação de qualidade em produção.
Oito famílias novas foram inicialmente reservadas sem avaliação pelo modelo. A folha local
`evals/reports/revisao-controles-jev-20261002.md` omite as decisões Jev para revisão
dos rótulos. [Contrato, resultados e pendências](../specs/005-criterios-jev-controles.md).

## Calibração experimental e reserva

O runner [jev_calibration.py](../evals/jev_calibration.py) permite continuar a
exploração com revisão `ai_reviewed`, separada de `reviewed` por humano. Exige
justificativa por controle, positivos e negativos por família e divisões sem
sobreposição de perguntas/fontes, inclusive cópias de fonte com outros IDs.
Não altera a configuração da aplicação, publica curadoria ou declara calibração
operacional. O runner anterior continua recusando a execução da reserva.

Congelar primeiro o perfil com probabilidades v2 da calibração já gravadas;
modelo, rubricas, textos, fontes, grade e limiares têm hashes verificáveis.
Só depois executar a reserva. Perfil ou entradas alteradas, observações ausentes,
duplicadas, truncadas ou falhas na calibração impedem a chamada. A mesma avaliação
v2 gera as decisões das duas políticas, sem repetir geração OpenAI. Arquivos de
saída existentes não são sobrescritos por uma nova execução.

```bash
python -m evals.jev_calibration --calibration evals/reports/controles-jev-calibracao-ia-20261002.jsonl --reserved evals/reports/controles-jev-reservados-ia-20261002.jsonl --calibration-report evals/reports/controles-jev-v1-v2-20261002.json --profile evals/reports/novo-perfil-experimental.json --freeze
python -m evals.jev_calibration --calibration evals/reports/controles-jev-calibracao-ia-20261002.jsonl --reserved evals/reports/controles-jev-reservados-ia-20261002.jsonl --calibration-report evals/reports/controles-jev-v1-v2-20261002.json --profile evals/reports/novo-perfil-experimental.json --output evals/reports/nova-avaliacao-reserva.json --repetitions 3
```

A execução de 02/10 selecionou 0,88/0,12 usando apenas seis famílias de calibração.
Na reserva de oito outras famílias, os bloqueios propostos de positivos caíram
de 22/48 para 12/48, sem aprovar os 48 negativos. São 32 textos repetidos três
vezes, com rótulos IA, não 96 amostras independentes. O objetivo de não bloquear
positivos não se manteve na reserva: **não habilitar enforcement** com esse perfil.
Configuração local/padrão: OpenAI, verificação desligada, calibração falsa, 0,9/0,1.

Relatórios locais `reserva-jev-experimental-20261002.json`/`.md`, perfil e revisão
IA permanecem ignorados em `evals/reports/`. Medem fidelidade às referências do
banco; atualidade das orientações, especialmente tarifação histórica, exige
checagem independente. [Contrato e validação](../specs/006-calibracao-jev-experimental.md).

Na revisão posterior, o usuário considerou boas quatro das cinco respostas com
bloqueio e ruim a paráfrase sobre saúde. Os quatro textos aprovados tiveram nove
bloqueios em doze avaliações. A paráfrase fica contestada como controle positivo
de qualidade, sem novo rótulo de suporte/contradição presumido. Excluí-la apenas
em análise de sensibilidade deixa nove bloqueios em 45 observações positivas
propostas; a métrica original 12/48 permanece preservada. Registro local em
`revisao-humana-parcial-jev-20261002.json`/`.md`. Demais textos ainda não revisados
por humano; perfil e resultados congelados não foram alterados.

## Diagnóstico por afirmação

O runner [jev_claims.py](../evals/jev_claims.py) compara a verificação integral
com trechos factuais anotados em offsets exatos do texto. Mantém modelo, rubricas
Noul v2 e limiares experimentais 0,88/0,12; só muda a granularidade. O agregado
aprova apenas se todos os trechos factuais forem aprovados. Cobertura textual
completa é obrigatória; títulos/formatação exigem anotação estrutural explícita.
A validação de offsets não comprova que a segmentação preserva todos os sentidos:
condições, contexto e classificação factual exigem revisão humana.

Casos anteriores ficam em desenvolvimento. Perguntas/famílias/fontes já usadas
são excluídas da nova reserva, incluindo cópias com outro ID. Congelar manifesto
antes de executar; modelo, rubricas, textos, fontes, anotação e limiares alterados
impedem a chamada. Saídas existentes não são sobrescritas. Até três repetições,
40 casos, 60 segmentos por resposta e 600 avaliações planejadas por execução.

```bash
python -m evals.jev_claims --input evals/reports/afirmacoes-jev-20261002-final.jsonl --seen evals/reports/referencias-vistas-jev-20261002.jsonl --manifest evals/reports/novo-manifesto-afirmacoes.json --freeze --repetitions 3
python -m evals.jev_claims --input evals/reports/afirmacoes-jev-20261002-final.jsonl --seen evals/reports/referencias-vistas-jev-20261002.jsonl --manifest evals/reports/novo-manifesto-afirmacoes.json --output evals/reports/nova-comparacao-afirmacoes.json
```

O relatório mostra os trechos que provocaram cada bloqueio e suas probabilidades,
separando falha técnica de decisão semântica. Utilidade, completude e atualidade
não são aprovadas pelo suporte factual. A paráfrase de saúde contestada continua
fora das positivas deste experimento. Não habilita Jev em produção nem muda o
banco ou a configuração local. [Contrato](../specs/007-jev-afirmacoes.md).

A rodada real de 02/10 avaliou 28 textos/125 trechos, com três repetições e 459
chamadas Jev. Na nova reserva, a verificação integral bloqueou nove de 24
observações positivas propostas; exigir aprovação de todos os trechos bloqueou
21 de 24. Nenhuma aprovação dos 24 negativos em nenhum método. **Não adotar a
segmentação literal com essa política**. O relatório indica fragmentos dependentes
de contexto e 66 bloqueios de trechos positivos apenas pela curadoria. Esse
critério precisa de investigação em outro protocolo; não ajustar na reserva.
Análise local: `analise-afirmacoes-jev-20261002.md`; cobertura/rótulos humanos
continuam pendentes e o Jev permanece off na aplicação.

## Afirmação com contexto e curadoria global

O runner [jev_context.py](../evals/jev_context.py) usa Choice para a relação de
cada trecho com os documentos. A resposta completa serve para resolver
referências, nunca como evidência. Curadoria é avaliada uma vez na resposta
inteira. Novo serviço experimental, sem ligação com rotas/pipeline; o decoder
Noul operacional continua rejeitando Choice inesperado.

Congelar dados, rubricas e grade; executar somente calibração; congelar perfil;
avaliar reserva apenas se o perfil tiver zero bloqueios positivos e zero
aprovações negativas em toda a calibração. Os três comandos seguintes não
executam a reserva e exigem caminhos de saída novos:

```bash
python -m evals.jev_context --input evals/reports/contexto-jev-20261002.jsonl --seen evals/reports/referencias-vistas-contexto-jev-20261002.jsonl --manifest evals/reports/novo-manifesto-contexto.json --freeze
python -m evals.jev_context --input evals/reports/contexto-jev-20261002.jsonl --seen evals/reports/referencias-vistas-contexto-jev-20261002.jsonl --manifest evals/reports/novo-manifesto-contexto.json --phase calibration --output evals/reports/nova-calibracao-contexto.json
python -m evals.jev_context --input evals/reports/contexto-jev-20261002.jsonl --seen evals/reports/referencias-vistas-contexto-jev-20261002.jsonl --manifest evals/reports/novo-manifesto-contexto.json --select-profile --calibration evals/reports/nova-calibracao-contexto.json --profile evals/reports/novo-perfil-contexto.json
```

A fase `--phase reserved` exige `--calibration` e `--profile`, cuja identidade é
recalculada antes de qualquer chamada. Perfil inelegível, dados alterados ou
observação faltante/falha impedem acesso à reserva. Todas as fases usam orçamento
compartilhado entre verificação integral, curadoria global e trechos.

Na rodada de 02/10, foram avaliadas quatro referências aceitas pelo usuário e
oito controles negativos, três vezes: 198 chamadas, US$ 0,01097586 estimados,
sem falhas técnicas. Verificação integral v2 bloqueou 10/12 positivas; contexto
bloqueou 9/12 em 0,95 e 6/12 em todos os limiares de 0,90 a 0,80. Ambos
rejeitaram os 24 negativos. **Nenhum perfil atingiu o critério congelado**;
`selected_support_floor=null` e `ready_for_reserved=false`. Os 16 textos novos
da reserva continuam sem avaliação. Não baixar a confiança nem retirar trechos
após observar resultados para liberar essa reserva.

Próximo trabalho: revisão da classificação factual dos dois trechos persistentes
(oferta de ajuda e precisão do levantamento de contatos), antes de um protocolo
novo. A resposta de saúde contestada permanece fora dos positivos; não recebeu
rótulo de contradição por inferência. [Spec e gates](../specs/008-jev-contexto-curadoria.md).
Resumo local legível: `evals/reports/analise-contexto-jev-20261002.md`.

## Fidelidade documental explícita

A [spec 009](../specs/009-jev-fidelidade-documental.md) mantém todos os textos,
segmentos e limiares da 008, com outra rubrica: verificar o que a fonte afirma,
sem confundir apoio documental com verdade externa, utilidade ou atualidade.
Somente o runner manual seleciona `--protocol documentary`; o padrão continua
`context` (v3), e a aplicação não usa nenhum desses serviços experimentais.
Manifesto/perfil de outro protocolo ou rubricado depois do congelamento impedem
execução. Usar nomes de saída novos; preservar arquivos das rodadas anteriores.

```bash
python -m evals.jev_context --protocol documentary --input evals/reports/contexto-jev-20261002.jsonl --seen evals/reports/referencias-vistas-contexto-jev-20261002.jsonl --manifest evals/reports/novo-manifesto-documental.json --freeze
python -m evals.jev_context --protocol documentary --input evals/reports/contexto-jev-20261002.jsonl --seen evals/reports/referencias-vistas-contexto-jev-20261002.jsonl --manifest evals/reports/novo-manifesto-documental.json --phase calibration --output evals/reports/nova-calibracao-documental.json
python -m evals.jev_context --protocol documentary --input evals/reports/contexto-jev-20261002.jsonl --seen evals/reports/referencias-vistas-contexto-jev-20261002.jsonl --manifest evals/reports/novo-manifesto-documental.json --select-profile --calibration evals/reports/nova-calibracao-documental.json --profile evals/reports/novo-perfil-documental.json
python -m evals.jev_context --protocol documentary --input evals/reports/contexto-jev-20261002.jsonl --seen evals/reports/referencias-vistas-contexto-jev-20261002.jsonl --manifest evals/reports/novo-manifesto-documental.json --phase reserved --calibration evals/reports/nova-calibracao-documental.json --profile evals/reports/novo-perfil-documental.json --output evals/reports/nova-reserva-documental.json
```

Em 02/10, a calibração aprovou 12/12 positivas e rejeitou 24/24 negativas,
selecionando suporte 0,95 antes da reserva. Na reserva, o baseline integral v2
bloqueou 6/24 positivas propostas; documental v4 bloqueou 3/24. Ambos rejeitaram
24/24 negativas. São 16 textos repetidos três vezes, não 48 amostras independentes.
O bloqueio remanescente foi a introdução de uma lista de ferramentas de IA:
Choice escolheu suporte, mas com probabilidade 0,92–0,94 abaixo de 0,95. Não
ajustar critério usando essa reserva. **Ainda não habilitar enforcement.**

372 chamadas, sem falhas técnicas/truncamento, US$ 0,019740042 estimados;
416 testes e todos os gates, incluindo pip-audit padrão, passaram. Novo relatório
simples em `evals/reports/analise-documental-jev-20261002.md` e oito textos para
revisão humana em `textos-revisao-documental-jev-20261002.md`. Rótulos/cobertura
dos controles novos por IA; qualidade/atualidade e geração do RAG não medidas.

### Revisão humana posterior: referência de tags rejeitada

Em 05/10/2026, o usuário confirmou que a orientação de acessar “Relatórios” e
filtrar/exportar chamados ou contatos sem tags descreve uma seção e um recurso
inexistentes. O rastreio somente leitura encontrou essa orientação num registro
ingerido e num documento com metadata de curadoria. A referência e a paráfrase
não são positivos de qualidade; os resultados originais de fidelidade à fonte
permanecem preservados.

Integral v2 rejeitou as seis observações erradas; documental v4 aprovou todas.
O antigo resultado de 6 bloqueios contra 3 não comprova melhoria: os seis
bloqueios eram justamente a família incorreta. Excluindo a família na análise
de sensibilidade, v2 bloqueou 0/18 positivas propostas e v4 3/18; nenhum
aprovou os 18 controles negativos restantes. Isso não valida os demais rótulos
como corretos no produto; continuam anotados por IA.

Diagnóstico com a correção explícita como fonte rejeitou as duas orientações
erradas em 6/6 e aprovou o texto corrigido em 3/3 pelo v4. É regressão no caso
já visto, sem reserva nova nem alteração de limites. Rastreio, revisão humana,
resultados e correção estão em `evals/reports/reavaliacao-tags-20261005.md`
e `correcao-tags-20261005.txt`. Essa reavaliação inicial foi somente leitura;
a publicação autorizada posterior está registrada abaixo. Não habilitar
enforcement com o perfil documental.

### Publicação da correção e teste do RAG — 05/10/2026

Após autorização para continuar, a correção humana foi publicada pelo serviço
de ingestão existente, com embedding real e backup anterior às escritas.
Leitura posterior confirmou o novo documento ativo, o antigo marcado como
substituído (preservando seu conteúdo) e a resposta corrigida no registro de
origem. Uma segunda leitura reconciliou as escritas, sem repetir a publicação.
Backup, IDs e recibo estão nos artefatos privados
`backup-publicacao-tags-20261005.json` e `publicacao-tags-20261005.json`.

A pergunta original selecionou a correção e respondeu corretamente que a
funcionalidade descrita não existe. A pergunta curta “Como exportar uma lista
de contatos sem tags na Digisac?” falhou: a correção ficou em 19º na busca
híbrida bruta, fora dos 15 candidatos usados pelo RAG. O documento aposentado
foi descartado pelo serviço; os outros trechos descrevem exportação geral e a
geração acrescentou um filtro sem tags sem suporte específico.

**Publicação confirmada; validação do RAG com paráfrase reprovada.** O recibo
mantém a ocorrência de falha inicial e distingue escrita confirmada de qualidade
da resposta. O diagnóstico com 50 candidatos foi somente leitura: não alterou
limites, ranking ou configuração de produção. A recuperação de correções
relevantes e a geração de procedimentos sem suporte continuam pendentes;
não tratar a publicação como solução completa desse erro de resposta.
Jev permanece desligado; históricos e resultados congelados foram preservados.
Gates desta etapa: 416 testes, Ruff, mypy, Bandit e pip-audit padrão aprovados.

### Correção do RAG posterior à publicação — 05/10/2026

A [spec 010](../specs/010-rag-recuperacao-evidencia.md) registra a mudança no RAG
OpenAI: 30 candidatos por padrão (configurável até 60), conteúdo curado até 6000
caracteres na seleção, prioridade somente quando aplicável e geração que exige
suporte às condições pedidas. Temperatura zero; a curadoria relevante não recebe
alternativas derivadas dos trechos comuns. Fontes sem suporte específico não
autorizam deduzir filtros ou conteúdo do arquivo exportado.

Rodada final: 12/12 observações de tags corretas quanto à funcionalidade, 6/6
controles gerais seguindo as fontes e 3/3 fontes parciais sem procedimento
inventado. Cinco respostas de tags ainda acrescentam ajuda/encaminhamento:
aderência literal de redação não foi alcançada. São casos conhecidos repetidos,
avaliados pelo assistente em `orientacao`, sem reserva nova ou revisão humana
integral, e não comprovam ganho geral do RAG ou do Jev. Rodadas iniciais falhas
preservadas. Gates: 424 testes, Ruff, mypy, Bandit e pip-audit padrão aprovados.

Não comparar automaticamente esses resultados com os baselines congelados:
o reranker OpenAI padrão agora recebe mais candidatos e texto curado ampliado.
O Jev continua desligado e conserva seus limites próprios; não foi validado
contra esse novo pool. Sem nova publicação, migração, gravação de histórico ou
deploy. Reiniciar/recarregar API em execução para aplicar o código alterado.
Relatório simples privado: `evals/reports/correcao-rag-20261005.md`.
Revisão de análise de servidor anotada em [PENDENCIAS_RAG.md](PENDENCIAS_RAG.md).

### Revisão de servidor — 05/10/2026

A [spec 011](../specs/011-analise-servidor.md) registra seleção mais completa
para infraestrutura, política de evidência, conferência literal de perfis e
separação de documentos/instruções na geração. A política geral foi simplificada
após uma regressão de evidência parcial de tags; os nove controles finais de
exportação/importação/fonte parcial passaram, assim como três respostas de tags.

Rodada real de servidor: 36 respostas completas, porém **aceite de qualidade
reprovado**. Há inferências sem suporte e reprodução de definições problemáticas
de load/steal. Os 452 testes offline e gates aprovados não comprovam qualidade
das respostas. A proposta documental está preparada, sem escrita no banco.
Jev continua off; não retunar avaliações congeladas ou promover respostas
geradas a curadoria. Mudanças de prompt/contexto impedem comparar automaticamente
o novo RAG com os baselines anteriores. Relatório:
`evals/reports/analise-servidor-20261005.md`; código local, sem deploy.

Em 06/10/2026, a [spec 012](../specs/012-servidor-continuacao.md) corrigiu a
continuidade das políticas de infraestrutura e a classificação de atualização
isolada de perfil como orientação. As respostas antigas fornecidas pelo usuário
são evidência de defeito, nunca curadoria ou critérios de capacidade. Os testes
reais mantêm reprovação integral por hipóteses sem consumo e outros acréscimos
sem suporte, apesar dos 476 testes offline e gates aprovados. Sem enforcement,
gravação remota ou deploy; não reusar esses casos conhecidos como reserva nova.

### Decisão do projeto — 06/10/2026

Após revisar os testes, o usuário decidiu manter o RAG existente e o Jev
desligado. Reranking OpenAI, shadow desativado e verificação off confirmados na
configuração local. Não houve ganho demonstrado que justificasse adoção nesta
etapa. Código de pilotos permanece experimental e disponível para reproduzir os
estudos; a prioridade é o ciclo de feedback revisado, curadoria e regressões.
O commit registra o trabalho e suas limitações, não ativa Jev ou publica uma
nova versão. A análise de servidor continua como próximo trabalho de qualidade,
sem considerar as tentativas locais uma correção integral aprovada.
