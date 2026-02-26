# Implementation Plan: Identity Manager Enterprise Patterns

## Overview

Implement the Outbox pattern, Unit of Work, async EventBridge publisher, application DTOs, and inbound port interfaces for `ugsys-identity-manager`. Tasks follow TDD order: domain entities and ports first, infrastructure second, application layer third, presentation last.

## Tasks

- [x] 1. Domain entities and ports
  - [x] 1.1 Write unit tests for `OutboxEvent` dataclass
    - Test field defaults (`retry_count=0`, `published_at=None`, `status="pending"`)
    - Test that `OutboxEvent` is a pure Python dataclass with no external imports
    - _Requirements: 3.3, 3.4_

  - [x] 1.2 Implement `OutboxEvent` dataclass in `src/domain/entities/outbox_event.py`
    - Fields: `id: str`, `aggregate_type: str`, `aggregate_id: str`, `event_type: str`, `payload: str`, `created_at: str`, `status: str`, `retry_count: int = 0`, `published_at: str | None = None`
    - Zero imports from infrastructure, application, or presentation layers
    - _Requirements: 3.3, 3.4_

  - [x] 1.3 Write unit tests for `OutboxRepository` ABC
    - Test that all abstract methods are declared: `save`, `find_pending`, `mark_published`, `increment_retry`, `mark_failed`, `save_operation`
    - _Requirements: 3.1, 3.2_

  - [x] 1.4 Implement `OutboxRepository` ABC in `src/domain/repositories/outbox_repository.py`
    - Abstract async methods: `save(event) -> OutboxEvent`, `find_pending(limit) -> list[OutboxEvent]`, `mark_published(event_id) -> None`, `increment_retry(event_id) -> None`, `mark_failed(event_id) -> None`
    - Synchronous method: `save_operation(event) -> TransactionalOperation`
    - Zero imports from infrastructure, application, or presentation layers
    - _Requirements: 3.1, 3.2_

  - [x] 1.5 Write unit tests for `UnitOfWork` ABC and `TransactionalOperation` dataclass
    - Test `TransactionalOperation` fields: `operation_type: str`, `params: dict[str, Any]`
    - Test that `UnitOfWork` declares abstract `execute(operations) -> None`
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 1.6 Implement `UnitOfWork` ABC and `TransactionalOperation` in `src/domain/repositories/unit_of_work.py`
    - `TransactionalOperation` dataclass with `operation_type: str` and `params: dict[str, Any]`
    - `UnitOfWork(ABC)` with single abstract async method `execute(operations: list[TransactionalOperation]) -> None`
    - Zero imports from infrastructure, application, or presentation layers
    - _Requirements: 4.1, 4.2, 4.3_

- [x] 2. DynamoDB outbox repository
  - [x] 2.1 Write unit tests for `DynamoDBOutboxRepository`
    - Mock aioboto3 client; test `_to_item` / `_from_item` round-trip for all fields
    - Test `save()` calls `put_item` with `ConditionExpression="attribute_not_exists(PK)"` and `status="pending"`, `retry_count=0`
    - Test `save_operation()` returns a `TransactionalOperation` without calling `put_item`
    - Test `mark_published()` sets `status="published"` and `published_at` to a UTC ISO 8601 timestamp
    - Test `increment_retry()` uses atomic counter expression
    - Test `mark_failed()` sets `status="failed"`
    - Test any `ClientError` raises `RepositoryError` (not raw `ClientError`)
    - _Requirements: 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 5.9_

  - [x] 2.2 Implement `DynamoDBOutboxRepository` in `src/infrastructure/persistence/dynamodb_outbox_repository.py`
    - Constructor: `(table_name: str, client: Any)`
    - Table key: `PK = OUTBOX#{ulid}`, `SK = EVENT`
    - `save()`: `put_item` with `ConditionExpression="attribute_not_exists(PK)"`, forces `status="pending"` and `retry_count=0`
    - `find_pending()`: query `StatusIndex` GSI with `status="pending"`, ordered by `created_at` ascending
    - `mark_published()`: `update_item` setting `status="published"` and `published_at` to current UTC ISO 8601
    - `increment_retry()`: `update_item` with atomic `ADD retry_count :one` expression
    - `mark_failed()`: `update_item` setting `status="failed"`
    - `save_operation()`: returns `TransactionalOperation` with low-level AttributeValue dict format — does NOT call `put_item`
    - `_to_item()` / `_from_item()` private serialization helpers; `_from_item` uses `.get()` with safe defaults
    - `_raise_repository_error()` logs full `ClientError` internally, raises `RepositoryError` with safe `user_message`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9_

  - [x] 2.3 Write integration tests for `DynamoDBOutboxRepository` with moto
    - Use `mock_aws` to create outbox table with `StatusIndex` GSI
    - Test `save()` + `find_pending()` round-trip
    - Test `increment_retry()` atomic counter across multiple calls
    - Test `mark_published()` and `mark_failed()` state transitions
    - Test backward compatibility: items missing optional fields deserialize with safe defaults
    - Test `ClientError` wrapping: verify `RepositoryError` raised, not raw `ClientError`
    - _Requirements: 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

