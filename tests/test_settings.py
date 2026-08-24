from dataclasses import replace

import pytest

from app.settings import SettingsError, settings


def _valid_production_settings():
    return replace(
        settings,
        app_env="production",
        database_url=(
            "postgresql+psycopg2://app:password@db.internal:5432/app"
            "?sslmode=require"
        ),
        frontend_url="https://app.hqlookup.test",
        cors_origins=("https://app.hqlookup.test",),
        trusted_hosts=("api.hqlookup.test",),
        forwarded_allow_ips=("10.0.0.10",),
        jwt_secret_key="aB3!dE6@gH9#kL2$mN5%qR8&sT1*vW4+xY7=zC0?fJ3!pS6@uV9#",
        jwt_cookie_secure=True,
        jwt_cookie_name="__Host-token",
        redis_url="rediss://default:password@redis.internal:6380/0",
        openai_api_key="sk-" + "a" * 48,
        llm_base_url="https://llm.example.net/v1",
        stripe_secret_key="sk_live_" + "a" * 48,
        stripe_webhook_secret="whsec_" + "a" * 48,
        stripe_price_starter="price_" + "a" * 24,
        resend_api_key="re_" + "a" * 32,
        resend_from_email="HQLookup <team@hqlookup.test>",
        embedding_model_path="/opt/models/all-MiniLM-L6-v2",
        public_signup_enabled=False,
        turnstile_secret_key="0x4AAAAAAAreal-looking-production-secret",
        email_verification_hours=24,
        password_reset_hours=1,
        data_encryption_key="P8DOzKW4P0pDL8G5mGk8jVvDsdRBwJceRIN7BuGbOvQ=",
        mfa_issuer="HQLookup",
    )


def test_valid_production_settings_pass_validation():
    _valid_production_settings().validate()


def test_production_allows_encrypted_railway_private_database_network():
    private_database = replace(
        _valid_production_settings(),
        database_url=(
            "postgresql+psycopg2://app:password@pgvector.railway.internal:5432/app"
        ),
    )

    private_database.validate()


def test_production_rejects_external_database_without_tls():
    insecure_database = replace(
        _valid_production_settings(),
        database_url="postgresql+psycopg2://app:password@db.example.net:5432/app",
    )

    with pytest.raises(SettingsError) as exc_info:
        insecure_database.validate()

    assert "DATABASE_URL" in str(exc_info.value)


def test_production_settings_report_names_without_secret_values():
    unsafe_value = "placeholder-secret-that-must-never-be-logged"
    invalid = replace(
        _valid_production_settings(),
        jwt_secret_key=unsafe_value,
        jwt_cookie_secure=False,
    )

    with pytest.raises(SettingsError) as exc_info:
        invalid.validate()

    message = str(exc_info.value)
    assert "JWT_SECRET_KEY" in message
    assert "JWT_COOKIE_SECURE" in message
    assert unsafe_value not in message


def test_production_allows_explicit_public_signup():
    public_signup = replace(
        _valid_production_settings(),
        public_signup_enabled=True,
    )

    public_signup.validate()


def test_production_rejects_turnstile_test_secret():
    test_key = replace(
        _valid_production_settings(),
        turnstile_secret_key="1x0000000000000000000000000000000AA",
    )

    with pytest.raises(SettingsError) as exc_info:
        test_key.validate()

    assert "TURNSTILE_SECRET_KEY" in str(exc_info.value)


def test_production_rejects_weak_provider_credentials():
    unsafe = replace(
        _valid_production_settings(),
        stripe_webhook_secret="whsec_x",
        turnstile_secret_key=None,
        data_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        forwarded_allow_ips=("0.0.0.0/0",),
    )

    with pytest.raises(SettingsError) as exc_info:
        unsafe.validate()

    message = str(exc_info.value)
    assert "STRIPE_WEBHOOK_SECRET" in message
    assert "TURNSTILE_SECRET_KEY" in message
    assert "DATA_ENCRYPTION_KEY" in message
    assert "FORWARDED_ALLOW_IPS" in message


def test_production_rejects_unsafe_mfa_issuer():
    invalid = replace(_valid_production_settings(), mfa_issuer="Bad:Issuer")

    with pytest.raises(SettingsError) as exc_info:
        invalid.validate()

    assert "MFA_ISSUER" in str(exc_info.value)


def test_email_worker_does_not_require_api_only_settings():
    worker = replace(
        _valid_production_settings(),
        openai_api_key="ollama",
        llm_base_url="http://localhost:11434/v1",
        embedding_model_path="all-MiniLM-L6-v2",
        stripe_secret_key=None,
        stripe_webhook_secret=None,
        stripe_price_starter=None,
        trusted_hosts=(),
    )

    worker.validate_email_worker()


def test_email_worker_requires_its_production_credentials():
    worker = replace(
        _valid_production_settings(),
        data_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        resend_api_key=None,
        resend_from_email="Team <onboarding@resend.dev>",
    )

    with pytest.raises(SettingsError) as exc_info:
        worker.validate_email_worker()

    message = str(exc_info.value)
    assert "DATA_ENCRYPTION_KEY" in message
    assert "RESEND_API_KEY" in message
    assert "RESEND_FROM_EMAIL" in message


def test_database_process_does_not_require_api_only_settings():
    database_process = replace(
        _valid_production_settings(),
        openai_api_key="ollama",
        stripe_secret_key=None,
        trusted_hosts=(),
    )

    database_process.validate_database()
