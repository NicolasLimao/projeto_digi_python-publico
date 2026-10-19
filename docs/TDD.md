# TDD no Digi

TDD é o fluxo de mudanças de comportamento: teste que demonstra o requisito, correção mínima e revisão da solução. O objetivo é reproduzir o erro e proteger o contrato observável, não aumentar contagem de testes.

## Ciclo de trabalho

1. Ler a especificação e identificar resultado observável, invariantes e efeitos persistentes.
2. **RED:** escrever o menor teste que reproduz o problema com dependências injetadas. Rodar o teste e conferir que falhou pelo comportamento esperado, não por erro de importação ou setup.
3. **GREEN:** implementar o comportamento mínimo que satisfaz o requisito, sem alterar caminhos não relacionados.
4. **REFACTOR:** revisar nomes, responsabilidades, limites e ciclo de vida; conservar o contrato e rodar novamente os testes afetados quando houver mudança.
5. Executar os gates do repositório e registrar resultado, limitações e rastreabilidade na especificação/revisão.

Para uma proteção já existente, um teste novo pode passar imediatamente; isso é cobertura de regressão, não evidência de que houve RED de uma implementação nova.

## Matriz de testes

Novo comportamento exercita sucesso, entrada inválida, configuração ausente e falha externa. Operação persistente verifica também o que ficou gravado ou preservado. Integrações com limites exercitam timeout, retries, tamanho, concorrência e cancelamento quando aplicáveis.

| Camada | Como testar |
| --- | --- |
| Funções de dados/chunking | Entradas reais mínimas e resultado determinístico |
| Serviços | Cliente injetado, fakes/mocks de transporte e falhas controladas |
| API | `TestClient`, contrato HTTP, autenticação e validação |
| Pipeline | Colaboradores injetados, ordem necessária, concorrência e resposta entregue |
| Dashboard | Camada de dados offline e `AppTest` para conteúdo efetivamente renderizado |
| RAG/qualidade de modelo | Dataset reservado, repetição e revisão humana; separado da suíte offline |

Não chamar APIs reais na suíte normal. Fakes pertencem aos testes e nunca entram nos caminhos de produção. Não usar a aprovação de um mock como evidência de qualidade de uma IA.

Uma aba criada sem conteúdo não conta como renderização bem-sucedida. Um retorno HTTP 200 sem confirmação de escrita não conta como sucesso de ingestão. Testes devem verificar o resultado útil e os efeitos persistentes.

## Exemplo aplicado: publicação vazia

[Spec 001](../specs/001-publicacao-documentos.md): uma collection vazia ou texto vazio não pode substituir a base vigente.

- RED observado: os testes de vazio e dependências ausentes falharam; duas proteções existentes para JSON inválido e falha de embedding já passaram.
- GREEN: validação explícita de dependências e rejeição de chunks inexistentes/vazios antes de inserir, salvar backup, apagar ou atualizar status.
- Regressão: testes de publicação válida e insert incompleto continuam passando.

Execução dirigida:

```bash
pytest -q tests/test_dashboard_dados.py -k publicar_lote
pytest -q tests/test_app.py tests/test_dashboard_dados.py
```

Execute a suíte completa antes da entrega. Para alterações apenas documentais ou de configuração local reversível, prefira verificação direta adequada à mudança; não crie testes artificiais de baixo valor.

## Registro de evidência

Registrar: requisito/spec, teste que reproduz o problema, causa do RED, alteração final, resultados dos checks e pendências. Não declarar sucesso completo se auditoria, integração necessária ou aceite falhou. Logs de validação não devem conter credenciais nem conteúdo real de conversas.