- [x] 3. DynamoDB Unit of Work
  - [x] 3.1 Write unit tests for `DynamoDBUnitOfWork`
    - Mock aioboto3 client; test empty list returns immediately without calling `transact_write_items`
    - Test list of 101 operations raises `RepositoryError` without calling `transact_write_items`
    - Test valid list (1–100 ops) calls `transact_write_items` exactly once with all operations
    - Test `TransactionCanceledException` logs cancellation reasons and raises `RepositoryError`
    - Test any other `ClientError` raises `RepositoryError`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 3.2 Implement `DynamoDBUnitOfWork` in `src/infrastructure/persistence/dynamodb_unit_of_work.py`
    - Constructor: `(client: Any)`
    - `execute()`: guard empty list (return immediately), guard > 100 (raise `RepositoryError`), call `transact_write_items` with all operations
    - Handle `TransactionCanceledException`: log cancellation reasons at `error` level, raise `RepositoryError`
    - Handle all other `ClientError`: log error, raise `RepositoryError`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 3.3 Write property test for `DynamoDBUnitOfWork` — oversized batch rejection
    - **Property 7: UnitOfWork rejects oversized batches**
    - **Validates: Requirements 6.3**
    - _Requirements: 6.3_

  - [ ]* 3.4 Write property test for `DynamoDBUnitOfWork` — all operations forwarded
    - **Property 8: UnitOfWork passes all operations to transact_write_items**
    - **Validates: Requirements 6.4**
    - _Requirements: 6.4_

- [x] 4. UserRepository transactional operation methods
  - [x] 4.1 Write unit tests for `save_operation()` and `update_operation()` on `DynamoDBUserRepository`
    - Test `save_operation()` returns `TransactionalOperation` with `operation_type="Put"` and `ConditionExpression="attribute_not_exists(pk)"`
    - Test `update_operation()` returns `TransactionalOperation` with `operation_type="Put"` and `ConditionExpression="attribute_exists(pk)"`
    - Test that neither method calls `put_item` directly
    - Test `_to_item_low_level()` produces AttributeValue dict format (`{"S": "..."}`, `{"BOOL": ...}`, `{"N": "..."}`)
    - _Requirements: 7.5_

  - [x] 4.2 Add `save_operation()`, `update_operation()`, and `_to_item_low_level()` to `DynamoDBUserRepository`
    - `_to_item_low_level(user: User) -> dict[str, Any]`: produces low-level AttributeValue dict format required by `transact_write_items`
    - `save_operation(user: User) -> TransactionalOperation`: returns `TransactionalOperation` using `_to_item_low_level()` with `ConditionExpression="attribute_not_exists(pk)"`
    - `update_operation(user: User) -> TransactionalOperation`: returns `TransactionalOperation` using `_to_item_low_level()` with `ConditionExpression="attribute_exists(pk)"`
    - Existing `save()` and `update()` methods remain unchanged
    - _Requirements: 7.5_

- [x] 5. EventBridgePublisher async migration
  - [x] 5.1 Write unit tests for the updated `EventBridgePublisher`
    - Mock `aioboto3.Session`; verify `publish()` uses async context manager to open/close the client
    - Test `FailedEntryCount > 0` raises `ExternalServiceError` with failed entry details in `message`
    - Test any exception from aioboto3 client raises `ExternalServiceError` (not swallowed)
    - Test success path logs at `info` level with `detail_type` and `event_id`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3_

  - [x] 5.2 Update `EventBridgePublisher` in `src/infrastructure/messaging/event_publisher.py`
    - Replace `self._client = boto3.client("events", ...)` with `self._session: aioboto3.Session` in constructor
    - Add `session: aioboto3.Session` parameter to `__init__`
    - `publish()`: use `async with self._session.client("events", region_name=self._region) as client:` and `await client.put_events(...)`
    - Check `response["FailedEntryCount"] > 0` → raise `ExternalServiceError` with failed entry details in `message`, `user_message="An unexpected error occurred"`
    - Replace silent `except Exception` with log at `error` level (`detail_type`, `error` fields) + raise `ExternalServiceError`
    - Keep success log at `info` level with `detail_type` and `event_id`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3_

  - [ ]* 5.3 Write property test for `EventBridgePublisher` — FailedEntryCount triggers error
    - **Property 1: FailedEntryCount triggers ExternalServiceError**
    - **Validates: Requirements 1.4**
    - _Requirements: 1.4_

  - [ ]* 5.4 Write property test for `EventBridgePublisher` — client exceptions always propagate
    - **Property 2: EventBridge client exceptions always propagate**
    - **Validates: Requirements 2.1, 2.2**
    - _Requirements: 2.1, 2.2_

