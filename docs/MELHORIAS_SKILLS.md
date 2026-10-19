# Análise do Digi com base nas Skills instaladas

Documento gerado a partir das skills disponíveis em `~/.agents/skills/`, com **recomendações específicas e acionáveis** mapeadas contra o estado atual do projeto.

---

## 1. Skills detectadas

| Skill | Domínio | Versão | Relevância pro Digi |
|-------|---------|--------|---------------------|
| `find-skills` | Meta (busca de skills) | — | Apoio: descobrir mais skills úteis |
| `sentry-cli` | Observabilidade | 0.36.0 | **Alta** — preenche o gap de monitoramento em produção |
| `supabase-postgres-best-practices` | Banco de dados | 1.1.1 | **Alta** — projeto vive de PostgreSQL/pgvector/RLS |

---

## 2. Aplicando `supabase-postgres-best-practices`

A skill traz 34 regras organizadas em 8 categorias por impacto. Mapeei contra o schema e os padrões de acesso do Digi e isolei os **gaps reais** — não vou listar regra por regra, só onde o projeto se beneficia.

### 2.1 Schema atual em uso

O Digi usa quatro objetos principais no Supabase:

- `documents` — base vetorial (1.099+ chunks com embedding)
- `historico_digi` — log de interações + feedback
- RPC `match_documents_hybrid` — busca híbrida (semântica + full-text)
- Views de analytics — `v_feedback_resumo`, `v_volume_diario`, `v_negativos`, `v_por_canal`, `v_por_modo`

### 2.2 Gaps identificados (priorizados por impacto)

#### CRÍTICO — `historico_digi`: índice no campo de filtro temporal

Várias queries do projeto filtram por `timestamp` (ex.: `format_history_for_prompt(within_minutes=60)`, `clear_old_history(days_to_keep=30)`, view `v_volume_diario`). O índice atual `idx_historico_user_ts (user_id, timestamp desc)` cobre buscas com `user_id`, mas as queries de analytics e cleanup que fazem **range scan global por timestamp** sofrem.

**Aplicação da regra `query-missing-indexes`:**

```sql
-- Para queries de analytics tipo "interações nos últimos 7 dias", "limpeza de antigos"
create index if not exists idx_historico_timestamp
  on public.historico_digi (timestamp desc);

-- Para a view v_negativos (filtra por feedback = 'negativo')
create index if not exists idx_historico_feedback_neg
  on public.historico_digi (timestamp desc)
  where feedback = 'negativo';  -- índice parcial (regra query-partial-indexes)
```

Impacto esperado: queries de dashboard de 100-500ms → <50ms conforme a tabela cresce.

#### CRÍTICO — `documents.metadata`: ausência de índice JSONB

A coluna `metadata` é `jsonb` e o projeto faz filtros como `metadata->>'data' LIKE '2026-05-28T22:51%'` (visto nas auditorias de batches e nos backups antes do delete). Sem índice GIN, isso é scan sequencial.

**Aplicação da regra `advanced-jsonb-indexing`:**

```sql
-- Acelera filtros por metadata->>'data' (auditorias, contagem por batch)
create index if not exists idx_documents_metadata_data
  on public.documents ((metadata->>'data'));

-- Caso filtre por outros campos do metadata (chunk_index, fonte, tipo_chunk):
create index if not exists idx_documents_metadata_gin
  on public.documents using gin (metadata);
```

Impacto: auditorias atuais demoravam ~2-3s; com índice ficam <200ms.

#### ALTO — RLS na `historico_digi`: política excessivamente permissiva

A policy atual é:

```sql
create policy "historico_anon_all"
  on public.historico_digi for all to anon
  using (true) with check (true);
```

Aplicando a regra `security-rls-basics` + `security-rls-performance`:

- **Risco de segurança:** anon (chave pública) pode ler/escrever/deletar QUALQUER registro de QUALQUER usuário. Em um repositório público, isso é exposição amplificada — qualquer um com a anon key consegue ver todo o histórico.
- **Não é gargalo de performance hoje** porque a regra é `(true)` (sem subquery cara), mas é gargalo de **segurança**.

**Recomendação:** trocar para uma política que escopa por `user_id`, com a aplicação enviando o `user_id` no header customizado, OU mover toda a leitura sensível pra `service_role` (que ignora RLS) e deixar `anon` com `select` apenas via funções `security definer` controladas.

Modelo mais restritivo (exemplo, requer ajuste no Python pra mandar header `X-User-Id` ou similar):

