-- Tabela de curadoria do dashboard: respostas oficiais às dúvidas pendentes.
-- Rode no Supabase SQL Editor. Após a migração 002 (hardening), o acesso
-- passa a exigir a service_role — o dashboard já prefere essa chave.
create table if not exists public.duvidas_respondidas (
  id uuid primary key default gen_random_uuid(),
  chave text not null unique,          -- 'prod:<timestamp>' | 'eval:<case_id>'
  pergunta text not null,
  resposta_correta text not null,
  ingerida boolean not null default false,
  chunks_criados int not null default 0,
  criado_em timestamptz not null default now()
);
