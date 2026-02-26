# Identity Manager Hardening — Bugfix Design

## Overview

The `ugsys-identity-manager` service has six enterprise pattern compliance gaps that must be
resolved before production deployment. Each gap is a security or reliability defect relative to
the platform contract. The fix strategy is surgical: change only the code paths that are
non-compliant, leaving all auth flows, domain logic, and passing tests untouched.

The six gaps and their target files are:

| Gap | Area | Files |
|-----|------|-------|
| 1 | Security headers | `src/presentation/middleware/security_headers.py` |
| 2 | DynamoDB ClientError wrapping | `src/infrastructure/persistence/dynamodb_user_repository.py`, `dynamodb_token_blacklist.py` |
| 3 | Rate limiting (per-user, 3 windows, headers) | `src/presentation/middleware/rate_limiting.py` |
| 4 | JWT RS256 enforcement + claims validation | `src/config.py`, `src/infrastructure/adapters/jwt_token_service.py` |
| 5 | Application factory pattern | `src/main.py` |
| 6 | Async I/O (aioboto3 migration) | both repository files + `src/main.py` |

---

## Glossary

- **Bug_Condition (C)**: Any of the 19 defect clauses (1.1–1.19) — the condition under which the
  service behaves incorrectly relative to the platform contract.
- **Property (P)**: The desired correct behavior for each bug condition (clauses 2.1–2.22).
- **Preservation**: All auth flows, domain logic, and existing correct behaviors (clauses 3.1–3.10)
  that must remain unchanged after the fix.
- **isBugCondition(input)**: Pseudocode predicate that returns `true` when an input triggers one
  of the 19 defect clauses.
- **SecurityHeadersMiddleware**: The middleware in `src/presentation/middleware/security_headers.py`
  that injects security response headers.
- **RateLimitMiddleware**: The middleware in `src/presentation/middleware/rate_limiting.py` that
  enforces per-user/IP request rate limits.
- **DynamoDBUserRepository**: The adapter in `src/infrastructure/persistence/dynamodb_user_repository.py`
  implementing the `UserRepository` port.
- **DynamoDBTokenBlacklistRepository**: The adapter in `src/infrastructure/persistence/dynamodb_token_blacklist.py`
  implementing the `TokenBlacklistRepository` port.
- **JWTTokenService**: The adapter in `src/infrastructure/adapters/jwt_token_service.py`
  implementing the `TokenService` port.
- **create_app()**: The factory function in `src/main.py` that must be the single composition root.
- **ClientError**: The `botocore.exceptions.ClientError` raised by boto3/aioboto3 on AWS API failures.
- **RepositoryError**: Domain exception (`src/domain/exceptions.py`) for infrastructure failures.
- **NotFoundError**: Domain exception for missing resources.
- **AuthenticationError**: Domain exception for invalid/rejected tokens.

---

## Bug Details

### Fault Condition

The bugs manifest across six independent areas. Each area has its own `isBugCondition` predicate.


**Gap 1 — Security Headers Formal Specification:**
```
FUNCTION isBugCondition_SecurityHeaders(response)
  INPUT: response of type HTTP Response
  OUTPUT: boolean

  RETURN response.headers["X-XSS-Protection"] != "0"
      OR response.headers["Strict-Transport-Security"] does not contain "preload"
      OR response.headers["Content-Security-Policy"] != "default-src 'none'; frame-ancestors 'none'"
      OR "Permissions-Policy" NOT IN response.headers
      OR "Cross-Origin-Opener-Policy" NOT IN response.headers
      OR "Cross-Origin-Resource-Policy" NOT IN response.headers
      OR ("server" IN response.headers AND response.headers["server"] != "")
      OR (request.path STARTS_WITH "/api/" AND "Cache-Control" NOT IN response.headers)
END FUNCTION
```

