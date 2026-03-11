# Implementation Plan: im-security-hardening

## Overview

Hardens the `ugsys-identity-manager` across four areas: RSA key rotation with zero-downtime
overlap, bcrypt adapter extraction, async token revocation completeness, and configurable
brute-force lockout with `Retry-After` header. All changes are confined to this repo.

Branch: `feature/im-security-hardening`

---

## Tasks

- [x] 1. Extend `Settings` and `RsaKeyPair` for key rotation and new config fields
  - Extend `RsaKeyPair` dataclass with `retiring_public_key: str | None` and `retiring_key_id: str | None`
  - Update `_resolve_rsa_keys()` to read optional `retiring_public_key` / `retiring_key_id` from Secrets Manager JSON
  - Add module-level `_previous_key_id` tracker; log `key_rotation.detected` at `info` with `old_kid` / `new_kid` when `key_id` changes — never log key material
  - Add `bcrypt_rounds: int = 12` field with `@field_validator` raising `ValueError` if `< 12`
  - Add `login_max_attempts: int = 5` and `login_lockout_minutes: int = 30` fields with validators raising `ValueError` if `< 1`
  - Add `jwt_retiring_public_key` and `jwt_retiring_key_id` properties that delegate to `_rsa_keys`
  - _Requirements: 1.6, 1.8, 2.2, 2.8, 4.1, 4.2, 4.9, 4.10_

- [x] 2. Implement `BcryptPasswordHasher` infrastructure adapter
  - [x] 2.1 Create `src/infrastructure/adapters/bcrypt_password_hasher.py`
    - Implement `BcryptPasswordHasher` satisfying the `PasswordHasher` Protocol
    - Constructor accepts `rounds: int = 12`; raises `ValueError` if `rounds < 12`
    - `hash(password: str) -> str` — calls `bcrypt.hashpw` with `bcrypt.gensalt(rounds=self._rounds)`
    - `verify(plain: str, hashed: str) -> bool` — calls `bcrypt.checkpw`; never raises on wrong password
    - _Requirements: 2.1, 2.2, 2.3, 2.6, 2.7_

  - [ ]* 2.2 Write unit tests for `BcryptPasswordHasher`
    - New file: `tests/unit/infrastructure/test_bcrypt_password_hasher.py`
    - `test_hash_verify_round_trip` — `verify(p, hash(p))` returns `True`
    - `test_wrong_password_returns_false` — `verify(p2, hash(p1))` returns `False` when `p1 != p2`
    - `test_rounds_guard_raises_value_error` — `BcryptPasswordHasher(rounds=11)` raises `ValueError`
    - `test_rounds_guard_accepts_minimum` — `BcryptPasswordHasher(rounds=12)` does not raise
    - _Requirements: 2.3, 2.6, 2.7_

  - [ ]* 2.3 Write property tests for `BcryptPasswordHasher`
    - Same file: `tests/unit/infrastructure/test_bcrypt_password_hasher.py`
    - **Property 1: Bcrypt round-trip** — `@given(st.text(min_size=1, max_size=72))` assert `verify(p, hash(p))` is `True`
    - **Property 2: Salt uniqueness** — `@given(st.text(min_size=1, max_size=72))` assert `hash(p) != hash(p)` for two independent calls
    - `@settings(max_examples=50)` (bcrypt is slow)
    - **Validates: Requirements 2.4, 2.5**

- [x] 3. Update `User.record_failed_login` to accept configurable lockout params
  - [x] 3.1 Update `src/domain/entities/user.py`
    - Add `max_attempts: int = 5` and `lockout_minutes: int = 30` params to `record_failed_login`
    - Replace hardcoded `5` and `30` with the new params; default values preserve backward compatibility
    - _Requirements: 4.3_

  - [ ]* 3.2 Write unit tests for `User.record_failed_login` with custom params
    - Extend `tests/unit/domain/test_user.py`
    - `test_lockout_at_custom_threshold` — `record_failed_login(max_attempts=3)` three times; assert `is_locked()` is `True`
    - `test_no_lockout_below_threshold` — `record_failed_login(max_attempts=3)` twice; assert `is_locked()` is `False`
    - `test_custom_lockout_duration` — assert `account_locked_until` is approximately `now + lockout_minutes`
    - _Requirements: 4.3_

  - [ ]* 3.3 Write property tests for lockout threshold
    - Same file: `tests/unit/domain/test_user.py`
    - **Property 3: Lockout at threshold** — `@given(st.integers(min_value=1, max_value=20))` for `max_attempts`; call `record_failed_login` exactly `max_attempts` times; assert `is_locked()` is `True`
    - **Property 4: No lockout below threshold** — same generator; call `max_attempts - 1` times; assert `is_locked()` is `False`
    - `@settings(max_examples=100)`
    - **Validates: Requirements 4.3**

