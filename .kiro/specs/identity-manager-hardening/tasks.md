# Implementation Plan

- [x] 1. Write bug condition exploration tests (BEFORE implementing any fix)
  - **Property 1: Fault Condition** - Identity Manager 6-Gap Compliance Defects
  - **CRITICAL**: These tests MUST FAIL on unfixed code — failure confirms each bug exists
  - **DO NOT attempt to fix the tests or the code when they fail**
  - **NOTE**: These tests encode the expected behavior — they will validate the fix when they pass after implementation
  - **GOAL**: Surface counterexamples that demonstrate each of the 19 defect clauses exists
  - **Scoped PBT Approach**: For deterministic bugs, scope each property to the concrete failing case(s)
  - Write tests in `ugsys-identity-manager/tests/unit/presentation/test_security_headers.py`:
    - Assert `X-XSS-Protection: 0` on any response (currently returns `1; mode=block`)
    - Assert `Strict-Transport-Security` contains `preload` (currently missing)
    - Assert `Permissions-Policy` header present (currently missing)
    - Assert `Cross-Origin-Opener-Policy` header present (currently missing)
    - Assert `Cross-Origin-Resource-Policy` header present (currently missing)
    - Assert `server` NOT in response headers (currently exposed as `uvicorn`)
    - Assert `Cache-Control: no-store, no-cache, must-revalidate` present on `/api/v1/users` response (currently missing)
  - Write tests in `ugsys-identity-manager/tests/unit/infrastructure/test_dynamodb_user_repository.py`:
    - Mock boto3 to raise `ClientError` on `find_by_id()` — assert `RepositoryError` raised (currently `ClientError` leaks)
    - Mock `ConditionalCheckFailedException` on `save()` — assert `RepositoryError` raised (currently leaks)
    - Mock `ConditionalCheckFailedException` on `update()` — assert `NotFoundError` raised (currently leaks)
  - Write tests in `ugsys-identity-manager/tests/unit/infrastructure/test_dynamodb_token_blacklist.py`:
    - Mock boto3 to raise `ClientError` on `add()` — assert `RepositoryError` raised (currently leaks)
    - Mock boto3 to raise `ClientError` on `is_blacklisted()` — assert `RepositoryError` raised (currently leaks)
  - Write tests in `ugsys-identity-manager/tests/unit/presentation/test_rate_limiting.py`:
    - Two requests with same JWT `sub`, different IPs — assert shared counter (currently IP-keyed, resets)
    - 11 requests in 1 second — assert 429 returned (currently no burst window)
    - Assert `X-RateLimit-Limit` present on 200 response (currently missing)
    - Assert `Retry-After` present on 429 response (currently missing)
  - Write tests in `ugsys-identity-manager/tests/unit/infrastructure/test_jwt_token_service.py`:
    - Assert `settings.jwt_algorithm == "RS256"` (currently `"HS256"`)
    - Present HS256-signed token to `verify_token()` — assert `AuthenticationError` raised (currently accepted)
    - Present token with `alg: none` — assert `AuthenticationError` raised before signature check
    - Present token missing `iss` claim — assert `AuthenticationError` raised (currently accepted)
    - Present token missing `sub` claim — assert `AuthenticationError` raised
  - Write tests in `ugsys-identity-manager/tests/unit/test_main.py`:
    - Assert `FastAPI` is NOT constructed at module import time (currently constructed at module level)
    - Assert two calls to `create_app()` produce independent `FastAPI` instances
  - Run all tests on UNFIXED code
  - **EXPECTED OUTCOME**: All tests FAIL (this is correct — it proves each bug exists)
  - Document counterexamples found (e.g., "X-XSS-Protection: 1; mode=block returned", "ClientError propagated to caller", "jwt_algorithm is HS256")
  - Mark task complete when tests are written, run, and failures are documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18, 1.19_

