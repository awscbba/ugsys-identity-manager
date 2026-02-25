"""HTTP integration tests for user management — moto DynamoDB + FastAPI."""

from __future__ import annotations

import httpx

from src.domain.entities.user import UserRole
from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository

_STRONG_PASSWORD = "Str0ng!Pass#1"
_USERS_TABLE = "ugsys-identity-manager-users-test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register_verify_login(
    client: httpx.AsyncClient,
    email: str,
    password: str = _STRONG_PASSWORD,
) -> dict:
    """Register → verify email → login. Returns login response JSON."""
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


async def _make_admin(email: str) -> str:
    """Assign admin role to a user directly in DynamoDB. Returns user_id."""
    repo = DynamoDBUserRepository(table_name=_USERS_TABLE, region="us-east-1")
    user = await repo.find_by_email(email)
    assert user is not None
    user.assign_role(UserRole.ADMIN)
    await repo.update(user)
    return str(user.id)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_list_users_as_admin_returns_paginated_envelope(
    app_client: httpx.AsyncClient,
) -> None:
    """Admin can list users; response has pagination metadata."""
    # Create 3 users
    emails = ["u1@test.com", "u2@test.com", "u3@test.com"]
    for email in emails:
        await _register_verify_login(app_client, email)

    # Promote first user to admin and log in again to get a fresh token
    await _make_admin(emails[0])
    login = await app_client.post(
        "/api/v1/auth/login", json={"email": emails[0], "password": _STRONG_PASSWORD}
    )
    assert login.status_code == 200
    admin_token = login.json()["data"]["access_token"]

    resp = await app_client.get("/api/v1/users", headers=_auth(admin_token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 3
    assert isinstance(body["data"], list)
    assert len(body["data"]) >= 1


async def test_list_users_as_non_admin_returns_403(app_client: httpx.AsyncClient) -> None:
    """Non-admin user gets 403 when listing users."""
    login_body = await _register_verify_login(app_client, "member@test.com")
    token = login_body["data"]["access_token"]

    resp = await app_client.get("/api/v1/users", headers=_auth(token))

    assert resp.status_code == 403


async def test_suspend_user_sets_status_inactive(app_client: httpx.AsyncClient) -> None:
    """Admin suspends a user → user status becomes inactive in DynamoDB."""
    admin_email = "admin-suspend@test.com"
    target_email = "target-suspend@test.com"

    await _register_verify_login(app_client, admin_email)
    await _register_verify_login(app_client, target_email)

    await _make_admin(admin_email)
    admin_login = await app_client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": _STRONG_PASSWORD}
    )
    admin_token = admin_login.json()["data"]["access_token"]

    # Get target user_id from the login response
    repo = DynamoDBUserRepository(table_name=_USERS_TABLE, region="us-east-1")
    target_user = await repo.find_by_email(target_email)
    assert target_user is not None
    target_id = str(target_user.id)

    resp = await app_client.post(f"/api/v1/users/{target_id}/suspend", headers=_auth(admin_token))

    assert resp.status_code == 200
    # Verify status in DynamoDB
    updated = await repo.find_by_id(target_user.id)
    assert updated is not None
    assert updated.status.value == "inactive"


async def test_activate_user_restores_active_status(app_client: httpx.AsyncClient) -> None:
    """Admin activates a suspended user → status becomes active."""
    admin_email = "admin-activate@test.com"
    target_email = "target-activate@test.com"

    await _register_verify_login(app_client, admin_email)
    await _register_verify_login(app_client, target_email)

    await _make_admin(admin_email)
    admin_login = await app_client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": _STRONG_PASSWORD}
    )
    admin_token = admin_login.json()["data"]["access_token"]

    repo = DynamoDBUserRepository(table_name=_USERS_TABLE, region="us-east-1")
    target_user = await repo.find_by_email(target_email)
    assert target_user is not None
    target_id = str(target_user.id)

    # Suspend first
    await app_client.post(f"/api/v1/users/{target_id}/suspend", headers=_auth(admin_token))

    # Then activate
    resp = await app_client.post(f"/api/v1/users/{target_id}/activate", headers=_auth(admin_token))

    assert resp.status_code == 200
    updated = await repo.find_by_id(target_user.id)
    assert updated is not None
    assert updated.status.value == "active"


async def test_require_password_change_sets_flag(app_client: httpx.AsyncClient) -> None:
    """Admin sets require_password_change flag → flag is persisted in DynamoDB."""
    admin_email = "admin-pwchange@test.com"
    target_email = "target-pwchange@test.com"

    await _register_verify_login(app_client, admin_email)
    await _register_verify_login(app_client, target_email)

    await _make_admin(admin_email)
    admin_login = await app_client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": _STRONG_PASSWORD}
    )
    admin_token = admin_login.json()["data"]["access_token"]

    repo = DynamoDBUserRepository(table_name=_USERS_TABLE, region="us-east-1")
    target_user = await repo.find_by_email(target_email)
    assert target_user is not None
    target_id = str(target_user.id)

    resp = await app_client.post(
        f"/api/v1/users/{target_id}/require-password-change", headers=_auth(admin_token)
    )

    assert resp.status_code == 200
    updated = await repo.find_by_id(target_user.id)
    assert updated is not None
    assert updated.require_password_change is True


async def test_get_user_by_id_returns_correct_data(app_client: httpx.AsyncClient) -> None:
    """Admin fetches a specific user by ID → envelope with correct user data."""
    admin_email = "admin-getuser@test.com"
    target_email = "target-getuser@test.com"

    await _register_verify_login(app_client, admin_email)
    await _register_verify_login(app_client, target_email)

    await _make_admin(admin_email)
    admin_login = await app_client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": _STRONG_PASSWORD}
    )
    admin_token = admin_login.json()["data"]["access_token"]

    repo = DynamoDBUserRepository(table_name=_USERS_TABLE, region="us-east-1")
    target_user = await repo.find_by_email(target_email)
    assert target_user is not None
    target_id = str(target_user.id)

    resp = await app_client.get(f"/api/v1/users/{target_id}", headers=_auth(admin_token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["id"] == target_id
    assert body["data"]["email"] == target_email
