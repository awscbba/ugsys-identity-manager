#!/usr/bin/env python3
"""
Acceptance smoke test for ugsys-identity-manager deployed API.

Covers the full register → verify-email → login → logout flow by reading
the verification token directly from DynamoDB (since omnichannel email
delivery is not yet built).

Usage:
    IDENTITY_API_URL=https://<id>.execute-api.us-east-1.amazonaws.com \
    AWS_PROFILE=awscbba \
    uv run python scripts/smoke_test.py

Environment variables:
    IDENTITY_API_URL   Base URL of the deployed API (required)
    DYNAMO_TABLE       DynamoDB table name (default: ugsys-identity-manager-users-prod)
    AWS_REGION         AWS region (default: us-east-1)
    AWS_PROFILE        AWS CLI profile (optional)
"""

import os
import sys
import time
import uuid

import boto3
import httpx
from boto3.dynamodb.conditions import Attr

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = os.environ.get("IDENTITY_API_URL", "").rstrip("/")
TABLE_NAME = os.environ.get("DYNAMO_TABLE", "ugsys-identity-manager-users-prod")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

if not BASE_URL:
    print("ERROR: IDENTITY_API_URL environment variable is required")
    sys.exit(1)

# Unique test user per run — avoids conflicts on repeated runs
RUN_ID = str(uuid.uuid4())[:8]
TEST_EMAIL = f"smoke+{RUN_ID}@test.cbba.cloud.org.bo"
TEST_PASSWORD = "Smoke@Test1!"
TEST_NAME = "Smoke Test User"

# ── Helpers ───────────────────────────────────────────────────────────────────

passed = 0
failed = 0


def step(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    status = "PASS" if ok else "FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{status}] {name}{suffix}")
    if ok:
        passed += 1
    else:
        failed += 1


def get_verification_token(email: str) -> str | None:
    """Read verification token directly from DynamoDB."""
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(TABLE_NAME)
    resp = table.scan(
        FilterExpression=Attr("email").eq(email) & Attr("sk").eq("PROFILE")
    )
    items = resp.get("Items", [])
    if not items:
        return None
    return items[0].get("email_verification_token")  # type: ignore[return-value]


# ── Test steps ────────────────────────────────────────────────────────────────

client = httpx.Client(base_url=BASE_URL, timeout=15)

print(f"\nugsys-identity-manager smoke test")
print(f"  API:   {BASE_URL}")
print(f"  Table: {TABLE_NAME}")
print(f"  Email: {TEST_EMAIL}")
print()

# 1. Health check
print("1. Health check")
r = client.get("/health")
step("GET /health → 200", r.status_code == 200, f"HTTP {r.status_code}")
step("response has status:ok", r.json().get("status") == "ok", str(r.json()))

# 2. Register
print("\n2. Register")
r = client.post(
    "/api/v1/auth/register",
    json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "full_name": TEST_NAME},
)
step("POST /register → 201", r.status_code == 201, f"HTTP {r.status_code}")
body = r.json()
user_id = body.get("data", {}).get("user_id")
step("response has user_id", bool(user_id), str(body))

# 3. Login before verification — must be rejected
print("\n3. Login before email verification")
r = client.post("/api/v1/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
step("POST /login → 401 (not verified)", r.status_code == 401, f"HTTP {r.status_code}")
error_code = r.json().get("error", {}).get("code", "")
step("error code is EMAIL_NOT_VERIFIED", error_code == "EMAIL_NOT_VERIFIED", error_code)

# 4. Resend verification (anti-enumeration — always 200)
print("\n4. Resend verification")
r = client.post("/api/v1/auth/resend-verification", json={"email": TEST_EMAIL})
step("POST /resend-verification → 200", r.status_code == 200, f"HTTP {r.status_code}")

# 5. Fetch verification token from DynamoDB
print("\n5. Fetch verification token from DynamoDB")
time.sleep(1)  # brief pause to ensure DynamoDB write is consistent
token = get_verification_token(TEST_EMAIL)
step("verification token found in DynamoDB", bool(token), token or "not found")

if not token:
    print("\nCannot continue without verification token — aborting remaining steps")
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

# 6. Verify email
print("\n6. Verify email")
r = client.post("/api/v1/auth/verify-email", json={"token": token})
step("POST /verify-email → 200", r.status_code == 200, f"HTTP {r.status_code}: {r.text[:120]}")

# 7. Login after verification
print("\n7. Login after verification")
r = client.post("/api/v1/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
step("POST /login → 200", r.status_code == 200, f"HTTP {r.status_code}: {r.text[:120]}")
data = r.json().get("data", {})
access_token = data.get("access_token", "")
refresh_token = data.get("refresh_token", "")
step("response has access_token", bool(access_token))
step("response has refresh_token", bool(refresh_token))

# 8. Refresh token
print("\n8. Refresh token")
r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
step("POST /refresh → 200", r.status_code == 200, f"HTTP {r.status_code}: {r.text[:120]}")
new_access = r.json().get("data", {}).get("access_token", "")
step("new access_token returned", bool(new_access))

# 9. Logout
print("\n9. Logout")
r = client.post(
    "/api/v1/auth/logout",
    headers={"Authorization": f"Bearer {access_token}"},
)
step("POST /logout → 200", r.status_code == 200, f"HTTP {r.status_code}: {r.text[:120]}")

# 10. Reuse revoked token — must be rejected
print("\n10. Reuse revoked token")
r = client.post(
    "/api/v1/auth/logout",
    headers={"Authorization": f"Bearer {access_token}"},
)
step("revoked token rejected (401)", r.status_code == 401, f"HTTP {r.status_code}: {r.text[:120]}")

# 11. Forgot password (anti-enumeration)
print("\n11. Forgot password")
r = client.post("/api/v1/auth/forgot-password", json={"email": TEST_EMAIL})
step("POST /forgot-password → 200", r.status_code == 200, f"HTTP {r.status_code}")

# 12. Duplicate registration
print("\n12. Duplicate registration")
r = client.post(
    "/api/v1/auth/register",
    json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "full_name": TEST_NAME},
)
step("duplicate email → 409", r.status_code == 409, f"HTTP {r.status_code}")

# 13. Weak password rejection
print("\n13. Weak password")
r = client.post(
    "/api/v1/auth/register",
    json={"email": f"weak+{RUN_ID}@test.cbba.cloud.org.bo", "password": "weak", "full_name": "Test"},
)
step("weak password → 422", r.status_code == 422, f"HTTP {r.status_code}")

# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'='*50}\n")

sys.exit(1 if failed else 0)