- [x] 4. Make `TokenService.verify_token` async and update `JWTTokenService`
  - [x] 4.1 Update `src/domain/repositories/token_service.py`
    - Change `verify_token` abstract method signature to `async def verify_token`
    - _Requirements: 3.4_

  - [x] 4.2 Update `src/infrastructure/adapters/jwt_token_service.py`
    - Add `retiring_public_key: str | None` and `retiring_key_id: str | None` constructor params
    - Replace `verify_token` with `async def verify_token`; remove `_check_blacklist`, `concurrent.futures`, and `asyncio` imports
    - After decoding, select public key by `kid`: active key → `self._public_key`; retiring key → `self._retiring_public_key`; unknown → raise `AuthenticationError(error_code="INVALID_TOKEN")`
    - Replace thread-pool blacklist check with `await self._token_blacklist.is_blacklisted(jti)`
    - Update `get_jwks()` to include retiring key entry when `self._retiring_public_key` is not `None`
    - _Requirements: 1.2, 1.3, 1.5, 3.3, 3.4, 3.5_

  - [ ]* 4.3 Write unit tests for `JWTTokenService` multi-key and async behaviour
    - Extend `tests/unit/infrastructure/test_jwt_token_service.py`
    - `test_verify_with_retiring_key_succeeds` — token signed with retiring key verifies successfully
    - `test_unknown_kid_raises_authentication_error` — token with unknown `kid` raises `AuthenticationError(error_code="INVALID_TOKEN")`
    - `test_jwks_includes_retiring_key_when_present` — `len(get_jwks()["keys"]) == 2`
    - `test_jwks_single_key_when_no_retiring_key` — `len(get_jwks()["keys"]) == 1`
    - `test_blacklisted_token_raises_token_revoked` — async mock blacklist returns `True`; assert `AuthenticationError(error_code="TOKEN_REVOKED")`
    - _Requirements: 1.2, 1.3, 1.5, 3.3, 3.5_

  - [ ]* 4.4 Write property tests for JWT round-trip
    - New file: `tests/unit/infrastructure/test_jwt_token_service_properties.py`
    - **Property 5: JWT round-trip (active key)** — `@given(random payloads)` encode then `await verify_token`; assert payload fields preserved
    - **Property 6: JWT round-trip (retiring key)** — token signed with retiring private key; `await verify_token` with retiring key configured; assert success
    - **Property 7: Unknown kid rejection** — token with arbitrary unknown `kid`; assert `AuthenticationError(error_code="INVALID_TOKEN")`
    - `@settings(max_examples=100)`
    - **Validates: Requirements 1.3, 1.5, 1.7**

- [x] 5. Checkpoint — domain and infrastructure layers
  - Ensure all tests pass, ask the user if questions arise.
  - Run `uv run pytest tests/unit/domain/ tests/unit/infrastructure/ -v` inside `ugsys/ugsys-identity-manager`
  - Run `uv run mypy src/ --strict` to confirm no type errors from the async signature change

- [x] 6. Update `LogoutCommand` and `AuthService` for revocation completeness and lockout config
  - [x] 6.1 Update `src/application/commands/logout.py`
    - Add `refresh_token: str` field to `LogoutCommand`
    - _Requirements: 3.2_

  - [x] 6.2 Update `src/application/services/auth_service.py`
    - Add `login_max_attempts: int = 5` and `login_lockout_minutes: int = 30` constructor params; store as `self._login_max_attempts` / `self._login_lockout_minutes`
    - Update all `verify_token` call sites to `await` (in `refresh`, `reset_password`, `validate_token`, `logout`)
    - Change `validate_token` to `async def validate_token`
    - In `logout`: blacklist access token JTI; then attempt to verify and blacklist refresh token JTI; on refresh verification failure log warning and continue (do not re-raise)
    - Pass `max_attempts=self._login_max_attempts` and `lockout_minutes=self._login_lockout_minutes` to `user.record_failed_login()`
    - Replace hardcoded `>= 5` account-locked event threshold with `>= self._login_max_attempts`
    - _Requirements: 3.1, 3.3, 3.6, 3.7, 4.4, 4.7, 4.8, 4.11_

  - [ ]* 6.3 Write unit tests for `AuthService` revocation and lockout
    - Extend `tests/unit/application/test_auth_service.py`
    - `test_logout_blacklists_both_tokens` — assert `token_blacklist.add` called twice (access JTI + refresh JTI)
    - `test_logout_tolerates_invalid_refresh_token` — invalid refresh token; assert no exception raised and access JTI still blacklisted
    - `test_authenticate_passes_lockout_params_to_entity` — assert `record_failed_login` called with `max_attempts` and `lockout_minutes` from service config
    - `test_account_locked_event_uses_configurable_threshold` — `login_max_attempts=3`; assert `account_locked` event published after 3rd failure
    - _Requirements: 3.1, 3.7, 4.4, 4.11_

  - [ ]* 6.4 Write property tests for `AuthService`
    - Same file: `tests/unit/application/test_auth_service.py`
    - **Property 8: Revocation completeness** — `@given(valid access+refresh token pair)` after `logout`, both JTIs are blacklisted
    - **Property 9: Account locked event at configurable threshold** — `@given(st.integers(min_value=1, max_value=10))` for `max_attempts`; assert event published exactly when threshold reached
    - `@settings(max_examples=100)`
    - **Validates: Requirements 3.8, 4.11**

