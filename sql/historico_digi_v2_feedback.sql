-- Migração v2: feedback + metadados no histórico
-- Rode no Supabase: Dashboard -> SQL Editor -> New query -> cole -> Run
alter table public.historico_digi
  add column if not exists pergunta_reescrita text,
  add column if not exists fontes jsonb,
  add column if not exists canal text,
  add column if not exists feedback text;  -- 'positivo' | 'negativo' | null
