"""Um-off: hasheia os user_id crus já existentes em historico_digi.
Re-executável (pula o que já é hash). Rodar DEPOIS do deploy do código novo,
com o MESMO USER_ID_SALT. Uso: python scripts/pseudonimizar_historico.py"""

import os
import sys

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.security import _e_id_discord_cru, pseudonimizar_user_id

load_dotenv()
salt = os.environ.get("USER_ID_SALT", "")
if not salt:
    print("ABORTADO: USER_ID_SALT não definido no ambiente.")
    sys.exit(1)

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

passo, inicio, atualizados, pulados = 1000, 0, 0, 0
while True:
    lote = (
        sb.table("historico_digi")
        .select("id, user_id")
        .order("id")
        .range(inicio, inicio + passo - 1)
        .execute()
        .data
        or []
    )
    for linha in lote:
        uid = str(linha.get("user_id") or "")
        if _e_id_discord_cru(uid):
            sb.table("historico_digi").update({"user_id": pseudonimizar_user_id(uid, salt)}).eq(
                "id", linha["id"]
            ).execute()
            atualizados += 1
        else:
            pulados += 1
    if len(lote) < passo:
        break
    inicio += passo

print(f"OK: {atualizados} hasheados, {pulados} pulados (já hash / não-cru).")
