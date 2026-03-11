# Requirements Document

## Introduction

This spec hardens the `ugsys-identity-manager` (IM) backend as the sole RS256 JWT issuer
for the ugsys platform. Four areas are addressed:

1. **RSA key rotation** — the current key pair is static in Secrets Manager with no rotation
   procedure. A zero-downtime rotation mechanism is needed so the JWKS endpoint serves both
   the active and the retiring key during the overlap window.

2. **Password hashing formalization** — bcrypt is in use via an anonymous `_BcryptHasher`
   class defined inline in `main.py`. The work factor is the library default (12) with no
   explicit configuration or enforcement. The hasher must be extracted to a proper
   infrastructure adapter with an auditable, configurable work factor.

3. **Token revocation completeness** — the `TokenBlacklistRepository` port and
   `DynamoDBTokenBlacklistRepository` adapter exist, and `logout` correctly blacklists the
   access token JTI. However, `verify_token` checks the blacklist via a synchronous
   thread-pool workaround (`_check_blacklist`) rather than a proper async call, and the
   refresh token is not blacklisted on logout. Both gaps must be closed.

4. **Login-specific brute-force protection** — account lockout logic exists in the `User`
   entity (`record_failed_login` / `is_locked`) and is exercised in `AuthService.authenticate`.
   The threshold (5 attempts, 30-minute lockout) is hardcoded in the entity. The lockout
   parameters must be configurable via `Settings`, and the `Retry-After` header must be
   returned on HTTP 423 responses so clients can back off correctly.

Scope: `ugsys-identity-manager` backend only. No frontend changes. No changes to the
`auth-gap-closure` spec scope (email claims, frontend routing).

---

## Glossary

- **Identity_Manager**: The `ugsys-identity-manager` FastAPI service — the sole RS256 JWT
  issuer for the ugsys platform.
- **JWT_Token_Service**: The `JWTTokenService` class in
  `src/infrastructure/adapters/jwt_token_service.py` that signs and verifies RS256 tokens.
- **Token_Service**: The `TokenService` ABC in `src/domain/repositories/token_service.py` —
  the outbound port that `JWT_Token_Service` implements.
- **Auth_Service**: The `AuthService` application service in
  `src/application/services/auth_service.py`.
- **Password_Hasher**: The `PasswordHasher` Protocol defined in `auth_service.py` — the
  inbound port for password hashing. The concrete implementation is `BcryptPasswordHasher`
  in `src/infrastructure/adapters/bcrypt_password_hasher.py`.
- **Token_Blacklist**: The `TokenBlacklistRepository` ABC in
  `src/domain/repositories/token_blacklist_repository.py` and its DynamoDB implementation
  `DynamoDBTokenBlacklistRepository`.
- **JWKS_Endpoint**: `GET /.well-known/jwks.json` — serves the public key set so consumers
  can verify tokens without sharing any secret.
- **Active_Key**: The RSA key pair currently used to sign new tokens. Its `kid` is the value
  in `Settings.jwt_key_id`.
- **Retiring_Key**: A previously active RSA key pair that is no longer used to sign new
  tokens but whose public key is still served via the JWKS_Endpoint during the overlap window
  so that tokens signed with it remain verifiable until they expire.
- **Key_Overlap_Window**: The period during which both the Active_Key and the Retiring_Key
  are served via the JWKS_Endpoint. Must be at least as long as `jwt_access_ttl_minutes`
  (default 30 minutes).
- **Secrets_Manager**: AWS Secrets Manager — stores the RSA key pair JSON
  `{"private_key": "...", "public_key": "...", "key_id": "..."}` at the ARN referenced by
  `JWT_KEYS_SECRET_ARN`.
- **Work_Factor**: The bcrypt cost parameter (rounds). Controls the time taken to hash a
  password. Default is 12; must be at least 12 in all environments.
- **JTI**: JWT ID — the `jti` claim, a UUID4 unique per token, used as the blacklist key.
- **Access_Token**: A short-lived RS256 JWT (30-minute TTL) carrying `sub`, `email`, `roles`,
  `type=access`, `jti`, `exp`, `iat`, `iss`, `aud`.
- **Refresh_Token**: A longer-lived RS256 JWT (7-day TTL) carrying `sub`, `type=refresh`,
  `jti`, `exp`, `iat`, `iss`.
- **Lockout_Threshold**: The number of consecutive failed login attempts before an account is
  locked. Configurable via `Settings.login_max_attempts` (default 5).
- **Lockout_Duration**: The duration an account remains locked after reaching
  `Lockout_Threshold`. Configurable via `Settings.login_lockout_minutes` (default 30).

---

## Requirements

### Requirement 1: RSA Key Rotation

**User Story:** As a platform operator, I want to rotate the RSA signing key pair without
downtime, so that tokens signed with the old key remain valid during the overlap window and
all new tokens are signed with the new key.

#### Acceptance Criteria

1. WHEN a new RSA key pair is stored in Secrets Manager under `JWT_KEYS_SECRET_ARN`, THE
   Identity_Manager SHALL begin signing all new tokens with the new Active_Key on the next
   Lambda cold start or explicit reload, without requiring a redeployment.

