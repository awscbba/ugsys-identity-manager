# Design Document — im-security-hardening

## Overview

This document describes the concrete file-level changes required to satisfy the five
requirements in `requirements.md`. All changes are confined to `ugsys-identity-manager`
and the platform CDK stack (Req 5 alarms only).

Architecture layer rules are unchanged: domain has zero infra imports, application has zero
infra imports, infrastructure implements domain ports.

---

## 1. RSA Key Rotation (Req 1)

### Problem

`_resolve_rsa_keys()` in `src/config.py` reads only `private_key`, `public_key`, and
`key_id` from Secrets Manager. There is no retiring key support. `JWTTokenService.get_jwks()`
returns a single-key array. `verify_token` decodes against `self._public_key` only, so
tokens signed with a retiring key fail verification immediately after rotation.

### Design

#### 1.1 `src/config.py` — extend `RsaKeyPair` and `_resolve_rsa_keys`

```python
@dataclass
class RsaKeyPair:
    private_key: str        # PEM — signs new tokens
    public_key: str         # PEM — verifies tokens signed with active key
    key_id: str             # kid for active key
    retiring_public_key: str | None = None   # PEM — optional, verifies old tokens
    retiring_key_id: str | None = None       # kid for retiring key
```

`_resolve_rsa_keys()` reads two additional optional fields from the Secrets Manager JSON:
`retiring_public_key` and `retiring_key_id`. When absent, both are `None`.

A module-level `_previous_key_id: str | None = None` variable tracks the last loaded
`key_id`. On each cold start (or explicit reload), if the loaded `key_id` differs from
`_previous_key_id`, log `key_rotation.detected` at `info` with `old_kid` / `new_kid` —
never log key material.

#### 1.2 `src/infrastructure/adapters/jwt_token_service.py` — multi-key support

Constructor gains two new optional params:
```python
def __init__(
    self,
    private_key: str,
    public_key: str,
    key_id: str = "ugsys-v1",
    token_blacklist: TokenBlacklistRepository | None = None,
    audience: str = "admin-panel",
    retiring_public_key: str | None = None,   # NEW
    retiring_key_id: str | None = None,        # NEW
) -> None:
```

`verify_token` — after reading the `kid` header, selects the correct public key:
1. If `kid == self._key_id` → use `self._public_key`
2. If `kid == self._retiring_key_id` and `self._retiring_public_key` is not None → use retiring key
3. Otherwise → raise `AuthenticationError(error_code="INVALID_TOKEN")`

`get_jwks()` — builds the `keys` array with 1 or 2 entries:
- Always includes the active key entry
- If `self._retiring_public_key` is not None, appends the retiring key entry

Response includes `Cache-Control: max-age=300` — set in the JWKS router, not in the service.

#### 1.3 `src/presentation/api/v1/jwks.py` — add Cache-Control header

The existing JWKS router adds `Cache-Control: max-age=300` to the response:
```python
from fastapi.responses import JSONResponse

@router.get("/.well-known/jwks.json")
async def get_jwks(...) -> JSONResponse:
    jwks = token_service.get_jwks()
    return JSONResponse(content=jwks, headers={"Cache-Control": "max-age=300"})
```

#### 1.4 `src/main.py` — pass retiring key fields

`_wire_dependencies` passes `settings.jwt_retiring_public_key` and
`settings.jwt_retiring_key_id` to `JWTTokenService`.

#### 1.5 `src/config.py` — new properties on `Settings`

```python
@property
def jwt_retiring_public_key(self) -> str | None:
    return _rsa_keys.retiring_public_key

@property
def jwt_retiring_key_id(self) -> str | None:
    return _rsa_keys.retiring_key_id
```

### Correctness Properties (PBT)

- **Round-trip**: `encode(payload)` then `verify_token(token)` succeeds for both active and retiring key.
- **Kid mismatch rejection**: token with unknown `kid` raises `AuthenticationError(error_code="INVALID_TOKEN")`.
- **JWKS key count**: when retiring key present, `len(get_jwks()["keys"]) == 2`; when absent, `== 1`.

---

## 2. Password Hashing Formalization (Req 2)

### Problem

`_BcryptHasher` is defined inline inside `_wire_dependencies()` in `main.py`. The work
factor is the bcrypt library default (12) with no explicit configuration or enforcement.
There is no `bcrypt_rounds` setting.

### Design

#### 2.1 New file: `src/infrastructure/adapters/bcrypt_password_hasher.py`

