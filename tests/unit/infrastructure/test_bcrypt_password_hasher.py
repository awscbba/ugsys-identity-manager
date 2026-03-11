"""Unit tests for BcryptPasswordHasher."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.infrastructure.adapters.bcrypt_password_hasher import BcryptPasswordHasher


class TestBcryptPasswordHasher:
    def test_hash_verify_round_trip(self) -> None:
        hasher = BcryptPasswordHasher(rounds=12)
        hashed = hasher.hash("correct-horse-battery-staple")
        assert hasher.verify("correct-horse-battery-staple", hashed) is True

    def test_wrong_password_returns_false(self) -> None:
        hasher = BcryptPasswordHasher(rounds=12)
        hashed = hasher.hash("password1")
        assert hasher.verify("password2", hashed) is False

    def test_rounds_guard_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="bcrypt rounds must be >= 12"):
            BcryptPasswordHasher(rounds=11)

    def test_rounds_guard_accepts_minimum(self) -> None:
        # Should not raise
        hasher = BcryptPasswordHasher(rounds=12)
        assert hasher._rounds == 12

    def test_salt_uniqueness(self) -> None:
        hasher = BcryptPasswordHasher(rounds=12)
        password = "same-password"
        hash1 = hasher.hash(password)
        hash2 = hasher.hash(password)
        assert hash1 != hash2

    def test_verify_does_not_raise_on_wrong_password(self) -> None:
        hasher = BcryptPasswordHasher(rounds=12)
        hashed = hasher.hash("original")
        # Must not raise — just return False
        result = hasher.verify("wrong", hashed)
        assert result is False


class TestBcryptPasswordHasherProperties:
    # Feature: im-security-hardening, Property 1: Bcrypt round-trip
    @given(st.text(min_size=1, max_size=72))
    @settings(max_examples=20, deadline=None)  # bcrypt at rounds=12 exceeds default 200ms deadline
    def test_property_round_trip(self, password: str) -> None:
        """For all valid passwords, verify(p, hash(p)) is True."""
        hasher = BcryptPasswordHasher(rounds=12)
        assert hasher.verify(password, hasher.hash(password)) is True

    # Feature: im-security-hardening, Property 2: Salt uniqueness
    @given(st.text(min_size=1, max_size=72))
    @settings(max_examples=20, deadline=None)
    def test_property_salt_uniqueness(self, password: str) -> None:
        """For all passwords, two independent hash calls produce different hashes."""
        hasher = BcryptPasswordHasher(rounds=12)
        assert hasher.hash(password) != hasher.hash(password)
