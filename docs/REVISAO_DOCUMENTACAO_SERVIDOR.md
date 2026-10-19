# Proposta de revisão da documentação de servidor

Preparada em 05/10/2026. Texto para revisão técnica; nenhum documento do banco
foi alterado e nenhuma proposta foi marcada como curadoria autorizada.

## Load — documento 921

O trecho recuperado define load como utilização total de CPU/RAM. Essa definição
deve ser substituída por:

> No Linux, load average representa a média de tarefas executáveis, incluindo
> tarefas em execução ou aguardando CPU, e tarefas em espera ininterruptível.
> Não é percentual de CPU nem de RAM. O painel pode transformar ou normalizar
> a métrica; confira a consulta, a unidade e o intervalo antes de interpretá-la.
> Para comparar com recursos da VM, confirme também o que o painel contabiliza
> como cores e a alocação efetiva da instância.

Base técnica: [documentação Linux de /proc](https://www.kernel.org/doc/html/latest/filesystems/proc.html)
e [manual Linux, definição de load average](https://www.kernel.org/pub/linux/docs/man-pages/book/man-pages-6.17.pdf).

## CPU steal — documento 931

O trecho atribui a competição ao uso prolongado de burst. Essa causa não pode
ser confirmada apenas pelo indicador. Proposta:

> CPU steal registra tempo de espera involuntária por CPU em um ambiente
> virtualizado. Um valor isolado não comprova que o burst acabou nem identifica
> sua causa. Confira a unidade, a série temporal, a configuração da instância
> e a correlação com uso de CPU e sintomas. Não conclua ausência de competição
> apenas porque um valor pontual parece baixo.

Base técnica: [contabilidade de CPU em /proc/stat](https://www.kernel.org/doc/html/latest/filesystems/proc.html)
e [funcionamento de instâncias Oracle Burstable](https://docs.oracle.com/en-us/iaas/Content/Compute/References/burstable-instances.htm).

## Configuração e snapshot — esclarecimento complementar

> Recursos esperados e baseline são configuração informada, não consumo medido
> nem confirmação dos recursos efetivamente entregues. Um snapshot histórico
> mostra aquele instante; não comprova desempenho sustentado ou necessidade de
> upgrade. Examine CPU, memória, swap, disco, load/steal e latência ao longo do
> período de pico, junto com sintomas e consumo de serviços/filas. Quantidade
> mensal de mensagens e usuários cadastrados não substitui essas medições.

Não mudar os números do exemplo do documento 938 nem apresentá-los como dados
de um cliente atual. O documento 929 de burstable também precisa preservar a
distinção entre baseline configurada, uso e burst; memória não recebe burst de
CPU. A referência Oracle acima sustenta essa distinção, sem definir capacidades
comerciais da Digisac.

## Informações do produto ainda necessárias

- Confirmar a versão original do treinamento e suas imagens. A busca textual
  realizada não cobre conteúdo presente apenas nos gráficos.
- Confirmar oficialmente as unidades dos perfis X/Y e os recursos contratados
  versus efetivamente alocados. Não inferir uma correspondência por analogia.
- Localizar uma regra de dimensionamento aprovada, caso exista. A tabela do
  documento 927 lista configurações, mas não determina quantas conexões,
  mensagens ou usuários cada perfil suporta. Ela não contém o perfil 8/12.

Após a revisão, a eventual publicação deve usar o fluxo de ingestão existente,
com backup, embedding real e leitura posterior de confirmação. Repetir os casos
reais antes de considerar a análise de servidor aprovada. A proposta não autoriza
promover uma resposta gerada pelo bot a referência validada por analista.
