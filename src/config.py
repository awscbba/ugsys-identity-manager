"""Application settings — loaded from environment variables."""

import json
import os

import boto3
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_environment() -> str:
    """Accept APP_ENV (CDK convention) or ENVIRONMENT — APP_ENV takes precedence."""
    return os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "dev"))


def _resolve_jwt_secret() -> str:
    """
    Resolve JWT secret key.

    Priority:
      1. JWT_SECRET_KEY env var (local dev / test override)
      2. SECRETS_MANAGER_JWT_SECRET_ARN env var → fetch from Secrets Manager (prod Lambda)
      3. Fallback default (dev only — will fail Bandit S105 in prod if not overridden)
    """
    direct = os.environ.get("JWT_SECRET_KEY", "")
    if direct:
        return direct

    secret_arn = os.environ.get("SECRETS_MANAGER_JWT_SECRET_ARN", "")
    if secret_arn:
        region = os.environ.get("AWS_REGION", "us-east-1")
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_arn)
        secret = response.get("SecretString", "{}")
        parsed: dict[str, str] = json.loads(secret)
        return str(parsed.get("jwt_secret_key", ""))

    return "change-me-in-production"


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

    # JWT — RS256 only; resolved via _resolve_jwt_secret() above
    jwt_secret_key: str = _resolve_jwt_secret()
    jwt_algorithm: str = "RS256"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 7

    # JWT RS256 config — populated from env in production
    jwt_audience: str = ""
    jwt_issuer: str = ""
    jwt_public_key: str = ""  # PEM-encoded public key
    jwt_private_key: str = ""  # PEM-encoded private key

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
        # Matches CDK IdentityManagerStack table name
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
