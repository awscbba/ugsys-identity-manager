"""User entity — core domain object."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_VERIFICATION = "pending_verification"


class UserRole(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MEMBER = "member"


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
