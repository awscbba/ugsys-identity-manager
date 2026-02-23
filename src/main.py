"""Composition root — wires all dependencies and starts the FastAPI app."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from mangum import Mangum

from src.config import settings
from src.infrastructure.logging import configure_logging
from src.presentation.api.v1 import auth, health, users
from src.presentation.middleware.correlation_id import CorrelationIdMiddleware
from src.presentation.middleware.rate_limiting import RateLimitMiddleware
from src.presentation.middleware.request_logging import RequestLoggingMiddleware
from src.presentation.middleware.security_headers import SecurityHeadersMiddleware

configure_logging(settings.service_name, settings.log_level)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    logger.info("startup", service=settings.service_name, environment=settings.environment)
    _wire_dependencies(app)
    yield
    logger.info("shutdown", service=settings.service_name)


def _wire_dependencies(app: FastAPI) -> None:
    """Wire infrastructure adapters into presentation layer via dependency overrides."""
    from src.application.services.auth_service import AuthService
    from src.infrastructure.adapters.jwt_token_service import JWTTokenService
    from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository
    from src.presentation.api.v1.auth import get_auth_service

    user_repo = DynamoDBUserRepository(
        table_name=settings.users_table,
        region=settings.aws_region,
    )
    token_service = JWTTokenService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    # Inline bcrypt hasher — no external dep needed beyond passlib (already in pyproject.toml)
    from passlib.context import CryptContext  # type: ignore[import-untyped]

    _pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

    class _BcryptHasher:
        def hash(self, password: str) -> str:
            return _pwd_ctx.hash(password)

        def verify(self, plain: str, hashed: str) -> bool:
            return _pwd_ctx.verify(plain, hashed)

    auth_service = AuthService(
        user_repo=user_repo,
        token_service=token_service,
        password_hasher=_BcryptHasher(),
    )
    app.dependency_overrides[get_auth_service] = lambda: auth_service


app = FastAPI(
    title="ugsys Identity Manager",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# Middleware — order matters: outermost first
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)

# Routers
app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")

# Lambda handler
handler = Mangum(app, lifespan="on")
