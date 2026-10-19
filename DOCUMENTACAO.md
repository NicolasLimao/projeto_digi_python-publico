# Digi — Documentação Técnica (como funciona)

Agente de IA com **RAG** (Retrieval-Augmented Generation) para suporte interno dos analistas N1 da Digisac. Responde dúvidas técnicas via Discord, consultando uma base de conhecimento vetorial.

> **Em uma frase:** o Digi pega a pergunta → busca os trechos mais relevantes da documentação da Digisac → e pede pro GPT escrever a resposta usando só esses trechos. Assim ele responde com base na documentação real, não em "achismo".

> 📦 **Este repositório contém apenas a API (Python).** O bot do Discord (Node) vive em [github.com/NicolasLimao/digi-bot](https://github.com/NicolasLimao/digi-bot).

---

## 1. Visão geral

- **Frontend:** bot do Discord (Node.js) — recebe perguntas e devolve respostas. Repo: [digi-bot](https://github.com/NicolasLimao/digi-bot).
- **Backend:** API em Python (FastAPI) — faz todo o trabalho de IA. (este repositório)
- **Banco:** Supabase (Postgres + pgvector) — guarda a documentação vetorizada e o histórico.
- **IA:** OpenAI — gera os *embeddings* (vetores) e escreve as respostas.

Tudo que era feito no n8n foi reescrito em **Python puro**.

---

## 2. Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                     DISCORD (analistas N1)                    │
│            #suporte-duvidas   ·   DM privada                  │
└───────────────────────────┬───────────────────────────────────┘
                            │  bot.js (Node, no WSL)
                            │  POST /api/rag/query
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  API PYTHON — FastAPI (main.py)              │
│                                                               │
│   rag_routes.py  ──►  RAGPipeline (orquestrador)             │
│                                                               │
│   ┌──────────── em paralelo (asyncio) ────────────┐          │
│   │  Classifier   ScopeValidator      RAGAgent     │          │
│   │  (modo)       (no escopo?)        .retrieve()   │          │
│   └─────────────────────────────────────┬──────────┘          │
│                                          ▼                     │
│                            RAGAgent.generate() (resposta)      │
│                                          │                     │
│                            HistoryService.save()               │
└───────────────┬──────────────────────────────┬────────────────┘
                │                              │
                ▼                              ▼
      ┌──────────────────┐          ┌────────────────────┐
      │     OpenAI       │          │     Supabase       │
      │ embeddings + LLM │          │ pgvector + tabelas │
      └──────────────────┘          └────────────────────┘
```

---

## 3. Stack / tecnologias

| Camada | Tecnologia |
|--------|-----------|
| Bot | Node.js + discord.js v14 |
| API | Python + FastAPI + Uvicorn |
| Validação de dados | Pydantic |
| Embeddings | OpenAI `text-embedding-3-small` (1536 dimensões) |
| Geração (LLM) | OpenAI `gpt-4o-mini` |
| Banco vetorial | Supabase (Postgres + extensão pgvector) |
| Busca | função RPC `match_documents_hybrid` (semântica + texto) |

---

## 4. O fluxo de uma pergunta (o coração do sistema)

Quando um analista manda uma pergunta, isto acontece:

**1. Discord → bot.js**
O bot escuta o canal `#suporte-duvidas` e as DMs. Ao receber, chama a API:
`POST /api/rag/query?user_id=<id>&canal=<dm|canal>` com `{ "query": "..." }`

**2. API → RAGPipeline** (`src/pipeline/rag_pipeline.py`)
O orquestrador roda o pipeline:

  **2.1 — Histórico:** busca as últimas 4 trocas daquele usuário (janela de 60 min) e formata pra injetar no prompt. É o que dá **memória** à conversa.

  **2.2 — Três tarefas EM PARALELO** (`asyncio.gather`):
  - **Classificar** o modo: `orientacao`, `resposta-cliente` ou `bug`
  - **Validar escopo:** a pergunta é sobre a Digisac? (na dúvida, sim)
  - **Recuperar** (`RAGAgent.retrieve`):
    1. **Reescreve a query** (se for longa/ambígua ou tiver histórico) → tira ruído e resolve referências ("isso", "ele")
    2. Gera o **embedding** da query
    3. **Busca híbrida** no Supabase → traz 15 candidatos
    4. **Rerank** → reordena por relevância e fica com os 10 melhores

  *(Rodar tudo junto economiza tempo: a classificação acontece "embaixo" da busca.)*

  **2.3 — Fora do escopo?** Se sim, responde com uma mensagem de encaminhamento e para aqui.

  **2.4 — Gerar resposta** (`RAGAgent.generate`):
  Manda pro GPT: o **prompt do Digi** + os **10 trechos** + o **histórico** + o **modo**. O GPT escreve a resposta usando os trechos como fonte.

  **2.5 — Salvar:** grava a interação (pergunta, resposta, score, modo, canal, fontes, query reescrita) na tabela `historico_digi` e devolve um `interaction_id`.

**3. bot.js → Discord**
O bot posta a resposta e adiciona as reações **✅ / ❌**, guardando o vínculo `mensagem → interaction_id`.

**4. Feedback**
Quando o analista reage ✅ ou ❌, o bot chama `POST /api/rag/feedback` e o banco registra `positivo`/`negativo` naquela interação.

---

## 5. Componentes detalhados

### `bot.js` (Discord, Node)
- Escuta 3 origens: canal de ingestão (envia docs pro n8n), `#suporte-duvidas` e DMs.
- `handleRagQuery()` — função única que chama a API e responde (usada por canal e DM).
- `messageReactionAdd` — captura o 👍/👎 e envia pro endpoint de feedback.
- Usa `Partials.Channel/Reaction` (necessário pra receber eventos de DM no discord.js v14).

### `main.py`
Sobe o FastAPI e registra as rotas (`rag_routes`, `history_routes`). Endpoint de saúde em `/health`.

### `src/config.py`
Carrega as variáveis do `.env` via Pydantic Settings: chaves de API, salt para pseudonimização e parâmetros como `score_threshold` (0.30), `max_chunks` (10), `history_enabled`.

### `src/api/rag_routes.py`
- `POST /api/rag/query` — recebe a pergunta, monta as dependências (injeção de dependência do FastAPI) e chama o pipeline.
- `POST /api/rag/feedback` — grava o 👍/👎.

### `src/pipeline/rag_pipeline.py`
O **orquestrador**. Coordena classificação, validação, recuperação, geração e gravação. É aqui que está a paralelização (`asyncio.gather`).

### `src/agents/` (padrão "agente": cada um faz uma coisa)
- `base.py` — classe base `Agent` (logger + `execute`).
- `classifier.py` — decide o **modo** da pergunta.
- `scope_validator.py` — decide se está **dentro do escopo** da Digisac.
- `rag_agent.py` — o núcleo do RAG. Dividido em:
  - `retrieve()` — reescrita → embedding → busca → rerank (não precisa do modo)
  - `generate()` — monta o contexto e chama o LLM (precisa do modo)
- `formatter_agent.py` — hoje é *passthrough* (a formatação é controlada pelo prompt, não por pós-processamento).

### `src/services/openai_service.py`
Toda a conversa com a OpenAI:
- `classify()` / `validate_scope()` — classificação e escopo
- `get_embeddings()` — transforma texto em vetor (1536 números)
- `rewrite_query()` — limpa/expande a query pra busca (e resolve referências usando o histórico)
- `rerank()` — reordena os trechos por relevância real
- `generate_response()` — monta o **prompt do Digi** e gera a resposta
- `format_response()` — passthrough

### `src/services/supabase_service.py`
- `search_hybrid()` — chama a RPC `match_documents_hybrid` (busca semântica + texto, pesos 0.5/0.5) e filtra por score.
- `save_document()` — salva chunks na ingestão.

### `src/services/history_service.py`
- `save_interaction()` — grava cada pergunta/resposta + metadados.
- `get_recent_history()` / `format_history_for_prompt()` — leem o histórico recente pra dar **memória**.
- `update_feedback()` — grava o 👍/👎.

### `src/models/schemas.py`
Modelos Pydantic (contratos de dados): `QueryRequest`, `QueryResponse`, `FeedbackRequest`, `HistoryEntry`, `Document`, etc.

---

## 6. Os 3 modos de resposta

O Digi adapta o **tom e o formato** ao que foi pedido:

| Modo | Quando | Como responde |
|------|--------|---------------|
| **orientacao** | Analista quer entender/executar algo | Tom técnico de colega, bullets ou passos, pode citar processos internos |
| **resposta-cliente** | Texto pronto pro cliente final | Tom cordial e confiante, "fala como Digisac", sem expor processos internos |
| **bug** | Relato de comportamento inesperado | Causa provável (se houver) + checklist do que investigar |

Gatilho de `resposta-cliente`: a mensagem começa com **"Dúvida do cliente -"** ou similar.

---

## 7. Conceitos-chave explicados

**RAG (Retrieval-Augmented Generation)**
Em vez de confiar na "memória" do GPT (que pode inventar), o sistema **busca** os trechos certos na base e **aumenta** o prompt com eles. O GPT só redige usando essa fonte. Resultado: respostas baseadas na documentação real da Digisac.

**Embedding**
Um texto vira um vetor de 1536 números que representa seu *significado*. Textos parecidos têm vetores próximos. É assim que a busca "entende" a pergunta além das palavras exatas.

**Busca híbrida**
Combina dois tipos de busca: **semântica** (por significado, via embedding) + **full-text** (por palavra-chave). Pega o melhor dos dois (peso 0.5 / 0.5).

**Reescrita de query**
A mensagem crua ("Dúvida do cliente - ... Obs.1 ... Obs.2") tem ruído. Antes de buscar, o sistema extrai só a **intenção** ("disparo de webhook com conteúdo da mensagem"). Em follow-ups, usa o histórico pra resolver "isso/ele".

**Rerank**
A busca traz 15 candidatos; o rerank os reordena por relevância real e mantém os **10 melhores**. Reduz ruído e melhora a qualidade do contexto.

**Memória multi-turno**
Cada usuário tem seu histórico. As últimas trocas são injetadas no prompt, então follow-ups ("e como faço isso?") funcionam. Isolado por usuário.

**Loop de feedback**
Cada 👍/👎 é salvo. Vira **rótulo** pra medir qualidade (taxa de aprovação) e achar **gaps** (perguntas que falharam → documentação a melhorar).

---

## 8. Banco de dados (Supabase)

| Tabela / objeto | Função |
|-----------------|--------|
| `documents` | Chunks da documentação + embedding (a base de conhecimento) |
| `match_documents_hybrid` (RPC) | Função SQL que faz a busca híbrida |
| `historico_digi` | Cada interação: pergunta, resposta, modo, score, chunks, canal, fontes, pergunta_reescrita, **feedback** |
| Views `v_feedback_resumo`, `v_negativos`, etc. | Analytics (aprovação %, gaps, volume) |

---

## 9. Como rodar

**Servidor RAG (Python):**
**API (este repositório):**
```bash
pip install -r requirements.txt
python main.py          # sobe a API em http://localhost:8000
```

**Bot do Discord** ([repo separado](https://github.com/NicolasLimao/digi-bot)):
```bash
npm install
npm start               # conecta no Discord e chama a API
```

O bot só responde com a API Python no ar (`RAG_API_URL` apontando pra ela).

**Variáveis (`.env`):** chaves OpenAI/Supabase/Discord + `SCORE_THRESHOLD`, `MAX_CHUNKS`, `HISTORY_ENABLED`.

---

## 9b. Deploy na SquareCloud

Cada um dos dois repos sobe como uma app separada:

**API Python** (este repo):
- Arquivo `squarecloud.app` já configurado (`MAIN=main.py`, `SUBDOMAIN=digi-api`, 512 MB RAM)
- `requirements.txt` na raiz (a SquareCloud instala automaticamente)
- Variáveis no painel: `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `DISCORD_GUILD_ID`, `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_DUVIDAS`, `DISCORD_CHANNEL_LOGS`, `DISCORD_CHANNEL_GAPS`, `SCORE_THRESHOLD`, `MAX_CHUNKS`, `HISTORY_ENABLED`
- URL pública: `https://digi-api.squarecloud.app` (o subdomínio definido no config)

**Bot Node** ([digi-bot](https://github.com/NicolasLimao/digi-bot)):
- `squarecloud.app` configurado (`MAIN=bot.js`, 256 MB RAM)
- Variáveis no painel: `DISCORD_BOT_TOKEN`, `RAG_API_URL=http://localhost:8000/api/rag/query`
- Sem subdomínio (o bot só faz outbound — conecta no Discord via WebSocket)

Sobe a **API primeiro** (precisa estar no ar pro bot conseguir chamar), depois o bot.

---

## 10b. Observabilidade (Sentry)

A API tem instrumentação opcional via [Sentry](https://sentry.io). O setup é
condicional: só ativa se a variável `SENTRY_DSN` estiver definida no ambiente.
Sem ela, a app roda normalmente sem reportar nada.

**O que é capturado quando ativo:**
- Exceções não tratadas (com stack trace, request context, etc.)
- Traces de performance (por endpoint, com 10% de amostragem)
- Profiles de CPU (10% de amostragem)
- Logs estruturados

**Não é enviado:**
- Dados do usuário (`send_default_pii=False`) — IPs, headers de auth, payloads
  ficam fora

**Variáveis relevantes (no painel da SquareCloud):**

| Variável | Função |
|----------|--------|
| `SENTRY_DSN` | DSN do projeto Sentry. Sem ela, instrumentação fica off |
| `RELEASE_VERSION` | Tag de release (ex.: short SHA). Liga issues a commits |
| `SENTRY_TRACES_SAMPLE_RATE` | Padrão `0.1` (10%). Controla cota do free tier |
| `SENTRY_PROFILES_SAMPLE_RATE` | Padrão `0.1` |

**Investigação via CLI** (skill `sentry-cli` instalada):
- `sentry issue list --query "is:unresolved"` — issues abertas
- `sentry issue view DIGI-RAG-1` — detalhes
- `sentry issue explain DIGI-RAG-1` — análise de causa raiz por IA

---

## 11. Ingestão de documentos (sem n8n)

A ingestão é feita pela **própria API Python** — o n8n foi aposentado neste fluxo.

**Fluxo:**
1. Analista posta texto ou anexa PDF no canal `#alimentar-base`
2. `bot.js` responde com `📥 Recebido, processando...` e chama `POST /api/ingest`
3. `IngestionService` faz tudo:
   - Baixa anexo (Discord CDN)
   - Extrai texto: **PyMuPDF** primeiro (PDFs com texto selecionável, rápido e grátis); fallback **Mistral OCR** se vazio (PDFs imagem)
   - Chunka por parágrafos (~1.000 chars por chunk, semântico)
   - Gera embeddings em **batch** (uma chamada OpenAI por ~100 chunks)
   - Insere em batch no Supabase (`documents`) usando a chave **service_role** (sem timeout de 8s da anon)
4. Bot **edita** a mensagem inicial para `✅ Ingestão concluída em Ys / N chunks criados / fontes...`

**Uma única mensagem visível por ingestão** — evita o rate limit do Discord (5 msgs/5s/canal).

**Variáveis necessárias na API:**
- `SUPABASE_SERVICE_ROLE_KEY` — pra inserts pesados sem o timeout da anon
- `MISTRAL_API_KEY` — só usada se PyMuPDF retornar vazio (PDFs imagem/escaneados)

**Tipos suportados hoje:** PDF (`application/pdf`), texto puro (`.txt`, `.md`). Outros tipos retornam aviso e são ignorados.

---

## 10. Decisões de design (o "porquê")

- **Prompt genérico, não tunado por pergunta:** o diferencial do Digi pra um GPT comum é a *contextualização total da Digisac* + autonomia de raciocínio — não regras rígidas. Ele adapta a resposta ao que foi pedido ("resumido" → curto, "passo a passo" → numerado).
- **Formatação controlada pelo prompt** (não por pós-processamento): por isso o `FormatterAgent` virou passthrough.
- **Paralelização:** classificar + validar + recuperar rodam juntos → ~34% menos latência, sem perder qualidade.
- **Score ≠ qualidade:** o score da busca (~0.30) é só relevância de recuperação. A métrica de qualidade real é o **feedback 👍/👎**.
- **O teto de qualidade é a recuperação:** se o trecho certo não está na base, nenhum prompt salva. Por isso o foco em busca híbrida, reescrita, rerank — e o loop de gaps via feedback.

---

*Documento gerado para estudo e apresentação do projeto Digi.*