```python
import bcrypt

class BcryptPasswordHasher:
    def __init__(self, rounds: int = 12) -> None:
        if rounds < 12:
            raise ValueError(f"bcrypt rounds must be >= 12, got {rounds}")
        self._rounds = rounds

    def hash(self, password: str) -> str:
        return bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt(rounds=self._rounds)
        ).decode("utf-8")

    def verify(self, plain: str, hashed: str) -> bool:
        return bool(bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8")))
```

Satisfies the `PasswordHasher` Protocol defined in `auth_service.py`.

#### 2.2 `src/config.py` — add `bcrypt_rounds`

```python
bcrypt_rounds: int = 12  # loaded from BCRYPT_ROUNDS env var
```

Add a `@field_validator` that raises `ValueError` if `bcrypt_rounds < 12`.

#### 2.3 `src/main.py` — replace inline `_BcryptHasher`

Remove the `_BcryptHasher` class and the `import bcrypt as _bcrypt_lib` line.
Replace with:
```python
from src.infrastructure.adapters.bcrypt_password_hasher import BcryptPasswordHasher
# ...
password_hasher = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)
```

### Correctness Properties (PBT)

- **Round-trip**: `verify(p, hash(p))` is `True` for all valid passwords `p`.
- **Salt uniqueness**: `hash(p) != hash(p)` for two independent calls (different salts).
- **Wrong password**: `verify(p2, hash(p1))` is `False` when `p1 != p2`.
- **Rounds guard**: `BcryptPasswordHasher(rounds=11)` raises `ValueError`.

---

## 3. Token Revocation Completeness (Req 3)

### Problem

1. `TokenService.verify_token` is declared sync; `JWTTokenService._check_blacklist` uses a
   `ThreadPoolExecutor` + `asyncio.run` workaround to call the async blacklist from sync context.
2. `LogoutCommand` only carries `access_token`; `AuthService.logout` only blacklists the
   access token JTI.

### Design

#### 3.1 `src/domain/repositories/token_service.py` — make `verify_token` async

```python
@abstractmethod
async def verify_token(self, token: str) -> dict[str, object]: ...
```

All callers of `verify_token` in `auth_service.py` must be updated to `await` it.
`validate_token` (sync method on `AuthService`) must become `async def validate_token`.

#### 3.2 `src/infrastructure/adapters/jwt_token_service.py` — native async verify

Remove `_check_blacklist`, `concurrent.futures`, and `asyncio` imports.

```python
async def verify_token(self, token: str) -> dict[str, object]:
    # ... existing header + decode + claims checks (unchanged) ...

    # Step 4: async blacklist check
    if self._token_blacklist is not None:
        jti = str(payload.get("jti", ""))
        if jti and await self._token_blacklist.is_blacklisted(jti):
            raise AuthenticationError(
                message=f"Token {jti} has been revoked",
                user_message="Token has been revoked",
                error_code="TOKEN_REVOKED",
            )
    return payload
```

#### 3.3 `src/application/commands/logout.py` — add `refresh_token`

```python
@dataclass(frozen=True)
class LogoutCommand:
    access_token: str
    refresh_token: str
```

#### 3.4 `src/application/services/auth_service.py` — blacklist both tokens

`logout` updated to:
1. Verify and blacklist access token JTI (existing logic, now with `await verify_token`).
2. Attempt to verify refresh token; on success blacklist its JTI; on failure log warning
   and continue (Req 3 AC7 — logout must not fail due to invalid refresh token).

```python
async def logout(self, command: LogoutCommand) -> None:
    # --- access token ---
    try:
        payload = await self._token_service.verify_token(command.access_token)
    except Exception as e:
        logger.warning("auth_service.logout.invalid_access_token", error=str(e))
        raise AuthenticationError(...)

    jti = str(payload.get("jti", ""))
    exp = int(payload.get("exp", 0))
    await self._token_blacklist.add(jti, exp)

    # --- refresh token ---
    try:
        r_payload = await self._token_service.verify_token(command.refresh_token)
        r_jti = str(r_payload.get("jti", ""))
        r_exp = int(r_payload.get("exp", 0))
        if r_jti:
            await self._token_blacklist.add(r_jti, r_exp)
    except Exception as e:
        logger.warning("auth_service.logout.invalid_refresh_token", error=str(e))
        # Do not re-raise — access token is already blacklisted
```

#### 3.5 Callers of `verify_token` in `auth_service.py`

All four call sites (`refresh`, `reset_password`, `validate_token`, `logout`) must `await`
the call. `validate_token` becomes `async def validate_token`.

