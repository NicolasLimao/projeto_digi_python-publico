-- Passa a retornar o id do documento. As CTEs ja computavam d.id como doc_id e
-- o descartavam no SELECT final; agora ele sai junto.
--
-- Ranking intocado de proposito: mesmas CTEs, mesma formula, mesma ordenacao,
-- mesmo LIMIT. Assim, qualquer variacao no eval apos esta migracao e ruido de
-- geracao (temperature=0.5), nao efeito desta mudanca.
--
-- O ::bigint e explicito para nao depender de documents.id ser integer ou bigint.
--
-- Ordem de aplicacao: rodar depois da 003 e ANTES de publicar o codigo Python
-- que le o id. Nesta ordem a coluna extra e ignorada com seguranca pelo codigo
-- antigo, e o codigo novo nunca roda contra a funcao sem id.
--
-- Por que DROP + CREATE em vez de CREATE OR REPLACE: as colunas do RETURNS
-- TABLE sao parametros OUT, e acrescentar "id bigint" muda o tipo de retorno
-- da funcao. CREATE OR REPLACE recusa isso de forma deterministica com
-- "ERROR: cannot change return type of existing function" — nao ha como
-- aplicar esta migracao sem o DROP antes.
--
-- A transacao (begin/commit) evita janela de indisponibilidade: com DROP e
-- CREATE na mesma transacao, chamadas concorrentes que cheguem enquanto isto
-- roda ficam bloqueadas esperando o commit (e depois veem a funcao nova),
-- em vez de falhar com "function does not exist" no intervalo entre os dois
-- comandos.
--
-- O DROP tambem descarta privilegios (GRANT/REVOKE) da funcao, que voltam ao
-- default na recriacao. Hoje isso e inofensivo: a funcao roda como
-- SECURITY INVOKER e a RLS de documents ja protege o acesso. Mas importa se
-- algum dia alguem tornar esta funcao SECURITY DEFINER — nesse caso, confira
-- os grants apos aplicar.
--
-- Se a RPC responder 404/PGRST202 logo depois de aplicar, o PostgREST esta
-- com o schema cache antigo (nao encontrou a funcao nova ainda). O remedio e
-- rodar no SQL Editor: NOTIFY pgrst, 'reload schema';
--
-- Rollback (nesta ordem — reverter so o SQL sem reverter o Python devolve
-- fontes = ["chunk_0", ...] em vez dos ids reais):
--   1. DROP FUNCTION public.match_documents_hybrid(text, text, integer, double precision, double precision);
--   2. Reaplicar db/migrations/003_match_documents_hybrid.sql;
--   3. Reverter o deploy do codigo Python para a versao anterior a esta branch.

begin;

drop function if exists public.match_documents_hybrid(
  text, text, integer, double precision, double precision);

create function public.match_documents_hybrid(
  query_text text,
  query_embedding text,
  match_count integer DEFAULT 10,
  full_text_weight double precision DEFAULT 0.3,
  semantic_weight double precision DEFAULT 0.7
)
RETURNS TABLE(id bigint, content text, metadata jsonb, score double precision)
LANGUAGE plpgsql
AS $function$
DECLARE clean_embedding VECTOR(1536);
BEGIN
  clean_embedding := LTRIM(query_embedding, '=')::vector;
  RETURN QUERY
  WITH semantic AS (
    SELECT d.id AS doc_id, d.content AS doc_content, d.metadata AS doc_metadata,
      (1 - (d.embedding <=> clean_embedding))::float AS sem_score
    FROM documents d
  ),
  full_text AS (
    SELECT d.id AS doc_id,
      ts_rank(to_tsvector('portuguese', d.content), plainto_tsquery('portuguese', query_text))::float AS ft_score
    FROM documents d
    WHERE to_tsvector('portuguese', d.content) @@ plainto_tsquery('portuguese', query_text)
  ),
  combined AS (
    SELECT s.doc_id, s.doc_content, s.doc_metadata,
      (semantic_weight * s.sem_score) + (full_text_weight * COALESCE(f.ft_score, 0)) AS combined_score
    FROM semantic s LEFT JOIN full_text f ON s.doc_id = f.doc_id
  )
  SELECT doc_id::bigint AS id, doc_content AS content, doc_metadata AS metadata, combined_score AS score
  FROM combined ORDER BY combined_score DESC LIMIT match_count;
END;
$function$;

commit;
