# Requirements Document

## Introduction

The `ugsys-identity-manager` service currently has four enterprise-pattern gaps that create reliability, correctness, and maintainability risks:

1. **EventBridge async I/O** — the publisher uses synchronous `boto3` inside `async def publish()`, blocking the event loop on every event publish and degrading Lambda concurrency.
2. **Silent event loss** — publish failures are caught and swallowed; the caller never knows the event was not delivered.
3. **Dual-write inconsistency** — critical events (`identity.user.registered`, `identity.user.deactivated`, `identity.auth.password_changed`) are published after the DynamoDB write with no atomicity guarantee. If EventBridge is unavailable, the downstream `user-profile-service` never receives the signal to create or update the profile.
4. **Structural debt** — DTOs are defined inline in router files and application service contracts have no inbound port interfaces, making the presentation layer depend on concrete services rather than abstractions.

This spec covers the implementation of the Outbox pattern, Unit of Work, async EventBridge publisher, application DTOs, and inbound port interfaces for the identity-manager service.

---

## Glossary

- **EventBridgePublisher**: The infrastructure adapter in `src/infrastructure/messaging/event_publisher.py` that publishes domain events to the AWS EventBridge custom bus `ugsys-event-bus`.
- **OutboxRepository**: The domain port (ABC) for reading and writing `OutboxEvent` records to the DynamoDB outbox table.
- **OutboxEvent**: A domain entity representing a pending domain event stored in the outbox table, with fields: `id`, `aggregate_type`, `aggregate_id`, `event_type`, `payload`, `created_at`, `published_at`, `retry_count`, `status`.
- **OutboxProcessor**: The application service that reads pending `OutboxEvent` records and delivers them to EventBridge, then marks them published.
- **UnitOfWork**: The domain port (ABC) and DynamoDB infrastructure implementation that executes multiple repository write operations as a single `TransactWriteItems` call.
- **Critical event**: A domain event whose loss causes data inconsistency across services — specifically `identity.user.registered`, `identity.user.deactivated`, and `identity.auth.password_changed`.
- **Log-and-continue event**: A domain event whose loss is acceptable for consistency (analytics/audit) — specifically `identity.auth.login_success`, `identity.auth.login_failed`, `identity.auth.account_locked`, `identity.auth.password_reset_requested`, `identity.user.activated`, `identity.auth.verification_requested`.
- **Outbox table**: DynamoDB table `ugsys-outbox-identity-{env}` storing pending outbox events.
- **TransactWriteItems**: The DynamoDB API call that executes up to 100 write operations atomically — all succeed or all fail.
- **TokenId**: An opaque identifier for a password reset token, stored in the outbox instead of the raw token value.
- **AuthService**: The application service in `src/application/services/auth_service.py` that handles registration, authentication, password reset, and related flows.
- **UserService**: The application service in `src/application/services/user_service.py` that handles profile updates and admin user management.
- **IAuthService**: The inbound port interface (ABC) for `AuthService`, defined in `src/application/interfaces/`.
- **IUserService**: The inbound port interface (ABC) for `UserService`, defined in `src/application/interfaces/`.

---

## Requirements

### Requirement 1: EventBridge Async I/O

**User Story:** As a platform engineer, I want the EventBridge publisher to use non-blocking async I/O, so that Lambda concurrency is not degraded by synchronous network calls inside async handlers.

#### Acceptance Criteria

1. THE `EventBridgePublisher` SHALL use `aioboto3` to create an async EventBridge client, replacing the synchronous `boto3.client("events")` instantiation.
2. WHEN `EventBridgePublisher.publish()` is called, THE `EventBridgePublisher` SHALL call `put_events` via the async aioboto3 client using `await`, not a synchronous call.
3. THE `EventBridgePublisher` SHALL manage the aioboto3 client lifecycle using an async context manager consistent with the pattern used for the DynamoDB client in `src/main.py`.
4. WHEN `put_events` returns a response where `FailedEntryCount > 0`, THE `EventBridgePublisher` SHALL raise an `ExternalServiceError` with the failed entry details in the internal `message` and a safe `user_message` of `"An unexpected error occurred"`.

---

### Requirement 2: EventBridge Error Propagation

**User Story:** As a platform engineer, I want publish failures to surface as exceptions rather than being silently swallowed, so that callers can decide whether to retry, use the outbox, or alert.

#### Acceptance Criteria

1. WHEN `EventBridgePublisher.publish()` raises any exception from the aioboto3 client, THE `EventBridgePublisher` SHALL log the error with `structlog` at `error` level including `detail_type` and `error` fields, then raise an `ExternalServiceError`.
2. THE `EventBridgePublisher` SHALL NOT catch exceptions and return normally — the `except` block that currently swallows errors MUST be removed.
3. WHEN `EventBridgePublisher.publish()` succeeds, THE `EventBridgePublisher` SHALL log at `info` level with `detail_type` and `event_id` fields, consistent with the current success log.

