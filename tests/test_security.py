from src.security import _e_id_discord_cru, pseudonimizar_user_id


def test_pseudonimizar_deterministico_e_irreversivel():
    h1 = pseudonimizar_user_id("123456789012345678", "salt-secreto")
    h2 = pseudonimizar_user_id("123456789012345678", "salt-secreto")
    assert h1 == h2  # determinístico
    assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)  # 64-hex
    assert h1 != "123456789012345678"  # não é o cru
    # salt diferente → hash diferente
    assert pseudonimizar_user_id("123456789012345678", "outro") != h1


def test_e_id_discord_cru_distingue_cru_de_hash():
    assert _e_id_discord_cru("123456789012345678") is True
    assert _e_id_discord_cru(pseudonimizar_user_id("1", "s")) is False  # 64-hex
    assert _e_id_discord_cru("") is False
    assert _e_id_discord_cru("abc") is False
