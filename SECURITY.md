# Security policy

Report suspected vulnerabilities privately to the repository owner. Do not open a public issue containing credentials, conversation data, exploit payloads, or production identifiers.

## Deployment checklist

1. Set `ENVIRONMENT=production`.
2. Generate a long random `API_AUTH_TOKEN` and send it as `X-API-Key` from the bot.
3. Configure `SUPABASE_SERVICE_ROLE_KEY`; never ship it to a browser or Discord client.
4. Apply `db/migrations/002_harden_api_data.sql` before switching the API to service-role access.
5. Restrict `TRUSTED_HOSTS`, keep CORS empty unless a browser client is required, and allow only exact origins.
6. Keep `INGEST_ALLOWED_HOSTS` limited to trusted attachment CDNs.
7. Run the quality and security commands documented in `AGENTS.md`.

Configure a secret `USER_ID_SALT` before storing conversation history. Production with history enabled rejects missing or whitespace-only salt. Keep it stable across deployments so existing pseudonymized history remains accessible.

Jev is disabled by default. Active modes require `TYPESAFE_API_KEY`; enforcement additionally requires a declaration of calibrated criteria. Never expose provider credentials or log prompts/upstream bodies. Explicit authenticated `curated=true` is required to assign curation authority; ordinary content and attachments cannot self-promote. Audit historical curation provenance before a live pilot. See [Jev operations](docs/JEV_OPERACAO.md).

The Streamlit dashboard is a local tool without application login. Its project configuration binds to `127.0.0.1`. It uses backend credentials from the local `.env`.

Rotate a secret immediately if it appears in logs, commits, screenshots, support tickets, or chat history.