**Gap 2 — DynamoDB ClientError Wrapping Formal Specification:**
```
FUNCTION isBugCondition_ClientError(exception, caller_layer)
  INPUT: exception raised during DynamoDB operation, caller_layer = "application"
  OUTPUT: boolean

  RETURN exception IS ClientError
      AND caller_layer == "application"
      -- i.e., ClientError was not caught and re-raised as RepositoryError/NotFoundError
END FUNCTION
```

**Gap 3 — Rate Limiting Formal Specification:**
```
FUNCTION isBugCondition_RateLimit(request, response)
  INPUT: request of type HTTP Request, response of type HTTP Response
  OUTPUT: boolean

  has_jwt = request has valid Bearer token with "sub" claim
  keyed_by_sub = rate limit counter key includes JWT sub

  RETURN (has_jwt AND NOT keyed_by_sub)
      OR (response.status != 429 AND "X-RateLimit-Limit" NOT IN response.headers)
      OR (burst_count(request.key, last_1s) >= 10 AND response.status != 429)
      OR (minute_count(request.key, last_60s) >= 60 AND response.status != 429)
      OR (hour_count(request.key, last_3600s) >= 1000 AND response.status != 429)
      OR (response.status == 429 AND "Retry-After" NOT IN response.headers)
END FUNCTION
```

**Gap 4 — JWT Algorithm Formal Specification:**
```
FUNCTION isBugCondition_JWT(token, config)
  INPUT: token of type JWT string, config of type Settings
  OUTPUT: boolean

  RETURN config.jwt_algorithm == "HS256"
      OR config.jwt_algorithm == "none"
      OR (token.header.alg IN ["HS256", "none"] AND NOT AuthenticationError raised)
      OR (token.claims missing any of ["sub", "exp", "iat", "iss"] AND NOT AuthenticationError raised)
      OR (token.claims["aud"] != config.jwt_audience AND NOT AuthenticationError raised)
END FUNCTION
```

**Gap 5 — Application Factory Formal Specification:**
```
FUNCTION isBugCondition_Factory(module)
  INPUT: module = src.main
  OUTPUT: boolean

  RETURN FastAPI instance constructed at module level (not inside create_app())
      OR middleware/handlers/routers registered outside create_app()
END FUNCTION
```

**Gap 6 — Async I/O Formal Specification:**
```
FUNCTION isBugCondition_AsyncIO(repository_method)
  INPUT: repository_method = any async method in DynamoDBUserRepository or DynamoDBTokenBlacklistRepository
  OUTPUT: boolean

  RETURN repository_method calls boto3.resource() or boto3.client() synchronously
      -- i.e., uses synchronous I/O inside an async def, blocking the event loop
END FUNCTION
```

### Examples

**Gap 1:**
- Any response currently returns `X-XSS-Protection: 1; mode=block` → should be `0`
- Any response currently returns HSTS without `preload` → must include `preload`
- `GET /api/v1/users` response missing `Cache-Control` → must include `no-store, no-cache, must-revalidate`
- `GET /health` response includes `Server: uvicorn` → `Server` header must be removed

**Gap 2:**
- `DynamoDBUserRepository.find_by_id()` with DynamoDB unavailable → raw `ClientError` propagates to unhandled exception handler → should be `RepositoryError`
- `DynamoDBUserRepository.save()` with duplicate PK → `ConditionalCheckFailedException` propagates → should be `RepositoryError`
- `DynamoDBUserRepository.update()` with missing PK → `ConditionalCheckFailedException` propagates → should be `NotFoundError(user_message="User not found")`

**Gap 3:**
- User with JWT `sub=user-123` makes 61 requests/min from IP `1.2.3.4`, then switches to IP `5.6.7.8` and makes more requests → current code resets counter (IP-keyed) → should be blocked (sub-keyed)
- Any successful response missing `X-RateLimit-Remaining` header → must always be present
- 11 requests in 1 second → current code does not block → should return 429