- [x] 2. Write preservation property tests (BEFORE implementing any fix)
  - **Property 2: Preservation** - Auth Flows, Correct Headers, Successful DynamoDB Operations
  - **IMPORTANT**: Follow observation-first methodology — run unfixed code first, observe outputs, then write tests
  - Observe: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` on any response from unfixed code
  - Observe: `POST /api/v1/auth/login` with valid credentials returns 200 + tokens on unfixed code
  - Observe: `POST /api/v1/users` with unique email returns 201 on unfixed code
  - Observe: `POST /api/v1/users` with duplicate email returns 409 on unfixed code
  - Observe: `GET /health` returns 200 without auth on unfixed code
  - Observe: Requests exceeding 60/min return 429 on unfixed code
  - Observe: Successful `save()`/`find_by_id()`/`update()`/`delete()` return correct domain entity on unfixed code
  - Write property-based tests in `ugsys-identity-manager/tests/unit/presentation/test_security_headers.py`:
    - For any HTTP path, `X-Content-Type-Options: nosniff` is always present (from Preservation Requirement 3.10)
    - For any HTTP path, `X-Frame-Options: DENY` is always present (from Preservation Requirement 3.10)
    - For any HTTP path, `Referrer-Policy: strict-origin-when-cross-origin` is always present (from Preservation Requirement 3.10)
    - For any non-`/api/` path, `Cache-Control` is NOT added (e.g., `/health`, `/docs`)
  - Write property-based tests in `ugsys-identity-manager/tests/unit/infrastructure/test_jwt_token_service.py`:
    - For any valid RS256 token with all required claims (`sub`, `exp`, `iat`, `iss`), `verify_token()` returns the payload (from Preservation Requirement 3.2)
  - Write property-based tests in `ugsys-identity-manager/tests/unit/infrastructure/test_dynamodb_user_repository.py`:
    - For any successful DynamoDB operation (no `ClientError`), the returned domain entity is identical to the input entity (from Preservation Requirement 3.8)
  - Write integration tests in `ugsys-identity-manager/tests/integration/test_auth_flow.py`:
    - Full register → authenticate → refresh → logout flow produces same responses (from Preservation Requirements 3.1–3.5)
    - Revoked token after logout is rejected (from Preservation Requirement 3.3)
    - `GET /health` returns 200 without auth (from Preservation Requirement 3.6)
  - Run all preservation tests on UNFIXED code
  - **EXPECTED OUTCOME**: All preservation tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

- [x] 3. Fix Gap 1 — Security headers compliance

  - [x] 3.1 Update `_SECURITY_HEADERS` dict and dispatch logic in `security_headers.py`
    - Replace `_SECURITY_HEADERS` dict with complete 9-header set per platform contract Section 9.2
    - Set `X-XSS-Protection: 0` (was `1; mode=block`)
    - Set `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` (add `preload`)
    - Set `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`
    - Add `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`
    - Add `Cross-Origin-Opener-Policy: same-origin`
    - Add `Cross-Origin-Resource-Policy: same-origin`
    - In `dispatch()`: `response.headers.pop("server", None)` after setting headers
    - In `dispatch()`: if `request.url.path.startswith("/api/")`, set `Cache-Control: no-store, no-cache, must-revalidate`
    - _Bug_Condition: isBugCondition_SecurityHeaders(response) — wrong/missing headers, Server exposed, Cache-Control absent on /api/ paths_
    - _Expected_Behavior: all 9 headers present with exact platform-contract values; Server absent; Cache-Control on /api/ paths_
    - _Preservation: X-Content-Type-Options, X-Frame-Options, Referrer-Policy retain current correct values (3.10); non-/api/ paths do not get Cache-Control_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 3.2 Verify security headers exploration tests now pass
    - **Property 1: Expected Behavior** - Security Headers Completeness
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Run security headers exploration tests from step 1
    - **EXPECTED OUTCOME**: All 7 security header assertions PASS (confirms Gap 1 is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 3.3 Verify security headers preservation tests still pass
    - **Property 2: Preservation** - Existing Correct Headers Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation tests for `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, non-/api/ path exclusion
    - **EXPECTED OUTCOME**: All preservation tests PASS (confirms no regressions)