- [x] 6. AuthService atomic dual-write
  - [x] 6.1 Write unit tests for `AuthService` atomic dual-write paths
    - Mock `UnitOfWork`, `OutboxRepository`, `UserRepository`; test `register()` calls `UnitOfWork.execute()` with exactly two operations (user save + outbox save)
    - Test `register()` backward-compat fallback: when `outbox_repo=None` or `unit_of_work=None`, falls back to direct `save()` + log-and-continue publish
    - Test `reset_password()` calls `UnitOfWork.execute()` with exactly two operations (user update + outbox save)
    - Test `UnitOfWork.execute()` raising `RepositoryError` propagates to caller (no partial state)
    - Test `forgot_password()` outbox payload contains `token_id` and does NOT contain `reset_token` or `verification_token`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.1, 8.2_

  - [x] 6.2 Update `AuthService` in `src/application/services/auth_service.py`
    - Add optional constructor parameters: `outbox_repo: OutboxRepository | None = None`, `unit_of_work: UnitOfWork | None = None`
    - `register()`: when outbox wired, create `OutboxEvent` for `identity.user.registered` and call `UnitOfWork.execute([user_repo.save_operation(user), outbox_repo.save_operation(outbox_event)])`; else fall back to direct `save()` + log-and-continue publish
    - Deactivation path: use `UnitOfWork.execute([user_repo.update_operation(user), outbox_repo.save_operation(outbox_event)])` for `identity.user.deactivated`
    - `reset_password()`: use `UnitOfWork.execute([user_repo.update_operation(user), outbox_repo.save_operation(outbox_event)])` for `identity.auth.password_changed`
    - `forgot_password()`: store only `token_id` (jti/ULID from token claims) in event payload — NOT the raw token string
    - Propagate `RepositoryError` from `UnitOfWork.execute()` to caller
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.1, 8.2_

  - [ ]* 6.3 Write property test for `AuthService` — critical operations use atomic dual-write
    - **Property 9: Critical operations use atomic dual-write**
    - **Validates: Requirements 7.1, 7.2, 7.3**
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 6.4 Write property test for `AuthService` — transaction failure leaves no partial writes
    - **Property 10: Transaction failure leaves no partial writes**
    - **Validates: Requirements 7.4, 12.1**
    - _Requirements: 7.4, 12.1_

  - [ ]* 6.5 Write property test for `AuthService` — password reset payload never contains raw token
    - **Property 11: Password reset outbox payload never contains raw token**
    - **Validates: Requirements 8.1, 8.2**
    - _Requirements: 8.1, 8.2_