**Gap 4:**
- `settings.jwt_algorithm` defaults to `"HS256"` → service starts with insecure algorithm
- Token signed with HS256 presented to `verify_token()` → current code accepts it if signature matches → must reject with `AuthenticationError`
- Token missing `iss` claim → current code accepts it → must reject with `AuthenticationError`

**Gap 5:**
- `from src.main import app` triggers full middleware/router registration at import time → makes testing harder and violates factory pattern
- Two test cases that import `app` share the same instance → calling `create_app()` twice must produce independent instances

**Gap 6:**
- `await user_repo.save(user)` calls `self._table.put_item(...)` synchronously → blocks the event loop thread → under concurrent Lambda invocations, throughput degrades

---

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Valid login (POST `/api/v1/auth/login`) with correct credentials continues to return access + refresh tokens (3.1)
- Valid access token presented to protected endpoints continues to authenticate (3.2)
- Revoked token (after logout) continues to be rejected (3.3)
- User registration with unique email continues to return 201 (3.4)
- User registration with duplicate email continues to return 409 (3.5)
- `GET /health` continues to return 200 without authentication (3.6)
- Requests exceeding 60 req/min continue to return 429 (3.7)
- Successful DynamoDB operations continue to return the correct domain entity (3.8)
- Lambda Mangum handler continues to work (3.9)
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` retain their current correct values (3.10)

**Scope:**
All inputs that do NOT trigger one of the 19 bug conditions must be completely unaffected.
This includes all auth flows, user CRUD operations, role management, health checks, and any
request that does not exercise the six defective code paths.

---

## Hypothesized Root Cause

**Gap 1 — Security Headers:**
The `_SECURITY_HEADERS` dict was written before the platform contract Section 9.2 was finalized.
The four missing headers were added to the contract after the initial implementation. The `Server`
header removal and `Cache-Control` conditional were never implemented.

**Gap 2 — DynamoDB ClientError Wrapping:**
The repository was implemented using the high-level `boto3.resource()` API without following the
repository pattern checklist. No `try/except ClientError` blocks were added, and the
`_raise_repository_error()` helper method was never implemented.

**Gap 3 — Rate Limiting:**
The middleware was written as a minimal IP-based implementation. JWT sub extraction, multi-window
enforcement, and response headers were deferred and never completed. The module-level `_request_log`
global was a quick prototype that was never refactored to instance state.

**Gap 4 — JWT Algorithm:**
The `jwt_algorithm` config default was set to `"HS256"` for local development convenience and
never updated to `"RS256"` for production. The `verify_token()` method relies on `python-jose`'s
`jwt.decode()` which accepts the algorithm from the config, but there is no pre-verification
algorithm check and no required claims validation beyond what `python-jose` does by default.

**Gap 5 — Application Factory:**
The `FastAPI` instance and all middleware/router registrations were placed at module level, which
is a common FastAPI pattern but violates the platform contract's `create_app()` factory requirement.
The `_wire_dependencies()` function in lifespan was a partial step toward the factory pattern that
was never completed.

**Gap 6 — Async I/O:**
The repositories were initially written with synchronous `boto3.resource()` calls inside `async def`
methods. This works functionally (Python does not prevent it) but blocks the event loop on every
DynamoDB call. The `aioboto3` dependency was not added when the repositories were first implemented.

---

## Correctness Properties

Property 1: Fault Condition — Security Headers Completeness

_For any_ HTTP response returned by the fixed `SecurityHeadersMiddleware`, all 9 required headers
SHALL be present with their exact platform-contract values; the `Server` header SHALL be absent;
and for any request path starting with `/api/`, `Cache-Control: no-store, no-cache, must-revalidate`
SHALL be present.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**

Property 2: Fault Condition — ClientError Isolation

_For any_ DynamoDB operation in `DynamoDBUserRepository` or `DynamoDBTokenBlacklistRepository`
that raises a `ClientError`, the fixed repositories SHALL catch the exception and raise either a
`RepositoryError` or `NotFoundError` — never a raw `ClientError` — to the application layer.

**Validates: Requirements 2.7, 2.8, 2.9, 2.10**

Property 3: Fault Condition — Rate Limit Key Isolation

_For any_ two requests carrying different JWT `sub` values, the fixed `RateLimitMiddleware` SHALL
maintain independent rate limit counters for each `sub`, regardless of whether the requests
originate from the same IP address.

**Validates: Requirements 2.11, 2.12, 2.13, 2.16**

Property 4: Fault Condition — Rate Limit Headers Always Present

_For any_ non-429 response, the fixed `RateLimitMiddleware` SHALL include `X-RateLimit-Limit`,
`X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers. For any 429 response, it SHALL also
include `Retry-After`.

