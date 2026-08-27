# Sonalim ERP — Web

React + TypeScript SPA for the CRM module (Leads today; Accounts, Contacts, and Opportunities land as the backend ships them — see the CRM architecture spec).

## Stack

- Vite + React + TypeScript
- TanStack Query for server state (no client-state library yet — add one only if a real cross-page need shows up)
- React Router (data router API)
- Tailwind CSS + hand-written Radix-based primitives in `src/components/ui/` (no shadcn CLI — Node wasn't available when this was scaffolded, so the components are written directly in that style)
- React Hook Form + Zod for the one form that needs real validation (New Lead); the login form uses plain state since two required fields don't need it

## Run it

Via Docker (no local Node needed):

```powershell
docker compose up web
```

Or locally, if you have Node 20+:

```powershell
cd frontend
npm install
npm run dev
```

Either way it talks to the API at `VITE_API_BASE_URL` (defaults to `http://localhost:8000`, see `.env.example`).

## Known gaps

Resolved:

- **`GET /crm/leads` now exists** (`LeadService.list_leads`, same tenant-scoped pattern as every other query). The Leads table is a real `useQuery` against it, not client-only state.
- **401s force a logout.** `apiFetch` dispatches a `window` `"auth:unauthorized"` event on any 401; `AuthProvider` listens and clears the session, which sends `ProtectedRoute` back to `/login`. No per-call-site handling needed.
- **Access tokens are short-lived (30 min) and silently renewed.** `AuthProvider` schedules a call to `POST /core/auth/refresh` just before the access token expires, trading it for a new one via the longer-lived (7 day) refresh token — an active user never sees a logout. A stolen access token is only useful for the 30-minute window.
- **Refresh tokens rotate on every use, with reuse detection.** Each refresh call revokes the refresh token it was given and issues a new one (`core/auth.py`). If a already-revoked refresh token is ever presented again — the signature of a stolen copy being replayed — the backend kills every session and refresh token that user has and forces a real re-login.
- **Sign-out revokes both tokens server-side.** `logout()` calls `POST /core/auth/logout` with the refresh token, which deletes the `core.sessions` row and marks the refresh token revoked — a signed-out (or force-logged-out) credential stops working immediately, not at natural expiry.
- **Passwords are bcrypt-hashed**, not single-round SHA-256 (`core/auth.py`) — backend-only, but closes the most severe finding from the security pass.
- **Login is rate-limited.** `core/auth.py` tracks failed attempts per email in Redis (already a stack dependency, previously unused) and locks out after 5 failures for 15 minutes.
- **Permissions are enforced.** `core.user_permissions` + `core.tenancy.require_permission(code)` check that the session's user was actually granted a permission, not just that they're logged in. CRM's router uses it (`crm.view_leads`, `crm.manage_leads`); other modules' routers still only call `require_session` and need the same one-line swap.

Still open — deliberate, not oversights:

- **Access token still lives in `sessionStorage`.** Safer than `localStorage` (cleared on tab close), but still readable by any injected script. Rotation, short expiry, and revocation now sharply limit what a stolen token is worth, but they don't remove the exposure itself. The alternative — an httpOnly cookie issued by the backend, with CORS/CSRF implications — was evaluated and deliberately deferred in favor of hardening the bearer-token model instead.
- **Only CRM's router enforces permissions.** Sales, finance, warehouse, and production routers still only depend on `require_session` — same gap, not yet closed for those modules.
- **No signup flow.** Users are still only created via `seed_dev.py`; the new admin UI manages permissions for existing users, not user creation itself.

Resolved (admin UI/API for permissions):

- **`core/users.py`** adds `GET /core/users` (tenant-scoped, with each user's current grants), `GET /core/permissions/catalog` (aggregated from every module's `module.json` — no second copy of the permission list to keep in sync), `POST /core/users/{id}/permissions`, and `DELETE /core/users/{id}/permissions/{permission}`. All four require `core.manage_permissions` via the same `require_permission()` used elsewhere — permissions administration is itself just another permission, not a separate role system.
- Granting validates the permission string against the catalog (typos become a 422, not a silent no-op grant); revoking and granting both verify the target user belongs to the caller's tenant; and an admin can't revoke their own `core.manage_permissions` and lock themselves out.
- **`/admin/users`** in the frontend — a table of users, their permission chips (click × to revoke), and a per-row grant control. `seed_dev.py` now grants the demo user `core.manage_permissions` so this is reachable immediately after seeding.

## Layout

```
src/
├── lib/          fetch wrapper, auth context, query client
├── components/ui/ shared primitives (Button, Input, Dialog, Table, ...)
├── routes/        router config, layout shell, login
└── features/
    └── crm/
        └── leads/  the only implemented feature — mirrors modules/crm on the backend
```

New modules get a new `features/<module>/` folder, not new top-level concepts — same boundary the backend draws at `modules/`.
