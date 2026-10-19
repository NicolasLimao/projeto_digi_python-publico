# DM History Feature Documentation

## Overview

The DM History feature enables Digi to remember recent conversations with each analyst, providing context-aware responses based on their interaction history stored in Supabase.

## Architecture

```
Discord DM → n8n Webhook
           ↓
      [Fetch History] → Supabase historico_digi table
           ↓
    [Format Context] → Inject into prompt
           ↓
      [Digi RAG Agent] → Generate response
           ↓
      [Save to History] → Store in Supabase
           ↓
      Response → Discord DM
```

## Database Schema

### historico_digi Table

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | TEXT | Discord user ID |
| pergunta | TEXT | User's question |
| resposta | TEXT | Digi's response |
| modo | TEXT | Response mode (orientacao, resposta-cliente, bug) |
| score | FLOAT | Vector similarity score (0-1) |
| chunks_used | INT | Number of KB chunks used |
| processing_time_ms | INT | Response generation time |
| timestamp | TIMESTAMP | When interaction occurred |

**Indexes:**
- `idx_historico_user_id` on (user_id, timestamp DESC) - Fast user lookups
- RLS enabled for security

**Constraints:**
- modo: CHECK (orientacao | resposta-cliente | bug)
- score: CHECK (0 <= score <= 1)

## Python API

### HistoryService

Located in `src/services/history_service.py`

```python
service = HistoryService(supabase_client)

# Save interaction
await service.save_interaction(
    user_id="discord_id",
    pergunta="Como fazer backup?",
    resposta="Acesse Configurações > Backup",
    modo="resposta-cliente",
    score=0.85,
    chunks_used=2,
    processing_time_ms=450
)

# Get recent history
history = await service.get_recent_history(user_id="discord_id", limit=5)

# Format for prompt injection
context = await service.format_history_for_prompt(user_id="discord_id", limit=5)
```

### REST API Endpoints

#### POST `/api/history/save`
Save a conversation interaction.

Query params: user_id, pergunta, resposta, modo, score, chunks_used, processing_time_ms

Response: `{"id": "entry_id", "status": "saved"}`

#### POST `/api/history/context`
Get formatted history context for prompt injection.

Request body:
```json
{
  "user_id": "discord_id",
  "limit": 5
}
```

Response:
```json
{
  "formatted_context": "HISTÓRICO RECENTE...",
  "entry_count": 5,
  "oldest_timestamp": "2026-05-15T10:30:00"
}
```

#### GET `/api/history/user/{user_id}`
Get raw history entries for a user.

Query params: limit (default: 10)

Response: List of HistoryEntry objects

#### DELETE `/api/history/cleanup`
Delete history older than N days.

Query params: days_to_keep (default: 30)

Response: `{"deleted_count": 42, "status": "completed"}`

## Discord Integration

### DM Handler

Located in `discord/dm_handler.py`

Setup in your bot:
```python
from discord.dm_handler import setup_dm_handler

setup_dm_handler(bot)
```

This enables the bot to:
1. Listen for incoming DMs from analysts
2. Extract message content
3. Route to n8n webhook
4. Send response back to DM

### Environment Variables

```env
DISCORD_BOT_TOKEN=your_token
N8N_WEBHOOK_RAG_URL=http://localhost:5678/webhook/digi-rag-dm
DISCORD_DM_ENABLED=true
HISTORY_ENABLED=true
HISTORY_RETENTION_DAYS=90
```

## n8n Workflow Integration

Workflow 3 (RAG) has been updated to:

1. **Fetch History Node** (HTTP Request)
   - URL: `http://localhost:8000/api/history/context`
   - Retrieves last 5 interactions for analyst
   - Returns formatted context

2. **Inject into Prompt**
   - Digi RAG agent receives: `{{ history_context }} + {{ current_query }}`
   - Enables context-aware responses

3. **Save History Node** (HTTP Request)
   - URL: `http://localhost:8000/api/history/save`
   - Saves interaction after response generated
   - Tracks score, chunks, processing time

## Testing

### Unit Tests

HistoryService methods:
```bash
pytest tests/services/test_history_service.py -v
```

Results: 6/6 tests pass

### API Tests

Endpoint validation:
```bash
pytest tests/api/test_history_routes.py -v
```

Results: 4/4 tests pass

### Integration Tests

End-to-end flow:
```bash
pytest tests/integration/test_dm_history_flow.py -v
```

Tests:
- Full DM history flow (fetch → generate → save)
- Multi-user isolation
- Context injection
- Save & retrieve cycle

Results: 4/4 tests pass

## Monitoring

Track these metrics in #logs-agente channel:
- Queries with history context (vs without)
- Average history depth per user
- Database query latency for history fetch
- Failed history saves
- Processing time with vs without history

## Performance Considerations

- History fetch: ~100ms (with proper indexing)
- Formatting: <50ms
- Save: async, doesn't block response
- Storage: ~500 bytes per interaction
- At 100 analysts × 50 entries: ~25MB

## Known Limitations

- History is lost if Supabase table is dropped (backup with migrations)
- No automatic cleanup (use DELETE /cleanup endpoint periodically)
- Search within history not implemented yet
- Maximum history per user: 50 (configurable)

## Future Improvements

- [ ] Semantic search within user history
- [ ] Automatic cleanup scheduled task
- [ ] History export/backup functionality
- [ ] Analytics dashboard for conversation patterns
- [ ] Privacy controls per user
- [ ] Conversation summarization (compress old history)
- [ ] Multi-workspace history isolation

## Troubleshooting

### History not saving
- Check N8N webhook URL in .env
- Verify Supabase table exists: `SELECT COUNT(*) FROM historico_digi;`
- Check API error logs

### History not fetching
- Verify user_id matches Discord user ID
- Check N8N POST endpoint returns 200
- Verify history exists: `SELECT * FROM historico_digi WHERE user_id='xxx';`

### DM not working
- Verify `DISCORD_DM_ENABLED=true` in .env
- Check bot has DM permissions
- Verify `setup_dm_handler(bot)` called in bot.py
- Check Discord bot intents: `discord.Intents.all()`
