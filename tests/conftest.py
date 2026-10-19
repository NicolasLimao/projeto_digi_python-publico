import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.pop("API_AUTH_TOKEN", None)
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_ANON_KEY", None)
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
for name in list(os.environ):
    if name.startswith("TYPESAFE_") or name in {"RERANK_PROVIDER", "RERANK_FULL_CONTEXT"}:
        os.environ.pop(name, None)

from src.config import (  # noqa: E402 -- sanitize environment before settings load
    Settings,
    get_settings,
)

# Tests must not read the developer's local .env; only explicit kwargs and
# the sanitized os.environ above may configure Settings during the suite.
Settings.model_config["env_file"] = None
get_settings.cache_clear()