---

### Requirement 3: Outbox Domain Port

**User Story:** As a platform engineer, I want an `OutboxRepository` abstract port defined in the domain layer, so that the application layer can write and read outbox events without depending on DynamoDB directly.

#### Acceptance Criteria

1. THE `OutboxRepository` SHALL be defined as an ABC in `src/domain/repositories/outbox_repository.py` with zero imports from infrastructure, application, or presentation layers.
2. THE `OutboxRepository` SHALL declare the following abstract async methods: `save(event: OutboxEvent) -> OutboxEvent`, `find_pending(limit: int) -> list[OutboxEvent]`, `mark_published(event_id: str) -> None`, `increment_retry(event_id: str) -> None`, `mark_failed(event_id: str) -> None`.
3. THE `OutboxEvent` entity SHALL be defined as a Python dataclass in `src/domain/entities/outbox_event.py` with fields: `id: str` (ULID), `aggregate_type: str`, `aggregate_id: str`, `event_type: str`, `payload: str` (JSON string), `created_at: str` (ISO 8601), `status: str` (one of `"pending"`, `"published"`, `"failed"`), `retry_count: int` (default 0), `published_at: str | None` (default None).
4. THE `OutboxEvent` entity SHALL have ZERO imports from infrastructure, application, or presentation layers.

---

### Requirement 4: Unit of Work Domain Port

**User Story:** As a platform engineer, I want a `UnitOfWork` abstract port defined in the domain layer, so that multi-aggregate atomic writes can be expressed without coupling the application layer to DynamoDB.

#### Acceptance Criteria

1. THE `UnitOfWork` ABC SHALL be defined in `src/domain/repositories/unit_of_work.py` with a single abstract async method `execute(operations: list[TransactionalOperation]) -> None`.
2. THE `TransactionalOperation` dataclass SHALL be defined in the same file with fields `operation_type: str` (one of `"Put"`, `"Update"`, `"Delete"`) and `params: dict[str, Any]`.
3. THE `UnitOfWork` and `TransactionalOperation` SHALL have ZERO imports from infrastructure, application, or presentation layers.

---

### Requirement 5: DynamoDB Outbox Repository Implementation

**User Story:** As a platform engineer, I want a `DynamoDBOutboxRepository` that implements `OutboxRepository` using the outbox table schema, so that outbox events are persisted and retrieved correctly.

#### Acceptance Criteria

1. THE `DynamoDBOutboxRepository` SHALL be defined in `src/infrastructure/persistence/dynamodb_outbox_repository.py` and SHALL implement all methods declared in `OutboxRepository`.
2. THE `DynamoDBOutboxRepository` SHALL use the DynamoDB table `ugsys-outbox-identity-{env}` with partition key `PK = OUTBOX#{ulid}` and sort key `SK = EVENT`.
3. WHEN `save()` is called, THE `DynamoDBOutboxRepository` SHALL write the outbox event with `status = "pending"` and `retry_count = 0` using a `put_item` call with `ConditionExpression="attribute_not_exists(PK)"`.
4. WHEN `find_pending()` is called, THE `DynamoDBOutboxRepository` SHALL query the `StatusIndex` GSI with `status = "pending"`, ordered by `created_at` ascending, limited to the requested count.
5. WHEN `mark_published()` is called, THE `DynamoDBOutboxRepository` SHALL update the item setting `status = "published"` and `published_at` to the current UTC ISO 8601 timestamp.
6. WHEN `increment_retry()` is called, THE `DynamoDBOutboxRepository` SHALL atomically increment `retry_count` by 1 using a DynamoDB `UpdateItem` with an atomic counter expression.
7. WHEN `mark_failed()` is called, THE `DynamoDBOutboxRepository` SHALL update the item setting `status = "failed"`.
8. WHEN any `boto3` / `aioboto3` call raises a `ClientError`, THE `DynamoDBOutboxRepository` SHALL log the full error internally and raise a `RepositoryError` with `user_message="An unexpected error occurred"`.
9. THE `DynamoDBOutboxRepository` SHALL expose a `save_operation(event: OutboxEvent) -> TransactionalOperation` method that returns a `TransactionalOperation` for use in `UnitOfWork.execute()` without executing the write directly.

---

### Requirement 6: DynamoDB Unit of Work Implementation

**User Story:** As a platform engineer, I want a `DynamoDBUnitOfWork` that wraps `TransactWriteItems`, so that multi-aggregate writes are atomic.

#### Acceptance Criteria

