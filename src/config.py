"""Application settings — loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "ugsys-identity-manager"
    environment: str = "dev"
    aws_region: str = "us-east-1"
    dynamodb_table_prefix: str = "ugsys"
    event_bus_name: str = "ugsys-event-bus"
    log_level: str = "INFO"

    # JWT — override in prod via env / Secrets Manager
    jwt_secret_key: str = "change-me-in-production"  # noqa: S105
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 7

    # Tracing
    xray_enabled: bool = False  # set to true in prod via XRAY_ENABLED=true

    @property
    def users_table(self) -> str:
        return f"{self.dynamodb_table_prefix}-identity-users-{self.environment}"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