- [x] 7. Update presentation layer — `Retry-After` header, JWKS cache, logout DTO
  - [x] 7.1 Update `src/presentation/middleware/exception_handler.py`
    - In `domain_exception_handler`, when `isinstance(exc, AccountLockedError)`, extract `retry_after_seconds` from `exc.additional_data`; build `JSONResponse` and set `Retry-After: max(int(retry_after_seconds), 1)` header
    - _Requirements: 4.5, 4.6_

  - [x] 7.2 Update `src/presentation/api/v1/jwks.py`
    - Change return type to `JSONResponse`; add `headers={"Cache-Control": "max-age=300"}`
    - _Requirements: 1.4_

  - [x] 7.3 Update `src/presentation/api/v1/auth.py`
    - Add `refresh_token: str` to the logout request DTO
    - Pass `refresh_token` from request body to `LogoutCommand`
    - Update `validate_token` endpoint to `await` the now-async `auth_service.validate_token`
    - _Requirements: 3.2, 3.4_

  - [ ]* 7.4 Write unit tests for exception handler `Retry-After` header
    - New file: `tests/unit/presentation/test_exception_handler.py`
    - `test_423_response_has_retry_after_header` — `AccountLockedError` with `retry_after_seconds=60`; assert response header `Retry-After == "60"`
    - `test_retry_after_minimum_is_1` — `retry_after_seconds=0`; assert `Retry-After == "1"`
    - `test_non_423_errors_have_no_retry_after_header` — `NotFoundError`; assert `Retry-After` absent
    - _Requirements: 4.5_

  - [ ]* 7.5 Write property test for `Retry-After` header
    - Same file: `tests/unit/presentation/test_exception_handler.py`
    - **Property 10: Retry-After always >= 1** — `@given(st.integers(min_value=0, max_value=3600))` for `retry_after_seconds`; assert `int(response.headers["Retry-After"]) >= 1`
    - `@settings(max_examples=200)`
    - **Validates: Requirements 4.5**

- [x] 8. Wire everything together in `src/main.py`
  - Remove inline `_BcryptHasher` class and `import bcrypt as _bcrypt_lib`
  - Import and instantiate `BcryptPasswordHasher(rounds=settings.bcrypt_rounds)`
  - Pass `retiring_public_key=settings.jwt_retiring_public_key` and `retiring_key_id=settings.jwt_retiring_key_id` to `JWTTokenService`
  - Pass `login_max_attempts=settings.login_max_attempts` and `login_lockout_minutes=settings.login_lockout_minutes` to `AuthService`
  - _Requirements: 1.1, 2.9, 4.4_

- [x] 9. Final checkpoint — full suite
  - Ensure all tests pass, ask the user if questions arise.
  - Run `uv run pytest tests/unit/ -v --tb=short` inside `ugsys/ugsys-identity-manager`
  - Run `uv run mypy src/ --strict` to confirm zero type errors end-to-end

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Task 4 (async `verify_token`) is a breaking change that cascades to all callers — complete tasks 4.1 and 4.2 together before moving to task 6
- Req 5 (CDK CloudWatch alarms) is out of scope for this repo — it belongs to `ugsys-platform-infrastructure` and is documented in the design for the platform infra team
- Property tests use `@settings(max_examples=50)` for bcrypt (slow) and `@settings(max_examples=100–200)` for all others
- Each property test comment must include `# Feature: im-security-hardening, Property N: <text>`
- The `Retry-After` value must always be `max(int(retry_after_seconds), 1)` — never zero
- Never log key material, passwords, tokens, or email addresses in security-sensitive log entries