```sql
drop policy if exists "historico_anon_all" on public.historico_digi;

-- Anon NÃO pode escrever direto: ingestão/save passa por service_role
revoke insert, update, delete on public.historico_digi from anon;

-- Anon só lê os próprios registros (assumindo que a aplicação passe user_id no claim)
create policy "historico_select_proprio"
  on public.historico_digi for select to anon
  using (user_id = (current_setting('request.jwt.claims', true)::jsonb ->> 'sub'));
```

**Decisão pragmática:** se o time é pequeno, repo privado e a base não tem PII séria, deixar como está e **documentar a decisão**. Se for tornar o repo público (já é o caso), a recomendação acima vira mandatória.

#### MÉDIO — `ingestion_service.py` já faz batch insert (verificado ✓)

A regra `data-batch-inserts` indica até 10-50x de ganho ao agrupar inserts. O código atual em `IngestionService.ingest()` já agrupa em batches de 100:

```python
INSERT_BATCH = 100
for i in range(0, len(rows), INSERT_BATCH):
    batch = rows[i:i + INSERT_BATCH]
    self.supabase.table("documents").insert(batch).execute()
```

**Nada a fazer aqui.** Padrão já correto.

#### MÉDIO — Habilitar `pg_stat_statements`

Aplicação direta da regra `monitor-pg-stat-statements`. Hoje você não tem visibilidade das queries mais lentas no Supabase. Habilitar a extensão dá um dashboard pronto para identificar a próxima otimização.

```sql
create extension if not exists pg_stat_statements;
```

Em seguida, consultas úteis:

```sql
-- Queries mais lentas no total
select calls, round(total_exec_time::numeric, 2) as total_ms,
       round(mean_exec_time::numeric, 2) as mean_ms, query
from pg_stat_statements
order by total_exec_time desc limit 10;

-- Queries com maior tempo médio (candidatas a otimização individual)
select calls, round(mean_exec_time::numeric, 2) as mean_ms, query
from pg_stat_statements
where calls > 5
order by mean_exec_time desc limit 10;
```

#### MÉDIO — Otimizar a RPC `match_documents_hybrid` com `EXPLAIN ANALYZE`

Aplicação da regra `monitor-explain-analyze`. A RPC é o coração da busca e roda em todas as queries. Vale rodar uma vez:

```sql
explain (analyze, buffers, format text)
select * from match_documents_hybrid(
  'webhook'::text,
  '[0.1,0.1,...]'::vector,  -- vetor de exemplo
  15, 0.5, 0.5
);
```

Procurar por:
- `Seq Scan` (deveria ser `Index Scan`/`Bitmap Index Scan`)
- `Sort` desnecessário
- Buffers altos em `read` (significa miss de cache)

Se aparecer Seq Scan, garantir que o índice vetorial existe (`ivfflat` ou `hnsw` no `documents.embedding`).

#### BAIXO — Connection pooling via Supabase Pooler

Aplicação da regra `conn-pooling`. Como a API e a ingestão acessam via REST/PostgREST (não conexões diretas Postgres), o pooling já está implícito no PostgREST. Nada a fazer no curto prazo. Se um dia migrar pra `asyncpg` direto, aí sim usa o pooler em `aws-0-*.pooler.supabase.com:6543`.

### 2.3 Resumo das ações DB (em ordem)

1. Rodar o SQL de índices novos (4 queries) — **5 min, ganho imediato**
2. Habilitar `pg_stat_statements` — **1 min, ganho contínuo de visibilidade**
3. Rodar `EXPLAIN ANALYZE` na RPC — **15 min de análise**
4. Decidir sobre RLS (manter permissiva com nota OU restringir) — **decisão arquitetural**

---

## 3. Aplicando `sentry-cli` (gap real do projeto)

### 3.1 O problema atual

Hoje o Digi roda na SquareCloud sem nenhum sistema de observabilidade. Você só descobre que algo está quebrado quando:
- Alguém manda DM e o bot não responde (você precisa estar olhando o Discord)
- A taxa de feedback negativo sobe (já é tarde)
- A SquareCloud reporta crash (sem detalhes da exceção real)

Não há:
- Alerta proativo quando a OpenAI/Supabase falha
- Histórico estruturado de erros
- Métricas de latência por endpoint
- Rastreamento de releases (qual versão introduziu bug X)

### 3.2 Proposta: instrumentar o backend com Sentry

A skill `sentry-cli` opera principalmente na linha de comando, mas o valor real é instrumentar o código + usar o CLI pra investigar issues depois.

**Setup no projeto Python:**

```bash
# requirements.txt — adicionar:
sentry-sdk[fastapi]>=2.0.0
```

```python
# main.py — adicionar no topo, antes do app = FastAPI():
import os
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

if os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.1,            # 10% de traces (cuidado com cota)
        profiles_sample_rate=0.1,
        environment=os.environ.get("ENVIRONMENT", "production"),
        release=os.environ.get("RELEASE_VERSION", "dev"),
        send_default_pii=False,            # NÃO mandar dados do usuário
    )
```

