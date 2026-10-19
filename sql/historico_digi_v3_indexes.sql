-- Migração v3: índices de performance + extensão de monitoramento
--
-- Origem: análise das regras `query-missing-indexes`, `query-partial-indexes`,
-- `advanced-jsonb-indexing` e `monitor-pg-stat-statements` da skill
-- supabase-postgres-best-practices contra o schema atual do Digi.
--
-- Como rodar: Supabase → SQL Editor → New query → cole → Run
-- Esperado: "Success. No rows returned" (operações idempotentes, com IF NOT EXISTS).

----------------------------------------------------------------------
-- 1. Índice descendente em historico_digi.timestamp
----------------------------------------------------------------------
-- Atende queries de analytics e cleanup que filtram SÓ por janela temporal,
-- sem user_id. Exemplos:
--   - view v_volume_diario  (group by date(timestamp))
--   - clear_old_history     (delete where timestamp < cutoff)
--   - dashboards "últimos N dias"
--
-- Regra: query-missing-indexes (CRITICAL, 100-1000x em tabelas grandes)
create index if not exists idx_historico_timestamp
  on public.historico_digi (timestamp desc);


----------------------------------------------------------------------
-- 2. Índice parcial dos feedbacks negativos
----------------------------------------------------------------------
-- A view v_negativos é o "mapa de gaps" — usada em toda análise de qualidade.
-- Índice parcial é dramaticamente menor que um índice completo na coluna
-- feedback (só armazena as linhas com feedback='negativo'), e responde
-- a essa query em milissegundos.
--
-- Regra: query-partial-indexes (HIGH, 10-100x em consultas filtradas)
create index if not exists idx_historico_feedback_neg
  on public.historico_digi (timestamp desc)
  where feedback = 'negativo';


----------------------------------------------------------------------
-- 3. Índice em expressão JSONB para documents.metadata->>'data'
----------------------------------------------------------------------
-- Toda auditoria de batch ("quantos chunks foram ingeridos em 2026-05-28?")
-- e detecção de batches parciais filtra por metadata->>'data' com LIKE.
-- Sem índice, vira sequential scan na tabela inteira (1.099+ chunks).
--
-- Regra: advanced-jsonb-indexing
create index if not exists idx_documents_metadata_data
  on public.documents ((metadata->>'data'));


----------------------------------------------------------------------
-- 4. Habilitar pg_stat_statements (monitoramento)
----------------------------------------------------------------------
-- Permite identificar as queries mais lentas/frequentes em produção.
-- Sem custo perceptível, ganho contínuo de visibilidade.
--
-- Regra: monitor-pg-stat-statements (LOW-MEDIUM, mas habilita TUDO de
-- diagnóstico futuro).
create extension if not exists pg_stat_statements;


----------------------------------------------------------------------
-- Validação pós-execução (rode separadamente para conferir)
----------------------------------------------------------------------
-- Conferir índices criados:
--   select indexname, tablename from pg_indexes
--   where schemaname = 'public'
--     and tablename in ('historico_digi', 'documents')
--   order by tablename, indexname;
--
-- Conferir extensão:
--   select * from pg_extension where extname = 'pg_stat_statements';
--
-- Ver as 10 queries mais lentas (após algumas horas de uso):
--   select calls,
--          round(total_exec_time::numeric, 2) as total_ms,
--          round(mean_exec_time::numeric, 2) as mean_ms,
--          left(query, 80) as query
--   from pg_stat_statements
--   order by total_exec_time desc
--   limit 10;