#### 3.6 `src/presentation/api/v1/auth.py` — update logout endpoint

The logout router must pass `refresh_token` from the request body to `LogoutCommand`.
The request DTO gains a `refresh_token: str` field.

### Correctness Properties (PBT)

- **Revocation completeness**: after `logout(access, refresh)`, both JTIs are blacklisted.
- **Revoked token rejection**: `verify_token(blacklisted_token)` raises
  `AuthenticationError(error_code="TOKEN_REVOKED")`.
- **Logout tolerates bad refresh**: `logout` with valid access + invalid refresh does not raise.

---

## 4. Login Brute-Force Protection (Req 4)

### Problem

`User.record_failed_login` hardcodes `5` and `30`. `AuthService.authenticate` hardcodes
`>= 5`. `Settings` has no `login_max_attempts` or `login_lockout_minutes`. The exception
handler returns 423 but does not set the `Retry-After` HTTP header.

### Design

#### 4.1 `src/config.py` — add lockout settings

```python
login_max_attempts: int = 5    # LOGIN_MAX_ATTEMPTS env var
login_lockout_minutes: int = 30  # LOGIN_LOCKOUT_MINUTES env var
```

Add `@field_validator` for each: raise `ValueError` if value < 1.

#### 4.2 `src/domain/entities/user.py` — parameterise `record_failed_login`

```python
def record_failed_login(
    self,
    max_attempts: int = 5,
    lockout_minutes: int = 30,
) -> None:
    self.failed_login_attempts += 1
    if self.failed_login_attempts >= max_attempts:
        self.account_locked_until = datetime.now(UTC) + timedelta(minutes=lockout_minutes)
```

Default values preserve backward compatibility with existing tests.

#### 4.3 `src/application/services/auth_service.py` — pass config to entity

`AuthService` gains two new constructor params:
```python
def __init__(
    self,
    ...
    login_max_attempts: int = 5,
    login_lockout_minutes: int = 30,
) -> None:
    ...
    self._login_max_attempts = login_max_attempts
    self._login_lockout_minutes = login_lockout_minutes
```

All calls to `user.record_failed_login()` become:
```python
user.record_failed_login(
    max_attempts=self._login_max_attempts,
    lockout_minutes=self._login_lockout_minutes,
)
```

The hardcoded `>= 5` check for publishing `account_locked` event becomes
`>= self._login_max_attempts`.

#### 4.4 `src/main.py` — pass settings to `AuthService`

```python
auth_service = AuthService(
    ...
    login_max_attempts=settings.login_max_attempts,
    login_lockout_minutes=settings.login_lockout_minutes,
)
```

#### 4.5 `src/presentation/middleware/exception_handler.py` — add `Retry-After` header

The `domain_exception_handler` already extracts `retry_after_seconds` from
`exc.additional_data` and puts it in the response body. Add the HTTP header:

```python
if isinstance(exc, AccountLockedError):
    retry_after = exc.additional_data.get("retry_after_seconds", 0)
    extra["retry_after_seconds"] = retry_after
    # Set Retry-After header
    response = JSONResponse(status_code=status, content=content)
    response.headers["Retry-After"] = str(max(int(retry_after), 1))
    return response
```

The `Retry-After` value is `max(retry_after_seconds, 1)` — minimum 1 second per Req 4 AC5.

### Correctness Properties (PBT)

- **Lockout at threshold**: after exactly `max_attempts` failed logins, `user.is_locked()` is `True`.
- **No lockout below threshold**: after `max_attempts - 1` failures, `user.is_locked()` is `False`.
- **Retry-After present**: HTTP 423 response always has `Retry-After` header with value >= 1.
- **Config validation**: `login_max_attempts=0` raises `ValueError` at startup.

---

## 5. Security Observability (Req 5)

### Problem

No CloudWatch metric filters or alarms exist for auth failure spikes or account lockout
events. The IM CDK stack is in `ugsys-platform-infrastructure` (separate repo).

### Design

The IM service already logs the required events:
- `auth_service.authenticate.invalid_credentials` (warning) — maps to Req 5 AC1 / AC4
- `auth_service.authenticate.account_locked` (warning) — maps to Req 5 AC2 / AC5

The CDK changes are in `ugsys-platform-infrastructure`. The spec covers the alarm
definitions; the actual CDK code is out of scope for this repo's tasks but is documented
here for the platform infra team.

#### 5.1 Required CDK constructs (platform infra)

