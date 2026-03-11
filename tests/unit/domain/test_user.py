"""Unit and property tests for User.record_failed_login with configurable lockout params.

Feature: im-security-hardening
"""

from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from src.domain.entities.user import User


def _make_user() -> User:
    return User(email="test@example.com", hashed_password="hashed", full_name="Test User")


# ── Unit tests ────────────────────────────────────────────────────────────────


def test_lockout_at_custom_threshold() -> None:
    """record_failed_login(max_attempts=3) three times → is_locked() is True."""
    user = _make_user()
    for _ in range(3):
        user.record_failed_login(max_attempts=3)
    assert user.is_locked() is True


def test_no_lockout_below_threshold() -> None:
    """record_failed_login(max_attempts=3) twice → is_locked() is False."""
    user = _make_user()
    for _ in range(2):
        user.record_failed_login(max_attempts=3)
    assert user.is_locked() is False


def test_custom_lockout_duration() -> None:
    """account_locked_until is approximately now + lockout_minutes."""
    user = _make_user()
    before = datetime.now(UTC)
    user.record_failed_login(max_attempts=1, lockout_minutes=15)
    after = datetime.now(UTC)

    assert user.account_locked_until is not None
    expected_min = before + timedelta(minutes=15)
    expected_max = after + timedelta(minutes=15)
    assert expected_min <= user.account_locked_until <= expected_max


def test_default_params_preserve_backward_compatibility() -> None:
    """Default max_attempts=5, lockout_minutes=30 still work."""
    user = _make_user()
    for _ in range(5):
        user.record_failed_login()
    assert user.is_locked() is True


def test_four_failures_with_default_threshold_not_locked() -> None:
    """4 failures with default threshold → not locked."""
    user = _make_user()
    for _ in range(4):
        user.record_failed_login()
    assert user.is_locked() is False


# ── Property tests ────────────────────────────────────────────────────────────


# Feature: im-security-hardening, Property 3: Lockout at threshold
@given(st.integers(min_value=1, max_value=20))
@settings(max_examples=100)
def test_property_lockout_at_threshold(max_attempts: int) -> None:
    """For all max_attempts in [1,20], exactly max_attempts failures → is_locked() is True."""
    user = _make_user()
    for _ in range(max_attempts):
        user.record_failed_login(max_attempts=max_attempts)
    assert user.is_locked() is True


# Feature: im-security-hardening, Property 4: No lockout below threshold
@given(st.integers(min_value=2, max_value=20))
@settings(max_examples=100)
def test_property_no_lockout_below_threshold(max_attempts: int) -> None:
    """For all max_attempts in [2,20], max_attempts-1 failures → is_locked() is False."""
    user = _make_user()
    for _ in range(max_attempts - 1):
        user.record_failed_login(max_attempts=max_attempts)
    assert user.is_locked() is False
