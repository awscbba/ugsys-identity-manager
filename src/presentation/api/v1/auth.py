"""Auth router — /api/v1/auth endpoints."""

import html

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator

from src.application.commands.authenticate_user import AuthenticateCommand
from src.application.commands.register_user import RegisterUserCommand
from src.application.services.auth_service import AuthService

logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str

    @field_validator("full_name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        return html.escape(v.strip())


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


def get_auth_service() -> AuthService:  # pragma: no cover
    """Dependency — overridden in main.py via app.dependency_overrides."""
    raise NotImplementedError("AuthService not wired")


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    service: AuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    try:
        user = await service.register(
            RegisterUserCommand(
                email=str(body.email),
                password=body.password,
                full_name=body.full_name,
            )
        )
        logger.info("auth.register.success", user_id=str(user.id))
        return {"message": "User registered", "user_id": str(user.id)}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    service: AuthService = Depends(get_auth_service),  # noqa: B008
) -> TokenResponse:
    try:
        tokens = await service.authenticate(
            AuthenticateCommand(email=str(body.email), password=body.password)
        )
        logger.info("auth.login.success")
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e


@router.post("/refresh")
async def refresh(refresh_token: str) -> TokenResponse:
    # TODO: implement refresh token flow
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")
