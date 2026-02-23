"""Unit tests for domain entities and value objects."""

import pytest

from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.value_objects.email import Email

# ── User entity ───────────────────────────────────────────────────────────


def test_user_defaults() -> None:
    user = User(email="a@b.com", hashed_password="h", full_name="A B")
    assert user.status == UserStatus.PENDING_VERIFICATION
    assert UserRole.MEMBER in user.roles
    assert user.id is not None


def test_user_is_active_false_by_default() -> None:
    user = User(email="a@b.com", hashed_password="h", full_name="A B")
    assert not user.is_active()


def test_user_activate() -> None:
    user = User(email="a@b.com", hashed_password="h", full_name="A B")
    user.activate()
    assert user.is_active()
    assert user.status == UserStatus.ACTIVE


def test_user_has_role() -> None:
    user = User(email="a@b.com", hashed_password="h", full_name="A B", roles=[UserRole.ADMIN])
    assert user.has_role(UserRole.ADMIN)
    assert not user.has_role(UserRole.SUPER_ADMIN)


def test_user_inactive_status() -> None:
    user = User(email="a@b.com", hashed_password="h", full_name="A B", status=UserStatus.INACTIVE)
    assert not user.is_active()


# ── Email value object ────────────────────────────────────────────────────


def test_email_valid() -> None:
    email = Email("user@example.com")
    assert str(email) == "user@example.com"


def test_email_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Invalid email"):
        Email("not-an-email")


def test_email_immutable() -> None:
    email = Email("user@example.com")
    with pytest.raises(AttributeError):  # frozen dataclass raises AttributeError
        email.value = "other@example.com"  # type: ignore[misc]
