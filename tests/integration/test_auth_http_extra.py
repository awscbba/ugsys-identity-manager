"""HTTP integration tests for auth endpoints not covered in test_auth_http.py."""

from __future__ import annotations

import httpx

from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository

_STRONG_PASSWORD = "Str0ng!Pass#1"
_USERS_TABLE = "ugsys-identity-manager-users-test"


async def _register_verify_login(
    client: httpx.AsyncClient, email: str, password: str = _STRONG_PASSWORD
) -> dict:
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Test User"},
    )
    assert reg.status_code == 201, reg.text

    repo = DynamoDBUserRepository(table_name=_USERS_TABLE, region="us-east-1")
    user = await repo.find_by_email(email)
    assert user is not None and user.email_verification_token is not None

    verify = await client.post(
        "/api/v1/auth/verify-email", json={"token": user.email_verification_token}
    )
    assert verify.status_code == 200, verify.text

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()


# ---------------------------------------------------------------------------
# resend-verification
# ---------------------------------------------------------------------------


async def test_resend_verification_returns_200(app_client: httpx.AsyncClient) -> None:
    """POST /auth/resend-verification always returns 200 (anti-enumeration)."""
    email = "resend@test.com"
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _STRONG_PASSWORD, "full_name": "Resend User"},
    )

    resp = await app_client.post("/api/v1/auth/resend-verification", json={"email": email})

    assert resp.status_code == 200
    assert "message" in resp.json()["data"]


async def test_resend_verification_unknown_email_still_200(app_client: httpx.AsyncClient) -> None:
    """Resend for unknown email must return 200 (anti-enumeration)."""
    resp = await app_client.post(
        "/api/v1/auth/resend-verification", json={"email": "ghost@test.com"}
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# validate-token
# ---------------------------------------------------------------------------


async def test_validate_token_valid_returns_true(app_client: httpx.AsyncClient) -> None:
    """POST /auth/validate-token with a valid token returns valid=true."""
    login_body = await _register_verify_login(app_client, "validate@test.com")
    access_token = login_body["data"]["access_token"]

    resp = await app_client.post("/api/v1/auth/validate-token", json={"token": access_token})

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["valid"] is True
    assert "sub" in body["data"]
    assert body["data"]["type"] == "access"


async def test_validate_token_invalid_returns_false(app_client: httpx.AsyncClient) -> None:
    """POST /auth/validate-token with a garbage token returns valid=false (never 4xx)."""
    resp = await app_client.post("/api/v1/auth/validate-token", json={"token": "not.a.token"})

    assert resp.status_code == 200
    assert resp.json()["data"]["valid"] is False


# ---------------------------------------------------------------------------
# service-token
# ---------------------------------------------------------------------------


async def test_service_token_unknown_client_returns_401(app_client: httpx.AsyncClient) -> None:
    """POST /auth/service-token with unknown client_id returns 401."""
    resp = await app_client.post(
        "/api/v1/auth/service-token",
        json={"client_id": "unknown-service", "client_secret": "whatever"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CLIENT_CREDENTIALS"
