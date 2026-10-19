from hmac import compare_digest

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from src.config import Settings, get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    supplied_key: str | None = Security(api_key_header),
    config: Settings = Depends(get_settings),
) -> None:
    """Protect private API routes with a constant-time token comparison.

    Authentication may be omitted only in non-production environments when no
    token is configured. Production settings fail fast without API_AUTH_TOKEN.
    """

    configured = config.api_auth_token
    if configured is None and config.environment != "production":
        return

    if configured is None or supplied_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )

    if not compare_digest(supplied_key, configured.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )
