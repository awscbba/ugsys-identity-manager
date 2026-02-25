# Implementation Plan: Identity Manager Phase 1 Completion

## Overview

Close all P0/P1/P2 gaps in `ugsys-identity-manager` following testability-first ordering: domain layer (pure Python, zero deps) first, then application layer (mockable ports), then infrastructure adapters, then presentation layer. Each task includes its tests as sub-tasks following TDD workflow.

## Tasks

- [x] 1. Domain exception hierarchy and User entity extensions
  - [x] 1.1 Create domain exception hierarchy in `src/domain/exceptions.py`
    - Implement `DomainError` base with `message`, `user_message`, `error_code`, `additional_data`
    - Implement `ValidationError`, `NotFoundError`, `ConflictError`, `AuthenticationError`, `AuthorizationError`, `AccountLockedError`, `RepositoryError`, `ExternalServiceError`
    - _Requirements: 8.1_

  - [ ]* 1.2 Write unit tests for domain exceptions in `tests/unit/domain/test_exceptions.py`
    - Test each exception type has correct default `error_code`
    - Test `message` and `user_message` are stored separately
    - Test `DomainError` is an `Exception` subclass
    - _Requirements: 8.1_

  - [x] 1.3 Extend User entity with new fields and methods in `src/domain/entities/user.py`
    - Add fields: `failed_login_attempts`, `account_locked_until`, `last_login_at`, `last_password_change`, `require_password_change`, `email_verified`, `email_verification_token`, `email_verified_at`, `is_admin`
    - Add `UserRole` enum values: `MODERATOR`, `AUDITOR`, `GUEST`, `SYSTEM`
    - Add `UserStatus` enum value: `PENDING_VERIFICATION` (if missing)
    - Implement methods: `is_locked()`, `record_failed_login()`, `reset_login_attempts()`, `record_successful_login()`, `verify_email()`, `generate_verification_token()`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [ ]* 1.4 Write unit tests for User entity extensions in `tests/unit/domain/test_user_entity.py`
    - Test all new field defaults on fresh User creation
    - Test `is_locked()` returns True when `account_locked_until` is in the future, False otherwise
    - Test `record_failed_login()` increments count and locks at 5
    - Test `reset_login_attempts()` clears count and lock
    - Test `record_successful_login()` resets attempts and sets `last_login_at`
    - Test `verify_email()` sets status=active, email_verified=True, clears token
    - Test `generate_verification_token()` returns UUID4 string and stores it
    - Test all UserRole enum values exist
    - Test all UserStatus enum values exist
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [ ]* 1.5 Write property tests for User entity in `tests/property/test_user_entity_props.py`
    - **Property 1: User entity defaults are correct**
    - **Validates: Requirements 1.1**
    - **Property 2: is_locked reflects account_locked_until correctly**
    - **Validates: Requirements 1.4**
    - **Property 3: record_failed_login increments and locks at threshold**
    - **Validates: Requirements 1.5, 2.2**
    - **Property 4: reset_login_attempts clears lockout state**
    - **Validates: Requirements 1.6**
    - **Property 5: record_successful_login resets attempts and sets last_login_at**
    - **Validates: Requirements 1.7, 2.4, 3.5**

