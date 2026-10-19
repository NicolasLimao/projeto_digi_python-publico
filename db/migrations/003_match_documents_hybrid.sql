-- Registro da funcao de busca hibrida que ja roda em producao desde a ingestao
-- via n8n. Exportada do Supabase em 2026-07-21 com pg_get_functiondef.
--
-- Esta migracao NAO muda comportamento: e um CREATE OR REPLACE com a definicao
-- identica a vigente, para que a logica que decide o que o bot enxerga passe a
-- existir no repositorio. A 004 evolui a partir daqui.
--
-- Pendencias conhecidas (fora do escopo desta migracao):
--   * pesos/escala: o Python envia 0.5/0.5 em vez dos defaults 0.3/0.7, e o
--     ts_rank nao e normalizado (0.01-0.1) contra o cosseno (0.3-0.5);
--   * LTRIM(query_embedding, '=') e heranca do n8n;
--   * nao ha indice vetorial (ivfflat/hnsw): a CTE semantica varre a tabela.
--
-- ATENCAO: esta migracao NAO se auto-verifica. CREATE OR REPLACE com a mesma
-- assinatura SEMPRE tem sucesso — ele sobrescreve o corpo da funcao qualquer
-- que ele fosse, sem erro nenhum. Se o export de 21/07/2026 abaixo estiver
-- desatualizado ou tiver perdido algo na transcricao, aplicar esta migracao
-- em producao troca a logica de recuperacao silenciosamente. Antes de
-- aplicar em producao, compare com o que esta no banco:
--
-- SELECT oid::regprocedure, md5(prosrc) FROM pg_proc WHERE proname = 'match_documents_hybrid';
-- SELECT pg_get_functiondef(oid) FROM pg_proc WHERE proname = 'match_documents_hybrid';
--
-- A primeira query tambem serve para detectar overload: se aparecer mais de
-- uma linha, ja existe outra sobrecarga da funcao no banco, e aplicar esta
-- migracao criaria uma terceira — o PostgREST passaria a responder PGRST203
-- (ambiguous) e a busca cairia. Por isso a query usa ::regprocedure (que
-- aceita overloads) e nao 'public.match_documents_hybrid'::regproc, que
-- falha justamente quando ha mais de uma sobrecarga no banco.

CREATE OR REPLACE FUNCTION public.match_documents_hybrid(
  query_text text,
  query_embedding text,
  match_count integer DEFAULT 10,
  full_text_weight double precision DEFAULT 0.3,
  semantic_weight double precision DEFAULT 0.7
)
RETURNS TABLE(content text, metadata jsonb, score double precision)
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
  SELECT doc_content AS content, doc_metadata AS metadata, combined_score AS score
  FROM combined ORDER BY combined_score DESC LIMIT match_count;
END;
$function$;