**Validates: Requirements 2.14, 2.15**

Property 5: Fault Condition — RS256 Algorithm Enforcement

_For any_ JWT where `header.alg` is `"HS256"` or `"none"`, the fixed `JWTTokenService.verify_token()`
SHALL raise `AuthenticationError` before attempting signature verification.

**Validates: Requirements 2.17, 2.18**

Property 6: Fault Condition — Required Claims Validation

_For any_ JWT missing any of the required claims (`sub`, `exp`, `iat`, `iss`) or where `aud` does
not match the configured service client ID, the fixed `JWTTokenService.verify_token()` SHALL raise
`AuthenticationError`.

**Validates: Requirements 2.19**

Property 7: Fault Condition — create_app() Idempotency

_For any_ two calls to `create_app()`, the fixed `src/main.py` SHALL produce two independent
`FastAPI` instances with identical middleware stacks, and no middleware or router registration
SHALL occur at module import time.

**Validates: Requirements 2.20, 2.21**

Property 8: Preservation — Existing Correct Headers Unchanged

_For any_ HTTP response where the bug condition does NOT hold (i.e., the response already had
correct header values), the fixed `SecurityHeadersMiddleware` SHALL continue to return
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and
`Referrer-Policy: strict-origin-when-cross-origin` with their current correct values.

**Validates: Requirements 3.10**

Property 9: Preservation — Auth Flow Regression

_For any_ valid auth flow input (register → verify_email → authenticate → refresh → logout),
the fixed service SHALL produce the same sequence of responses as the original service, with
valid tokens at each step and rejection after logout.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

Property 10: Preservation — Successful DynamoDB Operations Return Domain Entity

_For any_ DynamoDB operation that succeeds (no `ClientError`), the fixed repositories SHALL
return the same domain entity as the original repositories, preserving all serialization behavior.

**Validates: Requirements 3.8**

---

## Fix Implementation

### Gap 1 — Security Headers

**File**: `src/presentation/middleware/security_headers.py`

**Specific Changes:**
1. Replace `_SECURITY_HEADERS` dict with the complete 9-header set per platform contract Section 9.2:
   - `X-XSS-Protection: 0`
   - `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`
   - `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`
   - Add `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`
   - Add `Cross-Origin-Opener-Policy: same-origin`
   - Add `Cross-Origin-Resource-Policy: same-origin`
2. In `dispatch()`, after setting headers: `response.headers.pop("server", None)`
3. In `dispatch()`, add conditional: if `request.url.path.startswith("/api/")`, set `Cache-Control: no-store, no-cache, must-revalidate`

### Gap 2 — DynamoDB ClientError Wrapping

**Files**: `src/infrastructure/persistence/dynamodb_user_repository.py`,
`src/infrastructure/persistence/dynamodb_token_blacklist.py`

**Specific Changes:**
1. Add `from botocore.exceptions import ClientError` import to both files
2. Add `_raise_repository_error(self, operation: str, e: ClientError) -> None` instance method to both repositories — logs full error internally, raises `RepositoryError` with safe `user_message`
3. Wrap every `self._table.*` call in `try/except ClientError`
4. In `DynamoDBUserRepository.save()`: catch `ConditionalCheckFailedException` → raise `RepositoryError`
5. In `DynamoDBUserRepository.update()`: catch `ConditionalCheckFailedException` → raise `NotFoundError(user_message="User not found")`

