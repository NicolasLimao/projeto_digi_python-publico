# Pendências de qualidade do RAG

## Análise de servidor — registrada em 05/10/2026

O usuário relatou que a análise de servidor está muito ruim e pediu revisão
posterior. Ele acredita existir documentação específica para esse assunto.
Essa hipótese foi confirmada pelo rastreio descrito abaixo; a cobertura completa
e a versão original do treinamento permanecem pendentes.

Próximo trabalho, após a correção de recuperação/evidência de procedimentos:

1. Localizar a documentação de análise de servidor na base e conferir se está
   atualizada, ingerida e acessível pela recuperação, sem assumir sua existência.
2. Separar perguntas reais de analistas e respostas esperadas a partir dessa
   documentação; incluir variações e casos sem evidência suficiente.
3. Rastrear documentos recuperados, resposta gerada e informação acrescentada
   sem fonte, para distinguir falha de busca de falha de interpretação.
4. Especificar a correção, demonstrar regressão, comparar resultados e revisar
   com o analista antes de anunciar melhora.

Estado em 05/10/2026: revisão iniciada após autorização para continuar.
Documentação “Servidores e consumo”, Grafana e AWX encontrada na base;
reprodução confirmou sugestões de upgrade sem medições reais. Correção local e
regressões em [spec 011](../specs/011-analise-servidor.md): 452 testes e gates
passaram, mas a rodada real com 36 respostas continua reprovada em qualidade.
Conferência literal dos perfis resolveu a referência falsa ao 8/12; ainda há
inferência de capacidade/unidades, confusão de recursos esperados com atuais e
interpretação excessiva de snapshots. Não considerar a pendência resolvida.

Pendência documental: revisar as definições de load e CPU steal do treinamento,
confirmar versão atual/original dos gráficos e se existe tabela de dimensionamento
aprovada. O rastreio textual não encontrou regra de capacidade por mensagens,
usuários ou conexões; não comprova ausência em toda a documentação ou nas imagens.
Não houve substituição de fonte nem publicação de novas recomendações.
Texto concreto para revisão em
[REVISAO_DOCUMENTACAO_SERVIDOR.md](REVISAO_DOCUMENTACAO_SERVIDOR.md).
Relatório simples privado: `evals/reports/analise-servidor-20261005.md`.

Atualização em 06/10/2026: exemplo fornecido pelo usuário acrescentou “qual
recomendado” e “o cliente ja utiliza um 16/16”. Corrigida perda de contexto na
política e classificação indevida da atualização como bug, conforme
[spec 012](../specs/012-servidor-continuacao.md). O último turno deixou de traduzir
o perfil e garantir suficiência nos testes; hipóteses sem medidas nos turnos
anteriores persistem. Qualidade integral continua reprovada. Relatório privado:
`evals/reports/exemplo-servidor-20261006.md`; fontes e unidades ainda em revisão.
