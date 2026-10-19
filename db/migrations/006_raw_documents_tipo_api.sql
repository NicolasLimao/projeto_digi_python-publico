-- Permite guardar a Postman Collection crua (JSON) em raw_documents como tipo 'api'.
-- Recria o CHECK de tipo para incluir 'api' além de 'pdf' e 'texto'.

begin;

alter table public.raw_documents drop constraint if exists raw_documents_tipo_check;
alter table public.raw_documents
  add constraint raw_documents_tipo_check check (tipo in ('pdf', 'texto', 'api'));

commit;
