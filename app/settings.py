"""Validated application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"

    database_url: str
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_recycle: int = Field(default=1800, ge=60)

    frontend_url: str = "http://localhost:3000"
    cors_allowed_origins: str = ""

    jwt_secret_key: SecretStr = SecretStr("development-only-secret-change-me")
    jwt_cookie_secure: bool = False
    jwt_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    jwt_cookie_domain: str | None = None
    jwt_expire_hours: int = Field(default=168, ge=1, le=24 * 30)

    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "mistral:7b"
    spreadsheet_llm_model: str | None = None
    openai_api_key: SecretStr = SecretStr("ollama")
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    embedding_model: str = "all-MiniLM-L6-v2"

    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_price_starter: str | None = None

    resend_api_key: SecretStr | None = None
    resend_from_email: str = "Team <onboarding@resend.dev>"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("LOG_LEVEL must be a valid Python logging level")
        return normalized

    @field_validator("frontend_url", "llm_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_deployment_security(self) -> "Settings":
        if self.jwt_cookie_samesite == "none" and not self.jwt_cookie_secure:
            raise ValueError("JWT_COOKIE_SECURE must be true when SameSite=None")

        if self.app_env in {"staging", "production"}:
            required_explicit = {
                "frontend_url",
                "cors_allowed_origins",
                "jwt_secret_key",
                "llm_base_url",
                "llm_model",
                "openai_api_key",
                "redis_url",
                "stripe_secret_key",
                "stripe_webhook_secret",
                "stripe_price_starter",
                "resend_api_key",
                "resend_from_email",
            }
            missing = sorted(required_explicit - self.model_fields_set)
            if missing:
                raise ValueError(
                    "Production settings must be explicitly configured: " + ", ".join(missing)
                )
            secret = self.jwt_secret_key.get_secret_value()
            if (
                len(secret) < 32
                or secret == "development-only-secret-change-me"
                or any(marker in secret.lower() for marker in ("change_this", "change-me", "your_super_secret"))
            ):
                raise ValueError("JWT_SECRET_KEY must be a random value of at least 32 characters")
            if not self.jwt_cookie_secure:
                raise ValueError("JWT_COOKIE_SECURE must be true outside development/test")
            if not self.cors_allowed_origins.strip() or not self.cors_origins:
                raise ValueError("CORS_ALLOWED_ORIGINS must contain at least one trusted origin")
            if "*" in self.cors_origins:
                raise ValueError("Wildcard CORS origins are forbidden when credentials are enabled")
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Every production CORS origin must use HTTPS")
            if not self.openai_api_key.get_secret_value():
                raise ValueError("OPENAI_API_KEY must be configured")
            if not self.frontend_url.startswith("https://"):
                raise ValueError("FRONTEND_URL must use HTTPS outside development/test")
            if not self.stripe_secret_key or not self.stripe_secret_key.get_secret_value().startswith("sk_"):
                raise ValueError("STRIPE_SECRET_KEY must be configured with a Stripe secret key")
            if not self.stripe_webhook_secret or not self.stripe_webhook_secret.get_secret_value().startswith("whsec_"):
                raise ValueError("STRIPE_WEBHOOK_SECRET must be configured")
            if not self.stripe_price_starter or not self.stripe_price_starter.startswith("price_") or "xxxxx" in self.stripe_price_starter:
                raise ValueError("STRIPE_PRICE_STARTER must be a real Stripe price ID")
            if not self.resend_api_key or not self.resend_api_key.get_secret_value():
                raise ValueError("RESEND_API_KEY must be configured")
            if "@resend.dev" in self.resend_from_email.lower():
                raise ValueError("RESEND_FROM_EMAIL must use a verified production sender")
            redis_url = self.redis_url.get_secret_value().lower()
            if redis_url in {"redis://localhost:6379/0", "redis://127.0.0.1:6379/0"}:
                raise ValueError("REDIS_URL must be explicitly set to the production Redis service")

        return self

    @property
    def is_production(self) -> bool:
        return self.app_env in {"staging", "production"}

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_allowed_origins.strip()
        if not raw:
            return [self.frontend_url] if self.frontend_url else []
        return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]

    @property
    def spreadsheet_model(self) -> str:
        return self.spreadsheet_llm_model or self.llm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
