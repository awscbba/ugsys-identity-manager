# Requirements Document

## Introduction

This feature closes four authentication gaps across the ugsys platform that prevent end-to-end
login from working correctly in both the Projects Registry frontend and the Admin Panel frontend.

The gaps are:

1. **Email claim missing from access tokens** — `create_access_token` in the Identity Manager
   omits the `email` claim. The Projects Registry frontend's `extractUser()` reads `email` from
   the JWT payload; without it `$user.email` is always `null` after login.

2. **Projects Registry dashboard auth guard not verified** — `useProtectedRoute` exists and is
   called in `DashboardPage`, but the redirect behaviour under the in-memory token model (tokens
   lost on page reload) has not been confirmed end-to-end.

3. **Admin Panel has no login route** — `App.tsx` wraps every route inside `AppShell`, which
   already renders `LoginPage` when `$isAuthenticated` is false. However, there is no dedicated
   `/login` URL, so deep-links and browser-back after logout land on a blank shell rather than
   the login form. The `LoginPage` component exists but is not reachable via a URL.

4. **Admin Panel shell has no explicit unauthenticated redirect** — `AppShell` renders
   `LoginPage` inline when `!isAuthenticated`, but the URL stays at the protected path. A
   proper redirect to `/login` (preserving the intended destination) is needed so the browser
   history is correct and the `/login` route is the canonical entry point.

Affected repos: `ugsys-identity-manager`, `ugsys-projects-registry`, `ugsys-admin-panel`.

---

## Glossary

- **Identity_Manager**: The `ugsys-identity-manager` FastAPI service that issues and validates
  RS256 JWTs.
- **JWT_Token_Service**: The `JWTTokenService` class in
  `src/infrastructure/adapters/jwt_token_service.py` that signs and verifies tokens.
- **Auth_Service**: The `AuthService` application service in
  `src/application/services/auth_service.py` that orchestrates authentication use cases.
- **Access_Token**: A short-lived RS256 JWT (30 min TTL) issued by the Identity_Manager,
  carrying `sub`, `roles`, `type`, `email`, `iss`, `iat`, `exp`, and `jti` claims.
- **Registry_Frontend**: The React SPA in `ugsys-projects-registry/web/` that serves the
  community-facing portal at `registry.apps.cloud.org.bo`.
- **Auth_Store**: The nanostores module (`src/stores/authStore.ts`) in the Registry_Frontend
  that holds the in-memory access token and the derived `$user` atom.
- **extractUser**: The function inside `Auth_Store` that decodes the JWT payload and maps
  claims to an `AuthUser` object.
- **useProtectedRoute**: The React hook in `src/hooks/useProtectedRoute.ts` that redirects
  unauthenticated users to `/login`.
- **Admin_Shell**: The React SPA in `ugsys-admin-panel/admin-shell/` that serves the admin
  panel at `admin.apps.cloud.org.bo`.
- **AppShell**: The `AppShell` React component that provides the authenticated layout
  (sidebar + topbar + Outlet) and currently renders `LoginPage` inline when unauthenticated.
- **Admin_Auth_Store**: The nanostores module (`src/stores/authStore.ts`) in the Admin_Shell
  that holds the `$user` atom and exposes `login`, `logout`, and `initializeAuth` actions.
- **BFF**: The `ugsys-admin-panel` FastAPI backend-for-frontend that validates the `access_token`
  httpOnly cookie and proxies requests to downstream services.
- **BFF_Login_Endpoint**: `POST /api/v1/auth/login` on the BFF, which forwards credentials to
  the Identity_Manager and sets the `access_token` httpOnly cookie on success.
- **LoginPage**: The `LoginPage` React component in
  `admin-shell/src/presentation/components/views/LoginPage.tsx` that renders the login form
  and calls `login()` from Admin_Auth_Store.

---

## Requirements

### Requirement 1: Email Claim in Access Tokens

**User Story:** As a Registry_Frontend user, I want my email address to be available after
login, so that the dashboard can display my profile and personalised content correctly.

#### Acceptance Criteria

1. THE JWT_Token_Service SHALL include the `email` claim in every Access_Token it creates via
   `create_access_token`.

2. WHEN `create_access_token` is called with a `user_id` and `roles`, THE JWT_Token_Service
   SHALL also accept an `email` parameter and embed it in the token payload alongside `sub`
   and `roles`.

3. WHEN the Auth_Service calls `create_access_token` during the `authenticate` use case, THE
   Auth_Service SHALL pass the authenticated user's email address to `create_access_token`.

4. WHEN the Auth_Service calls `create_access_token` during the `refresh` use case, THE
   Auth_Service SHALL pass the user's email address to `create_access_token`.

5. THE JWT_Token_Service SHALL NOT include the `email` claim in `create_refresh_token`,
   `create_password_reset_token`, or `create_service_token` payloads (those token types have
   their own purpose-specific claim sets).

6. WHEN `extractUser` in the Auth_Store decodes an Access_Token, THE Auth_Store SHALL
   populate `AuthUser.email` from the `email` claim in the token payload.

7. WHEN an Access_Token is decoded and the `email` claim is present, THE Auth_Store SHALL
   return an `AuthUser` with a non-null `email` field.

---

### Requirement 2: Projects Registry Dashboard Auth Guard

**User Story:** As an unauthenticated visitor, I want to be redirected to the login page when
I try to access the dashboard, so that protected content is not exposed without authentication.

#### Acceptance Criteria

1. WHEN an unauthenticated user navigates to `/dashboard`, THE Registry_Frontend SHALL
   redirect the user to `/login?redirect=%2Fdashboard` before rendering any dashboard content.