- [x] 2. Password validator and domain ports
  - [x] 2.1 Create PasswordValidator value object in `src/domain/value_objects/password_validator.py`
    - Implement `validate(password: str) -> list[str]` returning list of violated rules
    - Rules: min 8 chars, 1 uppercase, 1 lowercase, 1 digit, 1 special char from `!@#$%^&*()_+-=[]{}|;:,.<>?`
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 2.2 Write unit tests for PasswordValidator in `tests/unit/domain/test_password_validator.py`
    - Test valid password returns empty list
    - Test each individual rule violation returns correct message
    - Test multiple violations are all reported
    - Test edge cases: exactly 8 chars, empty string, special chars only
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 2.3 Write property tests for PasswordValidator in `tests/property/test_password_validator_props.py`
    - **Property 17: Password validator correctly identifies all violated rules**
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [x] 2.4 Create TokenBlacklistRepository ABC in `src/domain/repositories/token_blacklist_repository.py`
    - Define `add(jti: str, ttl_epoch: int) -> None` and `is_blacklisted(jti: str) -> bool` abstract methods
    - _Requirements: 4.3_

  - [x] 2.5 Create EventPublisher ABC in `src/domain/repositories/event_publisher.py`
    - Define `publish(detail_type: str, payload: dict[str, Any]) -> None` abstract method
    - Replace existing `EventPublisherProtocol` usage with this ABC
    - _Requirements: 9.2_

  - [x] 2.6 Extend UserRepository ABC in `src/domain/repositories/user_repository.py`
    - Add `list_paginated(page, page_size, status_filter, role_filter) -> tuple[list[User], int]`
    - Add `find_by_verification_token(token: str) -> User | None`
    - _Requirements: 12.2, 5.3_

  - [x] 2.7 Extend TokenService ABC in `src/domain/repositories/token_service.py`
    - Ensure `jti` claim is part of the contract (tokens must include jti)
    - Add blacklist check requirement to `verify_token` contract
    - _Requirements: 4.1, 4.4_

- [x] 3. Checkpoint — Domain layer complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Application layer — AuthService security hardening
  - [x] 4.1 Create new command DTOs
    - Create `src/application/commands/verify_email.py` with `VerifyEmailCommand`
    - Create `src/application/commands/resend_verification.py` with `ResendVerificationCommand`
    - Create `src/application/commands/logout.py` with `LogoutCommand`
    - _Requirements: 5.3, 6.1, 4.2_

  - [x] 4.2 Modify AuthService for account lockout and login gates
    - Add `token_blacklist` and `password_validator` constructor dependencies
    - In `authenticate()`: check `is_locked()` → raise `AccountLockedError` with `retry_after_seconds`
    - In `authenticate()`: on invalid password → call `record_failed_login()`, persist, publish `identity.auth.login_failed`; on 5th failure also publish `identity.auth.account_locked`
    - In `authenticate()`: check `pending_verification` → raise `AuthenticationError(EMAIL_NOT_VERIFIED)`
    - In `authenticate()`: check `require_password_change` → raise `AuthenticationError(PASSWORD_CHANGE_REQUIRED)`
    - On success: call `record_successful_login()`, persist, publish `identity.auth.login_success`
    - Include `require_password_change` in login response
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 3.1, 3.3, 3.5, 3.6_

  - [ ]* 4.3 Write unit tests for AuthService lockout and login gates in `tests/unit/application/test_auth_service.py`
    - Test locked account raises `AccountLockedError` with positive `retry_after_seconds`
    - Test failed login increments attempts and persists
    - Test 5th failure publishes `identity.auth.account_locked` event
    - Test `pending_verification` user raises `AuthenticationError(EMAIL_NOT_VERIFIED)`
    - Test `require_password_change` user raises `AuthenticationError(PASSWORD_CHANGE_REQUIRED)`
    - Test successful login calls `record_successful_login()` and publishes `identity.auth.login_success`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 3.1, 3.3, 3.5_

  - [x] 4.4 Implement verify_email, resend_verification, and logout in AuthService
    - `verify_email(token)`: find by verification token, validate not expired (24h), call `user.verify_email()`, publish `identity.user.activated`
    - `resend_verification(email)`: find user, if `pending_verification` generate new token, publish `identity.auth.verification_requested`; always return success
    - `logout(access_token)`: extract jti, add to blacklist with TTL = token exp
    - _Requirements: 4.2, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4_

  - [ ]* 4.5 Write unit tests for verify_email, resend_verification, logout in `tests/unit/application/test_auth_service.py`
    - Test verify_email with valid token activates user and publishes event
    - Test verify_email with invalid token raises `ValidationError`
    - Test verify_email on already-verified user raises `ConflictError`
    - Test resend_verification with pending user generates new token and publishes event
    - Test resend_verification with non-existent email returns success without event
    - Test logout blacklists the token jti
    - _Requirements: 4.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4_

  - [x] 4.6 Migrate AuthService to domain exceptions and add password validation
    - Replace all `ValueError` raises with `ConflictError` (duplicate email) and `AuthenticationError` (invalid credentials)
    - Add `PasswordValidator.validate()` call in `register()` and `reset_password()`; raise `ValidationError` on failure
    - Update `register()` to set `status=pending_verification`, generate verification token, publish `identity.user.registered` (not `identity.user.created`)
    - Add password validation to `reset_password()`, publish `identity.auth.password_changed`
    - _Requirements: 7.4, 7.5, 8.2, 8.3, 9.3_

  - [ ]* 4.7 Write unit tests for domain exception migration and password validation in AuthService
    - Test duplicate email raises `ConflictError` (not `ValueError`)
    - Test invalid credentials raises `AuthenticationError` (not `ValueError`)
    - Test weak password during registration raises `ValidationError`
    - Test weak password during reset raises `ValidationError`
    - Test registration sets `pending_verification` and generates verification token
    - Test registration publishes `identity.user.registered` event with correct payload
    - _Requirements: 7.4, 7.5, 8.2, 8.3, 9.3_

  - [ ]* 4.8 Write property tests for AuthService in `tests/property/test_auth_service_props.py`
    - **Property 6: Locked accounts are rejected at login**
    - **Validates: Requirements 2.3**
    - **Property 7: Login failure publishes account_locked event on 5th attempt**
    - **Validates: Requirements 2.6**
    - **Property 8: Pending verification users are rejected at login**
    - **Validates: Requirements 3.1**
    - **Property 9: Password change required users are rejected at login**
    - **Validates: Requirements 3.3**
    - **Property 10: All tokens contain a unique jti claim**
    - **Validates: Requirements 4.1**
    - **Property 11: Logout blacklists the token jti**
    - **Validates: Requirements 4.2, 4.4, 4.5**
    - **Property 12: Registration produces pending_verification user with verification token**
    - **Validates: Requirements 5.1**
    - **Property 13: Registration publishes identity.user.registered event**
    - **Validates: Requirements 5.2, 9.3**
    - **Property 14: Email verification activates user and clears  token**
    - **Validates: Requirements 5.3**
    - **Property 15: Invalid verification tokens are rejected**
    - **Validates: Requirements 5.4**
    - **Property 16: Resend verification generates new token or no-ops safely**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
    - **Property 18: Weak passwords are rejected during registration and reset**
    - **Validates: Requirements 7.4, 7.5**
    - **Property 19: AuthService raises correct domain exception types**
    - **Validates: Requirements 8.2, 8.3**

