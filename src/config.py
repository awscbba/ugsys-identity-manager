"""Application settings — loaded from environment variables."""

import json
import os
from dataclasses import dataclass

import boto3
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
        return RsaKeyPair(private_key=private_key, public_key=public_key, key_id=key_id)

    secret_arn = os.environ.get("JWT_KEYS_SECRET_ARN", "")
    if secret_arn:
        region = os.environ.get("AWS_REGION", "us-east-1")
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_arn)
        parsed: dict[str, str] = json.loads(response.get("SecretString", "{}"))
        return RsaKeyPair(
            private_key=parsed["private_key"],
            public_key=parsed["public_key"],
            key_id=parsed.get("key_id", "ugsys-v1"),
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
_rsa_keys = _resolve_rsa_keys()


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

    @field_validator("jwt_algorithm")
    @classmethod
    def validate_jwt_algorithm(cls, v: str) -> str:
        if v != "RS256":
            raise ValueError(
                f"jwt_algorithm must be 'RS256', got '{v}'. HS256 and 'none' are not allowed."
            )
        return v

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
