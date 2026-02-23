"""FastAPI application entry point."""

import structlog
from fastapi import FastAPI
from mangum import Mangum

from src.api.middleware.logging import LoggingMiddleware
from src.api.routers import auth, users

logger = structlog.get_logger()

app = FastAPI(
    title="ugsys Identity Manager",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(LoggingMiddleware)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "ugsys-identity-manager"}


# Lambda handler
handler = Mangum(app, lifespan="off")
