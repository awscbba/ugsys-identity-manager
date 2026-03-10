"""Composition root — wires all dependencies and starts the FastAPI app."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from src.config import Settings

import aioboto3
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

from src.config import settings
from src.domain.exceptions import DomainError
from src.infrastructure.logging import configure_logging
from src.presentation.api.v1 import auth, health, jwks, roles, users
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


def _load_service_accounts(cfg: Settings) -> dict[str, dict[str, object]]:
    """Load service accounts from config. In prod these come from Secrets Manager."""
    import json
    import os

    raw = os.environ.get("SERVICE_ACCOUNTS_JSON", "")
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                result: dict[str, dict[str, object]] = {}
                for k, v in loaded.items():
                    if isinstance(v, dict):
                        result[str(k)] = v
                return result
            return {}
        except Exception:
            logger.warning("service_accounts.parse_failed")
    return {}


def _wire_dependencies(app: FastAPI) -> None:
    """Wire infrastructure adapters into presentation layer via dependency overrides."""
    import bcrypt as _bcrypt_lib

    from src.application.services.auth_service import AuthService
    from src.application.services.user_service import UserService
    from src.infrastructure.adapters.jwt_token_service import JWTTokenService
    from src.infrastructure.messaging.event_publisher import EventBridgePublisher
    from src.infrastructure.persistence.dynamodb_outbox_repository import DynamoDBOutboxRepository
    from src.infrastructure.persistence.dynamodb_unit_of_work import DynamoDBUnitOfWork
    from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository
    from src.presentation.api.v1.auth import get_auth_service
    from src.presentation.api.v1.roles import get_token_service as get_roles_token_service
    from src.presentation.api.v1.users import get_token_service, get_user_service

    session = aioboto3.Session()

    user_repo = DynamoDBUserRepository(
        table_name=settings.users_table,
        region=settings.aws_region,
        session=session,
    )

    from src.domain.value_objects.password_validator import PasswordValidator
    from src.infrastructure.persistence.dynamodb_token_blacklist import (
        DynamoDBTokenBlacklistRepository,
    )

    password_validator = PasswordValidator()

    token_blacklist = DynamoDBTokenBlacklistRepository(
        table_name=settings.token_blacklist_table,
        region=settings.aws_region,
        session=session,
    )

    token_service = JWTTokenService(
        private_key=settings.jwt_private_key,
        public_key=settings.jwt_public_key,
        key_id=settings.jwt_key_id,
        token_blacklist=token_blacklist,
        audience=settings.jwt_audience,
    )
    event_publisher = EventBridgePublisher(
        bus_name=settings.event_bus_name,
        region=settings.aws_region,
        session=session,
    )

    outbox_repo = DynamoDBOutboxRepository(
        table_name=settings.outbox_table,
        region=settings.aws_region,
        session=session,
    )
    unit_of_work = DynamoDBUnitOfWork(region=settings.aws_region, session=session)

    class _BcryptHasher:
        def hash(self, password: str) -> str:
            return _bcrypt_lib.hashpw(password.encode("utf-8"), _bcrypt_lib.gensalt()).decode(
                "utf-8"
            )

        def verify(self, plain: str, hashed: str) -> bool:
            return bool(_bcrypt_lib.checkpw(plain.encode("utf-8"), hashed.encode("utf-8")))

    auth_service = AuthService(
        user_repo=user_repo,
        token_service=token_service,
        password_hasher=_BcryptHasher(),
        token_blacklist=token_blacklist,
        password_validator=password_validator,
        event_publisher=event_publisher,
        service_accounts=_load_service_accounts(settings),
        outbox_repo=outbox_repo,
        unit_of_work=unit_of_work,
    )
    user_service = UserService(user_repo=user_repo, event_publisher=event_publisher)

    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_user_service] = lambda: user_service
    app.dependency_overrides[get_token_service] = lambda: token_service
    app.dependency_overrides[get_roles_token_service] = lambda: token_service


def create_app() -> FastAPI:
    """Application factory — single place for all wiring."""
    app = FastAPI(
        title="ugsys Identity Manager",
        version="0.1.0",
        docs_url="/docs" if settings.environment != "prod" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Middleware — order matters: outermost first
    # CORS must be first so OPTIONS preflights are handled before any other middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    if settings.xray_enabled:
        app.add_middleware(TracingMiddleware, service_name=settings.service_name)
    app.add_middleware(CorrelationIdMiddleware)

    # Exception handlers — registered before routers
    ExcHandler = Callable[[StarletteRequest, Exception], Awaitable[StarletteResponse]]
    app.add_exception_handler(
        DomainError,
        cast(ExcHandler, domain_exception_handler),
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Routers
    app.include_router(health.router)
    app.include_router(jwks.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(roles.router, prefix="/api/v1")

    return app


app = create_app()

# Lambda handler
handler = Mangum(app, lifespan="on")
