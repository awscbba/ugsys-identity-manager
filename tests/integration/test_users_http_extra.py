"""HTTP integration tests for user endpoints not covered in test_users_http.py."""

from __future__ import annotations

import httpx

from src.domain.entities.user import UserRole
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


async def _make_admin(email: str) -> None:
    repo = DynamoDBUserRepository(table_name=_USERS_TABLE, region="us-east-1")
    user = await repo.find_by_email(email)
    assert user is not None
    user.assign_role(UserRole.ADMIN)
    await repo.update(user)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /users/me
# ---------------------------------------------------------------------------


async def test_get_me_returns_own_profile(app_client: httpx.AsyncClient) -> None:
    """GET /users/me returns the authenticated user's profile."""
    login_body = await _register_verify_login(app_client, "me@test.com")
    token = login_body["data"]["access_token"]

    resp = await app_client.get("/api/v1/users/me", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["email"] == "me@test.com"
    assert "id" in body["data"]


async def test_get_me_without_token_returns_401(app_client: httpx.AsyncClient) -> None:
    """GET /users/me without Authorization header returns 401."""
    resp = await app_client.get("/api/v1/users/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /users/{id} — update profile
# ---------------------------------------------------------------------------


async def test_update_profile_own_name(app_client: httpx.AsyncClient) -> None:
    """PATCH /users/{id} updates the user's full_name."""
    login_body = await _register_verify_login(app_client, "patch@test.com")
    token = login_body["data"]["access_token"]
    user_id = (
        login_body["data"].get("user_id")
        or (await app_client.get("/api/v1/users/me", headers=_auth(token))).json()["data"]["id"]
    )

    resp = await app_client.patch(
        f"/api/v1/users/{user_id}",
        json={"full_name": "Updated Name"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["full_name"] == "Updated Name"


async def test_update_profile_other_user_returns_403(app_client: httpx.AsyncClient) -> None:
    """PATCH /users/{other_id} by a non-admin returns 403."""
    login_a = await _register_verify_login(app_client, "user-a@test.com")
    login_b = await _register_verify_login(app_client, "user-b@test.com")
    token_a = login_a["data"]["access_token"]

    me_b = await app_client.get("/api/v1/users/me", headers=_auth(login_b["data"]["access_token"]))
    user_b_id = me_b.json()["data"]["id"]

    resp = await app_client.patch(
        f"/api/v1/users/{user_b_id}",
        json={"full_name": "Hacked"},
        headers=_auth(token_a),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /users/{id}/roles
# ---------------------------------------------------------------------------


async def test_get_own_roles(app_client: httpx.AsyncClient) -> None:
    """GET /users/{id}/roles returns the user's roles."""
    login_body = await _register_verify_login(app_client, "roles@test.com")
    token = login_body["data"]["access_token"]
    me = await app_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me.json()["data"]["id"]

    resp = await app_client.get(f"/api/v1/users/{user_id}/roles", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert "member" in body["data"]["roles"]


# ---------------------------------------------------------------------------
# PUT /users/{id}/roles/{role} and DELETE /users/{id}/roles/{role}
# ---------------------------------------------------------------------------


async def test_assign_and_remove_role(app_client: httpx.AsyncClient) -> None:
    """Admin assigns a role then removes it — both operations persist correctly."""
    admin_email = "admin-roles@test.com"
    target_email = "target-roles@test.com"

    await _register_verify_login(app_client, admin_email)
    await _register_verify_login(app_client, target_email)
    await _make_admin(admin_email)

    admin_login = await app_client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": _STRONG_PASSWORD}
    )
    admin_token = admin_login.json()["data"]["access_token"]

    repo = DynamoDBUserRepository(table_name=_USERS_TABLE, region="us-east-1")
    target = await repo.find_by_email(target_email)
    assert target is not None
    target_id = str(target.id)

    # Assign moderator role
    assign_resp = await app_client.put(
        f"/api/v1/users/{target_id}/roles/moderator", headers=_auth(admin_token)
    )
    assert assign_resp.status_code == 200
    assert "moderator" in assign_resp.json()["data"]["roles"]

    # Remove moderator role
    remove_resp = await app_client.delete(
        f"/api/v1/users/{target_id}/roles/moderator", headers=_auth(admin_token)
    )
    assert remove_resp.status_code == 200
    assert "moderator" not in remove_resp.json()["data"]["roles"]


# ---------------------------------------------------------------------------
# GET /roles
# ---------------------------------------------------------------------------


async def test_list_roles_as_admin(app_client: httpx.AsyncClient) -> None:
    """GET /roles returns all system roles for an admin."""
    admin_email = "admin-listroles@test.com"
    await _register_verify_login(app_client, admin_email)
    await _make_admin(admin_email)

    admin_login = await app_client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": _STRONG_PASSWORD}
    )
    admin_token = admin_login.json()["data"]["access_token"]

    resp = await app_client.get("/api/v1/roles", headers=_auth(admin_token))

    assert resp.status_code == 200
    roles = resp.json()["roles"]
    role_names = [r["name"] for r in roles]
    assert "member" in role_names
    assert "admin" in role_names


async def test_list_roles_as_non_admin_returns_403(app_client: httpx.AsyncClient) -> None:
    """GET /roles returns 403 for non-admin users."""
    login_body = await _register_verify_login(app_client, "member-roles@test.com")
    token = login_body["data"]["access_token"]

    resp = await app_client.get("/api/v1/roles", headers=_auth(token))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /users/{id} — deactivate
# ---------------------------------------------------------------------------


async def test_deactivate_own_account(app_client: httpx.AsyncClient) -> None:
    """DELETE /users/{id} deactivates the user's own account."""
    login_body = await _register_verify_login(app_client, "deactivate@test.com")
    token = login_body["data"]["access_token"]
    me = await app_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me.json()["data"]["id"]

    resp = await app_client.delete(f"/api/v1/users/{user_id}", headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "inactive"
