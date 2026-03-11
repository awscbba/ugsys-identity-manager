"""IAuthService — inbound port interface for the auth application service.

Imports only from domain and application layers — never from infrastructure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.commands.authenticate_user import AuthenticateCommand, TokenPair
    from src.application.commands.logout import LogoutCommand
    from src.application.commands.refresh_token import RefreshTokenCommand
    from src.application.commands.register_user import RegisterUserCommand
    from src.application.commands.resend_verification import ResendVerificationCommand
    from src.application.commands.reset_password import ForgotPasswordCommand, ResetPasswordCommand
    from src.application.commands.service_token import ServiceTokenCommand, ValidateTokenCommand
    from src.application.commands.verify_email import VerifyEmailCommand
    from src.domain.entities.user import User


class IAuthService(ABC):
    """Inbound port — defines the contract for the auth application service."""

    @abstractmethod
    async def register(self, command: RegisterUserCommand) -> User: ...

    @abstractmethod
    async def authenticate(self, command: AuthenticateCommand) -> TokenPair: ...

    @abstractmethod
    async def refresh(self, command: RefreshTokenCommand) -> TokenPair: ...

    @abstractmethod
    async def forgot_password(self, command: ForgotPasswordCommand) -> str | None: ...

    @abstractmethod
    async def reset_password(self, command: ResetPasswordCommand) -> None: ...

    @abstractmethod
    async def validate_token(self, command: ValidateTokenCommand) -> dict[str, object]: ...

    @abstractmethod
    def issue_service_token(self, command: ServiceTokenCommand) -> TokenPair: ...

    @abstractmethod
    async def verify_email(self, command: VerifyEmailCommand) -> None: ...

    @abstractmethod
    async def resend_verification(self, command: ResendVerificationCommand) -> None: ...

    @abstractmethod
    async def logout(self, command: LogoutCommand) -> None: ...
