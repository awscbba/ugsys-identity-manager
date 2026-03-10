"""HTTP integration tests for auth flows — moto DynamoDB + FastAPI."""

from __future__ import annotations

import httpx

from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STRONG_PASSWORD = "Str0ng!Pass#1"
_USERS_TABLE = "ugsys-identity-manager-users-test"


async def _register(
    client: httpx.AsyncClient, email: str, password: str = _STRONG_PASSWORD
) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Test User"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _get_verification_token(email: str) -> str:
    """Fetch the verification token directly from moto DynamoDB."""
    repo = DynamoDBUserRepository(table_name=_USERS_TABLE, region="us-east-1")
    user = await repo.find_by_email(email)
    assert user is not None
    assert user.email_verification_token is not None
    return user.email_verification_token


async def _verify_email(client: httpx.AsyncClient, token: str) -> None:
    resp = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert resp.status_code == 200, resp.text


async def _login(client: httpx.AsyncClient, email: str, password: str = _STRONG_PASSWORD) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _register_verify_login(
    client: httpx.AsyncClient, email: str, password: str = _STRONG_PASSWORD
) -> dict:
    """Full happy path: register → verify email → login. Returns login response JSON."""
    await _register(client, email, password)
    token = await _get_verification_token(email)
    await _verify_email(client, token)
    return await _login(client, email, password)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_register_verify_login_happy_path(app_client: httpx.AsyncClient) -> None:
    """Register → verify email → login returns access_token."""
    # Arrange
    email = "happy@test.com"

    # Act
    await _register(app_client, email)
    token = await _get_verification_token(email)
    await _verify_email(app_client, token)
    login_resp = await app_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _STRONG_PASSWORD}
    )

    # Assert
    assert login_resp.status_code == 200
    body = login_resp.json()
    assert "access_token" in body["data"]
    assert "refresh_token" in body["data"]
    assert body["data"]["token_type"] == "bearer"


async def test_register_duplicate_email_returns_409(app_client: httpx.AsyncClient) -> None:
    """Registering the same email twice returns 409 CONFLICT."""
    email = "dup@test.com"
    await _register(app_client, email)

    resp = await app_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _STRONG_PASSWORD, "full_name": "Dup User"},
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] in ("EMAIL_ALREADY_EXISTS", "CONFLICT")


async def test_login_before_email_verification_returns_401(app_client: httpx.AsyncClient) -> None:
    """Login before verifying email returns 401 with EMAIL_NOT_VERIFIED."""
    email = "unverified@test.com"
    await _register(app_client, email)

    resp = await app_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _STRONG_PASSWORD}
    )

    assert resp.status_code == 401
    body = resp.json()
    error_code = body.get("error", {}).get("code")
    email_not_verified_flag = body.get("data", {}).get("email_not_verified")
    assert error_code == "EMAIL_NOT_VERIFIED" or email_not_verified_flag is True


async def test_login_wrong_password_returns_401(app_client: httpx.AsyncClient) -> None:
    """Login with wrong password returns 401 INVALID_CREDENTIALS."""
    email = "wrongpw@test.com"
    await _register(app_client, email)
    token = await _get_verification_token(email)
    await _verify_email(app_client, token)

    resp = await app_client.post(
        "/api/v1/auth/login", json={"email": email, "password": "WrongPass!99"}
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_account_lockout_after_five_failures_returns_423(
    app_client: httpx.AsyncClient,
) -> None:
    """Five consecutive wrong passwords lock the account → 423 with retry_after_seconds."""
    email = "lockout@test.com"
    await _register(app_client, email)
    token = await _get_verification_token(email)
    await _verify_email(app_client, token)

    # 4 failures — should get 401 each time
    for _ in range(4):
        resp = await app_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "WrongPass!99"}
        )
        assert resp.status_code == 401

    # 5th failure — account locks → 423
    resp = await app_client.post(
        "/api/v1/auth/login", json={"email": email, "password": "WrongPass!99"}
    )
    assert resp.status_code == 423
    body = resp.json()
    assert body["error"]["code"] == "ACCOUNT_LOCKED"
    assert body["error"]["retry_after_seconds"] > 0


async def test_logout_then_token_reuse_returns_401(app_client: httpx.AsyncClient) -> None:
    """Logout blacklists the access token; reusing it returns 401."""
    email = "logout@test.com"
    login_body = await _register_verify_login(app_client, email)
    access_token = login_body["data"]["access_token"]

    # Logout
    logout_resp = await app_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_resp.status_code == 200

    # Reuse the same token — should be rejected
    reuse_resp = await app_client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert reuse_resp.status_code == 401


async def test_refresh_token_returns_new_access_token(app_client: httpx.AsyncClient) -> None:
    """POST /auth/refresh with a valid refresh_token returns a new access_token."""
    email = "refresh@test.com"
    login_body = await _register_verify_login(app_client, email)
    refresh_token = login_body["data"]["refresh_token"]

    resp = await app_client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body["data"]
    assert body["data"]["access_token"] != login_body["data"]["access_token"]


async def test_forgot_password_returns_200(app_client: httpx.AsyncClient) -> None:
    """POST /auth/forgot-password always returns 200 (anti-enumeration)."""
    email = "forgot@test.com"
    await _register(app_client, email)

    resp = await app_client.post("/api/v1/auth/forgot-password", json={"email": email})

    assert resp.status_code == 200
    assert "message" in resp.json()["data"]


async def test_forgot_password_nonexistent_email_still_200(app_client: httpx.AsyncClient) -> None:
    """Forgot password for unknown email still returns 200 (anti-enumeration)."""
    resp = await app_client.post("/api/v1/auth/forgot-password", json={"email": "nobody@test.com"})
    assert resp.status_code == 200


async def test_reset_password_with_valid_token(app_client: httpx.AsyncClient) -> None:
    """Forgot password → reset password with the returned token → login with new password."""
    email = "reset@test.com"
    await _register(app_client, email)
    token = await _get_verification_token(email)
    await _verify_email(app_client, token)

    # Get reset token directly from the service (simulate email delivery)
    from src.infrastructure.adapters.jwt_token_service import JWTTokenService
    from src.infrastructure.persistence.dynamodb_user_repository import (
        DynamoDBUserRepository as Repo,
    )
    from tests.integration.conftest import _JWT_PRIVATE_KEY_PEM, _JWT_PUBLIC_KEY_PEM

    repo = Repo(table_name=_USERS_TABLE, region="us-east-1")
    user = await repo.find_by_email(email)
    assert user is not None

    jwt_svc = JWTTokenService(
        private_key=_JWT_PRIVATE_KEY_PEM,
        public_key=_JWT_PUBLIC_KEY_PEM,
        key_id="test-key",
    )
    reset_token = jwt_svc.create_password_reset_token(user_id=user.id, email=email)

    new_password = "NewStr0ng!Pass#2"
    resp = await app_client.post(
        "/api/v1/auth/reset-password",
        json={"token": reset_token, "new_password": new_password},
    )
    assert resp.status_code == 200

    # Login with new password
    login_resp = await app_client.post(
        "/api/v1/auth/login", json={"email": email, "password": new_password}
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()["data"]