Note: ClientError wrapping (Gap 2) is applied to the existing `boto3.resource()` API first.
The migration to `aioboto3` (Gap 6) is a separate, subsequent change that replaces the sync client.

### Gap 3 — Rate Limiting

**File**: `src/presentation/middleware/rate_limiting.py`

**Specific Changes:**
1. Remove module-level `_request_log` global; replace with `self._counters: dict[str, list[float]] = defaultdict(list)` in `__init__`
2. Add `_extract_key(self, request: Request) -> str` method:
   - Decode Bearer JWT without signature verification, extract `sub` → return `f"user:{sub}"`
   - Fallback to `X-Forwarded-For` or `client.host` → return `f"ip:{ip}"`
3. Add three window constants: `_WINDOW_MINUTE=60.0`, `_WINDOW_HOUR=3600.0`, `_BURST_WINDOW=1.0`
4. Add three limit constants: `_MAX_PER_MINUTE=60`, `_MAX_PER_HOUR=1000`, `_MAX_BURST=10`
5. In `dispatch()`: prune `self._counters[key]` to 1-hour window; compute burst/minute/hour hit counts; return 429 with `Retry-After` if any limit exceeded
6. On non-429 responses: set `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers

### Gap 4 — JWT RS256 Enforcement

**File**: `src/config.py`

**Specific Changes:**
1. Change `jwt_algorithm: str = "HS256"` → `jwt_algorithm: str = "RS256"`
2. Add `jwt_audience: str = ""` — loaded from env `JWT_AUDIENCE`
3. Add `jwt_issuer: str = ""` — loaded from env `JWT_ISSUER`
4. Add `jwt_public_key: str = ""` — loaded from env `JWT_PUBLIC_KEY` (PEM format)
5. Add `jwt_private_key: str = ""` — loaded from env `JWT_PRIVATE_KEY` (PEM format)
6. Add a `@field_validator("jwt_algorithm")` that raises `ValueError` if value is not `"RS256"`

**File**: `src/infrastructure/adapters/jwt_token_service.py`

**Specific Changes:**
1. In `verify_token()`: check `header = jwt.get_unverified_header(token)` BEFORE calling `jwt.decode()`; if `header.get("alg")` is not `"RS256"`, raise `AuthenticationError` immediately
2. Pass `algorithms=["RS256"]` explicitly to `jwt.decode()` — never derive from config at decode time
3. After decode, validate required claims: if any of `sub`, `exp`, `iat`, `iss` is missing from payload, raise `AuthenticationError`
4. If `settings.jwt_audience` is set, validate `payload.get("aud") == settings.jwt_audience`; mismatch → `AuthenticationError`
5. Update `_encode()` to include `iss` and `aud` claims when configured

### Gap 5 — Application Factory Pattern

**File**: `src/main.py`

**Specific Changes:**
1. Move the `FastAPI(...)` constructor call and all `app.add_middleware(...)`, `app.add_exception_handler(...)`, `app.include_router(...)` calls into a new `create_app() -> FastAPI` function
2. Keep `_wire_dependencies()` called from `lifespan` (acceptable — lifespan is part of the factory's app)
3. At module level, replace the inline construction with: `app = create_app()`
4. Keep `handler = Mangum(app, lifespan="on")` at module level after `app = create_app()`

### Gap 6 — aioboto3 Migration

**Files**: `src/infrastructure/persistence/dynamodb_user_repository.py`,
`src/infrastructure/persistence/dynamodb_token_blacklist.py`, `src/main.py`

**Specific Changes:**
1. Add `aioboto3` to `pyproject.toml` dependencies
2. Replace `boto3.resource("dynamodb", ...)` with `aioboto3.Session()` stored as `self._session`
3. Use `async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:` and `table = await dynamodb.Table(self._table_name)` inside each async method
4. This preserves the existing `_to_item`/`_from_item` serialization (Python native types, not AttributeValue dicts) — no serialization changes required
5. Update `_wire_dependencies()` in `src/main.py` to pass `session=aioboto3.Session()` to both repositories
6. Update repository `__init__` signatures: `(self, table_name: str, region: str, session: aioboto3.Session) -> None`

---

## Testing Strategy

### Validation Approach

Two-phase approach: first surface counterexamples on unfixed code to confirm root cause analysis,
then verify the fix and preservation.

### Exploratory Fault Condition Checking

**Goal**: Surface counterexamples that demonstrate each bug BEFORE implementing the fix.

**Test Plan**: Write tests that exercise each defective code path and assert the correct behavior.
Run on UNFIXED code to observe failures and confirm root cause.

**Test Cases:**

1. **Security Headers — XSS header wrong** (will fail on unfixed code): Assert `X-XSS-Protection: 0` on any response
2. **Security Headers — missing Permissions-Policy** (will fail on unfixed code): Assert header present
3. **Security Headers — Server header exposed** (will fail on unfixed code): Assert `server` not in response headers
4. **Security Headers — Cache-Control on /api/ path** (will fail on unfixed code): Assert header present for `/api/v1/users`
5. **ClientError leaks — UserRepository** (will fail on unfixed code): Mock boto3 to raise `ClientError`, assert `RepositoryError` raised
6. **ConditionalCheck mapping — save()** (will fail on unfixed code): Mock `ConditionalCheckFailedException`, assert `RepositoryError`
7. **ConditionalCheck mapping — update()** (will fail on unfixed code): Mock `ConditionalCheckFailedException`, assert `NotFoundError`
8. **Rate limit — IP-only keying** (will fail on unfixed code): Two requests with same sub, different IPs — assert shared counter
9. **Rate limit — burst window** (will fail on unfixed code): 11 requests in 1 second — assert 429
10. **Rate limit — missing headers** (will fail on unfixed code): Assert `X-RateLimit-Limit` present on 200 response
11. **JWT — HS256 default** (will fail on unfixed code): Assert `settings.jwt_algorithm == "RS256"`
12. **JWT — HS256 token accepted** (will fail on unfixed code): Present HS256-signed token, assert `AuthenticationError`
13. **JWT — missing iss claim** (will fail on unfixed code): Present token without `iss`, assert `AuthenticationError`
14. **Factory — module-level construction** (will fail on unfixed code): Assert `FastAPI` not constructed at import time
15. **Async I/O — sync boto3 in async** (will fail on unfixed code): Assert no `boto3.resource()` calls in async methods

**Expected Counterexamples:**
- Security header assertions fail because `_SECURITY_HEADERS` dict has wrong/missing values
- `ClientError` propagates because no `try/except` blocks exist in repositories
- Rate limit counter is keyed by IP, not sub — different IPs bypass per-user limits
- `jwt_algorithm` is `"HS256"` in config; `verify_token()` accepts HS256 tokens
- `FastAPI(...)` call is at module level, not inside `create_app()`

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed code produces the expected behavior.

**Pseudocode:**
```
FOR ALL response WHERE isBugCondition_SecurityHeaders(response) DO
  result := SecurityHeadersMiddleware_fixed.dispatch(request, response)
  ASSERT all 9 headers present with correct values
  ASSERT "server" NOT IN result.headers
  ASSERT (path STARTS_WITH "/api/" IMPLIES "Cache-Control" IN result.headers)
