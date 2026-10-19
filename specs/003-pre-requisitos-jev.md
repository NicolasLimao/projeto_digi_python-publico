# 003 — Pré-requisitos da integração Jev

Estado: implementado; validação dirigida aprovada, gates finais na entrega.

Curadoria exige `curated=true` explícito no contrato autenticado, conteúdo no formato de correção e ausência de anexos. Texto comum e anexos não ganham autoridade por marcador. Metadados históricos não serão alterados automaticamente.

Produção com histórico exige `USER_ID_SALT` não vazio. O dashboard só encerra dúvidas após resposta JSON válida, chunks positivos e nenhum erro de ingestão; resultado indeterminado permanece pendente, sem retry automático. Falha em uma aba não interrompe abas independentes.

Dependências vulneráveis devem ser atualizadas consistentemente e auditadas. Testes verificam sucesso, entrada inválida, configuração ausente e falha externa, preservando estado. Nenhuma migração ou escrita real é necessária nesta etapa.

Evidência: novas regressões em `tests/services/test_ingestion_service.py`, `tests/test_config.py`, `tests/test_dashboard_dados.py` e `tests/test_dashboard_app.py`. Locks de produção, desenvolvimento e uv atualizados para PyJWT 2.15.1 e urllib3 2.8.0; auditoria complementar sem vulnerabilidades conhecidas.