2. WHEN the Active_Key changes, THE JWKS_Endpoint SHALL serve both the new Active_Key and
   the Retiring_Key public key in the `keys` array for at least the duration of
   `jwt_access_ttl_minutes` (the Key_Overlap_Window).

3. WHILE the Key_Overlap_Window is active, THE JWT_Token_Service SHALL successfully verify
   tokens signed with the Retiring_Key by matching the `kid` header claim against all keys
   in the served JWKS set.

4. THE JWKS_Endpoint SHALL return a response with `Cache-Control: max-age=300` so that
   consumers refresh their cached key set within 5 minutes of a rotation.

5. IF a token's `kid` header does not match any key in the current JWKS set, THEN THE
   JWT_Token_Service SHALL raise `AuthenticationError` with `error_code="INVALID_TOKEN"` and
   SHALL NOT expose key material in the error message.

6. THE Secrets_Manager secret schema for key rotation SHALL support a `retiring_key` object
   alongside the `active_key` object:
   `{"private_key": "...", "public_key": "...", "key_id": "...", "retiring_public_key": "...", "retiring_key_id": "..."}`.
   The `retiring_public_key` and `retiring_key_id` fields are optional; when absent, the
   JWKS_Endpoint SHALL serve only the Active_Key.

7. FOR ALL valid tokens signed with the Active_Key, encoding a token and then verifying it
   SHALL succeed (round-trip property) both before and after a key rotation event.

8. THE Identity_Manager SHALL log `key_rotation.detected` at `info` level when the loaded
   `key_id` differs from the previously loaded `key_id`, including the old and new `kid`
   values but never including key material.

---

### Requirement 2: Password Hashing Formalization

**User Story:** As a platform engineer, I want the password hashing implementation to be an
explicit, auditable infrastructure adapter with a configurable work factor, so that the
hashing algorithm and strength can be verified and adjusted without touching the composition
root.

#### Acceptance Criteria

1. THE Identity_Manager SHALL implement password hashing in a dedicated
   `BcryptPasswordHasher` class in `src/infrastructure/adapters/bcrypt_password_hasher.py`
   that satisfies the `PasswordHasher` Protocol.

2. THE `BcryptPasswordHasher` SHALL use bcrypt with a Work_Factor of at least 12 in all
   environments.

3. WHEN `BcryptPasswordHasher` is instantiated, THE `BcryptPasswordHasher` SHALL accept a
   `rounds` parameter (default 12) and SHALL raise `ValueError` if `rounds` is less than 12.

4. THE `BcryptPasswordHasher.hash` method SHALL produce a hash that is verifiable by
   `BcryptPasswordHasher.verify` using the same password (round-trip property).

5. FOR ALL plaintext passwords `p`, `BcryptPasswordHasher.hash(p)` called twice SHALL
   produce two different hash strings (salt uniqueness — bcrypt generates a new salt per
   call).

6. WHEN `BcryptPasswordHasher.verify` is called with a correct plaintext password and its
   corresponding hash, THE `BcryptPasswordHasher` SHALL return `True`.

7. WHEN `BcryptPasswordHasher.verify` is called with an incorrect plaintext password, THE
   `BcryptPasswordHasher` SHALL return `False` and SHALL NOT raise an exception.

8. THE `Settings` class SHALL expose a `bcrypt_rounds` field (type `int`, default `12`,
   loaded from the `BCRYPT_ROUNDS` environment variable) so the Work_Factor is configurable
   per environment without code changes.

9. THE `main.py` composition root SHALL instantiate `BcryptPasswordHasher` using
   `settings.bcrypt_rounds` and SHALL remove the inline `_BcryptHasher` class.

---

### Requirement 3: Token Revocation Completeness

**User Story:** As a platform security engineer, I want logout to revoke both the access
token and the refresh token, and want token verification to check the blacklist via a proper
async call, so that revoked tokens cannot be reused and the verification path has no
synchronous thread-pool workarounds.

#### Acceptance Criteria

1. WHEN `AuthService.logout` is called with a valid access token, THE Auth_Service SHALL
   blacklist both the access token JTI and the refresh token JTI in the Token_Blacklist.

2. THE `LogoutCommand` SHALL carry both `access_token` and `refresh_token` fields so the
   Auth_Service can extract and blacklist both JTIs.

3. WHEN `JWT_Token_Service.verify_token` is called and a `Token_Blacklist` is configured,
   THE JWT_Token_Service SHALL check the blacklist using a native `async` call (not via
   `asyncio.run` or a thread pool executor).

4. THE `Token_Service` port (`verify_token`) SHALL be declared `async` so that the blacklist
   check is a first-class async operation throughout the call chain.

5. WHEN a blacklisted JTI is presented to `verify_token`, THE JWT_Token_Service SHALL raise
   `AuthenticationError` with `error_code="TOKEN_REVOKED"` and `user_message="Token has
   been revoked"`.

6. WHEN `AuthService.logout` is called with an already-expired access token, THE Auth_Service
   SHALL still attempt to blacklist the JTI (idempotent — expired tokens in the blacklist
   cause no harm and prevent replay if the clock is skewed).

