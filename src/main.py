"""Composition root — wires all dependencies and starts the FastAPI app."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import Settings

import structlog
from fastapi import FastAPI
from mangum import Mangum

from src.config import settings
from src.domain.exceptions import DomainError
from src.infrastructure.logging import configure_logging
from src.presentation.api.v1 import auth, health, roles, users
from src.presentation.middleware.correlation_id import CorrelationIdMiddleware
from src.presentation.middleware.exception_handler import (
    domain_exception_handler,
    unhandled_exception_handler,
)
from src.presentation.middleware.rate_limiting import RateLimitMiddleware
from src.presentation.middleware.request_logging import RequestLoggingMiddleware
from src.presentation.middleware.security_headers import SecurityHeadersMiddleware
from src.presentation.middleware.tracing import TracingMiddleware

configure_logging(settings.service_name, settings.log_level)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    logger.info("startup", service=settings.service_name, environment=settings.environment)
    if settings.xray_enabled:
        from src.infrastructure.tracing import configure_tracing

        configure_tracing(settings.service_name)
    _wire_dependencies(app)
    yield
    logger.info("shutdown", service=settings.service_name)


def _load_service_accounts(cfg: Settings) -> dict:  # type: ignore[type-arg]
    """Load service accounts from config. In prod these come from Secrets Manager."""
    import json
    import os

    raw = os.environ.get("SERVICE_ACCOUNTS_JSON", "")
    if raw:
        try:
            return dict(json.loads(raw))  # type: ignore[arg-type]
        except Exception:
            logger.warning("service_accounts.parse_failed")
    return {}


def _wire_dependencies(app: FastAPI) -> None:
    """Wire infrastructure adapters into presentation layer via dependency overrides."""
    from passlib.context import CryptContext

    from src.application.services.auth_service import AuthService
    from src.application.services.user_service import UserService
    from src.infrastructure.adapters.jwt_token_service import JWTTokenService
    from src.infrastructure.messaging.event_publisher import EventBridgePublisher
    from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository
    from src.presentation.api.v1.auth import get_auth_service
    from src.presentation.api.v1.roles import get_token_service as get_roles_token_service
    from src.presentation.api.v1.users import get_token_service, get_user_service

    user_repo = DynamoDBUserRepository(
        table_name=settings.users_table,
        region=settings.aws_region,
    )

    # Token blacklist and password validator — wired for AuthService lockout/gates
    from src.domain.value_objects.password_validator import PasswordValidator
    from src.infrastructure.persistence.dynamodb_token_blacklist import (
        DynamoDBTokenBlacklistRepository,
    )

    password_validator = PasswordValidator()

    token_blacklist = DynamoDBTokenBlacklistRepository(
        table_name=settings.token_blacklist_table,
        region=settings.aws_region,
    )

    token_service = JWTTokenService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        token_blacklist=token_blacklist,
    )
    event_publisher = EventBridgePublisher(
        bus_name=settings.event_bus_name,
        region=settings.aws_region,
    )

    _pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

    class _BcryptHasher:
        def hash(self, password: str) -> str:
            return str(_pwd_ctx.hash(password))

        def verify(self, plain: str, hashed: str) -> bool:
            return bool(_pwd_ctx.verify(plain, hashed))

    auth_service = AuthService(
        user_repo=user_repo,
        token_service=token_service,
        password_hasher=_BcryptHasher(),
        token_blacklist=token_blacklist,
        password_validator=password_validator,
        event_publisher=event_publisher,
        service_accounts=_load_service_accounts(settings),
    )
    user_service = UserService(user_repo=user_repo, event_publisher=event_publisher)

    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_user_service] = lambda: user_service
    app.dependency_overrides[get_token_service] = lambda: token_service
    app.dependency_overrides[get_roles_token_service] = lambda: token_service


app = FastAPI(
    title="ugsys Identity Manager",
    version="0.1.0",
    docs_url="/docs" if settings.environment != "prod" else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Middleware — order matters: outermost first
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
if settings.xray_enabled:
    app.add_middleware(TracingMiddleware, service_name=settings.service_name)
app.add_middleware(CorrelationIdMiddleware)

# Exception handlers — registered before routers
app.add_exception_handler(DomainError, domain_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Routers
app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(roles.router, prefix="/api/v1")

# Lambda handler
handler = Mangum(app, lifespan="on")
