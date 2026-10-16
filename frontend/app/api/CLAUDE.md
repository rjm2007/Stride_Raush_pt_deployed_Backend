# app/api — server routes

These run on the server (the `dashboard` container). They are the only code that sees secrets.

| Route | Purpose |
| --- | --- |
| `auth/login/route.ts` | `POST` employee ID + password → verifies against `DASHBOARD_USERS_JSON`, sets the HttpOnly signed `rpt_staff_session` cookie (12 h). |
| `auth/logout/route.ts` | Clears the session cookie. |
| `dashboard/[[...path]]/route.ts` | Proxy to the backend `/api/v1/dashboard/*`. Requires a valid session, checks the path against `ALLOWED_PATH` and the method, then adds `X-Dashboard-Token`, `X-Dashboard-User-ID`, `X-Dashboard-User-Name` (URL-encoded), `X-Dashboard-User-Role` and `X-Trace-ID`. Size limits: 20 KB (64 KB for the assistant); timeouts 20 s (90 s for the assistant). Streams the response back. |

## Rules

- `ALLOWED_PATH` lists every backend path the browser may reach. There is no bare `leads` (create) path and
  no appointment, calendar or Keap path in this build.
- When the backend adds or renames a dashboard endpoint, update `ALLOWED_PATH` (and the per-path method
  checks) here or the browser gets "dashboard path not allowed".
- Never log request bodies, upstream URLs or patient data; errors are returned as generic messages.
- The identity headers must match `require_dashboard_auth` in the backend's `security.py`.