- [x] 4. Fix Gap 2 — DynamoDB ClientError wrapping

  - [x] 4.1 Add ClientError wrapping to `dynamodb_user_repository.py`
    - Add `from botocore.exceptions import ClientError` import
    - Add `_raise_repository_error(self, operation: str, e: ClientError) -> None` method — logs full error with `structlog`, raises `RepositoryError(message=..., user_message="An unexpected error occurred")`
    - Wrap every `self._table.*` call in `try/except ClientError`
    - In `save()`: catch `ConditionalCheckFailedException` → raise `RepositoryError`
    - In `update()`: catch `ConditionalCheckFailedException` → raise `NotFoundError(user_message="User not found")`
    - All other `ClientError` codes → `_raise_repository_error()`
    - NOTE: Apply to existing `boto3.resource()` API — aioboto3 migration is Gap 6
    - _Bug_Condition: isBugCondition_ClientError(exception, "application") — raw ClientError leaks to application layer_
    - _Expected_Behavior: all ClientError caught; RepositoryError or NotFoundError raised to application layer_
    - _Preservation: successful DynamoDB operations return same domain entity as before (3.8)_
    - _Requirements: 2.7, 2.8, 2.9, 2.10_

  - [x] 4.2 Add ClientError wrapping to `dynamodb_token_blacklist.py`
    - Add `from botocore.exceptions import ClientError` import
    - Add `_raise_repository_error(self, operation: str, e: ClientError) -> None` method (same pattern as 4.1)
    - Wrap every `self._table.*` call in `try/except ClientError`
    - _Bug_Condition: isBugCondition_ClientError(exception, "application") — raw ClientError leaks from token blacklist repository_
    - _Expected_Behavior: all ClientError caught; RepositoryError raised to application layer_
    - _Preservation: successful add()/is_blacklisted() operations return same result as before (3.8)_
    - _Requirements: 2.7, 2.8_

  - [x] 4.3 Verify ClientError exploration tests now pass
    - **Property 1: Expected Behavior** - ClientError Isolation
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Run ClientError exploration tests for both repositories from step 1
    - **EXPECTED OUTCOME**: All 5 ClientError assertions PASS (confirms Gap 2 is fixed)
    - _Requirements: 2.7, 2.8, 2.9, 2.10_

  - [x] 4.4 Verify ClientError preservation tests still pass
    - **Property 2: Preservation** - Successful DynamoDB Operations Return Domain Entity
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation tests for successful DynamoDB round-trips
    - **EXPECTED OUTCOME**: All preservation tests PASS (confirms no regressions)