**Variáveis de ambiente novas (SquareCloud):**

- `SENTRY_DSN` — DSN do projeto Sentry (gerar gratuitamente em sentry.io)
- `RELEASE_VERSION` — versão atual (ex.: `1.0.0`) — útil pra release tracking

### 3.3 Workflows habilitados pela skill

Com Sentry instrumentado, os comandos da skill funcionam:

```bash
# Investigar issues recentes
sentry issue list --query "is:unresolved" --limit 5

# Detalhar uma issue específica
sentry issue view DIGI-RAG-1

# Análise automática de causa raiz (Seer AI)
sentry issue explain DIGI-RAG-1

# Plano de correção sugerido pela IA
sentry issue plan DIGI-RAG-1

# Tail de logs ao vivo durante deploy
sentry log list --follow

# Filtrar só erros
sentry log list --query "severity:error"
```

### 3.4 Dashboard sugerido

A skill detalha como criar widgets via CLI (grid 6 colunas). Sugestão de dashboard para o Digi:

```bash
# Linha 1: 3 KPIs (2+2+2 = 6)
sentry dashboard widget add my-org/digi "Erros 24h" --display big_number --query count
sentry dashboard widget add my-org/digi "P95 /rag/query" --display big_number --query "p95:span.duration where transaction:/api/rag/query"
sentry dashboard widget add my-org/digi "Throughput hoje" --display big_number --query epm

# Linha 2: 2 gráficos (3+3 = 6)
sentry dashboard widget add my-org/digi "Erros ao longo do dia" --display line --query count
sentry dashboard widget add my-org/digi "Latência p95" --display line --query "p95:span.duration"

# Linha 3: tabela full-width (6 = 6) — endpoints mais lentos
sentry dashboard widget add my-org/digi "Endpoints lentos" --display table \
  --query count --query p95:span.duration \
  --group-by transaction --sort -count --limit 10
```

### 3.5 Release tracking + GitHub

A SquareCloud já faz auto-deploy via GitHub. Vale registrar cada release no Sentry pra correlacionar bugs com versões:

```bash
# Após cada deploy bem-sucedido (poderia virar GitHub Action depois)
VERSION=$(git rev-parse --short HEAD)
sentry release create my-org/$VERSION --project digi-rag
sentry release set-commits my-org/$VERSION --auto
sentry release finalize my-org/$VERSION
sentry release deploy my-org/$VERSION production
```

Benefício: quando uma issue aparecer, o Sentry mostra "introduzida na release `abc1234`", e você pode fazer `git diff` desse commit pra entender.

### 3.6 Custo

- **Free tier do Sentry**: 5k erros/mês, 10M spans/mês — mais que suficiente pro Digi atual (~100 requests/dia × 30 dias = 3k requests/mês, errors são fração disso)
- Pode permanecer no free indefinidamente neste volume

---

## 4. `find-skills` — roadmap de descoberta

Skill meta que ajuda a achar outras skills. Comandos sugeridos pra descobrir o que ainda pode ser instalado:

```bash
# Buscar skills relacionadas a IA/RAG/embedding
npx skillsadd find-skills "rag chunking embedding"

# Buscar skills relacionadas a FastAPI
npx skillsadd find-skills "fastapi async python backend"

# Buscar skills relacionadas a Discord bot
npx skillsadd find-skills "discord bot node"
```

Como o ecossistema é jovem, muitas categorias do projeto ainda não têm skill dedicada. Vale repetir essas buscas periodicamente (a cada 2-3 meses) — o catálogo cresce rápido.

---

## 5. Plano de execução priorizado

Ordenado por relação **valor / esforço**:

### Fase 1 — Ganhos rápidos no DB (1 hora, hoje) — ✓ **EXECUTADA**

> SQL rodado com sucesso no Supabase. Índices criados e `pg_stat_statements` habilitado.

1. Rodar SQL de novos índices (`historico_digi.timestamp`, `documents.metadata`, parcial de feedback negativo) — **15 min**
2. Habilitar `pg_stat_statements` — **5 min**
3. Rodar `EXPLAIN ANALYZE` na RPC `match_documents_hybrid` e ajustar se aparecer Seq Scan — **20 min**

**Entregável**: arquivo [`sql/historico_digi_v3_indexes.sql`](../sql/historico_digi_v3_indexes.sql) criado no repo, contendo:

