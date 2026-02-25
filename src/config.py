"""Application settings — loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "ugsys-identity-manager"
    environment: str = "dev"
    aws_region: str = "us-east-1"
    dynamodb_table_prefix: str = "ugsys"
    version: str = "0.1.0"
    event_bus_name: str = "ugsys-platform-bus"
    log_level: str = "INFO"

    # DynamoDB — matches CDK stack: ugsys-identity-manager-users-{env}
    dynamodb_table_name: str = ""  # if set, overrides the computed property
    token_blacklist_table_name: str = ""  # if set, overrides the computed property

    # JWT — override in prod via env / Secrets Manager
    jwt_secret_key: str = "change-me-in-production"  # noqa: S105
    jwt_algorithm: str = "RS256"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 7

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

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
