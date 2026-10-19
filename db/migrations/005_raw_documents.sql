-- Tabela de documentos crus (texto extraido, sem chunking) — fonte da verdade
-- para re-chunkar quando quiser, sem re-OCR. Nasce com RLS ativo: so a
-- service_role (usada pelo dashboard) acessa; anon/authenticated sem privilegios.

begin;

create table if not exists public.raw_documents (
  id         bigint generated always as identity primary key,
  nome       text not null,
  fonte_alvo text not null,
  tipo       text not null check (tipo in ('pdf', 'texto')),
  texto      text not null,
  n_chars    integer not null default 0,
  status     text not null default 'cru' check (status in ('cru', 'chunkado')),
  criado_em  timestamptz not null default now()
);

alter table public.raw_documents enable row level security;
revoke all on table public.raw_documents from anon, authenticated;

commit;
