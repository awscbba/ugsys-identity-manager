"""Auth router — /api/v1/auth endpoints."""

import html

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator

from src.application.commands.authenticate_user import AuthenticateCommand
from src.application.commands.refresh_token import RefreshTokenCommand
from src.application.commands.register_user import RegisterUserCommand
from src.application.commands.reset_password import ForgotPasswordCommand, ResetPasswordCommand
from src.application.commands.service_token import ServiceTokenCommand, ValidateTokenCommand
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


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ValidateTokenRequest(BaseModel):
    token: str


class ServiceTokenRequest(BaseModel):
    client_id: str
    client_secret: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


class ServiceTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int = 3600


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


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    service: AuthService = Depends(get_auth_service),  # noqa: B008
) -> TokenResponse:
    try:
        tokens = await service.refresh(RefreshTokenCommand(refresh_token=body.refresh_token))
        logger.info("auth.refresh.success")
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(
    body: ForgotPasswordRequest,
    service: AuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    # Always return 200 — never reveal whether email exists (anti-enumeration)
    await service.forgot_password(ForgotPasswordCommand(email=str(body.email)))
    logger.info("auth.forgot_password.requested")
    return {"message": "If that email is registered, a reset link has been sent"}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    body: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    try:
        await service.reset_password(
            ResetPasswordCommand(token=body.token, new_password=body.new_password)
        )
        logger.info("auth.reset_password.success")
        return {"message": "Password updated successfully"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/validate-token", status_code=status.HTTP_200_OK)
async def validate_token(
    body: ValidateTokenRequest,
    service: AuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    """S2S token introspection — used by other services to validate JWTs."""
    try:
        payload = service.validate_token(ValidateTokenCommand(token=body.token))
        return {
            "valid": True,
            "sub": str(payload.get("sub")),
            "roles": list(payload.get("roles", [])),  # type: ignore[arg-type]
            "type": str(payload.get("type")),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e


@router.post("/service-token", response_model=ServiceTokenResponse)
async def service_token(
    body: ServiceTokenRequest,
    service: AuthService = Depends(get_auth_service),  # noqa: B008
) -> ServiceTokenResponse:
    """client_credentials grant — issues a service-to-service access token."""
    try:
        tokens = service.issue_service_token(
            ServiceTokenCommand(client_id=body.client_id, client_secret=body.client_secret)
        )
        logger.info("auth.service_token.issued", client_id=body.client_id)
        return ServiceTokenResponse(access_token=tokens.access_token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e
