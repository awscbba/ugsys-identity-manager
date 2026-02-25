# Requirements Document

## Introduction

Complete all P0, P1, and P2 implementation gaps in the `ugsys-identity-manager` service as defined in the platform contract (`ugsys-documentation/specs/platform-contract.md`, Section 3 and Section 10.1). The service currently has a working hexagonal architecture with auth flows (register, login, refresh, forgot-password, reset-password), DynamoDB persistence, and EventBridge publishing. This spec closes every remaining gap to reach Phase 1 completion: account lockout, email verification, token blacklist, missing events, admin user management endpoints, domain exception migration, response envelope standardization, and pagination.

## Glossary

- **Identity_Manager**: The `ugsys-identity-manager` microservice responsible for authentication, user management, and role-based access control
- **User_Entity**: The core domain object representing a registered user, stored in DynamoDB table `ugsys-identity-manager-users-{env}`
- **Auth_Service**: The application-layer service that orchestrates authentication use cases (register, login, refresh, logout, verify-email, resend-verification, forgot-password, reset-password)
- **User_Service**: The application-layer service that orchestrates user management use cases (get, list, update, suspend, activate, role assignment)
- **Token_Service**: The domain port (interface) for JWT token creation and verification
- **Token_Blacklist**: A DynamoDB table (`ugsys-identity-{env}-token-blacklist`) that stores revoked token JTIs with TTL-based auto-expiry
- **Event_Publisher**: The infrastructure adapter that publishes domain events to the `ugsys-platform-bus` EventBridge bus using the `ugsys-event-lib` envelope format
- **Domain_Exception**: A structured exception hierarchy (`DomainError`, `ConflictError`, `AuthenticationError`, `AuthorizationError`, `NotFoundError`, `ValidationError`, `AccountLockedError`) that separates internal log messages from user-safe messages
- **Response_Envelope**: The standardized JSON response format `{ "data": ..., "meta": { "request_id": ... } }` for all API responses
- **Password_Validator**: A domain value object that enforces password complexity rules (min 8 chars, uppercase, lowercase, digit, special character)
- **Verification_Token**: A UUID4 token generated on registration, stored on the User_Entity, used to verify email ownership within 24 hours
- **Account_Lockout**: A security mechanism that locks a user account for 30 minutes after 5 consecutive failed login attempts
- **UserRole_Enum**: The set of valid roles: `super_admin`, `admin`, `moderator`, `auditor`, `member`, `guest`, `system`
- **UserStatus_Enum**: The set of valid statuses: `active`, `inactive`, `pending_verification`

## Requirements

### Requirement 1: User Entity Field Completion

**User Story:** As a platform operator, I want the User entity to contain all fields defined in the platform contract, so that security features (lockout, verification, password change enforcement) can be implemented.

#### Acceptance Criteria

1. THE User_Entity SHALL include the fields `failed_login_attempts` (int, default 0), `account_locked_until` (datetime or None, default None), `last_login_at` (datetime or None, default None), `last_password_change` (datetime or None, default None), `require_password_change` (bool, default False), `email_verified` (bool, default False), `email_verification_token` (str or None, default None), `email_verified_at` (datetime or None, default None), and `is_admin` (bool, default False)
2. THE UserRole_Enum SHALL include all seven roles defined in the platform contract: `super_admin`, `admin`, `moderator`, `auditor`, `member`, `guest`, `system`
3. THE UserStatus_Enum SHALL include exactly three values: `active`, `inactive`, `pending_verification`
4. THE User_Entity SHALL expose a method `is_locked()` that returns True WHEN `account_locked_until` is not None and `account_locked_until` is in the future
5. THE User_Entity SHALL expose a method `record_failed_login()` that increments `failed_login_attempts` by 1 and sets `account_locked_until` to 30 minutes from now WHEN `failed_login_attempts` reaches 5
6. THE User_Entity SHALL expose a method `reset_login_attempts()` that sets `failed_login_attempts` to 0 and `account_locked_until` to None
7. THE User_Entity SHALL expose a method `record_successful_login()` that calls `reset_login_attempts()` and sets `last_login_at` to the current UTC timestamp

### Requirement 2: Account Lockout Enforcement

**User Story:** As a security officer, I want user accounts to be locked after 5 consecutive failed login attempts, so that brute-force attacks are mitigated.

#### Acceptance Criteria

