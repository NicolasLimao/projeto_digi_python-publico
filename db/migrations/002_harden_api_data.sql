-- Security migration for existing Digi installations.
-- Run with an administrative role in the Supabase SQL editor.

begin;

alter table public.historico_digi enable row level security;
drop policy if exists "historico_anon_all" on public.historico_digi;
drop policy if exists "Allow service role full access" on public.historico_digi;
revoke all on table public.historico_digi from anon, authenticated;

alter table public.historico_digi
  add column if not exists pergunta_reescrita text,
  add column if not exists fontes jsonb,
  add column if not exists canal text,
  add column if not exists feedback text;

alter table public.documents enable row level security;
revoke all on table public.documents from anon, authenticated;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'historico_digi_modo_check'
  ) then
    alter table public.historico_digi
      add constraint historico_digi_modo_check
      check (modo in ('orientacao', 'resposta-cliente', 'bug')) not valid;
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'historico_digi_feedback_check'
  ) then
    alter table public.historico_digi
      add constraint historico_digi_feedback_check
      check (feedback is null or feedback in ('positivo', 'negativo')) not valid;
  end if;
end $$;

alter table public.historico_digi validate constraint historico_digi_modo_check;
alter table public.historico_digi validate constraint historico_digi_feedback_check;

-- The API uses service_role. Do not grant direct browser/client access to any
-- analytics views derived from protected history or document tables.
do $$
declare
  view_name text;
begin
  for view_name in
    select quote_ident(schemaname) || '.' || quote_ident(viewname)
    from pg_views
    where schemaname = 'public'
      and (
        viewname like 'v_historico_%'
        or viewname like 'v_rag_%'
        or viewname like 'v_feedback_%'
        or viewname like 'v_volume_%'
        or viewname like 'v_por_%'
        or viewname = 'v_negativos'
      )
  loop
    execute 'revoke all on ' || view_name || ' from anon, authenticated';
  end loop;
end $$;

commit;