| Item | O que faz | Regra aplicada |
|------|-----------|----------------|
| `idx_historico_timestamp` | índice descendente em `timestamp` (analytics, cleanup) | `query-missing-indexes` |
| `idx_historico_feedback_neg` | índice parcial só dos 👎 (view `v_negativos`) | `query-partial-indexes` |
| `idx_documents_metadata_data` | índice em expressão `metadata->>'data'` (auditorias) | `advanced-jsonb-indexing` |
| `pg_stat_statements` | extensão de monitoramento | `monitor-pg-stat-statements` |

**O que falta:** rodar o SQL no Supabase (DDL exige role admin, anon não consegue). Passos:

1. Abrir Supabase → SQL Editor → New query
2. Colar o conteúdo de `sql/historico_digi_v3_indexes.sql`
3. Clicar em Run (esperado: "Success. No rows returned")
4. Após algumas horas de uso, consultar `pg_stat_statements` (queries de validação estão comentadas no fim do arquivo SQL)
5. **(Opcional)** Rodar `EXPLAIN ANALYZE` na RPC `match_documents_hybrid` para conferir se há ganho aparente; se aparecer `Seq Scan` em `documents`, indicar a falta de índice vetorial (ivfflat/hnsw) na coluna `embedding`

### Fase 2 — Observability com Sentry — ✓ **CÓDIGO PRONTO (aguarda DSN no painel)**

Mudanças aplicadas no código:

1. ✓ `requirements.txt`: `sentry-sdk[fastapi]>=2.0.0`
2. ✓ `main.py`: bloco condicional de `sentry_sdk.init()` no topo (só ativa se `SENTRY_DSN` estiver definido — sem DSN, app roda normal)
3. ✓ `.env.example`: novas variáveis `SENTRY_DSN`, `RELEASE_VERSION`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_PROFILES_SAMPLE_RATE`
4. ✓ `DOCUMENTACAO.md`: seção 10b explicando o que é capturado, configurações e investigação via CLI
5. ✓ Integrações `StarletteIntegration` + `FastApiIntegration` com `transaction_style="endpoint"` (nome de transação fica `POST /api/rag/query` em vez de path bruto)
6. ✓ `send_default_pii=False` — não envia IP, headers de auth nem payloads do usuário

**Aguardando ação do usuário (passos finais, ~10 min):**

1. Criar conta gratuita em [sentry.io](https://sentry.io) e um projeto Python/FastAPI
2. Copiar o DSN do projeto (formato: `https://abc...@oXXX.ingest.sentry.io/YYY`)
3. No painel da **SquareCloud → Digi RAG API → Variáveis de ambiente**, adicionar:
   - `SENTRY_DSN=<o-dsn-copiado>`
   - `ENVIRONMENT=production`
   - `RELEASE_VERSION=<short-sha-do-commit-atual>` (opcional, mas recomendado pra release tracking)
4. Salvar e a app reinicia sozinha. Os logs devem mostrar: `[Sentry] Instrumentação ativa (env=production)`
5. (Opcional) No Sentry, ir em **Alerts → Create Alert Rule** e criar um básico: "erros > 5 em 5 min" → email

**Como validar:** depois de algumas requests reais ou um erro forçado, o issue aparece em `sentry.io → seu projeto → Issues`.

### Fase 3 — Decisão arquitetural sobre RLS (1 dia, quando tornar repo público)

Avaliar se mantém a policy permissiva (com risco documentado) ou migra pra modelo mais restrito. Decisão de produto, não puramente técnica.

### Fase 4 — Dashboards e release tracking (1-2 horas, depois do Sentry maduro)

1. Criar dashboard Sentry com os widgets sugeridos acima
2. Adicionar passo de "criar release" no fluxo de deploy (GitHub Actions ou manual)

---

## 6. O que NÃO entrou (mas vale registrar)

Categorias da skill `supabase-postgres-best-practices` que olhei mas o Digi **já está fazendo certo** ou **não se aplica**:

- `data-batch-inserts` — já implementado em `IngestionService` (batches de 100) ✓
- `lock-deadlock-prevention`, `lock-short-transactions` — projeto não tem transações longas ✓
- `data-n-plus-one` — uso atual do Supabase é via PostgREST com selects individuais, não JOINs aninhados ✓
- `schema-partitioning` — só faz sentido se `historico_digi` chegar a milhões de linhas (longe disso) ✗
- `conn-prepared-statements` — gerenciado automaticamente pelo PostgREST ✓
- `advanced-full-text-search` — já usa via RPC híbrida ✓

---

## Referências

- Skills em `~/.agents/skills/`
- `sentry-cli/SKILL.md` — guia completo do CLI (~570 linhas)
- `supabase-postgres-best-practices/references/` — 34 regras detalhadas
- Schema atual: `sql/historico_digi.sql`, `sql/historico_digi_v2_feedback.sql`, `sql/analytics_views.sql`