1. WHEN a login attempt fails due to invalid credentials, THE Auth_Service SHALL call `record_failed_login()` on the User_Entity and persist the updated state
2. WHEN a user account has `failed_login_attempts` equal to 5, THE User_Entity SHALL set `account_locked_until` to 30 minutes from the current UTC timestamp
3. WHEN a login attempt is made against a locked account (where `is_locked()` returns True), THE Auth_Service SHALL raise an `AccountLockedError` with a user-safe message containing `retry_after_seconds`
4. WHEN a login attempt succeeds, THE Auth_Service SHALL call `record_successful_login()` on the User_Entity and persist the updated state
5. IF the Auth_Service raises an `AccountLockedError`, THEN THE Identity_Manager SHALL return HTTP 423 with body `{ "retry_after_seconds": N }`
6. WHEN the 5th consecutive failed login attempt occurs, THE Event_Publisher SHALL publish an `identity.auth.account_locked` event with payload `{ user_id, email, locked_until }`

### Requirement 3: Login Flow Enforcement (Verification and Password Change)

**User Story:** As a platform operator, I want login to enforce email verification and password change requirements, so that users complete mandatory security steps before accessing the system.

#### Acceptance Criteria

1. WHEN a user with status `pending_verification` attempts to log in, THE Auth_Service SHALL raise an `AuthenticationError` with error code `EMAIL_NOT_VERIFIED` and user message indicating email verification is required
2. IF the Auth_Service raises an `EMAIL_NOT_VERIFIED` error, THEN THE Identity_Manager SHALL return HTTP 403 with body containing `{ "email_not_verified": true }`
3. WHEN a user with `require_password_change` set to True attempts to log in, THE Auth_Service SHALL raise an `AuthenticationError` with error code `PASSWORD_CHANGE_REQUIRED` and user message indicating password change is required
4. IF the Auth_Service raises a `PASSWORD_CHANGE_REQUIRED` error, THEN THE Identity_Manager SHALL return HTTP 403 with body containing `{ "require_password_change": true }`
5. WHEN a login attempt succeeds, THE Auth_Service SHALL set `last_login_at` on the User_Entity to the current UTC timestamp
6. THE Auth_Service SHALL include `require_password_change` in the login success response body

### Requirement 4: Token Blacklist for Logout

**User Story:** As a security officer, I want logout to invalidate tokens server-side, so that stolen tokens cannot be reused after the user logs out.

#### Acceptance Criteria

1. THE Token_Service SHALL include a unique `jti` (JWT ID) claim in every access token and refresh token it creates
2. WHEN a user calls POST `/api/v1/auth/logout`, THE Auth_Service SHALL extract the `jti` from the provided access token and store it in the Token_Blacklist with a TTL matching the token expiration time
3. THE Token_Blacklist SHALL be a DynamoDB table with partition key `jti` (String) and a `ttl` attribute (Number) configured for DynamoDB TTL auto-expiry
4. WHEN the Token_Service verifies a token, THE Token_Service SHALL check the Token_Blacklist for the token `jti` and reject the token if the `jti` is found
5. IF a blacklisted token is presented for authentication, THEN THE Token_Service SHALL raise an `AuthenticationError` with user message "Token has been revoked"

### Requirement 5: Email Verification Flow

**User Story:** As a new user, I want to verify my email address after registration, so that my account becomes active and I can log in.

#### Acceptance Criteria

1. WHEN a new user registers, THE Auth_Service SHALL generate a UUID4 verification token, store it on the User_Entity as `email_verification_token`, and set the user status to `pending_verification`
2. WHEN a new user registers, THE Event_Publisher SHALL publish an `identity.user.registered` event with payload `{ user_id, email, full_name, verification_token, expires_at }` where `expires_at` is 24 hours from registration time
3. WHEN a valid verification token is submitted to POST `/api/v1/auth/verify-email`, THE Auth_Service SHALL set the user status to `active`, set `email_verified` to True, set `email_verified_at` to the current UTC timestamp, and clear `email_verification_token`
4. IF an invalid or expired verification token is submitted, THEN THE Auth_Service SHALL raise a `ValidationError` with user message "Invalid or expired verification token"
5. IF a verification token is submitted for an already-verified user, THEN THE Auth_Service SHALL raise a `ConflictError` with user message "Email already verified"
6. WHEN email verification succeeds, THE Event_Publisher SHALL publish an `identity.user.activated` event with payload `{ user_id, email }`

### Requirement 6: Resend Verification Email

