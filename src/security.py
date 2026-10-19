"""Pseudonimização de identificadores (ex.: user_id do Discord) para não persistir PII."""

import hashlib
import hmac
import re

_ID_DISCORD = re.compile(r"\d{15,20}")


def pseudonimizar_user_id(user_id: str, salt: str) -> str:
    """HMAC-SHA256 (hex) do user_id com um salt secreto. Determinístico e
    irreversível sem o salt — usado porque IDs do Discord são enumeráveis."""
    return hmac.new(salt.encode("utf-8"), user_id.encode("utf-8"), hashlib.sha256).hexdigest()


def _e_id_discord_cru(valor: str) -> bool:
    """True se `valor` parece um ID cru do Discord (snowflake numérico), não um hash."""
    return bool(_ID_DISCORD.fullmatch(valor or ""))
