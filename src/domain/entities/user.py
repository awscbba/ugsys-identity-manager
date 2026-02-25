"""User entity — core domain object."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_VERIFICATION = "pending_verification"


class UserRole(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MODERATOR = "moderator"
    AUDITOR = "auditor"
    MEMBER = "member"
    GUEST = "guest"
    SYSTEM = "system"


@dataclass
class User:
    email: str
    hashed_password: str
    full_name: str
    id: UUID = field(default_factory=uuid4)
    status: UserStatus = UserStatus.PENDING_VERIFICATION
    roles: list[UserRole] = field(default_factory=lambda: [UserRole.MEMBER])
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Security fields
    failed_login_attempts: int = 0
    account_locked_until: datetime | None = None
    last_login_at: datetime | None = None
    last_password_change: datetime | None = None
    require_password_change: bool = False

    # Verification fields
    email_verified: bool = False
    email_verification_token: str | None = None
    email_verified_at: datetime | None = None

    # Legacy compatibility
    is_admin: bool = False

    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    def has_role(self, role: UserRole) -> bool:
        return role in self.roles

    def activate(self) -> None:
        self.status = UserStatus.ACTIVE
        self.updated_at = datetime.now(UTC)

    def deactivate(self) -> None:
        self.status = UserStatus.INACTIVE
        self.updated_at = datetime.now(UTC)

    def assign_role(self, role: UserRole) -> None:
        if role not in self.roles:
            self.roles.append(role)
            self.updated_at = datetime.now(UTC)

    def remove_role(self, role: UserRole) -> None:
        if role in self.roles:
            self.roles.remove(role)
            self.updated_at = datetime.now(UTC)

    def update_profile(self, full_name: str) -> None:
        self.full_name = full_name
        self.updated_at = datetime.now(UTC)

    def is_locked(self) -> bool:
        """True when account_locked_until is set and in the future."""
        if self.account_locked_until is None:
            return False
        return self.account_locked_until > datetime.now(UTC)

    def record_failed_login(self) -> None:
        """Increment failed_login_attempts; lock for 30 min at 5 failures."""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= 5:
            self.account_locked_until = datetime.now(UTC) + timedelta(minutes=30)

    def reset_login_attempts(self) -> None:
        """Reset failed_login_attempts to 0 and clear account_locked_until."""
        self.failed_login_attempts = 0
        self.account_locked_until = None

    def record_successful_login(self) -> None:
        """Call reset_login_attempts() and set last_login_at to now UTC."""
        self.reset_login_attempts()
        self.last_login_at = datetime.now(UTC)

    def verify_email(self) -> None:
        """Set status=active, email_verified=True, email_verified_at=now, clear token."""
        self.status = UserStatus.ACTIVE
        self.email_verified = True
        self.email_verified_at = datetime.now(UTC)
        self.email_verification_token = None

    def generate_verification_token(self) -> str:
        """Generate UUID4 token, store on entity, return it."""
        token = str(uuid4())
        self.email_verification_token = token
        return token