**User Story:** As a user who did not receive the verification email, I want to request a new verification email, so that I can complete the verification process.

#### Acceptance Criteria

1. WHEN a user submits POST `/api/v1/auth/resend-verification` with an email address, THE Auth_Service SHALL generate a new UUID4 verification token and update the User_Entity
2. THE Identity_Manager SHALL return HTTP 200 with message "If the account exists and is unverified, a new email has been sent" regardless of whether the email exists or the account status, to prevent user enumeration
3. WHEN the email corresponds to a user with status `pending_verification`, THE Event_Publisher SHALL publish an `identity.auth.verification_requested` event with payload `{ user_id, email, verification_token, expires_at }`
4. WHEN the email does not correspond to any user or corresponds to an already-verified user, THE Auth_Service SHALL return success without publishing any event

### Requirement 7: Password Strength Validation

**User Story:** As a security officer, I want passwords to meet complexity requirements, so that user accounts are protected against dictionary and brute-force attacks.

#### Acceptance Criteria

1. THE Password_Validator SHALL enforce a minimum length of 8 characters
2. THE Password_Validator SHALL require at least one uppercase letter, one lowercase letter, one digit, and one special character from the set `!@#$%^&*()_+-=[]{}|;:,.<>?`
3. WHEN a password fails validation, THE Password_Validator SHALL return a descriptive error message listing which rules were violated
4. THE Auth_Service SHALL validate passwords using the Password_Validator during registration, password change, and password reset operations
5. IF a password fails validation, THEN THE Auth_Service SHALL raise a `ValidationError` with a user-safe message describing the password requirements

### Requirement 8: Domain Exception Migration

**User Story:** As a developer, I want all application and domain layer code to use the domain exception hierarchy, so that error handling is consistent and internal details are never exposed to API callers.

#### Acceptance Criteria

1. THE Identity_Manager SHALL define a domain exception hierarchy in `src/domain/exceptions.py` containing `DomainError`, `ValidationError`, `NotFoundError`, `ConflictError`, `AuthenticationError`, `AuthorizationError`, `AccountLockedError`, `RepositoryError`, and `ExternalServiceError`
2. THE Auth_Service SHALL raise `ConflictError` instead of `ValueError` when a duplicate email is detected during registration
3. THE Auth_Service SHALL raise `AuthenticationError` instead of `ValueError` when credentials are invalid during login
4. THE User_Service SHALL raise `NotFoundError` instead of `ValueError` when a user is not found
5. THE User_Service SHALL raise `AuthorizationError` instead of `PermissionError` when an IDOR violation is detected
6. THE Identity_Manager SHALL register a `domain_exception_handler` in `main.py` that maps each domain exception type to the correct HTTP status code and returns only the `user_message` to the client
7. THE Identity_Manager SHALL register an `unhandled_exception_handler` that returns HTTP 500 with a generic message and logs the full exception details

### Requirement 9: EventBridge Event Alignment

**User Story:** As a platform architect, I want all identity-manager events to match the platform contract event catalog, so that downstream services (user-profile, omnichannel) can consume events reliably.

#### Acceptance Criteria

1. THE Identity_Manager config SHALL use `event_bus_name = "ugsys-platform-bus"` instead of `"ugsys-event-bus"`
2. THE Event_Publisher SHALL use the `ugsys-event-lib` envelope format with fields `event_id`, `event_version`, `timestamp`, `correlation_id`, and `payload`
3. WHEN a user registers, THE Event_Publisher SHALL publish `identity.user.registered` (not `identity.user.created`)
4. WHEN a login succeeds, THE Event_Publisher SHALL publish `identity.auth.login_success` with payload `{ user_id, ip_address }`
5. WHEN a login fails, THE Event_Publisher SHALL publish `identity.auth.login_failed` with payload `{ email, ip_address, attempt_count }`
6. WHEN a password is changed or reset, THE Event_Publisher SHALL publish `identity.auth.password_changed` with payload `{ user_id, email }`
7. WHEN a user is deactivated, THE Event_Publisher SHALL publish `identity.user.deactivated` with payload `{ user_id, email }`
8. WHEN a role is assigned or removed, THE Event_Publisher SHALL publish `identity.user.role_changed` with payload `{ user_id, email, role, action }`

### Requirement 10: Admin User Management Endpoints

**User Story:** As an admin, I want to suspend, activate, and force password changes on user accounts, so that I can manage user lifecycle and enforce security policies.