7. IF `AuthService.logout` is called with a refresh token that fails signature verification,
   THEN THE Auth_Service SHALL blacklist the access token JTI and SHALL log a warning for
   the invalid refresh token, but SHALL NOT fail the logout operation.

8. FOR ALL `(access_jti, refresh_jti)` pairs produced by a single `authenticate` call,
   after `logout` is called, `Token_Blacklist.is_blacklisted(access_jti)` and
   `Token_Blacklist.is_blacklisted(refresh_jti)` SHALL both return `True` (revocation
   completeness property).

9. THE `DynamoDBTokenBlacklistRepository.add` method SHALL set the DynamoDB item TTL to the
   token's `exp` epoch value so that blacklist entries are automatically deleted after the
   token would have expired anyway.

---

### Requirement 4: Login Brute-Force Protection

**User Story:** As a platform operator, I want the account lockout threshold and duration to
be configurable via environment variables, and I want the HTTP 423 response to include a
`Retry-After` header, so that the lockout policy can be tuned per environment and clients
can implement correct back-off.

#### Acceptance Criteria

1. THE `Settings` class SHALL expose a `login_max_attempts` field (type `int`, default `5`,
   loaded from `LOGIN_MAX_ATTEMPTS` env var) representing the Lockout_Threshold.

2. THE `Settings` class SHALL expose a `login_lockout_minutes` field (type `int`, default
   `30`, loaded from `LOGIN_LOCKOUT_MINUTES` env var) representing the Lockout_Duration in
   minutes.

3. THE `User.record_failed_login` method SHALL accept `max_attempts` and `lockout_minutes`
   parameters (both with defaults matching the current hardcoded values: 5 and 30) so the
   lockout policy is driven by configuration rather than hardcoded constants.

4. WHEN `AuthService.authenticate` calls `user.record_failed_login`, THE Auth_Service SHALL
   pass `settings.login_max_attempts` and `settings.login_lockout_minutes` as arguments.

5. WHEN `AuthService.authenticate` raises `AccountLockedError`, THE presentation layer SHALL
   return HTTP 423 with a `Retry-After` header whose value equals the number of seconds
   until the lockout expires (minimum 1).

6. WHEN `AuthService.authenticate` raises `AccountLockedError`, THE response body SHALL
   include `additional_data.retry_after_seconds` so API clients that do not read headers can
   also implement back-off.

7. WHEN a user's account is locked and `AuthService.authenticate` is called, THE Auth_Service
   SHALL NOT verify the password (lockout check precedes password verification) and SHALL
   return `AccountLockedError` immediately.

8. WHEN a user successfully authenticates after a previous lockout has expired, THE
   Auth_Service SHALL call `user.reset_login_attempts()` and persist the reset so the
   failed-attempt counter returns to zero.

9. IF `login_max_attempts` is set to a value less than 1 via environment variable, THEN THE
   `Settings` class SHALL raise a `ValueError` at startup with a message indicating the
   invalid value.

10. IF `login_lockout_minutes` is set to a value less than 1 via environment variable, THEN
    THE `Settings` class SHALL raise a `ValueError` at startup with a message indicating the
    invalid value.

11. WHEN `AuthService.authenticate` records a failed login attempt that reaches the
    Lockout_Threshold, THE Auth_Service SHALL publish an `identity.auth.account_locked`
    event containing `user_id` and `locked_until` (ISO 8601) and SHALL NOT include the
    user's password or any credential material in the event payload.

---

### Requirement 5: Security Observability

**User Story:** As a platform operator, I want CloudWatch alarms for auth failure spikes and
account lockout events, so that brute-force attacks and credential-stuffing attempts are
detected and alerted within minutes.

#### Acceptance Criteria

1. THE Identity_Manager CDK stack SHALL define a CloudWatch metric filter on the structured
   log group that counts log events where `event` contains `authenticate.invalid_credentials`
   and SHALL create an alarm that triggers when the count reaches 100 within 1 hour.

2. THE Identity_Manager CDK stack SHALL define a CloudWatch metric filter that counts log
   events where `event` contains `authenticate.account_locked` and SHALL create an alarm
   that triggers when the count reaches 10 within 5 minutes.

3. WHEN the auth failure alarm triggers, THE CDK stack SHALL publish to the platform SNS
   topic so that the Slack notification channel receives an alert within 5 minutes.

4. THE Identity_Manager SHALL log `auth.login_failed` at `warning` level with fields
   `user_id` and `attempt_count` on every failed password verification, and SHALL NOT
   include the submitted password or any credential material in the log entry.

5. THE Identity_Manager SHALL log `auth.account_locked` at `warning` level with fields
   `user_id` and `locked_until` (ISO 8601) when an account transitions to the locked state,
   and SHALL NOT include the user's email address in this log entry.

6. THE Identity_Manager SHALL log `key_rotation.detected` at `info` level (as specified in
   Requirement 1, criterion 8) so that key rotation events are visible in CloudWatch Logs
   Insights queries.
