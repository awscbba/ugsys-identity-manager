"""Auth router — /api/v1/auth endpoints."""

import structlog
from fastapi import APIRouter, Cookie, Depends, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.application.commands.authenticate_user import AuthenticateCommand
from src.application.commands.logout import LogoutCommand
from src.application.commands.refresh_token import RefreshTokenCommand
from src.application.commands.register_user import RegisterUserCommand
from src.application.commands.resend_verification import ResendVerificationCommand
from src.application.commands.reset_password import ForgotPasswordCommand, ResetPasswordCommand
from src.application.commands.service_token import ServiceTokenCommand, ValidateTokenCommand
from src.application.commands.verify_email import VerifyEmailCommand
from src.application.dtos.auth_dtos import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    ServiceTokenRequest,
    ValidateTokenRequest,
    VerifyEmailRequest,
)
from src.application.interfaces.auth_service import IAuthService
from src.config import settings
from src.domain.exceptions import AuthenticationError
from src.presentation.middleware.correlation_id import correlation_id_var
from src.presentation.response_envelope import success_response

logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer()

# Refresh token cookie TTL — matches jwt_refresh_ttl_days (7 days in seconds)
_REFRESH_COOKIE_MAX_AGE = 7 * 24 * 60 * 60


# ── Dependency ────────────────────────────────────────────────────────────────


def get_auth_service() -> IAuthService:  # pragma: no cover
    """Dependency — overridden in main.py via app.dependency_overrides."""
    raise NotImplementedError("AuthService not wired")


# ── Cookie helpers ────────────────────────────────────────────────────────────


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Set the httpOnly refresh token cookie scoped to the platform domain."""
    response.set_cookie(
        key=settings.refresh_token_cookie_name,
        value=token,
        max_age=_REFRESH_COOKIE_MAX_AGE,
        path="/api/v1/auth",
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Expire the refresh token cookie immediately."""
    response.set_cookie(
        key=settings.refresh_token_cookie_name,
        value="",
        max_age=0,
        path="/api/v1/auth",
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    service: IAuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    user = await service.register(
        RegisterUserCommand(
            email=str(body.email),
            password=body.password,
            full_name=body.full_name,
        )
    )
    logger.info("auth.register.success", user_id=str(user.id))
    request_id = correlation_id_var.get("")
    return success_response({"message": "User registered", "user_id": str(user.id)}, request_id)


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    service: IAuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    tokens = await service.authenticate(
        AuthenticateCommand(email=str(body.email), password=body.password)
    )
    logger.info("auth.login.success")
    # Set httpOnly cookie for browser clients (cross-subdomain session persistence)
    _set_refresh_cookie(response, tokens.refresh_token)
    request_id = correlation_id_var.get("")
    data: dict[str, object] = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,  # kept for non-browser / API clients
        "token_type": "bearer",
        "expires_in": 1800,  # 30 minutes in seconds — matches jwt_access_ttl_minutes
    }
    if hasattr(tokens, "require_password_change") and tokens.require_password_change:
        data["require_password_change"] = True
    return success_response(data, request_id)


@router.post("/refresh")
async def refresh(
    body: RefreshRequest,
    response: Response,
    ugsys_refresh_token: str | None = Cookie(default=None),
    service: IAuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    # Cookie-first precedence: browser clients use the httpOnly cookie;
    # non-browser / API clients fall back to the JSON body token.
    token = ugsys_refresh_token or body.refresh_token
    if not token:
        _clear_refresh_cookie(response)
        raise AuthenticationError(
            message="No refresh token provided in cookie or body",
            user_message="Session expired. Please log in again.",
            error_code="MISSING_REFRESH_TOKEN",
        )
    try:
        tokens = await service.refresh(RefreshTokenCommand(refresh_token=token))
    except Exception:
        _clear_refresh_cookie(response)
        raise
    logger.info("auth.refresh.success")
    _set_refresh_cookie(response, tokens.refresh_token)
    request_id = correlation_id_var.get("")
    return success_response(
        {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": "bearer",
        },
        request_id,
    )


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(
    body: ForgotPasswordRequest,
    service: IAuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    # Always return 200 — never reveal whether email exists (anti-enumeration)
    await service.forgot_password(ForgotPasswordCommand(email=str(body.email)))
    logger.info("auth.forgot_password.requested")
    request_id = correlation_id_var.get("")
    return success_response(
        {"message": "If that email is registered, a reset link has been sent"}, request_id
    )


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    body: ResetPasswordRequest,
    service: IAuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    await service.reset_password(
        ResetPasswordCommand(token=body.token, new_password=body.new_password)
    )
    logger.info("auth.reset_password.success")
    request_id = correlation_id_var.get("")
    return success_response({"message": "Password updated successfully"}, request_id)


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(
    body: VerifyEmailRequest,
    service: IAuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    """Verify a user's email address using the verification token."""
    await service.verify_email(VerifyEmailCommand(token=body.token))
    logger.info("auth.verify_email.success")
    request_id = correlation_id_var.get("")
    return success_response({"message": "Email verified successfully"}, request_id)


@router.post("/resend-verification", status_code=status.HTTP_200_OK)
async def resend_verification(
    body: ResendVerificationRequest,
    service: IAuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    """Resend email verification — always returns 200 (anti-enumeration)."""
    await service.resend_verification(ResendVerificationCommand(email=str(body.email)))
    logger.info("auth.resend_verification.requested")
    request_id = correlation_id_var.get("")
    msg = "If that email is registered and pending verification, a new link has been sent"
    return success_response({"message": msg}, request_id)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    body: LogoutRequest,
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(bearer),  # noqa: B008
    ugsys_refresh_token: str | None = Cookie(default=None),
    service: IAuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    """Logout — blacklists both the access token and the refresh token."""
    # Cookie-first precedence for the refresh token
    refresh_token = ugsys_refresh_token or body.refresh_token
    await service.logout(
        LogoutCommand(
            access_token=credentials.credentials,
            refresh_token=refresh_token,
        )
    )
    _clear_refresh_cookie(response)
    logger.info("auth.logout.success")
    request_id = correlation_id_var.get("")
    return success_response({"message": "Logged out successfully"}, request_id)


@router.post("/validate-token", status_code=status.HTTP_200_OK)
async def validate_token(
    body: ValidateTokenRequest,
    service: IAuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    """S2S token introspection — used by other services to validate JWTs."""
    result = await service.validate_token(ValidateTokenCommand(token=body.token))
    request_id = correlation_id_var.get("")
    return success_response(result, request_id)


@router.post("/service-token", status_code=status.HTTP_200_OK)
async def service_token(
    body: ServiceTokenRequest,
    service: IAuthService = Depends(get_auth_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    """client_credentials grant — issues a service-to-service access token."""
    tokens = service.issue_service_token(
        ServiceTokenCommand(client_id=body.client_id, client_secret=body.client_secret)
    )
    logger.info("auth.service_token.issued", client_id=body.client_id)
    request_id = correlation_id_var.get("")
    return success_response(
        {
            "access_token": tokens.access_token,
            "token_type": "bearer",
            "expires_in": 3600,
        },
        request_id,
    )