- [x] 5. Checkpoint — AuthService complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Application layer — UserService admin operations and pagination
  - [x] 6.1 Create admin command DTOs and ListUsersQuery
    - Create `src/application/commands/admin_user.py` with `SuspendUserCommand`, `ActivateUserCommand`, `RequirePasswordChangeCommand`
    - Create `src/application/queries/list_users.py` with `ListUsersQuery`
    - _Requirements: 10.1, 10.2, 10.3, 12.1_

  - [x] 6.2 Implement admin operations and pagination in UserService
    - `suspend_user(cmd)`: verify admin, set status=inactive, persist, publish `identity.user.deactivated`
    - `activate_user(cmd)`: verify admin, set status=active, persist, publish `identity.user.activated`
    - `require_password_change(cmd)`: verify admin, set flag, persist
    - `list_users(query)`: verify admin, delegate to `user_repository.list_paginated()`, cap `page_size` at 100
    - Migrate all `ValueError` to `NotFoundError`, `PermissionError` to `AuthorizationError`
    - _Requirements: 8.4, 8.5, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 12.1, 12.2, 12.3, 12.4, 12.5_

  - [ ]* 6.3 Write unit tests for UserService admin operations and pagination in `tests/unit/application/test_user_service.py`
    - Test suspend sets status=inactive and publishes `identity.user.deactivated`
    - Test activate sets status=active and publishes `identity.user.activated`
    - Test require_password_change sets flag
    - Test non-admin raises `AuthorizationError` for all admin operations
    - Test non-existent user raises `NotFoundError`
    - Test list_users returns correct page with metadata
    - Test page_size capped at 100
    - Test status and role filters are passed through
    - _Requirements: 8.4, 8.5, 10.1, 10.2, 10.3, 10.4, 10.5, 12.1, 12.2, 12.4, 12.5_

  - [ ]* 6.4 Write property tests for UserService in `tests/property/test_user_service_props.py`
    - **Property 20: UserService raises correct domain exception types**
    - **Validates: Requirements 8.4, 8.5**
    - **Property 24: Suspend then activate restores active status**
    - **Validates: Requirements 10.1, 10.2**
    - **Property 25: Require password change sets the flag**
    - **Validates: Requirements 10.3**
    - **Property 26: Non-admin users are rejected from admin endpoints**
    - **Validates: Requirements 10.4**
    - **Property 28: Paginated list returns correct page with correct metadata**
    - **Validates: Requirements 12.1, 12.2, 12.3**
    - **Property 29: Status and role filters produce correct subsets**
    - **Validates: Requirements 12.5**

