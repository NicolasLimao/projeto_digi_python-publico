# RAG Implementation - 100% Python

## Visão Geral

O Digi implementa um sistema **RAG (Retrieval-Augmented Generation) 100% em Python**, sem dependência de workflows n8n. O sistema processa perguntas de analistas através de um pipeline completo:

```
Discord DM → FastAPI Endpoint → Classification → Scope Validation → 
Vector Search → LLM Response → Formatting → History Save → Discord Response
```

## Arquitetura

### Componentes Principais

#### 1. **Services** (`src/services/`)

**OpenAIService** - Integração com APIs OpenAI
- `classify(query)` - Classifica pergunta em: `orientacao`, `resposta-cliente`, `bug`
- `validate_scope(query)` - Valida se pergunta é sobre Digisac
- `get_embeddings(text)` - Gera embeddings usando `text-embedding-3-small`
- `generate_response(query, chunks, mode)` - Gera resposta com RAG
- `format_response(response, mode)` - Formata resposta por modo
- **Mock fallback**: Se sem API key, usa implementação mock local

**SupabaseService** - Busca vetorial em Supabase
- `search_hybrid(embedding, query, k)` - Busca pgvector com score
- `save_document(content, embedding, metadata)` - Salva documento com embedding
- `get_document(doc_id)` - Recupera documento por ID
- **Mock fallback**: Sem Supabase, retorna dados mock

**HistoryService** - Persistência de histórico
- `save_interaction()` - Salva pergunta/resposta em Supabase
- `get_recent_history()` - Recupera histórico do usuário
- `format_history_for_prompt()` - Formata para injeção no prompt
- `clear_old_history()` - Limpeza automática de histórico antigo

#### 2. **Agents** (`src/agents/`)

**ClassifierAgent**
- Classifica query usando OpenAIService
- Saída: modo (`orientacao` | `resposta-cliente` | `bug`)

**ScopeValidatorAgent**
- Valida se query está dentro do escopo
- Saída: `{dentro_do_escopo: bool, motivo?: string}`

**RAGAgent** ⭐ (Novo)
- Orquestra retrieval + generation
- Etapas:
  1. Obter embeddings da query
  2. Buscar documentos similares em Supabase
  3. Filtrar por score_threshold
  4. Gerar resposta com contexto
  5. Retornar resultado com metadata
- Saída: `{response, score, chunks_used, documents}`

**FormatterAgent** ⭐ (Novo)
- Formata resposta baseado no modo
- `orientacao`: bullet points
- `resposta-cliente`: texto pronto para WhatsApp
- `bug`: análise estruturada de erro

#### 3. **Pipeline** (`src/pipeline/`)

**RAGPipeline** ⭐ (Novo)
- Orquestra fluxo completo:
  1. ClassifierAgent → detecta modo
  2. ScopeValidatorAgent → valida escopo
  3. RAGAgent → busca + geração (se em escopo)
  4. FormatterAgent → formata resposta
  5. HistoryService → salva interação
  6. Retorna QueryResponse
- Tratamento de erros em cada etapa
- Medição de tempo de processamento

#### 4. **API** (`src/api/`)

**RAG Endpoint**
```
POST /api/rag/query
Query params: user_id (obrigatório)
Body: {
  "query": "sua pergunta",
  "mode": "orientacao" (opcional)
}

Response: QueryResponse {
  "response": "resposta formatada",
  "mode": "orientacao",
  "score": 0.85,
  "chunks_used": 2,
  "processing_time_ms": 150
}
```

**History Endpoints** (existentes)
- `POST /api/history/save` - Salva interação
- `POST /api/history/context` - Obtem histórico formatado
- `GET /api/history/user/{user_id}` - Lista histórico do usuário
- `DELETE /api/history/cleanup` - Limpeza de histórico antigo

## Fluxo de Execução

### Request DM → Response

```
1. Analyst envia DM no Discord
   ↓
2. dm_handler.py recebe mensagem
   ↓
3. POST /api/rag/query com:
   - query: mensagem do analista
   - user_id: Discord user ID
   ↓
4. RAGPipeline.process():
   a. ClassifierAgent.execute() → modo
   b. ScopeValidatorAgent.execute() → validação
   c. Se fora de escopo → resposta padrão
   d. Se em escopo:
      - RAGAgent.execute() → busca + geração
      - FormatterAgent.execute() → formatação
   e. HistoryService.save_interaction() → persistência
   f. Retorna QueryResponse
   ↓
5. dm_handler recebe resposta
   ↓
6. Envia reply no Discord DM
```

### Detalhamento do RAGAgent

```
RAGAgent.execute(query, mode):
  1. embedding = OpenAIService.get_embeddings(query)
  2. documents = SupabaseService.search_hybrid(
       embedding=embedding,
       query=query,
       k=min(5, MAX_CHUNKS),
       score_threshold=0.65
     )
  3. Se len(documents) == 0:
       response = "Desculpe, não encontrei informações..."
       score = 0.0
     Senão:
       response = OpenAIService.generate_response(
         query=query,
         chunks=documents,
         mode=mode
       )
       score = avg(doc.score for doc in documents)
  4. response = OpenAIService.format_response(response, mode)
  5. Retorna: {response, mode, score, chunks_used, documents}
```

