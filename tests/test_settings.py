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
    )


def test_valid_production_settings_pass_validation():
    _valid_production_settings().validate()


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


def test_production_rejects_public_signup_and_weak_provider_credentials():
    unsafe = replace(
        _valid_production_settings(),
        public_signup_enabled=True,
        stripe_webhook_secret="whsec_x",
        forwarded_allow_ips=("0.0.0.0/0",),
    )

    with pytest.raises(SettingsError) as exc_info:
        unsafe.validate()

    message = str(exc_info.value)
    assert "PUBLIC_SIGNUP_ENABLED" in message
    assert "STRIPE_WEBHOOK_SECRET" in message
    assert "FORWARDED_ALLOW_IPS" in message