- [x] 7. Checkpoint — Application layer complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Infrastructure layer — DynamoDB adapters and JWT changes
  - [x] 8.1 Extend DynamoDBUserRepository for new fields and queries
    - Update `_to_item` / `_from_item` to serialize/deserialize all new User fields
    - Handle backward compatibility: missing attributes default to safe values
    - Implement `list_paginated()` with offset-based pagination; use `status-index` GSI when status filter provided
    - Implement `find_by_verification_token()` with scan + filter expression
    - _Requirements: 13.1, 13.2, 13.4_

  - [ ]* 8.2 Write integration tests for DynamoDBUserRepository in `tests/integration/test_dynamodb_user_repo.py`
    - Test round-trip serialization of User with all new fields (moto)
    - Test deserialization of legacy items missing new fields uses defaults
    - Test `list_paginated` returns correct page and total count
    - Test `find_by_verification_token` returns matching user
    - _Requirements: 13.1, 13.2, 13.4_

  - [ ]* 8.3 Write property tests for DynamoDB serialization in `tests/property/test_serialization_props.py`
    - **Property 30: DynamoDB serialization round trip preserves User entity**
    - **Validates: Requirements 13.1**
    - **Property 31: DynamoDB deserialization handles missing new fields with defaults**
    - **Validates: Requirements 13.2**

  - [x] 8.4 Create DynamoDBTokenBlacklistRepository in `src/infrastructure/persistence/dynamodb_token_blacklist.py`
    - Implement `add(jti, ttl_epoch)` writing `{jti, ttl}` to `ugsys-identity-{env}-token-blacklist`
    - Implement `is_blacklisted(jti)` checking item existence
    - _Requirements: 4.3, 13.3_

  - [ ]* 8.5 Write integration tests for DynamoDBTokenBlacklistRepository in `tests/integration/test_dynamodb_token_blacklist.py`
    - Test `add` writes item with correct jti and ttl (moto)
    - Test `is_blacklisted` returns True for existing jti, False for unknown
    - _Requirements: 4.3, 13.3_

  - [x] 8.6 Modify JWTTokenService for jti and blacklist integration
    - Add `jti` (UUID4) claim to every token created (access, refresh, service)
    - Add `token_blacklist: TokenBlacklistRepository` constructor parameter
    - In `verify_token()`: check blacklist for jti before returning payload; raise `AuthenticationError("Token has been revoked")` if blacklisted
    - _Requirements: 4.1, 4.4, 4.5_

  - [ ]* 8.7 Write unit tests for JWTTokenService jti and blacklist in `tests/unit/test_jwt_token_service.py`
    - Test all created tokens contain a `jti` claim (UUID4)
    - Test two consecutive tokens have different `jti` values
    - Test `verify_token` raises `AuthenticationError` when jti is blacklisted
    - Test `verify_token` succeeds when jti is not blacklisted
    - _Requirements: 4.1, 4.4, 4.5_

  - [x] 8.8 Update EventBridgePublisher to implement EventPublisher ABC
    - Migrate from existing `EventPublisher` class to implement the new domain `EventPublisher` ABC
    - Use `ugsys-event-lib` envelope format with `event_id`, `event_version`, `timestamp`, `correlation_id`, `payload`
    - Hardcode source to `"ugsys.identity-manager"`
    - _Requirements: 9.1, 9.2_

  - [x] 8.9 Update `src/config.py` for event bus name and token blacklist table
    - Change `event_bus_name` default to `"ugsys-platform-bus"` (was `"ugsys-event-bus"`)
    - Add `token_blacklist_table_name` field with computed property for `ugsys-identity-{env}-token-blacklist`
    - _Requirements: 9.1, 4.3_

