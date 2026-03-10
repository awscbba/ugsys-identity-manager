# Implementation Plan: auth-gap-closure

## Overview

Closes four authentication gaps across three repos. Changes are surgical — every file
touched already exists. No new services, no new infrastructure, no new dependencies.

Branch `feature/auth-gap-closure-email-claim` → identity-manager changes (tasks 1–8).
Branch `feature/auth-gap-closure-admin-login` → admin-panel BFF + admin-shell changes (tasks 9–17).

---

## Tasks

- [x] 1. Update TokenService ABC — add `email` param to `create_access_token`
  - Add required `email: str` parameter to the `create_access_token` abstract method signature
  - No other methods change (`create_refresh_token`, `create_password_reset_token`, `create_service_token` are untouched)
  - _Requirements: 1.1, 1.2_

- [x] 2. Update JWTTokenService — embed email claim in access token payload
  - [x] 2.1 Update `create_access_token` implementation to accept and embed `email`
    - Change signature: `create_access_token(self, user_id: UUID, email: str, roles: list[str]) -> str`
    - Update payload dict: `{"sub": str(user_id), "email": email, "roles": roles, "type": "access"}`
    - The `_encode` helper already appends `jti`, `exp`, `iat`, `iss` — no change needed there
    - _Requirements: 1.1, 1.2, 6.1_

  - [ ]* 2.2 Write unit tests for `JWTTokenService` email claim
    - Extend `tests/unit/test_jwt_token_service.py`
    - `test_create_access_token_includes_email_claim` — decode payload, assert `"email"` key present with correct value
    - `test_create_access_token_email_is_unchanged` — assert round-trip preserves email exactly
    - `test_refresh_token_has_no_email_claim` — assert `"email"` absent from refresh token payload
    - `test_service_token_has_no_email_claim` — assert `"email"` absent from service token payload
    - _Requirements: 1.1, 1.5, 6.3_

- [x] 3. Update AuthService — pass `user.email` to `create_access_token`
  - [x] 3.1 Update `authenticate` use case call site
    - Add `email=user.email` kwarg to the `create_access_token` call in `AuthService.authenticate`
    - `user.email` is already available at this point — no extra repository lookup needed
    - _Requirements: 1.3_

  - [x] 3.2 Update `refresh` use case call site
    - Add `email=user.email` kwarg to the `create_access_token` call in `AuthService.refresh`
    - _Requirements: 1.4_

  - [ ]* 3.3 Update unit tests for `AuthService.authenticate`
    - Extend `tests/unit/test_authenticate_user.py`
    - `test_authenticate_passes_email_to_create_access_token` — assert mock `create_access_token` called with `email=<expected>`
    - _Requirements: 6.4_

  - [ ]* 3.4 Update unit tests for `AuthService.refresh`
    - Extend `tests/unit/test_refresh_token.py`
    - `test_refresh_passes_email_to_create_access_token` — assert mock `create_access_token` called with `email=<expected>`
    - _Requirements: 6.4_

- [ ] 4. Write property-based tests for token round-trip (Hypothesis)
  - [ ]* 4.1 Write Property 1 — access token email round-trip
    - New file: `tests/unit/test_jwt_token_service_properties.py`
    - `@given(user_id=st.uuids(), email=st.emails(), roles=st.lists(st.text()))`
    - Assert `payload["sub"] == str(user_id)`, `payload["email"] == email`, `payload["roles"] == roles`
    - `@settings(max_examples=200)`
    - Comment: `# Feature: auth-gap-closure, Property 1: access token email round-trip`
    - **Property 1: Access token email round-trip**
    - **Validates: Requirements 1.1, 1.2, 6.2, 6.3**

  - [ ]* 4.2 Write Property 2 — non-access tokens carry no email claim
    - Same file: `tests/unit/test_jwt_token_service_properties.py`
    - `@given(user_id=st.uuids())` — call `create_refresh_token` and `create_service_token`, decode, assert `"email"` absent
    - `@settings(max_examples=200)`
    - Comment: `# Feature: auth-gap-closure, Property 2: non-access tokens carry no email claim`
    - **Property 2: Non-access tokens carry no email claim**
    - **Validates: Requirements 1.5**

  - [ ]* 4.3 Write Property 3 — access token claim set is exact
    - Same file: `tests/unit/test_jwt_token_service_properties.py`
    - `@given(user_id=st.uuids(), email=st.emails(), roles=st.lists(st.text()))`
    - Assert `set(payload.keys()) == {"sub", "email", "roles", "type", "jti", "exp", "iat", "iss"}`
    - `@settings(max_examples=200)`
    - Comment: `# Feature: auth-gap-closure, Property 3: access token claim set is exact`
    - **Property 3: Access token claim set is exact**
    - **Validates: Requirements 6.1**

