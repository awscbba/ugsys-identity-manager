# Bugfix Requirements Document

## Introduction

The `ugsys-identity-manager` service has six enterprise pattern compliance gaps that constitute security and reliability defects. These violations of the platform contract must be resolved before production deployment. The gaps span security headers, DynamoDB error handling, rate limiting, JWT algorithm enforcement, the application factory pattern, and async I/O correctness.

---

## Bug Analysis

### Current Behavior (Defect)

**Security Headers (Section 9.2)**

1.1 WHEN any HTTP response is returned THEN the system sets `X-XSS-Protection: 1; mode=block`, which re-enables the legacy browser XSS filter that is known to introduce vulnerabilities

1.2 WHEN any HTTP response is returned THEN the system sets `Strict-Transport-Security: max-age=31536000; includeSubDomains` without the `preload` directive, preventing HSTS preload list inclusion

1.3 WHEN any HTTP response is returned THEN the system sets `Content-Security-Policy: default-src 'self'`, which is too permissive for a pure API service and does not include `frame-ancestors 'none'`

1.4 WHEN any HTTP response is returned THEN the system omits the `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`, and `Cache-Control` headers required by the platform contract

1.5 WHEN any HTTP response is returned THEN the system includes the `Server` response header, exposing the technology stack to potential attackers

**DynamoDB ClientError Wrapping**

1.6 WHEN a DynamoDB operation fails in `DynamoDBUserRepository` THEN the system allows raw `ClientError` exceptions to propagate to the unhandled exception handler, leaking infrastructure error details

1.7 WHEN a DynamoDB operation fails in `DynamoDBTokenBlacklistRepository` THEN the system allows raw `ClientError` exceptions to propagate to the unhandled exception handler, leaking infrastructure error details

1.8 WHEN `DynamoDBUserRepository.save()` encounters a `ConditionalCheckFailedException` THEN the system propagates the raw boto3 exception instead of raising a `RepositoryError`

1.9 WHEN `DynamoDBUserRepository.update()` encounters a `ConditionalCheckFailedException` THEN the system propagates the raw boto3 exception instead of raising a `NotFoundError`

**Rate Limiting**

1.10 WHEN an authenticated user makes requests THEN the system keys rate limiting only by IP address (`X-Forwarded-For` / `client.host`), not by JWT `sub`, allowing a single user to bypass per-user limits from multiple IPs

1.11 WHEN a request is made THEN the system enforces only a 60 req/min window and does not enforce the 1000 req/hour or 10 req/second burst limits required by the platform contract

1.12 WHEN a request is processed or rate-limited THEN the system omits the `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` response headers

1.13 WHEN the service starts THEN the rate limit counters are stored in a module-level global `_request_log` dict, which is shared across all middleware instances and cannot be properly reset or isolated

**JWT Algorithm**

1.14 WHEN the service starts THEN the system defaults `jwt_algorithm` to `"HS256"` in `src/config.py`, violating the platform contract that mandates RS256 only

1.15 WHEN a JWT is verified THEN the system does not enforce algorithm restriction before signature verification, leaving it vulnerable to algorithm confusion attacks

1.16 WHEN a JWT is decoded THEN the system does not validate required claims (`sub`, `exp`, `iat`, `iss`) nor the `aud` claim against the service's client ID

**Application Factory Pattern**

1.17 WHEN the application module is imported THEN the system constructs the `FastAPI` instance and wires all middleware, exception handlers, and routers at module level rather than inside a `create_app()` factory function, violating the platform contract composition root pattern

1.18 WHEN the application starts THEN dependency wiring is deferred to `_wire_dependencies()` called from the lifespan hook rather than being part of the factory, making the composition root split across two functions

**Async I/O**

1.19 WHEN `DynamoDBUserRepository` or `DynamoDBTokenBlacklistRepository` performs any DynamoDB operation THEN the system uses synchronous `boto3.resource()` calls inside `async` methods, blocking the event loop and degrading throughput under concurrent load

---

### Expected Behavior (Correct)

**Security Headers (Section 9.2)**

2.1 WHEN any HTTP response is returned THEN the system SHALL set `X-XSS-Protection: 0` to disable the legacy XSS filter and rely on CSP instead

2.2 WHEN any HTTP response is returned THEN the system SHALL set `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`

2.3 WHEN any HTTP response is returned THEN the system SHALL set `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`

2.4 WHEN any HTTP response is returned THEN the system SHALL include `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`, `Cross-Origin-Opener-Policy: same-origin`, and `Cross-Origin-Resource-Policy: same-origin`