- [x] 9. Checkpoint — Infrastructure layer complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Presentation layer — Exception handler, response envelope, and router updates
  - [x] 10.1 Create exception handler in `src/presentation/middleware/exception_handler.py`
    - Implement `domain_exception_handler` mapping each domain exception to correct HTTP status
    - Special handling: `AccountLockedError` → include `retry_after_seconds`; `EMAIL_NOT_VERIFIED` → include `email_not_verified: true`; `PASSWORD_CHANGE_REQUIRED` → include `require_password_change: true`
    - Implement `unhandled_exception_handler` returning 500 with generic message, logging full details
    - All error responses wrapped in envelope format
    - _Requirements: 8.6, 8.7, 2.5, 3.2, 3.4, 11.3_

  - [ ]* 10.2 Write unit tests for exception handler in `tests/unit/presentation/test_exception_handler.py`
    - Test each domain exception type maps to correct HTTP status code
    - Test response body contains `user_message` only (never internal `message`)
    - Test `AccountLockedError` response includes `retry_after_seconds`
    - Test `EMAIL_NOT_VERIFIED` response includes `email_not_verified: true`
    - Test `PASSWORD_CHANGE_REQUIRED` response includes `require_password_change: true`
    - Test unhandled exception returns 500 with generic message
    - _Requirements: 8.6, 8.7, 2.5, 3.2, 3.4, 11.3_

  - [ ]* 10.3 Write property tests for exception handler in `tests/property/test_exception_handler_props.py`
    - **Property 21: Domain exception handler maps exceptions to correct HTTP status codes**
    - **Validates: Requirements 8.6, 11.3**

  - [x] 10.4 Create response envelope utilities in `src/presentation/response_envelope.py`
    - Implement `success_response(data, request_id)` → `{ "data": ..., "meta": { "request_id": ... } }`
    - Implement `list_response(data, total, page, page_size, request_id)` → includes pagination metadata with `total_pages = ceil(total / page_size)`
    - _Requirements: 11.1, 11.2_

  - [ ]* 10.5 Write unit tests for response envelope in `tests/unit/presentation/test_response_envelope.py`
    - Test `success_response` wraps data with meta.request_id
    - Test `list_response` includes correct pagination metadata
    - Test `total_pages` calculation (ceil division)
    - _Requirements: 11.1, 11.2_

  - [x] 10.6 Update auth router with new endpoints and envelope wrapping
    - Add `POST /api/v1/auth/verify-email` (public)
    - Add `POST /api/v1/auth/resend-verification` (public)
    - Add `POST /api/v1/auth/logout` (Bearer required)
    - Add `POST /api/v1/auth/validate-token` (service Bearer required)
    - Wrap all existing endpoint responses in envelope format
    - Remove manual try/except ValueError blocks (handled by exception_handler)
    - _Requirements: 5.3, 6.1, 4.2, 14.1, 14.2, 14.3, 14.4, 11.1, 11.4_

  - [ ]* 10.7 Write unit tests for auth router new endpoints in `tests/unit/presentation/test_auth_router.py`
    - Test verify-email endpoint calls service and returns envelope
    - Test resend-verification endpoint returns 200 with consistent message
    - Test logout endpoint blacklists token and returns envelope
    - Test validate-token with valid token returns `{valid: true, sub, roles, type}`
    - Test validate-token with invalid token returns `{valid: false}` (HTTP 200)
    - Test validate-token without service token returns 401
    - _Requirements: 5.3, 6.2, 4.2, 14.1, 14.2, 14.3, 14.4_

  - [x] 10.8 Update users router with admin endpoints and pagination
    - Add `POST /api/v1/users/{id}/suspend` (admin only)
    - Add `POST /api/v1/users/{id}/activate` (admin only)
    - Add `POST /api/v1/users/{id}/require-password-change` (admin only)
    - Update `GET /api/v1/users` to accept `page`, `page_size`, `status`, `role` query params
    - Wrap all responses in envelope format, list endpoint uses `list_response`
    - Remove manual exception catching
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 11.1, 11.2, 12.1, 12.4_

  - [ ]* 10.9 Write unit tests for users router admin endpoints and pagination
    - Test suspend endpoint calls service and returns envelope
    - Test activate endpoint calls service and returns envelope
    - Test require-password-change endpoint calls service and returns envelope
    - Test non-admin gets 403 on admin endpoints
    - Test GET /users returns paginated envelope with metadata
    - Test page_size > 100 is capped
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 12.1, 12.4_

