# Avaliação demonstrativa

`dataset.jsonl` contém 32 casos sintéticos, com origem `sintetico`, ancorados em `corpus/demo.md`. Não contém feedback real, datas de atendimento, scores de produção ou conversas de clientes.

Para uma avaliação manual, carregue esse corpus em uma instância de teste e configure suas próprias credenciais localmente. O runner usa localhost por padrão. `python evals/run_eval.py --dry-run` valida/carrega os casos sem chamadas externas. Uma execução real pode consumir serviços pagos e deve ser iniciada explicitamente. Os exemplos não demonstram qualidade medida.

Guarde datasets privados em `evals/private/` (ignorado) e relatórios em `evals/reports/` (ignorado).