1. THE `DynamoDBUnitOfWork` SHALL be defined in `src/infrastructure/persistence/dynamodb_unit_of_work.py` and SHALL implement `UnitOfWork`.
2. WHEN `execute()` is called with an empty list, THE `DynamoDBUnitOfWork` SHALL return immediately without making any DynamoDB call.
3. WHEN `execute()` is called with more than 100 operations, THE `DynamoDBUnitOfWork` SHALL raise a `RepositoryError` with `message` describing the count and `user_message="An unexpected error occurred"`.
4. WHEN `execute()` is called with a valid list of operations, THE `DynamoDBUnitOfWork` SHALL call `transact_write_items` with all operations in a single request.
5. WHEN `transact_write_items` raises a `ClientError` with code `TransactionCanceledException`, THE `DynamoDBUnitOfWork` SHALL log the cancellation reasons at `error` level and raise a `RepositoryError`.
6. WHEN `transact_write_items` raises any other `ClientError`, THE `DynamoDBUnitOfWork` SHALL log the error and raise a `RepositoryError`.

---

### Requirement 7: Atomic Dual-Write for Critical Events

**User Story:** As a platform engineer, I want critical domain events to be written to the outbox in the same DynamoDB transaction as the domain entity write, so that event loss is impossible even if EventBridge is unavailable.

#### Acceptance Criteria

1. WHEN `AuthService.register()` saves a new `User`, THE `AuthService` SHALL use `UnitOfWork.execute()` to atomically write both the `User` (via `UserRepository.save_operation()`) and an `OutboxEvent` for `identity.user.registered` (via `OutboxRepository.save_operation()`).
2. WHEN `AuthService` deactivates a user, THE `AuthService` SHALL use `UnitOfWork.execute()` to atomically write both the updated `User` and an `OutboxEvent` for `identity.user.deactivated`.
3. WHEN `AuthService.reset_password()` completes successfully, THE `AuthService` SHALL use `UnitOfWork.execute()` to atomically write both the updated `User` and an `OutboxEvent` for `identity.auth.password_changed`.
4. IF the `UnitOfWork.execute()` call raises a `RepositoryError`, THEN THE `AuthService` SHALL propagate the error to the caller — the domain write and the outbox write SHALL both be absent.
5. THE `UserRepository` SHALL expose `save_operation(user: User) -> TransactionalOperation` and `update_operation(user: User) -> TransactionalOperation` methods consistent with the repository pattern checklist.

---

### Requirement 8: Outbox Payload Security

**User Story:** As a security engineer, I want sensitive token values to never be stored in plaintext in the outbox table, so that a DynamoDB table compromise does not expose active password reset tokens.

#### Acceptance Criteria

1. WHEN an `OutboxEvent` is created for `identity.auth.password_reset_requested`, THE `AuthService` SHALL store only the `token_id` (the ULID or UUID identifier of the token) in the outbox payload — NOT the raw token string.
2. THE outbox payload for `identity.auth.password_reset_requested` SHALL contain the fields: `user_id`, `email`, `token_id`, `expires_at` — and SHALL NOT contain the field `verification_token` or any raw token value.
3. IF a raw token value is detected in an outbox payload during code review or testing, THEN THE implementation SHALL be considered non-compliant with this requirement.

---

### Requirement 9: Outbox Processor Lambda

**User Story:** As a platform engineer, I want a separate Lambda function that reads pending outbox events and delivers them to EventBridge, so that critical events are delivered reliably with at-least-once semantics.

#### Acceptance Criteria

1. THE `OutboxProcessor` application service SHALL be defined in `src/application/services/outbox_processor.py` with a `process_pending(batch_size: int = 25) -> int` method that returns the count of successfully published events.
2. WHEN `process_pending()` is called, THE `OutboxProcessor` SHALL call `OutboxRepository.find_pending(limit=batch_size)` to retrieve pending events.
3. FOR EACH pending event, WHEN `EventPublisher.publish()` succeeds, THE `OutboxProcessor` SHALL call `OutboxRepository.mark_published(event.id)`.
4. FOR EACH pending event, WHEN `EventPublisher.publish()` raises an exception, THE `OutboxProcessor` SHALL log the error at `error` level and call `OutboxRepository.increment_retry(event.id)` — the event SHALL remain in `pending` status.
5. WHEN an outbox event has `retry_count >= 5`, THE `OutboxProcessor` SHALL call `OutboxRepository.mark_failed(event.id)` instead of attempting delivery, and SHALL log at `error` level with `event_id`, `event_type`, and `retry_count` fields.
6. THE outbox processor Lambda entry point SHALL be defined in `src/main_outbox.py` as a standalone Lambda handler function, separate from the main FastAPI application.
7. THE `OutboxProcessor` SHALL log `duration_ms` for the full `process_pending()` call at `info` level on completion.

---