- [x] 5. Checkpoint — identity-manager branch
  - Ensure all tests pass, ask the user if questions arise.
  - Run `uv run pytest tests/unit/ -v` inside `ugsys/ugsys-identity-manager`
  - Run `uv run mypy src/ --strict` to confirm no type errors from the signature change

- [x] 6. Add admin role gate to BFF login endpoint
  - [x] 6.1 Implement `_extract_roles_from_token` helper and role gate in `src/presentation/api/v1/auth.py`
    - Add `_extract_roles_from_token(token: str) -> list[str]` — base64url-decode the JWT payload segment, return `roles` list; return `[]` on any parse error (safe default)
    - After `token_pair` is obtained from `auth_service.login()`, extract roles and check intersection with `{"admin", "super_admin"}`
    - If no admin role: decode `sub` for audit log, call `logger.warning("auth_login_forbidden_role", user_id=sub, roles=roles)` (token value MUST NOT appear in log), raise `AuthorizationError` with `user_message="You do not have permission to access the Admin Panel"`
    - Exception is raised BEFORE `response.set_cookie` — no cookies set on 403
    - `AuthorizationError` is caught by the existing `domain_exception_handler` → HTTP 403
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ]* 6.2 Write unit tests for BFF login role gate
    - New file: `tests/unit/test_bff_login_role_gate.py`
    - `test_login_returns_403_when_no_admin_role` — roles=["member"]
    - `test_login_returns_403_when_roles_empty` — roles=[]
    - `test_login_returns_200_when_admin_role` — roles=["admin"]
    - `test_login_returns_200_when_super_admin_role` — roles=["super_admin"]
    - `test_login_does_not_log_token_on_403` — capture structlog output, assert token string absent from all log entries
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 6.3 Write Property 8 — BFF admin role gate (Hypothesis)
    - Same file: `tests/unit/test_bff_login_role_gate.py`
    - `@given(roles=st.lists(st.text()))` — assert 403 iff `set(roles).isdisjoint({"admin", "super_admin"})`
    - `@settings(max_examples=200)`
    - Comment: `# Feature: auth-gap-closure, Property 8: BFF admin role gate`
    - **Property 8: BFF admin role gate**
    - **Validates: Requirements 5.1, 5.2**

- [x] 7. Add `/login` route outside AppShell in `App.tsx`
  - File: `admin-shell/src/App.tsx`
  - Add `LoginRoute` inline component: reads `$isAuthenticated` via `useStore`; if authenticated, `<Navigate to={redirect ?? "/dashboard"} replace />`; else `<LoginPage />`
  - Add `<Route path="login" element={<LoginRoute />} />` OUTSIDE the `<Route element={<AppShell />}>` wrapper
  - Import `useSearchParams`, `Navigate` from `react-router-dom`; import `LoginPage`; import `$isAuthenticated` from authStore
  - _Requirements: 3.1, 3.3, 3.7_

- [x] 8. Replace inline LoginPage render in AppShell with Navigate redirect
  - File: `admin-shell/src/presentation/components/layout/AppShell.tsx`
  - Import `useLocation`, `Navigate` from `react-router-dom`; remove `LoginPage` import
  - Replace `return <LoginPage />` with:
    ```tsx
    const redirect = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?redirect=${redirect}`} replace />;
    ```
  - _Requirements: 3.2, 4.1_

- [x] 9. Update LoginPage to navigate after successful login and display auth errors
  - File: `admin-shell/src/presentation/components/views/LoginPage.tsx`
  - Import `useNavigate`, `useSearchParams` from `react-router-dom`; import `$error` from authStore
  - After `await login(email, password)`, check `$user.get() !== null`; if so, `navigate(redirect ?? "/dashboard", { replace: true })`
  - Render `$error` (via `useStore`) in the existing `role="alert"` paragraph — covers 403 "You do not have permission" message
  - _Requirements: 3.4, 5.4_

- [ ] 10. Write vitest unit + property tests for authStore
  - [ ]* 10.1 Write unit tests for authStore
    - New file: `admin-shell/src/stores/__tests__/authStore.test.ts`
    - `login sets $user on success` — mock BFF returning AdminUser, assert `$user.get()` equals it
    - `login sets $error on failure` — mock BFF returning 403, assert `$error.get()` is non-null and does not contain token value
    - `logout clears $user regardless of server error` — mock server error on logout call, assert `$user.get() === null`
    - `initializeAuth sets $isLoading to false after completion` — assert `$isLoading.get() === false` after promise resolves
    - _Requirements: 3.5, 3.6, 4.3, 4.4_

  - [ ]* 10.2 Write Property 6 — successful login sets $user (fast-check)
    - Same file: `admin-shell/src/stores/__tests__/authStore.test.ts`
    - `fc.record({ userId: fc.uuid(), email: fc.emailAddress(), roles: fc.array(fc.string()) })`
    - Assert `$user.get()` equals the returned AdminUser and `$isAuthenticated` is `true`
    - `{ numRuns: 200 }`
    - Comment: `// Feature: auth-gap-closure, Property 6: successful login sets $user`
    - **Property 6: Successful login sets $user**
    - **Validates: Requirements 3.5**

  - [ ]* 10.3 Write Property 7 — logout always clears $user (fast-check)
    - Same file: `admin-shell/src/stores/__tests__/authStore.test.ts`
    - `fc.anything()` as initial `$user` value; call `logout()`; assert `$user.get() === null` and `$isAuthenticated === false`
    - `{ numRuns: 200 }`
    - Comment: `// Feature: auth-gap-closure, Property 7: logout always clears $user`
    - **Property 7: logout always clears $user**
    - **Validates: Requirements 4.4**