2.5 WHEN a request path matches `/api/*` THEN the system SHALL include `Cache-Control: no-store, no-cache, must-revalidate`

2.6 WHEN any HTTP response is returned THEN the system SHALL remove the `Server` response header

**DynamoDB ClientError Wrapping**

2.7 WHEN any DynamoDB operation fails in `DynamoDBUserRepository` THEN the system SHALL catch `ClientError`, log the full error detail internally, and raise a `RepositoryError` with a safe `user_message`

2.8 WHEN any DynamoDB operation fails in `DynamoDBTokenBlacklistRepository` THEN the system SHALL catch `ClientError`, log the full error detail internally, and raise a `RepositoryError` with a safe `user_message`

2.9 WHEN `DynamoDBUserRepository.save()` encounters a `ConditionalCheckFailedException` THEN the system SHALL raise a `RepositoryError` with `error_code="REPOSITORY_ERROR"` and `user_message="An unexpected error occurred"`

2.10 WHEN `DynamoDBUserRepository.update()` encounters a `ConditionalCheckFailedException` THEN the system SHALL raise a `NotFoundError` with `error_code="NOT_FOUND"` and `user_message="User not found"`

**Rate Limiting**

2.11 WHEN an authenticated request carries a valid JWT THEN the system SHALL extract the `sub` claim and key rate limiting by that value instead of by IP address

2.12 WHEN an unauthenticated request is received THEN the system SHALL fall back to IP-based rate limiting

2.13 WHEN any request is processed THEN the system SHALL enforce a 60 req/min window, a 1000 req/hour window, and a 10 req/second burst limit

2.14 WHEN any response is returned THEN the system SHALL include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers

2.15 WHEN a 429 response is returned THEN the system SHALL include a `Retry-After` header

2.16 WHEN the middleware is instantiated THEN the system SHALL store rate limit counters as instance state (`self._counters`) rather than a module-level global

**JWT Algorithm**

2.17 WHEN the service starts THEN the system SHALL default `jwt_algorithm` to `"RS256"` in `src/config.py` and SHALL reject `"HS256"` and `"none"` at configuration load time

2.18 WHEN a JWT is verified THEN the system SHALL enforce the allowed algorithm list before attempting signature verification

2.19 WHEN a JWT is decoded THEN the system SHALL validate that `sub`, `exp`, `iat`, and `iss` claims are all present and SHALL validate `aud` against the configured service client ID, rejecting tokens missing any required claim

**Application Factory Pattern**

2.20 WHEN the application module is imported THEN the system SHALL expose a `create_app()` factory function that constructs the `FastAPI` instance and wires all middleware, exception handlers, and routers in one place

2.21 WHEN `create_app()` is called THEN the system SHALL perform all dependency wiring inside the factory (or its lifespan), making `create_app()` the single composition root

**Async I/O**

2.22 WHEN `DynamoDBUserRepository` or `DynamoDBTokenBlacklistRepository` performs any DynamoDB operation THEN the system SHALL use `aioboto3` with `async with session.client("dynamodb")` so that I/O does not block the event loop

---

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a valid login request is submitted with correct credentials THEN the system SHALL CONTINUE TO return a valid access token and refresh token

3.2 WHEN a valid access token is presented to a protected endpoint THEN the system SHALL CONTINUE TO authenticate the request and return the expected response

3.3 WHEN a token is revoked via logout THEN the system SHALL CONTINUE TO reject subsequent requests using that token

3.4 WHEN a user registration request is submitted with a unique email THEN the system SHALL CONTINUE TO create the user and return a 201 response

3.5 WHEN a user registration request is submitted with a duplicate email THEN the system SHALL CONTINUE TO return a 409 Conflict response

3.6 WHEN a request is made to `/health` THEN the system SHALL CONTINUE TO return a 200 response without requiring authentication

3.7 WHEN a request exceeds the 60 req/min limit THEN the system SHALL CONTINUE TO return a 429 response

3.8 WHEN a DynamoDB operation succeeds THEN the system SHALL CONTINUE TO return the correct domain entity to the caller

3.9 WHEN the service is deployed to Lambda THEN the system SHALL CONTINUE TO handle requests via the Mangum adapter

3.10 WHEN `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` headers are evaluated THEN the system SHALL CONTINUE TO return their current correct values (`nosniff`, `DENY`, `strict-origin-when-cross-origin`)
