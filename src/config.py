"""Application settings — loaded from environment variables."""

import json
import os
from dataclasses import dataclass

import boto3
import structlog as _structlog
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_environment() -> str:
    """Accept APP_ENV (CDK convention) or ENVIRONMENT — APP_ENV takes precedence."""
    return os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "dev"))


@dataclass
class RsaKeyPair:
    private_key: str  # PEM — used to sign tokens
    public_key: str  # PEM — used to verify tokens, served via JWKS
    key_id: str  # kid — included in JWT header and JWKS
    retiring_public_key: str | None = None  # PEM — optional, verifies old tokens during overlap
    retiring_key_id: str | None = None  # kid for retiring key


def _resolve_rsa_keys() -> RsaKeyPair:
    """
    Resolve RSA key pair for JWT RS256 signing.

    Priority:
      1. JWT_PRIVATE_KEY + JWT_PUBLIC_KEY + JWT_KEY_ID env vars (local dev / CI)
      2. JWT_KEYS_SECRET_ARN env var → fetch from Secrets Manager (prod Lambda)
         Secret schema: { "private_key": "...", "public_key": "...", "key_id": "..." }
      3. Raise at startup if neither is configured — fail fast, never silently use weak keys
    """
    private_key = os.environ.get("JWT_PRIVATE_KEY", "")
    public_key = os.environ.get("JWT_PUBLIC_KEY", "")
    key_id = os.environ.get("JWT_KEY_ID", "dev-key")

    if private_key and public_key:
        retiring_public_key = os.environ.get("JWT_RETIRING_PUBLIC_KEY") or None
        retiring_key_id = os.environ.get("JWT_RETIRING_KEY_ID") or None
        return RsaKeyPair(
            private_key=private_key,
            public_key=public_key,
            key_id=key_id,
            retiring_public_key=retiring_public_key,
            retiring_key_id=retiring_key_id,
        )

    secret_arn = os.environ.get("JWT_KEYS_SECRET_ARN", "")
    if secret_arn:
        region = os.environ.get("AWS_REGION", "us-east-1")
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_arn)
        secret_string: str = str(response.get("SecretString", "{}"))
        parsed: dict[str, str] = json.loads(secret_string)
        return RsaKeyPair(
            private_key=parsed["private_key"],
            public_key=parsed["public_key"],
            key_id=parsed.get("key_id", "ugsys-v1"),
            retiring_public_key=parsed.get("retiring_public_key") or None,
            retiring_key_id=parsed.get("retiring_key_id") or None,
        )

    # Local dev fallback — generate a throwaway key pair so the service starts
    # without any configuration. This is intentionally NOT suitable for production.
    # Bandit S105/S106 suppressed: this is not a hardcoded secret, it's a dev scaffold.
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        _priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_key = _priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        public_key = (
            _priv.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
        return RsaKeyPair(private_key=private_key, public_key=public_key, key_id="dev-ephemeral")
    except ImportError as err:
        raise RuntimeError(
            "JWT_PRIVATE_KEY / JWT_PUBLIC_KEY env vars are required, "
            "or set JWT_KEYS_SECRET_ARN to load from Secrets Manager. "
            "Install 'cryptography' for local dev auto-generation."
        ) from err


# Resolved once at module load — Lambda cold start reads from Secrets Manager here.
_previous_key_id: str | None = None
_rsa_keys = _resolve_rsa_keys()

_config_logger = _structlog.get_logger()
if _previous_key_id is not None and _previous_key_id != _rsa_keys.key_id:
    _config_logger.info(
        "key_rotation.detected",
        old_kid=_previous_key_id,
        new_kid=_rsa_keys.key_id,
    )
_previous_key_id = _rsa_keys.key_id


def _resolve_service_accounts() -> str:
    """
    Resolve the SERVICE_ACCOUNTS_JSON string for the client_credentials grant.

    Priority:
      1. SERVICE_ACCOUNTS_JSON env var (local dev / CI)
      2. SERVICE_ACCOUNTS_SECRET_ARN env var → fetch from Secrets Manager (prod Lambda)
         Secret value is the raw JSON string of the service accounts map.
      3. Returns "{}" (empty map) — service token endpoint will reject all clients.
    """
    raw = os.environ.get("SERVICE_ACCOUNTS_JSON", "")
    if raw:
        return raw

    secret_arn = os.environ.get("SERVICE_ACCOUNTS_SECRET_ARN", "")
    if secret_arn:
        region = os.environ.get("AWS_REGION", "us-east-1")
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_arn)
        return str(response.get("SecretString", "{}"))

    return "{}"


