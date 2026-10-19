import pytest
from pydantic import ValidationError

from src.config import Settings


def test_development_can_start_without_external_credentials():
    settings = Settings(environment="development")
    assert settings.openai_key is None
    assert settings.database_key is None


def test_empty_secrets_are_treated_as_unset():
    settings = Settings(openai_api_key="", api_auth_token="")
    assert settings.openai_api_key is None
    assert settings.api_auth_token is None


def test_production_requires_private_backend_credentials():
    with pytest.raises(ValidationError, match="Missing production configuration"):
        Settings(environment="production")


def test_production_configuration_uses_service_role():
    settings = Settings(
        environment="production",
        openai_api_key="openai-secret",
        supabase_url="https://project.supabase.co",
        supabase_service_role_key="service-secret",
        api_auth_token="api-secret",
        user_id_salt="stable-test-salt",
    )
    assert settings.database_key == "service-secret"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("score_threshold", 1.1),
        ("max_chunks", 0),
        ("port", 70_000),
        ("retrieval_candidate_count", 0),
        ("retrieval_candidate_count", 61),
    ],
)
def test_numeric_bounds_are_enforced(field: str, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_user_id_salt_default_none_e_aceita_valor():
    from src.config import Settings

    assert Settings(environment="test").user_id_salt is None
    s = Settings(environment="test", user_id_salt="segredo")
    assert s.user_id_salt is not None and s.user_id_salt.get_secret_value() == "segredo"


@pytest.mark.parametrize("salt", [None, "", "   "])
def test_production_history_requires_nonempty_salt(salt):
    with pytest.raises(ValidationError, match="USER_ID_SALT"):
        Settings(
            environment="production",
            openai_api_key="test",
            supabase_url="https://test.co",
            supabase_service_role_key="test",
            api_auth_token="test",
            user_id_salt=salt,
        )


@pytest.mark.parametrize(
    "options",
    [
        {"rerank_provider": "typesafe"},
        {"typesafe_verify_mode": "shadow"},
        {"typesafe_rerank_shadow": True},
    ],
)
def test_active_typesafe_requires_key(options):
    with pytest.raises(ValidationError, match="TYPESAFE_API_KEY"):
        Settings(**options)


def test_enforcement_requires_calibrated_criteria():
    with pytest.raises(ValidationError, match="calibrated"):
        Settings(typesafe_api_key="test", typesafe_verify_mode="enforce")


def test_invalid_configuration_does_not_display_secret_values():
    with pytest.raises(ValidationError) as error:
        Settings(typesafe_api_key="private-typesafe-token", typesafe_verify_mode="enforce")
    assert "private-typesafe-token" not in str(error.value)


def test_enforcement_rejects_calibration_for_an_old_criteria_version():
    with pytest.raises(ValidationError, match="current criteria version"):
        Settings(
            typesafe_api_key="test",
            typesafe_verify_mode="enforce",
            typesafe_criteria_calibrated=True,
            typesafe_criteria_version="pilot-v1",
        )


@pytest.mark.parametrize(
    "options", [{"typesafe_verify_mode": "shadow"}, {"typesafe_rerank_shadow": True}]
)
def test_observation_cannot_label_revised_rubrics_as_an_old_version(options):
    with pytest.raises(ValidationError, match="current criteria version"):
        Settings(typesafe_api_key="test", typesafe_criteria_version="pilot-v1", **options)