- [x] 7. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. OutboxProcessor application service
  - [x] 8.1 Write unit tests for `OutboxProcessor`
    - Mock `OutboxRepository` and `EventPublisher`; test `process_pending()` calls `find_pending(limit=batch_size)`
    - Test successful publish calls `mark_published(event.id)` and increments return count
    - Test failed publish calls `increment_retry(event.id)` and does NOT call `mark_published`
    - Test event with `retry_count >= 5` calls `mark_failed(event.id)` and does NOT call `publish()`
    - Test return value equals count of successfully published events only
    - Test `duration_ms` is logged at `info` level on completion
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.7_

  - [x] 8.2 Implement `OutboxProcessor` in `src/application/services/outbox_processor.py`
    - Constructor: `(outbox_repo: OutboxRepository, publisher: EventPublisher)`
    - `process_pending(batch_size: int = 25) -> int`: fetch pending events, iterate, skip and `mark_failed` if `retry_count >= 5`, else attempt publish; on success call `mark_published`, on failure log `error` and call `increment_retry`
    - Log `duration_ms` at `info` level on completion
    - Return count of successfully published events
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.7_

  - [ ]* 8.3 Write property test for `OutboxProcessor` — return value equals successful publishes
    - **Property 12: OutboxProcessor return value equals successful publishes**
    - **Validates: Requirements 9.1**
    - _Requirements: 9.1_

  - [ ]* 8.4 Write property test for `OutboxProcessor` — successful publish triggers mark_published
    - **Property 13: Successful publish triggers mark_published**
    - **Validates: Requirements 9.3**
    - _Requirements: 9.3_

  - [ ]* 8.5 Write property test for `OutboxProcessor` — delivery failure increments retry_count by exactly 1
    - **Property 14: Delivery failure increments retry_count by exactly 1**
    - **Validates: Requirements 9.4, 12.2**
    - _Requirements: 9.4, 12.2_

  - [ ]* 8.6 Write property test for `OutboxProcessor` — max-retry events are marked failed, not retried
    - **Property 15: Events at max retries are marked failed, not retried**
    - **Validates: Requirements 9.5**
    - _Requirements: 9.5_

- [x] 9. Outbox Lambda entry point
  - [x] 9.1 Write smoke test for `main_outbox.py` handler wiring
    - Mock all infrastructure dependencies; verify `handler()` calls `OutboxProcessor.process_pending()` and returns without error
    - _Requirements: 9.6_

  - [x] 9.2 Implement `src/main_outbox.py` standalone Lambda handler
    - Standalone `handler(event, context)` function — no FastAPI, no Mangum
    - Wire own `aioboto3.Session`, DynamoDB client, `DynamoDBOutboxRepository`, `EventBridgePublisher`, `OutboxProcessor`
    - Use `asyncio.run()` to drive `OutboxProcessor.process_pending()`
    - Log handler start and completion with `published_count`
    - _Requirements: 9.6_

- [x] 10. Application DTOs extraction
  - [x] 10.1 Write unit tests verifying DTOs are importable from `src/application/dtos/`
    - Test `from src.application.dtos.auth_dtos import RegisterUserRequest, LoginRequest, RefreshRequest, ForgotPasswordRequest, TokenPairResponse` succeeds
    - Test `from src.application.dtos.user_dtos import UserResponse, UpdateProfileRequest, AssignRoleRequest, PaginatedUsersResponse` succeeds
    - Test `RegisterUserRequest` has `sanitize_name` field validator
    - Test `UserResponse.from_domain(user)` classmethod returns correct field values
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_

  - [x] 10.2 Create `src/application/dtos/auth_dtos.py`
    - Extract from `src/presentation/api/v1/auth.py`: `RegisterUserRequest` (with `sanitize_name` validator), `LoginRequest`, `RefreshRequest`, `ForgotPasswordRequest`, `ResetPasswordRequest`, `VerifyEmailRequest`, `ResendVerificationRequest`, `ServiceTokenRequest`, `TokenResponse`, `ServiceTokenResponse`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 10.3 Create `src/application/dtos/user_dtos.py`
    - Extract from `src/presentation/api/v1/users.py`: `UpdateProfileRequest`, `AssignRoleRequest`, `UserResponse` (with `from_domain()` classmethod), `PaginatedUsersResponse`
    - _Requirements: 10.6, 10.7, 10.8_

  - [x] 10.4 Update router files to import DTOs from `src/application/dtos/`
    - `src/presentation/api/v1/auth.py`: remove all inline Pydantic model definitions, import from `src/application/dtos/auth_dtos.py`
    - `src/presentation/api/v1/users.py`: remove all inline Pydantic model definitions, import from `src/application/dtos/user_dtos.py`
    - _Requirements: 10.9_

