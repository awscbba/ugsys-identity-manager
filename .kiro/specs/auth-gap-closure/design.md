# Design Document — auth-gap-closure

## Overview

This feature closes four authentication gaps that prevent end-to-end login from working in
both the Projects Registry and Admin Panel frontends. The changes span three repos:

- **ugsys-identity-manager** — add `email` claim to access tokens (backend + port change)
- **ugsys-projects-registry** — no code change needed; the frontend already reads `email`
  from the JWT payload; it just needs the token to carry it
- **ugsys-admin-panel** — two sub-systems:
  - **admin-shell** (React SPA) — add `/login` route, replace inline `LoginPage` render
    with a proper `<Navigate>` redirect, handle post-login navigation and 403 display
  - **BFF** (FastAPI) — gate the login endpoint to admin/super_admin roles only

The changes are deliberately minimal: no new services, no new infrastructure, no new
dependencies. Every file touched already exists; this is surgical correction.

---

## Architecture

The fix flows through the existing hexagonal layers without adding new ones:

```
┌─────────────────────────────────────────────────────────────────────┐
│  ugsys-identity-manager                                             │
│                                                                     │
│  domain/repositories/token_service.py  ← add email param to ABC   │
│  infrastructure/adapters/jwt_token_service.py  ← embed email claim │
│  application/services/auth_service.py  ← pass user.email           │
└─────────────────────────────────────────────────────────────────────┘
                          │  RS256 JWT (now with email claim)
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ugsys-projects-registry / web                                      │
│                                                                     │
│  src/stores/authStore.ts  ← already reads email; no change needed  │
│  src/hooks/useProtectedRoute.ts  ← already correct; no change      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  ugsys-admin-panel / admin-shell                                    │
│                                                                     │
│  src/App.tsx  ← add /login route outside AppShell                  │
│  src/presentation/components/layout/AppShell.tsx  ← Navigate       │
│  src/presentation/components/views/LoginPage.tsx  ← post-login nav │
└─────────────────────────────────────────────────────────────────────┘
                          │  POST /api/v1/auth/login
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ugsys-admin-panel / BFF                                            │
│                                                                     │
│  src/presentation/api/v1/auth.py  ← decode token, check roles      │
│  src/application/services/auth_service.py  ← extract_roles helper  │
└─────────────────────────────────────────────────────────────────────┘
```

No new layers, no new abstractions. The dependency arrows remain unchanged.

---

## Components and Interfaces

### 1. Identity Manager — TokenService port

**File:** `src/domain/repositories/token_service.py`

The `create_access_token` abstract method gains a required `email` parameter:

```python
# Before
@abstractmethod
def create_access_token(self, user_id: UUID, roles: list[str]) -> str: ...

# After
@abstractmethod
def create_access_token(self, user_id: UUID, email: str, roles: list[str]) -> str: ...
```

All other methods (`create_refresh_token`, `create_password_reset_token`,
`create_service_token`) are unchanged. The `email` claim is intentionally absent from
those token types — each has its own purpose-specific claim set.

### 2. Identity Manager — JWTTokenService adapter

**File:** `src/infrastructure/adapters/jwt_token_service.py`

`create_access_token` embeds `email` in the payload dict passed to `_encode`:

```python
# Before
def create_access_token(self, user_id: UUID, roles: list[str]) -> str:
    return self._encode(
        {"sub": str(user_id), "roles": roles, "type": "access"},
        self._access_ttl,
    )

# After
def create_access_token(self, user_id: UUID, email: str, roles: list[str]) -> str:
    return self._encode(
        {"sub": str(user_id), "email": email, "roles": roles, "type": "access"},
        self._access_ttl,
    )
```

The `_encode` helper is unchanged — it adds `jti`, `exp`, `iat`, `iss` automatically.
The resulting access token payload will be exactly:
`{sub, email, roles, type, jti, exp, iat, iss}`.

### 3. Identity Manager — AuthService