END FOR

FOR ALL operation WHERE isBugCondition_ClientError(ClientError, "application") DO
  result := repository_fixed.operation(...)
  ASSERT result IS RepositoryError OR result IS NotFoundError
  ASSERT result IS NOT ClientError
END FOR

FOR ALL request WHERE isBugCondition_RateLimit(request, response) DO
  result := RateLimitMiddleware_fixed.dispatch(request, call_next)
  ASSERT correct window enforced
  ASSERT rate limit headers present
END FOR

FOR ALL token WHERE isBugCondition_JWT(token, config) DO
  result := JWTTokenService_fixed.verify_token(token)
  ASSERT result IS AuthenticationError
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed code produces the same result as the original.

**Pseudocode:**
```
FOR ALL response WHERE NOT isBugCondition_SecurityHeaders(response) DO
  ASSERT SecurityHeadersMiddleware_original(response) headers subset == SecurityHeadersMiddleware_fixed(response) headers subset
  -- specifically: X-Content-Type-Options, X-Frame-Options, Referrer-Policy unchanged
END FOR

FOR ALL operation WHERE NOT isBugCondition_ClientError(exception, layer) DO
  -- i.e., DynamoDB operation succeeds
  ASSERT repository_original.operation() == repository_fixed.operation()
END FOR

FOR ALL request WHERE NOT isBugCondition_RateLimit(request, response) DO
  -- i.e., request is within limits
  ASSERT response.status == original_response.status
END FOR

FOR ALL token WHERE NOT isBugCondition_JWT(token, config) DO
  -- i.e., valid RS256 token with all required claims
  ASSERT JWTTokenService_original.verify_token(token) == JWTTokenService_fixed.verify_token(token)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many token/request/response combinations automatically
- It catches edge cases (unusual claim combinations, path variations) that manual tests miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Cases:**
1. **Auth flow preservation**: register → verify_email → authenticate → refresh → logout produces same responses before and after fix
2. **Correct headers unchanged**: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` values unchanged after security headers fix
3. **Successful DynamoDB round-trip**: save/find/update/delete on valid inputs returns same domain entity after ClientError wrapping fix
4. **Valid RS256 token accepted**: Token with all required claims and correct algorithm continues to be accepted after JWT fix
5. **Rate limit 429 still fires**: Requests exceeding 60/min still return 429 after rate limit fix