## Configuração

### Variáveis de Ambiente

```env
# OpenAI
OPENAI_API_KEY=replace-with-your-key  # Obrigatório para modo real

# Supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=xxxx        # Obrigatório para modo real

# RAG API
RAG_API_URL=http://localhost:8000/api/rag/query  # Para Discord DM

# Discord
DISCORD_BOT_TOKEN=xxxx
DISCORD_GUILD_ID=xxx
DISCORD_CHANNEL_DUVIDAS=xxx
DISCORD_CHANNEL_LOGS=xxx
DISCORD_CHANNEL_GAPS=xxx
DISCORD_DM_ENABLED=true

# História
HISTORY_ENABLED=true
HISTORY_RETENTION_DAYS=90

# App
LOG_LEVEL=INFO
SCORE_THRESHOLD=0.65      # Mínimo para retornar documento
MAX_CHUNKS=10             # Máximo de chunks por query
```

### Setup Local (Sem APIs Real)

```bash
# 1. Clonar e instalar em ambiente virtual
git clone <repo>
cd projeto_digi_python
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock

# 2. Health checks e testes funcionam sem credenciais externas.
# Para consultar o RAG, configurar credenciais reais na .env.

# 3. Rodar servidor
python main.py
# Acessa em http://localhost:8000/docs

# 4. Rodar testes
python -m pytest tests/ -v
```

### Setup Production (Com APIs Real)

```bash
# 1. Provisionar o banco conforme db/migrations/, na ordem numérica.
# A busca usada pelo projeto é match_documents_hybrid.

# 2. Configurar .env a partir de .env.example, sem versionar segredos.
# Usar SUPABASE_SERVICE_ROLE_KEY no backend; acesso público não deve ser restaurado.
# Configurar também OPENAI_API_KEY, API_AUTH_TOKEN e USER_ID_SALT.

# 3. Execução Python:
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python main.py

# Dashboard em outro terminal, com o mesmo ambiente virtual:
python -m pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501
```

## Testes

### Cobertura de Testes

| Componente | Tests | Status |
|---|---|---|
| OpenAIService | 11 | ✅ PASS |
| SupabaseService | 8 | ✅ PASS |
| RAGAgent | 10 | ✅ PASS |
| FormatterAgent | 13 | ✅ PASS |
| RAGPipeline | 14 | ✅ PASS |
| RAG Routes (API) | 10 | ✅ PASS |
| History Service | 6 | ✅ PASS |
| Integration DM | 4 | ✅ PASS |
| **TOTAL** | **79** | **✅ PASS** |

### Rodar Testes

```bash
# Todos os testes
python -m pytest tests/ -v

# Um arquivo específico
python -m pytest tests/agents/test_rag_agent.py -v

# Com cobertura
python -m pytest tests/ --cov=src --cov-report=html
```

## Performance

### Latência Típica

| Operação | Tempo |
|---|---|
| Classificação | 200-500ms |
| Validação de escopo | 200-500ms |
| Get embeddings | 100-300ms |
| Vector search | 50-200ms |
| LLM generation | 1-3s |
| Formatação | <50ms |
| Histórico save | <100ms |
| **Total e2e** | **2-5s** |

### Otimizações

- Caching de embeddings (todo)
- Batch processing de queries (todo)
- Connection pooling com Supabase
- Async/await em todas as operações

## Troubleshooting

### "No Supabase client" Warning

**Causa**: `SUPABASE_URL` ou `SUPABASE_ANON_KEY` não configuradas

**Solução**: Adicionar em `.env` ou usar dados mock

### "No API key" Warning

**Causa**: `OPENAI_API_KEY` não configurada

**Solução**: Adicionar chave válida em `.env` ou usar dados mock

### Score sempre 0

**Causa**: Nenhum documento encontrado no vector search

**Solução**:
- Verificar se tabela `documents` existe em Supabase
- Verificar se há documents com embedding compatível
- Verificar SCORE_THRESHOLD (padrão 0.65)

### Discord DM não funciona

**Causa**: RAG_API_URL incorreta ou servidor não rodando

**Solução**:
```bash
# 1. Verificar servidor está rodando
curl http://localhost:8000/health

# 2. Verificar RAG_API_URL em .env
# Deve ser http://localhost:8000/api/rag/query (local)
# ou endereço do server (produção)

# 3. Verificar logs do bot Discord
```

## Próximas Melhorias

- [ ] Semantic search na history (MMR)
- [ ] Automatic scheduled cleanup
- [ ] Conversation summarization
- [ ] Analytics dashboard
- [ ] User feedback loop (thumbs up/down)
- [ ] A/B testing de prompts
- [ ] Custom knowledge bases por workspace
- [ ] Multilingual support

## Referências

- OpenAI API: https://platform.openai.com/docs
- Supabase Vector Search: https://supabase.com/docs/guides/database/vector
- FastAPI: https://fastapi.tiangolo.com/
- Discord.py: https://discordpy.readthedocs.io/

---

**Status**: Production-ready (com modo mock fallback para testing)
**Última atualização**: 2026-05-21
**Versão**: 1.0.0