- [x] 11. Wire everything in main.py
  - [x] 11.1 Update `src/main.py` composition root
    - Register `domain_exception_handler` and `unhandled_exception_handler`
    - Wire `DynamoDBTokenBlacklistRepository` and inject into `JWTTokenService` and `AuthService`
    - Wire `PasswordValidator` into `AuthService`
    - Disable docs in prod (`docs_url=None if settings.environment == "prod" else "/docs"`)
    - _Requirements: 8.6, 8.7, 4.3_

  - [ ]* 11.2 Write unit tests for main.py wiring
    - Test `create_app()` returns a FastAPI instance with all routers registered
    - Test exception handlers are registered for `DomainError` and `Exception`
    - _Requirements: 8.6, 8.7_

- [x] 12. Final checkpoint — Full integration verification
  - Ensure all tests pass, ask the user if questions arise.
  - Verify all 14 requirements are covered by implementation
  - Verify domain exceptions are used everywhere (no raw ValueError/PermissionError from app/domain)
  - Verify all API responses use envelope format

- [x] 13. Moto integration tests — DynamoDB adapters
  - [x] 13.1 Write integration tests for DynamoDBUserRepository in `tests/integration/test_dynamodb_user_repo.py`
    - Use `moto` `mock_aws` decorator to spin up a fake DynamoDB table matching the real schema (PK=`pk`, SK=`sk`, GSI `status-index`)
    - Test `save()` then `find_by_id()` round-trips all User fields including new security/verification fields
    - Test `find_by_email()` returns correct user
    - Test deserialization of a legacy item (missing new fields) uses correct defaults for `failed_login_attempts`, `email_verified`, `require_password_change`, `is_admin`
    - Test `update()` persists changed fields
    - Test `list_paginated(page=1, page_size=2)` with 5 users returns 2 users and total=5
    - Test `list_paginated` with `status_filter="active"` returns only active users
    - Test `find_by_verification_token()` returns the matching user
    - Test `find_by_verification_token()` returns None for unknown token
    - _Requirements: 13.1, 13.2, 13.4_

  - [x] 13.2 Write integration tests for DynamoDBTokenBlacklistRepository in `tests/integration/test_dynamodb_token_blacklist.py`
    - Use `moto` `mock_aws` decorator to spin up a fake DynamoDB table with PK=`jti` and TTL attribute `ttl`
    - Test `add(jti, ttl_epoch)` writes item with correct attributes
    - Test `is_blacklisted(jti)` returns `True` for a jti that was added
    - Test `is_blacklisted(jti)` returns `False` for an unknown jti
    - Test adding the same jti twice does not raise (idempotent)
    - _Requirements: 4.3, 13.3_