- [ ] 11. Write vitest unit + property tests for AppShell
  - [ ]* 11.1 Write unit tests for AppShell
    - New file: `admin-shell/src/presentation/components/__tests__/AppShell.test.tsx`
    - `shows loading indicator when $isLoading is true` — assert loading element rendered, no Navigate
    - `redirects to /login when unauthenticated` — `$isAuthenticated=false`, `$isLoading=false`; assert `<Navigate>` to `/login?redirect=...`
    - `renders outlet when authenticated` — `$isAuthenticated=true`; assert `<Outlet>` rendered
    - _Requirements: 3.2, 4.1, 4.2_

  - [ ]* 11.2 Write Property 5 — AppShell redirects unauthenticated users (fast-check)
    - Same file: `admin-shell/src/presentation/components/__tests__/AppShell.test.tsx`
    - `fc.webPath()` as current pathname; render AppShell with `$isAuthenticated=false`, `$isLoading=false`
    - Assert rendered `<Navigate to>` equals `/login?redirect=<url-encoded-pathname>` with `replace=true`
    - Assert sidebar, topbar, and Outlet are NOT rendered
    - `{ numRuns: 200 }`
    - Comment: `// Feature: auth-gap-closure, Property 5: AppShell redirects unauthenticated users`
    - **Property 5: AppShell redirects unauthenticated users to /login**
    - **Validates: Requirements 3.2, 4.1**

- [ ] 12. Write vitest unit + property tests for useProtectedRoute
  - [ ]* 12.1 Write unit tests for useProtectedRoute
    - New file: `admin-shell/src/hooks/__tests__/useProtectedRoute.test.ts`
    - `allows render when authenticated` — `$isAuthenticated=true`; assert no navigation triggered
    - `redirects with replace:true when unauthenticated` — `$isAuthenticated=false`; assert `navigate` called with `replace: true`
    - _Requirements: 2.3, 2.5_

  - [ ]* 12.2 Write Property 4 — useProtectedRoute encodes current path (fast-check)
    - Same file: `admin-shell/src/hooks/__tests__/useProtectedRoute.test.ts`
    - `fc.webPath()` as pathname; call hook with `$isAuthenticated=false`
    - Assert `navigate` called with `/login?redirect=<url-encoded-pathname>` and `{ replace: true }`
    - `{ numRuns: 200 }`
    - Comment: `// Feature: auth-gap-closure, Property 4: useProtectedRoute encodes current path`
    - **Property 4: useProtectedRoute redirect encodes the current path**
    - **Validates: Requirements 2.2, 2.5**

- [x] 13. Final checkpoint — admin-panel branch
  - Ensure all tests pass, ask the user if questions arise.
  - Run `uv run pytest tests/unit/ -v` inside `ugsys/ugsys-admin-panel` (BFF tests)
  - Run `npx vitest run` inside `ugsys/ugsys-admin-panel/admin-shell` (frontend tests)
  - Run `uv run mypy src/ --strict` on BFF to confirm no type errors

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Tasks 1–5 belong to branch `feature/auth-gap-closure-email-claim` (identity-manager)
- Tasks 6–13 belong to branch `feature/auth-gap-closure-admin-login` (admin-panel BFF + admin-shell)
- Property tests use `@settings(max_examples=200)` (Hypothesis) and `{ numRuns: 200 }` (fast-check)
- Each property test comment must include `# Feature: auth-gap-closure, Property N: <text>`
- The BFF role gate MUST raise `AuthorizationError` before any `response.set_cookie` call
- Token values must never appear in log entries — only `user_id` and `roles`
