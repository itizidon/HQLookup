"""Central application configuration with production fail-fast validation.

Only environment-variable *names* are included in validation errors.  Secret
values must never be rendered through settings diagnostics or logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.utils import parseaddr
import base64
import ipaddress
import os
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv


load_dotenv()


class SettingsError(RuntimeError):
    """Raised when deployment configuration is unsafe or incomplete."""


_TURNSTILE_TEST_SECRETS = {
    "1x0000000000000000000000000000000AA",
    "2x0000000000000000000000000000000AA",
    "3x0000000000000000000000000000000AA",
}
_DEVELOPMENT_DATA_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{name} must be a boolean value")


def _read_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer") from exc
    if value <= 0:
        raise SettingsError(f"{name} must be greater than zero")
    return value


def _read_bounded_int(name: str, default: int, *, maximum: int) -> int:
    value = _read_positive_int(name, default)
    if value > maximum:
        raise SettingsError(f"{name} must be at most {maximum}")
    return value


def _read_nonnegative_bounded_int(name: str, default: int, *, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer") from exc
    if value < 0 or value > maximum:
        raise SettingsError(f"{name} must be between zero and {maximum}")
    return value


def _read_csv(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _looks_like_placeholder(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.strip().lower().replace("-", "_")
    markers = (
        "change_this",
        "changethis",
        "replace_me",
        "replaceme",
        "your_super_secret",
        "example",
        "placeholder",
        "xxxxx",
        "development_only",
    )
    return any(marker in normalized for marker in markers)


def _is_local_hostname(hostname: str | None) -> bool:
    if hostname is None:
        return True
    host = hostname.lower().strip("[]").rstrip(".")
    if host in {"localhost", "0.0.0.0"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _is_safe_forwarded_network(value: str) -> bool:
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False
    return network.prefixlen > 0 and not network.is_unspecified


def _is_safe_production_database_url(value: str) -> bool:
    database = urlparse(value)
    sslmodes = parse_qs(database.query).get("sslmode", [])
    sslmode = sslmodes[0].lower() if len(sslmodes) == 1 else ""
    is_railway_private_database = (
        database.scheme in {"postgresql", "postgresql+psycopg2"}
        and database.hostname is not None
        and database.hostname.lower().endswith(".railway.internal")
        and sslmode in {"", "disable", "prefer"}
    )
    is_tls_database = (
        database.scheme in {"postgresql", "postgresql+psycopg2"}
        and not _is_local_hostname(database.hostname)
        and sslmode in {"require", "verify-ca", "verify-full"}
    )
    return is_railway_private_database or is_tls_database


def _is_safe_production_data_key(value: str) -> bool:
    try:
        decoded_data_key = base64.urlsafe_b64decode(value.encode("ascii"))
    except (ValueError, UnicodeError):
        return False
    return (
        len(decoded_data_key) == 32
        and value != _DEVELOPMENT_DATA_KEY
        and not _looks_like_placeholder(value)
    )


def _is_safe_production_resend_key(value: str | None) -> bool:
    return bool(
        value
        and not _looks_like_placeholder(value)
        and len(value) >= 12
    )


def _is_safe_production_resend_sender(value: str) -> bool:
    _, resend_address = parseaddr(value)
    return bool(
        resend_address
        and not resend_address.lower().endswith("@resend.dev")
        and resend_address.count("@") == 1
        and not any(character.isspace() for character in resend_address)
    )


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str | None
    frontend_url: str
    cors_origins: tuple[str, ...]
    trusted_hosts: tuple[str, ...]
    forwarded_allow_ips: tuple[str, ...]

    jwt_secret_key: str
    jwt_cookie_secure: bool
    jwt_cookie_name: str
    jwt_expire_hours: int
    jwt_issuer: str
    jwt_audience: str

    redis_url: str
    openai_api_key: str
    llm_base_url: str
    llm_model: str
    llm_timeout_seconds: int
    ask_deadline_seconds: int
    max_spreadsheet_llm_chars: int
    max_visuals_for_llm: int
    max_chart_reference_cells: int
    max_tables_from_llm: int
    max_headers_per_table: int
    max_findings_from_llm: int
    spreadsheet_llm_model: str
    spreadsheet_vision_model: str
    max_llm_prompt_chars: int
    max_llm_output_tokens: int
    max_ingested_chunk_chars: int
    embedding_model_path: str
    public_signup_enabled: bool
    turnstile_secret_key: str | None
    email_verification_hours: int
    password_reset_hours: int
    data_encryption_key: str
    mfa_issuer: str

    stripe_secret_key: str | None
    stripe_webhook_secret: str | None
    stripe_price_starter: str | None
    stripe_live_mode: bool
    resend_api_key: str | None
    resend_from_email: str

    max_llm_calls_per_request: int
    max_upload_files: int
    max_upload_total_mb: int
    max_archive_uncompressed_mb: int
    max_archive_ratio: int

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def _validate_runtime_basics(self) -> None:
        if self.app_env not in {"development", "test", "production"}:
            raise SettingsError("APP_ENV must be development, test, or production")

        if not self.database_url:
            raise SettingsError("DATABASE_URL is required")

    def validate_database(self) -> None:
        """Validate settings needed by database-only processes such as Alembic."""

        self._validate_runtime_basics()
        if (
            self.is_production
            and not _is_safe_production_database_url(self.database_url or "")
        ):
            raise SettingsError(
                "Unsafe or missing production settings: DATABASE_URL"
            )

    def validate_email_worker(self) -> None:
        """Validate only the settings required to deliver queued email."""

        self._validate_runtime_basics()
        if not self.is_production:
            return

        invalid: list[str] = []
        if not _is_safe_production_database_url(self.database_url or ""):
            invalid.append("DATABASE_URL")
        if not _is_safe_production_data_key(self.data_encryption_key):
            invalid.append("DATA_ENCRYPTION_KEY")
        if not _is_safe_production_resend_key(self.resend_api_key):
            invalid.append("RESEND_API_KEY")
        if not _is_safe_production_resend_sender(self.resend_from_email):
            invalid.append("RESEND_FROM_EMAIL")

        if invalid:
            names = ", ".join(sorted(set(invalid)))
            raise SettingsError(f"Unsafe or missing production settings: {names}")

    def validate(self) -> None:
        """Validate the complete API configuration."""

        self._validate_runtime_basics()

        if not self.is_production:
            return

        invalid: list[str] = []

        if (
            _looks_like_placeholder(self.jwt_secret_key)
            or len(self.jwt_secret_key) < 32
            or len(set(self.jwt_secret_key)) < 10
        ):
            invalid.append("JWT_SECRET_KEY")
        if not self.jwt_cookie_secure:
            invalid.append("JWT_COOKIE_SECURE")

        frontend = urlparse(self.frontend_url)
        if (
            frontend.scheme != "https"
            or _is_local_hostname(frontend.hostname)
            or frontend.username
            or frontend.password
            or frontend.path not in {"", "/"}
            or frontend.query
            or frontend.fragment
        ):
            invalid.append("FRONTEND_URL")

        if not _is_safe_production_database_url(self.database_url or ""):
            invalid.append("DATABASE_URL")

        redis = urlparse(self.redis_url)
        redis_query = parse_qs(redis.query)
        redis_cert_reqs = redis_query.get("ssl_cert_reqs", ["required"])
        redis_hostname_check = redis_query.get("ssl_check_hostname", ["true"])
        is_railway_private_redis = (
            redis.scheme == "redis"
            and redis.hostname is not None
            and redis.hostname.lower().endswith(".railway.internal")
        )
        is_tls_redis = (
            redis.scheme == "rediss"
            and not _is_local_hostname(redis.hostname)
            and len(redis_cert_reqs) == 1
            and redis_cert_reqs[0].lower() == "required"
            and len(redis_hostname_check) == 1
            and redis_hostname_check[0].lower() in {"1", "true", "yes", "on"}
        )
        if not (is_railway_private_redis or is_tls_redis):
            invalid.append("REDIS_URL")

        llm = urlparse(self.llm_base_url)
        if (
            llm.scheme != "https"
            or _is_local_hostname(llm.hostname)
            or llm.username
            or llm.password
        ):
            invalid.append("LLM_BASE_URL")
        if (
            _looks_like_placeholder(self.openai_api_key)
            or self.openai_api_key == "ollama"
            or len(self.openai_api_key) < 16
        ):
            invalid.append("OPENAI_API_KEY")
        if not self.llm_model.strip():
            invalid.append("LLM_MODEL")
        if not self.spreadsheet_llm_model.strip():
            invalid.append("SPREADSHEET_LLM_MODEL")

        parsed_origins = [urlparse(origin) for origin in self.cors_origins]
        if not parsed_origins or any(
            parsed.scheme != "https"
            or _is_local_hostname(parsed.hostname)
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
            for parsed in parsed_origins
        ):
            invalid.append("CORS_ORIGINS")
        if not self.trusted_hosts or any(
            host in {"*", "localhost", "127.0.0.1", "0.0.0.0", "::1"}
            or "*" in host
            or any(character in host for character in "/@")
            or any(character.isspace() for character in host)
            or "://" in host
            for host in self.trusted_hosts
        ):
            invalid.append("TRUSTED_HOSTS")
        if not self.forwarded_allow_ips or any(
            not _is_safe_forwarded_network(value)
            for value in self.forwarded_allow_ips
        ):
            invalid.append("FORWARDED_ALLOW_IPS")

        if not self.jwt_issuer.strip():
            invalid.append("JWT_ISSUER")
        if not self.jwt_audience.strip():
            invalid.append("JWT_AUDIENCE")
        if self.llm_timeout_seconds > 60:
            invalid.append("LLM_TIMEOUT_SECONDS")
        if self.ask_deadline_seconds > 300:
            invalid.append("ASK_DEADLINE_SECONDS")

        if (
            not self.stripe_secret_key
            or not self.stripe_secret_key.startswith("sk_live_")
            or len(self.stripe_secret_key) < 24
            or _looks_like_placeholder(self.stripe_secret_key)
        ):
            invalid.append("STRIPE_SECRET_KEY")
        if (
            not self.stripe_webhook_secret
            or not self.stripe_webhook_secret.startswith("whsec_")
            or len(self.stripe_webhook_secret) < 24
            or _looks_like_placeholder(self.stripe_webhook_secret)
        ):
            invalid.append("STRIPE_WEBHOOK_SECRET")
        if (
            _looks_like_placeholder(self.stripe_price_starter)
            or not (self.stripe_price_starter or "").startswith("price_")
            or len(self.stripe_price_starter or "") < 12
        ):
            invalid.append("STRIPE_PRICE_STARTER")
        if not _is_safe_production_resend_key(self.resend_api_key):
            invalid.append("RESEND_API_KEY")
        if not _is_safe_production_resend_sender(self.resend_from_email):
            invalid.append("RESEND_FROM_EMAIL")

        if (
            not self.turnstile_secret_key
            or _looks_like_placeholder(self.turnstile_secret_key)
            or len(self.turnstile_secret_key) < 20
            or self.turnstile_secret_key in _TURNSTILE_TEST_SECRETS
        ):
            invalid.append("TURNSTILE_SECRET_KEY")

        if not _is_safe_production_data_key(self.data_encryption_key):
            invalid.append("DATA_ENCRYPTION_KEY")
        if (
            not self.mfa_issuer
            or len(self.mfa_issuer) > 100
            or any(character in self.mfa_issuer for character in "\r\n:")
        ):
            invalid.append("MFA_ISSUER")

        if not os.path.isabs(self.embedding_model_path):
            invalid.append("EMBEDDING_MODEL_PATH")

        if invalid:
            names = ", ".join(sorted(set(invalid)))
            raise SettingsError(f"Unsafe or missing production settings: {names}")


def _load_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "").strip().lower()
    if not app_env:
        raise SettingsError("APP_ENV must be explicitly set")
    is_production = app_env == "production"
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    default_cors = (frontend_url,) if is_production else (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )

    return Settings(
        app_env=app_env,
        database_url=os.getenv("DATABASE_URL"),
        frontend_url=frontend_url,
        cors_origins=_read_csv("CORS_ORIGINS", default_cors),
        trusted_hosts=_read_csv(
            "TRUSTED_HOSTS",
            ("localhost", "127.0.0.1", "testserver") if not is_production else (),
        ),
        forwarded_allow_ips=_read_csv("FORWARDED_ALLOW_IPS", ("127.0.0.1",)),
        jwt_secret_key=os.getenv(
            "JWT_SECRET_KEY",
            "development_only_insecure_secret_do_not_deploy",
        ),
        jwt_cookie_secure=_read_bool("JWT_COOKIE_SECURE", is_production),
        jwt_cookie_name="__Host-token" if is_production else "token",
        jwt_expire_hours=_read_bounded_int("JWT_EXPIRE_HOURS", 24, maximum=168),
        jwt_issuer=os.getenv("JWT_ISSUER", "hqlookup-api"),
        jwt_audience=os.getenv("JWT_AUDIENCE", "hqlookup-web"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        openai_api_key=os.getenv("OPENAI_API_KEY", "ollama"),
        llm_base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/"),
        llm_model=os.getenv("LLM_MODEL", "mistral:7b"),
        llm_timeout_seconds=_read_bounded_int(
            "LLM_TIMEOUT_SECONDS", 30, maximum=120
        ),
        ask_deadline_seconds=_read_bounded_int(
            "ASK_DEADLINE_SECONDS", 120, maximum=600
        ),
        max_spreadsheet_llm_chars=_read_bounded_int(
            "MAX_SPREADSHEET_LLM_CHARS", 60_000, maximum=200_000
        ),
        max_visuals_for_llm=_read_nonnegative_bounded_int(
            "MAX_VISUALS_FOR_LLM", 10, maximum=25
        ),
        max_chart_reference_cells=_read_bounded_int(
            "MAX_CHART_REFERENCE_CELLS", 100_000, maximum=200_000
        ),
        max_tables_from_llm=_read_bounded_int(
            "MAX_TABLES_FROM_LLM", 100, maximum=200
        ),
        max_headers_per_table=_read_bounded_int(
            "MAX_HEADERS_PER_TABLE", 1_000, maximum=2_000
        ),
        max_findings_from_llm=_read_bounded_int(
            "MAX_FINDINGS_FROM_LLM", 100, maximum=200
        ),
        spreadsheet_llm_model=os.getenv(
            "SPREADSHEET_LLM_MODEL", os.getenv("LLM_MODEL", "mistral:7b")
        ),
        spreadsheet_vision_model=os.getenv("SPREADSHEET_VISION_MODEL", "").strip(),
        max_llm_prompt_chars=_read_bounded_int(
            "MAX_LLM_PROMPT_CHARS", 60_000, maximum=200_000
        ),
        max_llm_output_tokens=_read_bounded_int(
            "MAX_LLM_OUTPUT_TOKENS", 1_500, maximum=4_000
        ),
        max_ingested_chunk_chars=_read_bounded_int(
            "MAX_INGESTED_CHUNK_CHARS", 12_000, maximum=50_000
        ),
        embedding_model_path=os.getenv(
            "EMBEDDING_MODEL_PATH", "all-MiniLM-L6-v2"
        ).strip(),
        public_signup_enabled=_read_bool(
            "PUBLIC_SIGNUP_ENABLED", not is_production
        ),
        turnstile_secret_key=os.getenv("TURNSTILE_SECRET_KEY"),
        email_verification_hours=_read_bounded_int(
            "EMAIL_VERIFICATION_HOURS", 24, maximum=72
        ),
        password_reset_hours=_read_bounded_int(
            "PASSWORD_RESET_HOURS", 1, maximum=24
        ),
        data_encryption_key=os.getenv(
            "DATA_ENCRYPTION_KEY", _DEVELOPMENT_DATA_KEY
        ).strip(),
        mfa_issuer=os.getenv("MFA_ISSUER", "HQLookup").strip(),
        stripe_secret_key=os.getenv("STRIPE_SECRET_KEY"),
        stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET"),
        stripe_price_starter=os.getenv("STRIPE_PRICE_STARTER"),
        stripe_live_mode=is_production,
        resend_api_key=os.getenv("RESEND_API_KEY"),
        resend_from_email=os.getenv("RESEND_FROM_EMAIL", "Team <onboarding@resend.dev>"),
        max_llm_calls_per_request=_read_bounded_int(
            "MAX_LLM_CALLS_PER_REQUEST", 10, maximum=20
        ),
        max_upload_files=_read_bounded_int("MAX_UPLOAD_FILES", 10, maximum=25),
        max_upload_total_mb=_read_bounded_int(
            "MAX_UPLOAD_TOTAL_MB", 50, maximum=500
        ),
        max_archive_uncompressed_mb=_read_bounded_int(
            "MAX_ARCHIVE_UNCOMPRESSED_MB", 50, maximum=100
        ),
        max_archive_ratio=_read_bounded_int(
            "MAX_ARCHIVE_COMPRESSION_RATIO", 50, maximum=100
        ),
    )


settings = _load_settings()