### Unit Tests

- `tests/unit/presentation/test_security_headers.py` — all 9 headers, Server removal, Cache-Control conditional, non-/api/ path exclusion
- `tests/unit/presentation/test_rate_limiting.py` — per-user keying, 3 windows, response headers, instance state isolation, IP fallback
- `tests/unit/infrastructure/test_jwt_token_service.py` — RS256 enforcement, HS256 rejection, none rejection, missing claims, aud validation, valid token acceptance
- `tests/unit/infrastructure/test_dynamodb_user_repository.py` — ClientError wrapping, ConditionalCheck mapping for save() and update(), successful operation passthrough
- `tests/unit/infrastructure/test_dynamodb_token_blacklist.py` — ClientError wrapping for add() and is_blacklisted()
- `tests/unit/test_main.py` — create_app() returns FastAPI instance, two calls produce independent instances, no module-level construction

### Property-Based Tests

- Generate random HTTP paths and assert Cache-Control presence/absence based on `/api/` prefix
- Generate random JWT payloads with missing claims and assert `AuthenticationError` for each missing claim
- Generate random `sub` values and assert rate limit counters are isolated per sub
- Generate random valid RS256 tokens and assert they continue to be accepted after fix
- Generate random DynamoDB `ClientError` codes and assert all map to `RepositoryError` (except `ConditionalCheckFailedException` which maps to `NotFoundError` on update)

### Integration Tests

- `tests/integration/test_dynamodb_user_repository.py` — moto-based: save/find/update/delete round-trips, ConditionalCheck scenarios, ClientError wrapping with mocked failures
- `tests/integration/test_dynamodb_token_blacklist.py` — moto-based: add/is_blacklisted round-trip
- `tests/integration/test_auth_flow.py` — full register → authenticate → refresh → logout flow with fixed service