2. WHEN `useProtectedRoute` is called and `$isAuthenticated` is `false`, THE
   useProtectedRoute hook SHALL trigger a navigation to `/login` with the current pathname
   encoded as the `redirect` query parameter.

3. WHEN `useProtectedRoute` is called and `$isAuthenticated` is `true`, THE
   useProtectedRoute hook SHALL allow the component to render without redirecting.

4. WHEN a user's in-memory session is lost (e.g. page reload), THE Registry_Frontend SHALL
   treat the user as unauthenticated and apply the redirect in criterion 1.

5. IF `useProtectedRoute` triggers a redirect, THEN THE Registry_Frontend SHALL use
   `replace: true` so the protected path is not added to the browser history stack.

---

### Requirement 3: Admin Panel Login Route

**User Story:** As an admin user, I want a dedicated `/login` URL in the Admin Panel, so that
I can bookmark the login page, be redirected there after session expiry, and use the browser
back button correctly after logging out.

#### Acceptance Criteria

1. THE Admin_Shell SHALL expose a `/login` route that renders the LoginPage component.

2. WHEN an unauthenticated user navigates to any protected route (any path other than
   `/login`), THE AppShell SHALL redirect the user to `/login` with the intended path encoded
   as a `redirect` query parameter (e.g. `/login?redirect=%2Fdashboard`).

3. WHEN an authenticated user navigates to `/login`, THE Admin_Shell SHALL redirect the user
   to `/dashboard` (or to the `redirect` query parameter value if present).

4. WHEN the LoginPage is rendered at `/login` and the user submits valid credentials, THE
   LoginPage SHALL call `login()` from Admin_Auth_Store and, on success, navigate to the
   `redirect` query parameter destination or `/dashboard` if no redirect is specified.

5. WHEN `login()` in Admin_Auth_Store succeeds, THE Admin_Auth_Store SHALL set `$user` to
   the authenticated AdminUser returned by the BFF.

6. WHEN `login()` in Admin_Auth_Store fails, THE Admin_Auth_Store SHALL set `$error` to a
   user-safe error message and SHALL NOT expose token values, stack traces, or internal
   service details in the error message.

7. THE `/login` route SHALL be accessible without authentication (it MUST NOT be wrapped
   inside AppShell's authenticated layout).

---

### Requirement 4: Admin Panel Shell Unauthenticated Redirect

**User Story:** As an admin user, I want the Admin Panel to redirect me to the login page
when my session is absent or has expired, so that I always land on the correct URL and can
log back in without confusion.

#### Acceptance Criteria

1. WHEN `AppShell` renders and `$isAuthenticated` is `false` after `initializeAuth` has
   completed, THE AppShell SHALL redirect to `/login` (with the current path as the
   `redirect` query parameter) instead of rendering `LoginPage` inline.

2. WHEN `AppShell` renders and `$isLoading` is `true` (session check in progress), THE
   AppShell SHALL display a loading indicator and SHALL NOT redirect or render protected
   content.

3. WHEN `initializeAuth` completes and `$user` is `null`, THE Admin_Auth_Store SHALL set
   `$isLoading` to `false` so the AppShell can evaluate the unauthenticated state.

4. WHEN `logout()` is called in Admin_Auth_Store, THE Admin_Auth_Store SHALL set `$user` to
   `null` and THE Admin_Shell SHALL redirect to `/login`.

5. WHEN the BFF returns HTTP 401 on any authenticated request, THE Admin_Shell HTTP client
   SHALL clear the `$user` atom and redirect to `/login`.

---

### Requirement 5: BFF Login Endpoint Accepts Admin Roles Only

**User Story:** As a platform operator, I want the Admin Panel login to reject non-admin
users at the BFF layer, so that community members who have valid Identity Manager credentials
cannot access the admin interface.

#### Acceptance Criteria

1. WHEN the BFF_Login_Endpoint receives valid credentials and the Identity_Manager returns an
   Access_Token, THE BFF SHALL decode the token and verify that the `roles` claim contains at
   least one value from the set `{admin, super_admin}`.

2. IF the `roles` claim in the Access_Token does not contain an admin role, THEN THE BFF
   SHALL return HTTP 403 with error code `FORBIDDEN` and SHALL clear any cookies that were
   set during the request.

3. WHEN the BFF_Login_Endpoint returns HTTP 403 due to insufficient roles, THE BFF SHALL log
   the `user_id` and the actual roles for audit purposes and SHALL NOT include the token
   value in the log entry.

4. WHEN the BFF_Login_Endpoint returns HTTP 403, THE LoginPage SHALL display a user-safe
   message such as "You do not have permission to access the Admin Panel" and SHALL NOT
   expose the internal error code or token details.

---

### Requirement 6: Token Payload Round-Trip Integrity

**User Story:** As a platform engineer, I want the token payload to be verifiable end-to-end,
so that any future change to the claim set is caught by automated tests before reaching
production.

#### Acceptance Criteria

1. THE JWT_Token_Service SHALL produce Access_Tokens whose decoded payload contains exactly
   the claims: `sub`, `email`, `roles`, `type`, `jti`, `exp`, `iat`, `iss`.

2. FOR ALL valid `(user_id, email, roles)` inputs, encoding an Access_Token and then decoding
   it with `verify_token` SHALL return a payload where `sub` equals `str(user_id)`, `email`
   equals the input email, and `roles` equals the input roles list (round-trip property).

3. WHEN `verify_token` is called with an Access_Token that contains an `email` claim, THE
   JWT_Token_Service SHALL return the `email` value unchanged in the decoded payload.

4. THE Auth_Service unit tests SHALL assert that `create_access_token` is called with the
   `email` argument during both the `authenticate` and `refresh` use cases.