**File:** `src/application/services/auth_service.py`

Two call sites need updating — `authenticate` and `refresh`:

```python
# authenticate (step 8 — "Create tokens and return")
# Before
access_token = self._token_service.create_access_token(
    user_id=user.id,
    roles=[r.value for r in user.roles],
)

# After
access_token = self._token_service.create_access_token(
    user_id=user.id,
    email=user.email,
    roles=[r.value for r in user.roles],
)
```

```python
# refresh (after user lookup)
# Before
access_token = self._token_service.create_access_token(
    user_id=user.id,
    roles=[r.value for r in user.roles],
)

# After
access_token = self._token_service.create_access_token(
    user_id=user.id,
    email=user.email,
    roles=[r.value for r in user.roles],
)
```

`user.email` is already available at both call sites — no additional repository
lookups are needed.

### 4. Projects Registry — no code change

**Files:** `web/src/stores/authStore.ts`, `web/src/hooks/useProtectedRoute.ts`

`extractUser` already reads `payload['email']` and returns `null` when it is missing.
Once the identity manager starts embedding the claim, `$user` will be non-null after
login and `$isAuthenticated` will be `true`. `useProtectedRoute` already calls
`navigate` with `replace: true` and encodes the current pathname as the `redirect`
query parameter. No changes are required in this repo.

### 5. Admin Shell — App.tsx routing

**File:** `admin-shell/src/App.tsx`

A `/login` route is added outside the `AppShell` wrapper. An authenticated guard is
added to the login route so that already-authenticated users are bounced to `/dashboard`
(or the `redirect` param). The existing routes inside `AppShell` are unchanged.

```tsx
// Before — all routes inside AppShell, no /login route
<Routes>
  <Route element={<AppShell />}>
    <Route index element={<Navigate to="/dashboard" replace />} />
    <Route path="dashboard" element={<HealthDashboard />} />
    {/* ... */}
  </Route>
</Routes>

// After — /login outside AppShell
<Routes>
  {/* Public route — no AppShell wrapper */}
  <Route path="login" element={<LoginRoute />} />

  {/* Protected routes — AppShell handles auth redirect */}
  <Route element={<AppShell />}>
    <Route index element={<Navigate to="/dashboard" replace />} />
    <Route path="dashboard" element={<HealthDashboard />} />
    <Route path="users" element={<UserManagement />} />
    <Route path="audit" element={<AuditLog />} />
    <Route path="config/:serviceName" element={<ConfigFormRoute />} />
    <Route path="app/:serviceName/*" element={<MicroFrontendRoute />} />
  </Route>
</Routes>
```

`LoginRoute` is a small inline component that redirects authenticated users away:

```tsx
function LoginRoute(): React.ReactElement {
  const isAuthenticated = useStore($isAuthenticated);
  const [searchParams] = useSearchParams();
  const redirect = searchParams.get("redirect") ?? "/dashboard";
  if (isAuthenticated) return <Navigate to={redirect} replace />;
  return <LoginPage />;
}
```

### 6. Admin Shell — AppShell.tsx

**File:** `admin-shell/src/presentation/components/layout/AppShell.tsx`

The inline `return <LoginPage />` is replaced with a `<Navigate>` redirect. The
`LoginPage` import is removed.

```tsx
// Before
if (!isAuthenticated) {
  return <LoginPage />;
}

// After
if (!isAuthenticated) {
  const redirect = encodeURIComponent(location.pathname + location.search);
  return <Navigate to={`/login?redirect=${redirect}`} replace />;
}
```

`useLocation` is imported from `react-router-dom` to read the current path.
The `LoginPage` import is removed from this file.

### 7. Admin Shell — LoginPage.tsx

**File:** `admin-shell/src/presentation/components/views/LoginPage.tsx`

After a successful `login()` call, the component navigates to the `redirect` query
parameter destination (or `/dashboard` as fallback). On a 403 response from the BFF,
a user-safe message is displayed.