- [x] 11. Inbound port interfaces
  - [x] 11.1 Write unit tests for `IAuthService` and `IUserService` interface compliance
    - Test `AuthService` is a subclass of `IAuthService`
    - Test `UserService` is a subclass of `IUserService`
    - Test all abstract methods declared in `IAuthService` are implemented on `AuthService`
    - Test all abstract methods declared in `IUserService` are implemented on `UserService`
    - _Requirements: 11.3, 11.4_

  - [x] 11.2 Implement `IAuthService` ABC in `src/application/interfaces/auth_service.py`
    - Abstract async methods: `register`, `authenticate`, `refresh`, `forgot_password`, `reset_password`, `validate_token`, `issue_service_token`, `verify_email`, `resend_verification`, `logout`
    - Import only from `src/domain/` and `src/application/commands/`, `src/application/queries/`, `src/application/dtos/`
    - _Requirements: 11.1, 11.5_

  - [x] 11.3 Implement `IUserService` ABC in `src/application/interfaces/user_service.py`
    - Abstract async methods for every public method on `UserService`: `get_user`, `update_profile`, and any admin methods
    - Import only from `src/domain/` and `src/application/commands/`, `src/application/queries/`, `src/application/dtos/`
    - _Requirements: 11.2, 11.5_

  - [x] 11.4 Update `AuthService` and `UserService` to implement interfaces
    - `class AuthService(IAuthService)` in `src/application/services/auth_service.py`
    - `class UserService(IUserService)` in `src/application/services/user_service.py`
    - _Requirements: 11.3, 11.4_

  - [x] 11.5 Update router type annotations to use interfaces
    - `src/presentation/api/v1/auth.py`: annotate injected service as `IAuthService`
    - `src/presentation/api/v1/users.py`: annotate injected service as `IUserService`
    - _Requirements: 11.6_

- [x] 12. Config and wiring
  - [x] 12.1 Write smoke test for dependency wiring
    - Mock all AWS clients; verify `create_app()` completes without error and `app.state` has `auth_service`, `user_service`, `outbox_processor` set
    - _Requirements: 7.1, 9.6_

  - [x] 12.2 Add `outbox_table_name` and `outbox_table` property to `src/config.py`
    - `outbox_table_name: str = ""` — override field
    - `@property outbox_table(self) -> str`: returns `outbox_table_name` if set, else `f"ugsys-outbox-identity-{self.environment}"`
    - _Requirements: 5.2_

  - [x] 12.3 Update `_wire_dependencies()` in `src/main.py`
    - Create a single `aioboto3.Session()` shared across all adapters
    - Instantiate `DynamoDBOutboxRepository(table_name=settings.outbox_table, client=dynamodb_client)`
    - Instantiate `DynamoDBUnitOfWork(client=dynamodb_client)`
    - Update `EventBridgePublisher(bus_name=..., region=..., session=session)` — pass `aioboto3.Session`
    - Pass `outbox_repo` and `unit_of_work` to `AuthService` constructor
    - Instantiate `OutboxProcessor` and attach to `app.state`
    - _Requirements: 1.3, 7.1_

- [ ] 13. Property-based tests (remaining properties)
  - [ ]* 13.1 Write property tests for `DynamoDBOutboxRepository` — Properties 3, 4, 5, 6
    - File: `tests/property/test_outbox_repository_properties.py`
    - **Property 3: Outbox save always writes pending status** — Validates: Requirements 5.3
    - **Property 4: find_pending returns only pending events** — Validates: Requirements 5.4
    - **Property 5: increment_retry always adds exactly 1** — Validates: Requirements 5.6
    - **Property 6: ClientError always becomes RepositoryError** — Validates: Requirements 5.8
    - Use `@settings(max_examples=100)` and `st.builds(OutboxEvent, ...)` generators
    - _Requirements: 5.3, 5.4, 5.6, 5.8_

  - [ ]* 13.2 Write property tests for `AuthService` — outbox creation invariant (Property 16)
    - File: `tests/property/test_auth_service_properties.py`
    - **Property 16: Outbox creation invariant for critical events**
    - **Validates: Requirements 12.3**
    - _Requirements: 12.3_

- [x] 14. Final checkpoint — Ensure all tests pass
  - Run `uv run pytest tests/unit/ tests/integration/ -v --tb=short` — all must pass
  - Run `uv run ruff check src/ tests/` and `uv run ruff format --check src/ tests/`
  - Run `uv run mypy src/ --strict` — no type errors
  - Run arch-guard: `grep -rn "from src.infrastructure\|from src.presentation\|from src.application" src/domain/` must return no matches; `grep -rn "from src.infrastructure\|from src.presentation" src/application/` must return no matches
  - Verify `uv run pytest tests/unit/ --cov=src --cov-report=term-missing` shows ≥ 80% coverage
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- TDD order is enforced: write the test first (RED), then implement (GREEN), then refactor
- Property tests use `hypothesis` with `@settings(max_examples=100)` minimum
- The `save_operation()` / `update_operation()` methods on repositories return `TransactionalOperation` without executing I/O — they are synchronous builders
- The backward-compat fallback in `AuthService` (when outbox not wired) ensures existing unit tests continue to pass without modification
- `main_outbox.py` is a completely separate Lambda entry point — it does not share the FastAPI lifespan