#### Acceptance Criteria

1. WHEN an admin calls POST `/api/v1/users/{id}/suspend`, THE User_Service SHALL set the user status to `inactive` and persist the change
2. WHEN an admin calls POST `/api/v1/users/{id}/activate`, THE User_Service SHALL set the user status to `active` and persist the change
3. WHEN an admin calls POST `/api/v1/users/{id}/require-password-change`, THE User_Service SHALL set `require_password_change` to True on the User_Entity and persist the change
4. IF a non-admin user calls any of the admin user management endpoints, THEN THE Identity_Manager SHALL return HTTP 403
5. IF the target user does not exist, THEN THE User_Service SHALL raise a `NotFoundError`
6. WHEN a user is suspended, THE Event_Publisher SHALL publish `identity.user.deactivated` with payload `{ user_id, email }`
7. WHEN a user is activated, THE Event_Publisher SHALL publish `identity.user.activated` with payload `{ user_id, email }`

### Requirement 11: Response Envelope Standardization

**User Story:** As an API consumer, I want all responses to follow a consistent envelope format, so that client-side parsing logic is uniform across all endpoints.

#### Acceptance Criteria

1. THE Identity_Manager SHALL wrap all successful single-resource responses in `{ "data": { ... }, "meta": { "request_id": "<correlation_id>" } }`
2. THE Identity_Manager SHALL wrap all successful list responses in `{ "data": [ ... ], "meta": { "request_id": "...", "total": N, "page": N, "page_size": N, "total_pages": N } }`
3. THE Identity_Manager SHALL wrap all error responses in `{ "error": { "code": "...", "message": "..." }, "meta": { "request_id": "..." } }`
4. THE Identity_Manager SHALL never return raw dictionaries or lists without the envelope wrapper from any API endpoint

### Requirement 12: Pagination on GET /users

**User Story:** As an admin, I want to paginate the user list, so that I can efficiently browse large numbers of users without loading all records at once.

#### Acceptance Criteria

1. WHEN an admin calls GET `/api/v1/users`, THE Identity_Manager SHALL accept query parameters `page` (default 1) and `page_size` (default 20, max 100)
2. THE User_Service SHALL return only the requested page of users along with total count
3. THE Identity_Manager SHALL include pagination metadata in the response envelope: `total`, `page`, `page_size`, `total_pages`
4. IF `page_size` exceeds 100, THEN THE Identity_Manager SHALL cap the value at 100 without raising an error
5. WHEN optional query parameters `status` and `role` are provided, THE User_Service SHALL filter the user list accordingly before pagination

### Requirement 13: DynamoDB Persistence for New Fields

**User Story:** As a developer, I want the DynamoDB adapter to persist and retrieve all new User entity fields, so that security state (lockout, verification, password change) survives across Lambda invocations.

#### Acceptance Criteria

1. THE DynamoDB adapter SHALL serialize and deserialize all new User_Entity fields: `failed_login_attempts`, `account_locked_until`, `last_login_at`, `last_password_change`, `require_password_change`, `email_verified`, `email_verification_token`, `email_verified_at`, `is_admin`
2. THE DynamoDB adapter SHALL handle missing attributes gracefully by using default values for new fields when reading records created before the schema update
3. WHEN the Token_Blacklist table is used, THE DynamoDB adapter SHALL write items with `jti` as partition key and `ttl` as a Number attribute set to the token expiration epoch timestamp
4. THE DynamoDB adapter SHALL use the `status-index` GSI (PK = `status`, SK = `created_at`) for filtered user queries by status

### Requirement 14: Validate Token Endpoint for S2S Auth

**User Story:** As a downstream service developer, I want a POST `/api/v1/auth/validate-token` endpoint, so that `ugsys-auth-client` can perform remote token validation as a fallback.

#### Acceptance Criteria

1. WHEN a service calls POST `/api/v1/auth/validate-token` with a valid service Bearer token and a body containing `{ "token": "..." }`, THE Auth_Service SHALL verify the provided token and return `{ "valid": true, "sub": "...", "roles": [...], "type": "..." }`
2. IF the provided token is invalid or expired, THEN THE Auth_Service SHALL return `{ "valid": false }` with HTTP 200
3. THE validate-token endpoint SHALL require a valid service token (type `service`) in the Authorization header
4. IF the Authorization header is missing or contains a non-service token, THEN THE Identity_Manager SHALL return HTTP 401