```tsx
// Added imports
import { useNavigate, useSearchParams } from "react-router-dom";
import { $error } from "../../../stores/authStore";

// Inside the component
const navigate = useNavigate();
const [searchParams] = useSearchParams();
const storeError = useStore($error);

const handleSubmit = async (e: React.FormEvent) => {
  e.preventDefault();
  setLoginError(null);
  await login(email, password);
  // login() sets $error on failure; $user on success
  // Check $user after the call — if set, navigate
  if ($user.get() !== null) {
    const redirect = searchParams.get("redirect") ?? "/dashboard";
    navigate(redirect, { replace: true });
  }
};
```

The `$error` atom from `authStore` already carries the user-safe message set by
`login()`. The component renders it in the existing `role="alert"` paragraph.
The BFF returns a 403 with `{"error": "FORBIDDEN", "message": "You do not have
permission to access the Admin Panel"}` — `HttpAuthRepository` maps this to an
`Error` with that message, which `login()` stores in `$error`.

### 8. BFF — auth.py login endpoint

**File:** `src/presentation/api/v1/auth.py`

After receiving the token pair from the Identity Manager, the BFF decodes the access
token payload (without re-verifying the signature — the Identity Manager already
verified it) and checks for an admin role. If the check fails, cookies are cleared and
403 is returned.

```python
# After token_pair is obtained from auth_service.login():
import base64, json as _json
from src.domain.exceptions import AuthorizationError

def _extract_roles_from_token(token: str) -> list[str]:
    """Decode JWT payload without signature verification (payload is trusted
    — it was just issued by the Identity Manager in this same request)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return []
        # Add padding for base64url decode
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(padded))
        raw = payload.get("roles", [])
        return [str(r) for r in raw] if isinstance(raw, list) else []
    except Exception:
        return []

ADMIN_ROLES = {"admin", "super_admin"}

# In the login endpoint, after token_pair is obtained:
access_token: str = token_pair.get("access_token", "")
roles = _extract_roles_from_token(access_token)

if not ADMIN_ROLES.intersection(roles):
    # Decode sub for audit log (no token value in log)
    try:
        parts = access_token.split(".")
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        sub = _json.loads(base64.urlsafe_b64decode(padded)).get("sub", "unknown")
    except Exception:
        sub = "unknown"
    logger.warning(
        "auth_login_forbidden_role",
        user_id=sub,
        roles=roles,
        # token is intentionally NOT logged
    )
    raise AuthorizationError(
        message=f"User {sub} attempted admin login with roles {roles}",
        user_message="You do not have permission to access the Admin Panel",
        error_code="FORBIDDEN",
    )
```

The `AuthorizationError` is caught by the existing `domain_exception_handler` which
returns HTTP 403. Because the exception is raised before `response.set_cookie` is
called, no cookies are set on a 403 response — the cookie-clearing concern is
automatically satisfied.

Design decision: payload extraction is done inline in the router rather than in
`AuthService.login()` because the role gate is a presentation-layer concern specific
to the admin BFF. The application service's job is to authenticate; the router decides
what to do with the result.

---

## Data Models

### Access Token Payload (after this change)

```
{
  "sub":   "550e8400-e29b-41d4-a716-446655440000",  // user UUID
  "email": "admin@example.com",                      // NEW
  "roles": ["admin"],
  "type":  "access",
  "jti":   "a1b2c3d4-...",                           // UUID4, unique per token
  "iss":   "ugsys-identity-manager",
  "iat":   1700000000,
  "exp":   1700001800
}
```

### Refresh Token Payload (unchanged)

```
{ "sub", "type": "refresh", "jti", "iss", "iat", "exp" }
```

### Password Reset Token Payload (unchanged)

```
{ "sub", "email", "type": "password_reset", "jti", "iss", "iat", "exp" }
```

Note: `email` already appears in password reset tokens for a different purpose
(binding the reset to a specific address). This is intentional and pre-existing.

### Service Token Payload (unchanged)