Two `MetricFilter` + `Alarm` pairs on the IM log group
(`/aws/lambda/ugsys-identity-manager-{env}`):

**Auth failure alarm**
- Filter pattern: `{ $.event = "auth_service.authenticate.invalid_credentials" }`
- Metric namespace: `ugsys/IdentityManager`, metric name: `AuthFailures`
- Alarm: threshold ≥ 100, period 1 hour, statistic Sum
- Action: SNS → Slack channel `C0AE6QV0URH`

**Account lockout alarm**
- Filter pattern: `{ $.event = "auth_service.authenticate.account_locked" }`
- Metric namespace: `ugsys/IdentityManager`, metric name: `AccountLockouts`
- Alarm: threshold ≥ 10, period 5 minutes, statistic Sum
- Action: same SNS topic

#### 5.2 Log field alignment

`auth_service.py` already logs `user_id` and `attempt_count` on invalid credentials, and
`user_id` and `retry_after_seconds` on account locked. Per Req 5 AC4/AC5:

- `auth.login_failed` log must include `attempt_count` — already present as
  `auth_service.authenticate.invalid_credentials` with `attempt_count` field.
- `auth.account_locked` log must NOT include `email` — the existing log at
  `auth_service.authenticate.account_locked` logs `user_id` and `retry_after_seconds`
  only. No change needed.

#### 5.3 `key_rotation.detected` log

Added in `src/config.py` `_resolve_rsa_keys()` as described in section 1.1. No CDK change
needed — it flows through the existing structured log pipeline.

---

## File Change Summary

| File | Change type | Req |
|------|-------------|-----|
| `src/config.py` | Extend `RsaKeyPair`, `_resolve_rsa_keys`, add `bcrypt_rounds`, `login_max_attempts`, `login_lockout_minutes`, retiring key properties | 1, 2, 4 |
| `src/infrastructure/adapters/jwt_token_service.py` | Multi-key verify, async `verify_token`, retiring key JWKS, remove `_check_blacklist` | 1, 3 |
| `src/infrastructure/adapters/bcrypt_password_hasher.py` | **New file** — `BcryptPasswordHasher` | 2 |
| `src/domain/repositories/token_service.py` | `verify_token` → `async` | 3 |
| `src/application/commands/logout.py` | Add `refresh_token` field | 3 |
| `src/application/services/auth_service.py` | Await `verify_token`, blacklist refresh JTI, pass lockout params, `validate_token` → async | 3, 4 |
| `src/domain/entities/user.py` | `record_failed_login` gains `max_attempts` / `lockout_minutes` params | 4 |
| `src/presentation/middleware/exception_handler.py` | Add `Retry-After` header on 423 | 4 |
| `src/presentation/api/v1/jwks.py` | Add `Cache-Control: max-age=300` | 1 |
| `src/presentation/api/v1/auth.py` | Logout DTO gains `refresh_token`; `validate_token` endpoint awaits | 3 |
| `src/main.py` | Remove `_BcryptHasher`, use `BcryptPasswordHasher`, pass retiring keys and lockout params | 1, 2, 4 |
| Platform CDK stack | `MetricFilter` + `Alarm` for auth failures and lockouts | 5 |

---

## Testing Strategy

### Unit tests (new / updated)

| Test file | What it covers |
|-----------|---------------|
| `tests/unit/infrastructure/test_bcrypt_password_hasher.py` | Round-trip, salt uniqueness, wrong password, rounds guard |
| `tests/unit/infrastructure/test_jwt_token_service.py` | Multi-key verify, retiring key round-trip, unknown kid rejection, JWKS key count, async blacklist check |
| `tests/unit/domain/test_user.py` | `record_failed_login` with custom params, lockout at threshold, no lockout below threshold |
| `tests/unit/application/test_auth_service.py` | Logout blacklists both JTIs, logout tolerates bad refresh, lockout params passed to entity, `account_locked` event at configurable threshold |
| `tests/unit/presentation/test_exception_handler.py` | 423 response has `Retry-After` header ≥ 1 |

### Property-based tests (hypothesis)

| Property | Generator |
|----------|-----------|
| JWT round-trip (active key) | random payloads |
| JWT round-trip (retiring key) | random payloads |
| Bcrypt round-trip | `st.text(min_size=1, max_size=72)` |
| Bcrypt salt uniqueness | same password, two hashes |
| Lockout at threshold | `st.integers(min_value=1, max_value=20)` for `max_attempts` |
| Retry-After ≥ 1 | `st.integers(min_value=0, max_value=3600)` for `retry_after_seconds` |
