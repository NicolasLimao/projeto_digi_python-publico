-- Tabela de histórico de conversas do agente Digi
-- Rode no Supabase: Dashboard -> SQL Editor -> New query -> cole -> Run
create table if not exists public.historico_digi (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  pergunta text not null,
  resposta text,
  modo text default 'orientacao',
  score double precision default 0,
  chunks_used integer default 0,
  processing_time_ms integer default 0,
  pergunta_reescrita text,
  fontes jsonb,
  canal text,
  feedback text check (feedback is null or feedback in ('positivo', 'negativo')),
  timestamp timestamptz not null default now()
);

-- Índice para buscar o histórico recente de um usuário rapidamente
create index if not exists idx_historico_user_ts
  on public.historico_digi (user_id, timestamp desc);

-- RLS: o backend usa SUPABASE_SERVICE_ROLE_KEY. A chave anon não pode ler
-- conversas nem gravar respostas; service_role ignora RLS de forma controlada.
alter table public.historico_digi enable row level security;

drop policy if exists "historico_anon_all" on public.historico_digi;
revoke all on table public.historico_digi from anon, authenticated;