```
{ "sub": client_id, "roles", "type": "service", "jti", "iss", "iat", "exp" }
```

### AdminUser (frontend entity — unchanged)

```typescript
interface AdminUser {
  userId: string;
  email: string;
  roles: string[];
  displayName: string;
  avatar: string | null;
}
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid
executions of a system — essentially, a formal statement about what the system should
do. Properties serve as the bridge between human-readable specifications and
machine-verifiable correctness guarantees.*

### Property 1: Access token email round-trip

*For any* valid `(user_id: UUID, email: str, roles: list[str])` triple, calling
`create_access_token(user_id, email, roles)` and then `verify_token` on the result
SHALL return a payload where `payload["sub"] == str(user_id)`,
`payload["email"] == email`, and `payload["roles"] == roles`.

**Validates: Requirements 1.1, 1.2, 6.2, 6.3**

### Property 2: Non-access tokens carry no email claim

*For any* valid `user_id`, calling `create_refresh_token(user_id)` or
`create_service_token(client_id, roles)` and decoding the result SHALL produce a
payload where the `"email"` key is absent.

**Validates: Requirements 1.5**

### Property 3: Access token claim set is exact

*For any* valid `(user_id, email, roles)` input, the decoded access token payload
SHALL contain exactly the keys `{"sub", "email", "roles", "type", "jti", "exp",
"iat", "iss"}` — no more, no fewer.

**Validates: Requirements 6.1**

### Property 4: useProtectedRoute redirect encodes the current path

*For any* pathname string, when `useProtectedRoute` is called with
`$isAuthenticated = false` and the current location set to that pathname, the
`navigate` call SHALL target `/login?redirect=<url-encoded-pathname>` with
`replace: true`.

**Validates: Requirements 2.2, 2.5**

### Property 5: AppShell redirects unauthenticated users to /login

*For any* protected path, when `AppShell` renders with `$isAuthenticated = false`
and `$isLoading = false`, it SHALL render a `<Navigate>` to
`/login?redirect=<url-encoded-path>` with `replace: true`, and SHALL NOT render
the sidebar, topbar, or `<Outlet>`.

**Validates: Requirements 3.2, 4.1**

### Property 6: Successful login sets $user

*For any* `AdminUser` value returned by the BFF `/api/v1/auth/me` endpoint, after
`login()` completes successfully, `$user.get()` SHALL equal that `AdminUser` and
`$isAuthenticated` SHALL be `true`.

**Validates: Requirements 3.5**

### Property 7: logout always clears $user

*For any* non-null `$user` value, after `logout()` completes (regardless of whether
the server call succeeds or fails), `$user.get()` SHALL be `null` and
`$isAuthenticated` SHALL be `false`.

**Validates: Requirements 4.4**

### Property 8: BFF admin role gate

*For any* access token whose `roles` claim does not intersect `{admin, super_admin}`,
the BFF login endpoint SHALL return HTTP 403 and SHALL NOT set any auth cookies.
*For any* access token whose `roles` claim contains at least one of `{admin,
super_admin}`, the endpoint SHALL return HTTP 200 and set the `access_token` cookie.

**Validates: Requirements 5.1, 5.2**

---

## Error Handling

### Identity Manager

No new error cases. The `email` parameter is required — callers that omit it will
get a `TypeError` at the Python level (caught by mypy strict before runtime).

### BFF — 403 on insufficient roles

`AuthorizationError` is raised before any cookie is set. The existing
`domain_exception_handler` maps it to:

```json
{ "error": "FORBIDDEN", "message": "You do not have permission to access the Admin Panel" }
```

HTTP 403. No token value, no stack trace, no internal detail in the response body.

### BFF — malformed token payload

If `_extract_roles_from_token` fails to parse the payload (e.g. malformed base64),
it returns `[]`. An empty roles list does not intersect `ADMIN_ROLES`, so the
endpoint returns 403. This is the safe default — a malformed token from the Identity
Manager should never grant access.

### Admin Shell — login failure display

`login()` in `authStore` catches all errors and stores a user-safe message in
`$error`. `LoginPage` renders `$error` in the `role="alert"` paragraph. The
`HttpAuthRepository` maps HTTP 403 from the BFF to:
`new Error("You do not have permission to access the Admin Panel")`.
No token values or internal codes reach the UI.

### Admin Shell — 401 on authenticated requests

`HttpClient` already handles 401 responses by calling `logout()` (which clears
`$user`). Once `$user` is null, `AppShell` renders the `<Navigate>` redirect to
`/login`. No additional handling is needed.

---

## Testing Strategy

### Dual approach

Unit tests cover specific examples, edge cases, and call-contract assertions.
Property-based tests (Hypothesis for Python, fast-check for TypeScript) verify
universal properties across randomized inputs. Both are required.

### Identity Manager — Python (pytest + Hypothesis)

**Unit tests** (extend `tests/unit/test_jwt_token_service.py`):
- `test_create_access_token_includes_email_claim` — specific example
- `test_create_access_token_email_is_unchanged` — specific example
- `test_refresh_token_has_no_email_claim` — edge case
- `test_service_token_has_no_email_claim` — edge case

**Unit tests** (extend `tests/unit/test_authenticate_user.py`):
- `test_authenticate_passes_email_to_create_access_token` — asserts mock called with `email=`
- `test_refresh_passes_email_to_create_access_token` — asserts mock called with `email=`

**Property tests** (new file `tests/unit/test_jwt_token_service_properties.py`):
- Property 1: access token email round-trip (Hypothesis `@given`)
- Property 2: non-access tokens carry no email claim
- Property 3: access token claim set is exact

Hypothesis configuration: `@settings(max_examples=200)` for all property tests.
Tag format in comments: `# Feature: auth-gap-closure, Property N: <text>`