- [x] 5. Fix Gap 3 — Rate limiting (per-user keying, 3 windows, response headers)

  - [x] 5.1 Refactor `rate_limiting.py` to per-user keying with 3 windows and response headers
    - Remove module-level `_request_log` global
    - Add `self._counters: dict[str, list[float]] = defaultdict(list)` in `__init__`
    - Add `_extract_key(self, request: Request) -> str`: decode Bearer JWT without sig verification, extract `sub` → `f"user:{sub}"`; fallback to IP → `f"ip:{ip}"`
    - Add window constants: `_WINDOW_MINUTE=60.0`, `_WINDOW_HOUR=3600.0`, `_BURST_WINDOW=1.0`
    - Add limit constants: `_MAX_PER_MINUTE=60`, `_MAX_PER_HOUR=1000`, `_MAX_BURST=10`
    - In `dispatch()`: prune `self._counters[key]` to 1-hour window; compute burst/minute/hour counts; return 429 with `Retry-After` if any limit exceeded
    - On non-429 responses: set `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers
    - _Bug_Condition: isBugCondition_RateLimit(request, response) — IP-only keying, missing windows, missing headers_
    - _Expected_Behavior: per-JWT-sub counters; burst/minute/hour windows enforced; X-RateLimit-* headers on all responses; Retry-After on 429_
    - _Preservation: requests exceeding 60/min still return 429 (3.7); auth flows unaffected (3.1–3.5)_
    - _Requirements: 2.11, 2.12, 2.13, 2.14, 2.15, 2.16_

  - [x] 5.2 Verify rate limiting exploration tests now pass
    - **Property 1: Expected Behavior** - Rate Limit Key Isolation and Headers
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Run rate limiting exploration tests from step 1
    - **EXPECTED OUTCOME**: All 4 rate limit assertions PASS (confirms Gap 3 is fixed)
    - _Requirements: 2.11, 2.12, 2.13, 2.14, 2.15, 2.16_

  - [x] 5.3 Verify rate limiting preservation tests still pass
    - **Property 2: Preservation** - Rate Limit 429 Still Fires
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation tests confirming 60/min limit still triggers 429
    - **EXPECTED OUTCOME**: All preservation tests PASS (confirms no regressions)

- [x] 6. Fix Gap 4 — JWT RS256 enforcement and required claims validation

  - [x] 6.1 Update `src/config.py` to enforce RS256 and add JWT config fields
    - Change `jwt_algorithm: str = "HS256"` → `jwt_algorithm: str = "RS256"`
    - Add `jwt_audience: str = ""` (from env `JWT_AUDIENCE`)
    - Add `jwt_issuer: str = ""` (from env `JWT_ISSUER`)
    - Add `jwt_public_key: str = ""` (from env `JWT_PUBLIC_KEY`, PEM format)
    - Add `jwt_private_key: str = ""` (from env `JWT_PRIVATE_KEY`, PEM format)
    - Add `@field_validator("jwt_algorithm")` that raises `ValueError` if value is not `"RS256"`
    - _Bug_Condition: isBugCondition_JWT(token, config) — jwt_algorithm defaults to HS256_
    - _Expected_Behavior: jwt_algorithm is always RS256; validator rejects any other value at startup_
    - _Requirements: 2.17_

  - [x] 6.2 Update `jwt_token_service.py` to pre-verify algorithm and validate required claims
    - In `verify_token()`: call `jwt.get_unverified_header(token)` BEFORE `jwt.decode()`; if `alg != "RS256"` → raise `AuthenticationError` immediately
    - Pass `algorithms=["RS256"]` explicitly to `jwt.decode()`
    - After decode, validate `sub`, `exp`, `iat`, `iss` all present; missing any → `AuthenticationError`
    - If `settings.jwt_audience` is set, validate `payload.get("aud") == settings.jwt_audience`; mismatch → `AuthenticationError`
    - Update `_encode()` to include `iss` and `aud` claims when configured
    - _Bug_Condition: isBugCondition_JWT(token, config) — HS256/none tokens accepted; missing claims accepted_
    - _Expected_Behavior: HS256/none tokens raise AuthenticationError before signature check; tokens missing sub/exp/iat/iss raise AuthenticationError_
    - _Preservation: valid RS256 tokens with all required claims continue to be accepted (3.2)_
    - _Requirements: 2.17, 2.18, 2.19_

  - [x] 6.3 Verify JWT exploration tests now pass
    - **Property 1: Expected Behavior** - RS256 Algorithm Enforcement and Required Claims Validation
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Run JWT exploration tests from step 1
    - **EXPECTED OUTCOME**: All 5 JWT assertions PASS (confirms Gap 4 is fixed)
    - _Requirements: 2.17, 2.18, 2.19_

  - [x] 6.4 Verify JWT preservation tests still pass
    - **Property 2: Preservation** - Valid RS256 Tokens Still Accepted
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation tests confirming valid RS256 tokens with all required claims are still accepted
    - **EXPECTED OUTCOME**: All preservation tests PASS (confirms no regressions)

- [x] 7. Fix Gap 5 — Application factory pattern

  - [x] 7.1 Move FastAPI construction and wiring into `create_app()` in `src/main.py`
    - Move `FastAPI(...)` constructor call into `create_app() -> FastAPI` function
    - Move all `app.add_middleware(...)` calls into `create_app()`
    - Move all `app.add_exception_handler(...)` calls into `create_app()`
    - Move all `app.include_router(...)` calls into `create_app()`
    - Keep `_wire_dependencies()` called from `lifespan` (lifespan is part of the factory's app)
    - At module level: `app = create_app()`
    - Keep `handler = Mangum(app, lifespan="on")` at module level after `app = create_app()`
    - _Bug_Condition: isBugCondition_Factory(module) — FastAPI constructed at module level, not inside create_app()_
    - _Expected_Behavior: create_app() is the single composition root; two calls produce independent FastAPI instances; no registration at import time_
    - _Preservation: Lambda Mangum handler continues to work (3.9); all auth flows unaffected (3.1–3.5)_
    - _Requirements: 2.20, 2.21_

  - [x] 7.2 Verify factory pattern exploration tests now pass
    - **Property 1: Expected Behavior** - create_app() Idempotency
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Run factory pattern exploration tests from step 1
    - **EXPECTED OUTCOME**: Both factory assertions PASS (confirms Gap 5 is fixed)
    - _Requirements: 2.20, 2.21_

  - [x] 7.3 Verify factory pattern preservation tests still pass
    - **Property 2: Preservation** - Mangum Handler and Auth Flows Unaffected
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation tests confirming Mangum handler and auth flows still work
    - **EXPECTED OUTCOME**: All preservation tests PASS (confirms no regressions)

- [x] 8. Fix Gap 6 — aioboto3 migration (async I/O)

  - [x] 8.1 Add `aioboto3` dependency to `pyproject.toml`
    - Add `aioboto3` to `[project.dependencies]` in `ugsys-identity-manager/pyproject.toml`
    - Run `uv lock` to update the lockfile
    - _Requirements: 2.22_

  - [x] 8.2 Migrate `dynamodb_user_repository.py` to aioboto3
    - Replace `boto3.resource("dynamodb", ...)` with `self._session: aioboto3.Session` stored from `__init__`
    - Update `__init__` signature: `(self, table_name: str, region: str, session: aioboto3.Session) -> None`
    - In each async method: use `async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:` and `table = await dynamodb.Table(self._table_name)`
    - Preserve existing `_to_item`/`_from_item` serialization (Python native types) — no serialization changes
    - ClientError wrapping from Gap 2 (task 4.1) remains intact — no changes to try/except blocks
    - _Bug_Condition: isBugCondition_AsyncIO(repository_method) — synchronous boto3.resource() inside async def blocks event loop_
    - _Expected_Behavior: all DynamoDB calls are non-blocking async I/O via aioboto3_
    - _Preservation: successful operations return same domain entity as before (3.8); ClientError wrapping unchanged_
    - _Requirements: 2.22_

  - [x] 8.3 Migrate `dynamodb_token_blacklist.py` to aioboto3
    - Same migration pattern as 8.2
    - Update `__init__` signature: `(self, table_name: str, region: str, session: aioboto3.Session) -> None`
    - Use `async with self._session.resource(...)` pattern in each async method
    - ClientError wrapping from Gap 2 (task 4.2) remains intact
    - _Bug_Condition: isBugCondition_AsyncIO(repository_method) — synchronous boto3.resource() inside async def in token blacklist_
    - _Expected_Behavior: all DynamoDB calls are non-blocking async I/O via aioboto3_
    - _Preservation: add()/is_blacklisted() return same result as before (3.8); revoked token rejection unchanged (3.3)_
    - _Requirements: 2.22_

  - [x] 8.4 Update `_wire_dependencies()` in `src/main.py` for aioboto3
    - Pass `session=aioboto3.Session()` to both repository constructors in `_wire_dependencies()`
    - Import `aioboto3` at top of `src/main.py`
    - _Requirements: 2.22_

  - [x] 8.5 Verify async I/O exploration tests now pass
    - **Property 1: Expected Behavior** - No Synchronous boto3 in Async Methods
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Run async I/O exploration tests from step 1 (assert no `boto3.resource()` calls in async methods)
    - **EXPECTED OUTCOME**: Assertion PASSES (confirms Gap 6 is fixed)
    - _Requirements: 2.22_

  - [x] 8.6 Verify async I/O preservation tests still pass
    - **Property 2: Preservation** - Successful DynamoDB Operations Return Domain Entity
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run integration tests for DynamoDB round-trips with aioboto3 (moto-based)
    - **EXPECTED OUTCOME**: All preservation tests PASS (confirms no regressions)

- [x] 9. Checkpoint — Ensure all tests pass
  - Run full test suite: `uv run pytest ugsys-identity-manager/tests/unit/ -v --tb=short`
  - Run integration tests: `uv run pytest ugsys-identity-manager/tests/integration/ -v --tb=short`
  - Confirm coverage gate: `uv run pytest ugsys-identity-manager/tests/unit/ --cov=src --cov-fail-under=80`
  - Run ruff: `uv run ruff check ugsys-identity-manager/src/ ugsys-identity-manager/tests/`
  - Run mypy: `uv run mypy ugsys-identity-manager/src/ --strict`
  - Ensure all 19 defect clauses are resolved and all 10 correctness properties hold
  - Ask the user if any questions arise