### Requirement 10: Application DTOs

**User Story:** As a developer, I want all request and response DTOs extracted to `src/application/dtos/`, so that the presentation layer depends on stable, reusable data contracts rather than inline Pydantic models defined in router files.

#### Acceptance Criteria

1. THE `RegisterUserRequest` DTO SHALL be defined in `src/application/dtos/auth_dtos.py` with fields: `email: EmailStr`, `password: str`, `full_name: str`, and the `sanitize_name` field validator currently in `src/presentation/api/v1/auth.py`.
2. THE `LoginRequest` DTO SHALL be defined in `src/application/dtos/auth_dtos.py` with fields: `email: EmailStr`, `password: str`.
3. THE `RefreshRequest` DTO SHALL be defined in `src/application/dtos/auth_dtos.py` with field: `refresh_token: str`.
4. THE `ForgotPasswordRequest` DTO SHALL be defined in `src/application/dtos/auth_dtos.py` with field: `email: EmailStr`.
5. THE `TokenPairResponse` DTO SHALL be defined in `src/application/dtos/auth_dtos.py` with fields: `access_token: str`, `refresh_token: str`, `token_type: str`, `expires_in: int`.
6. THE `UserResponse` DTO SHALL be defined in `src/application/dtos/user_dtos.py` with fields mirroring the `User` domain entity's public attributes, and a `from_domain(user: User) -> UserResponse` class method.
7. THE `UpdateProfileRequest` DTO SHALL be defined in `src/application/dtos/user_dtos.py` with fields: `full_name: str | None`, `bio: str | None` (or whichever fields `UpdateProfileCommand` currently accepts).
8. THE `AssignRoleRequest` DTO SHALL be defined in `src/application/dtos/user_dtos.py` with field: `role: UserRole`.
9. WHEN the DTOs are extracted, THE router files `src/presentation/api/v1/auth.py` and `src/presentation/api/v1/users.py` SHALL import the DTOs from `src/application/dtos/` and SHALL NOT define any Pydantic request/response models inline.

---

### Requirement 11: Inbound Port Interfaces

**User Story:** As a developer, I want `IAuthService` and `IUserService` ABCs defined in `src/application/interfaces/`, so that the presentation layer depends on abstractions and the services are independently testable via mocks.

#### Acceptance Criteria

1. THE `IAuthService` ABC SHALL be defined in `src/application/interfaces/auth_service.py` declaring abstract async methods for every public method currently on `AuthService`: `register`, `authenticate`, `refresh`, `forgot_password`, `reset_password`, `validate_token`, `issue_service_token`, `verify_email`, `resend_verification`, `logout`.
2. THE `IUserService` ABC SHALL be defined in `src/application/interfaces/user_service.py` declaring abstract async methods for every public method currently on `UserService`: `get_user`, `update_profile`, and any admin methods.
3. THE concrete `AuthService` class SHALL declare `class AuthService(IAuthService)` — implementing the interface.
4. THE concrete `UserService` class SHALL declare `class UserService(IUserService)` — implementing the interface.
5. THE `IAuthService` and `IUserService` ABCs SHALL import ONLY from `src/domain/` and `src/application/commands/`, `src/application/queries/`, `src/application/dtos/` — never from `src/infrastructure/` or `src/presentation/`.
6. THE router files SHALL type-annotate injected services as `IAuthService` and `IUserService` respectively, not as the concrete classes.

---

### Requirement 12: Correctness Properties

**User Story:** As a platform engineer, I want property-based tests covering the atomicity and reliability guarantees of the outbox pattern, so that regressions in transactional correctness are caught automatically.

#### Acceptance Criteria

1. FOR ALL valid `User` entities and critical event types, WHEN `UnitOfWork.execute()` raises a `RepositoryError` (simulating a DynamoDB transaction failure), THE `AuthService` SHALL propagate the error and NEITHER the `User` write NOR the `OutboxEvent` write SHALL be committed — verified by asserting both are absent from the moto-backed DynamoDB table (atomicity invariant).
2. FOR ALL `OutboxEvent` records in `pending` status, WHEN `OutboxProcessor.process_pending()` is called and `EventBridgePublisher.publish()` raises an `ExternalServiceError`, THE `OutboxEvent` status SHALL remain `"pending"` and `retry_count` SHALL be incremented by exactly 1 — verified across arbitrary sequences of failed delivery attempts (delivery failure invariant).
3. FOR ALL critical event types (`identity.user.registered`, `identity.user.deactivated`, `identity.auth.password_changed`), WHEN the corresponding `AuthService` method completes successfully, THE `OutboxRepository` SHALL contain exactly one `OutboxEvent` with matching `event_type` and `aggregate_id` — verified by reading the outbox table after the service call (outbox creation invariant).