### Admin Panel BFF — Python (pytest)

**Unit tests** (new file `tests/unit/test_bff_login_role_gate.py`):
- `test_login_returns_403_when_no_admin_role` — roles=["member"]
- `test_login_returns_403_when_roles_empty` — roles=[]
- `test_login_returns_200_when_admin_role` — roles=["admin"]
- `test_login_returns_200_when_super_admin_role` — roles=["super_admin"]
- `test_login_does_not_log_token_on_403` — capture log output, assert token absent

**Property tests** (same file, using Hypothesis):
- Property 8: BFF admin role gate — generate random role lists, assert 403 iff no admin role

### Admin Shell — TypeScript (vitest + fast-check)

fast-check is already installed (`admin-shell/node_modules/fast-check`).

**Unit tests** (new file `src/stores/__tests__/authStore.test.ts`):
- `login sets $user on success` — example
- `login sets $error on failure` — example
- `logout clears $user regardless of server error` — example
- `initializeAuth sets $isLoading to false after completion` — example

**Property tests** (same file):
- Property 6: successful login sets $user — `fc.record({userId, email, roles})`
- Property 7: logout always clears $user — `fc.anything()` as initial $user value

**Unit tests** (new file `src/presentation/components/__tests__/AppShell.test.tsx`):
- `shows loading indicator when $isLoading is true` — example (Req 4.2)
- `redirects to /login when unauthenticated` — example
- `renders outlet when authenticated` — example

**Property tests** (same file):
- Property 5: AppShell redirects unauthenticated users — `fc.webPath()` as pathname

**Unit tests** (new file `src/hooks/__tests__/useProtectedRoute.test.ts`):
- `allows render when authenticated` — example (Req 2.3)
- `redirects with replace:true when unauthenticated` — example (Req 2.5)

**Property tests** (same file):
- Property 4: useProtectedRoute encodes current path — `fc.webPath()` as pathname

Property test configuration: `{ numRuns: 200 }` for all fast-check properties.
Tag format in comments: `// Feature: auth-gap-closure, Property N: <text>`
