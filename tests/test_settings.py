"""Security-sensitive application settings validation."""

import pytest
from pydantic import ValidationError

from app.settings import Settings


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_deployed_environments_reject_insecure_jwt_fallback(app_env: str) -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            app_env=app_env,
            database_url="postgresql://example.invalid/test",
            jwt_secret_key="development-only-secret-change-me",
            jwt_cookie_secure=True,
            cors_allowed_origins="https://app.example.com",
            openai_api_key="test-placeholder",
        )


def test_production_settings_accept_explicit_secure_configuration() -> None:
    configured = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql://example.invalid/test",
        jwt_secret_key="a-unique-production-secret-that-is-long-enough",
        jwt_cookie_secure=True,
        jwt_cookie_samesite="lax",
        cors_allowed_origins="https://app.example.com, https://admin.example.com/",
        openai_api_key="test-placeholder",
    )

    assert configured.is_production is True
    assert configured.cors_origins == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_credentials_cannot_use_wildcard_cors_in_production() -> None:
    with pytest.raises(ValidationError, match="Wildcard CORS"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql://example.invalid/test",
            jwt_secret_key="a-unique-production-secret-that-is-long-enough",
            jwt_cookie_secure=True,
            cors_allowed_origins="*",
            openai_api_key="test-placeholder",
        )


def test_samesite_none_requires_a_secure_cookie() -> None:
    with pytest.raises(ValidationError, match="JWT_COOKIE_SECURE"):
        Settings(
            _env_file=None,
            app_env="test",
            database_url="postgresql://example.invalid/test",
            jwt_cookie_secure=False,
            jwt_cookie_samesite="none",
        )