- [-] 14. Moto integration tests — Full HTTP layer (httpx + moto + FastAPI)
  - [x] 14.1 Create integration test fixtures in `tests/integration/conftest.py`
    - `aws_credentials` fixture: set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` to moto-safe dummy values via `monkeypatch`
    - `dynamodb_tables` fixture (depends on `aws_credentials`): use `moto` `mock_aws` to create both DynamoDB tables (`ugsys-identity-manager-users-test` and `ugsys-identity-test-token-blacklist`) with correct key schemas and GSI
    - `app_client` fixture (depends on `dynamodb_tables`): set `ENVIRONMENT=test`, `DYNAMODB_TABLE_NAME=ugsys-identity-manager-users-test`, `TOKEN_BLACKLIST_TABLE_NAME=ugsys-identity-test-token-blacklist`, `JWT_SECRET_KEY=test-secret`, `JWT_ALGORITHM=HS256`; import and call `create_app()` (or use the existing `app`); return `httpx.AsyncClient(app=app, base_url="http://test")`
    - _No requirements reference — test infrastructure_

  - [ ] 14.2 Write HTTP integration tests for auth flows in `tests/integration/test_auth_http.py`
    - **Register → verify-email → login happy path**: POST `/api/v1/auth/register`, extract `verification_token` from the published event (or directly from DynamoDB), POST `/api/v1/auth/verify-email`, POST `/api/v1/auth/login` → assert 200 with `access_token`
    - **Register duplicate email**: POST register twice with same email → assert 409 with `error.code == "EMAIL_ALREADY_EXISTS"` (or `"CONFLICT"`)
    - **Login before email verification**: register then immediately login → assert 401 with `error.email_not_verified == true`
    - **Login with wrong password**: register + verify + login with wrong password → assert 401
    - **Account lockout**: register + verify + 5 failed logins → assert 423 with `error.retry_after_seconds > 0`
    - **Logout + token reuse**: register + verify + login → logout with access token → attempt to use same token → assert 401 with revoked message
    - **Refresh token**: register + verify + login → POST `/api/v1/auth/refresh` with refresh_token → assert new access_token
    - **Forgot password + reset**: register + verify + POST `/api/v1/auth/forgot-password` → assert 200; POST `/api/v1/auth/reset-password` with token from event → assert 200
    - _Requirements: 1–7, 11_

  - [ ] 14.3 Write HTTP integration tests for user management in `tests/integration/test_users_http.py`
    - **GET /api/v1/users (admin)**: create 3 users, login as admin, GET users → assert paginated envelope with `meta.total == 3`
    - **GET /api/v1/users (non-admin)**: login as regular member → assert 403
    - **Suspend user**: admin suspends a user → assert 200; suspended user tries to login → assert 401
    - **Activate user**: admin activates a suspended user → assert 200; user can login again
    - **Require password change**: admin sets flag → user logs in → response includes `require_password_change: true`
    - **GET /api/v1/users/{id}**: admin fetches specific user → assert envelope with correct user data
    - _Requirements: 10, 12_

- [ ] 15. Smoke test script against deployed API
  - [ ] 15.1 Create `scripts/smoke_test.py` inside `ugsys-identity-manager/`
    - Accept `BASE_URL` from environment variable (e.g. `IDENTITY_API_URL=https://<id>.execute-api.us-east-1.amazonaws.com/prod`)
    - Test sequence using `httpx` (sync):
      1. GET `/health` → assert `{"status": "ok"}`
      2. POST `/api/v1/auth/register` with unique email → assert 201, response has `data.user_id`
      3. POST `/api/v1/auth/login` with same credentials before verification → assert 401 with `email_not_verified`
      4. POST `/api/v1/auth/resend-verification` → assert 200
      5. POST `/api/v1/auth/forgot-password` → assert 200 (anti-enumeration)
    - Print PASS/FAIL for each step with response status and body summary
    - Exit with code 1 if any step fails
    - _No requirements reference — operational verification_

  - [ ] 15.2 Document the smoke test usage in `README.md`
    - Add a "Testing" section explaining how to run smoke tests: `IDENTITY_API_URL=<url> uv run python scripts/smoke_test.py`
    - Note that full register→verify→login flow requires checking CloudWatch logs or EventBridge for the verification token (since email delivery is async)
    - _No requirements reference — documentation_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (Properties 1–33)
- Unit tests validate specific examples and edge cases
- Domain layer tasks (1–2) have zero external dependencies and are instantly testable
- Application layer tasks (4, 6) depend only on mockable domain ports
- Infrastructure tasks (8) require moto for integration tests
- Presentation tasks (10) use FastAPI TestClient with mocked services
- Integration tests (13–14) use `moto` — no real AWS calls, no cost, safe to run in CI
- Smoke test (15) requires `IDENTITY_API_URL` env var pointing at the deployed API Gateway endpoint