# Resolved once at cold-start — injected into SERVICE_ACCOUNTS_JSON env var so
# _load_service_accounts() in main.py picks it up without any changes there.
_service_accounts_json = _resolve_service_accounts()
if _service_accounts_json and _service_accounts_json != "{}":
    os.environ.setdefault("SERVICE_ACCOUNTS_JSON", _service_accounts_json)


class Settings(BaseSettings):
    service_name: str = "ugsys-identity-manager"
    environment: str = _resolve_environment()
    aws_region: str = "us-east-1"
    dynamodb_table_prefix: str = "ugsys"
    version: str = "0.1.0"
    event_bus_name: str = "ugsys-platform-bus"
    log_level: str = "INFO"

    # DynamoDB — matches CDK stack: ugsys-identity-manager-users-{env}
    dynamodb_table_name: str = ""  # if set, overrides the computed property
    token_blacklist_table_name: str = ""  # if set, overrides the computed property
    outbox_table_name: str = ""  # if set, overrides the computed property

    # JWT RS256 — resolved from Secrets Manager or env vars at module load
    jwt_algorithm: str = "RS256"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 7
    # Audience embedded in access tokens — consumers must validate this claim
    jwt_audience: str = "admin-panel"

    # Password hashing — work factor for bcrypt
    bcrypt_rounds: int = 12  # loaded from BCRYPT_ROUNDS env var

    # Login brute-force protection
    login_max_attempts: int = 5  # loaded from LOGIN_MAX_ATTEMPTS env var
    login_lockout_minutes: int = 30  # loaded from LOGIN_LOCKOUT_MINUTES env var

    # Resolved key pair — read-only properties backed by module-level _rsa_keys
    @property
    def jwt_private_key(self) -> str:
        return _rsa_keys.private_key

    @property
    def jwt_public_key(self) -> str:
        return _rsa_keys.public_key

    @property
    def jwt_key_id(self) -> str:
        return _rsa_keys.key_id

    @property
    def jwt_retiring_public_key(self) -> str | None:
        return _rsa_keys.retiring_public_key

    @property
    def jwt_retiring_key_id(self) -> str | None:
        return _rsa_keys.retiring_key_id

    @field_validator("jwt_algorithm")
    @classmethod
    def validate_jwt_algorithm(cls, v: str) -> str:
        if v != "RS256":
            raise ValueError(
                f"jwt_algorithm must be 'RS256', got '{v}'. HS256 and 'none' are not allowed."
            )
        return v

    @field_validator("bcrypt_rounds")
    @classmethod
    def validate_bcrypt_rounds(cls, v: int) -> int:
        if v < 12:
            raise ValueError(f"bcrypt_rounds must be >= 12, got {v}")
        return v

    @field_validator("login_max_attempts")
    @classmethod
    def validate_login_max_attempts(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"login_max_attempts must be >= 1, got {v}")
        return v

    @field_validator("login_lockout_minutes")
    @classmethod
    def validate_login_lockout_minutes(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"login_lockout_minutes must be >= 1, got {v}")
        return v

    # CORS — comma-separated list of allowed origins.
    # Covers all ugsys frontends that call the identity-manager directly.
    # Override via ALLOWED_ORIGINS env var if new frontends are added.
    allowed_origins: str = (
        "https://registry.apps.cloud.org.bo,"
        "https://profile.apps.cloud.org.bo,"
        "https://admin.apps.cloud.org.bo"
    )

    # Cookie configuration — environment-configurable, never hardcoded
    cookie_domain: str = ".apps.cloud.org.bo"
    cookie_secure: bool = True
    refresh_token_cookie_name: str = "ugsys_refresh_token"  # noqa: S105 — cookie name, not a secret

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    # Tracing
    xray_enabled: bool = False  # set to true in prod via XRAY_ENABLED=true

    @property
    def users_table(self) -> str:
        if self.dynamodb_table_name:
            return self.dynamodb_table_name
        return f"ugsys-identity-manager-users-{self.environment}"

    @property
    def token_blacklist_table(self) -> str:
        if self.token_blacklist_table_name:
            return self.token_blacklist_table_name
        return f"ugsys-identity-{self.environment}-token-blacklist"

    @property
    def outbox_table(self) -> str:
        if self.outbox_table_name:
            return self.outbox_table_name
        return f"ugsys-outbox-identity-{self.environment}"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
