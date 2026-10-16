@AGENTS.md

# RPT staff dashboard (frontend, production)

Next.js 16 / React 19 / TypeScript staff dashboard for the Rausch PT outreach cadence, **production build**
(cadence only). It holds no patient data and no provider credentials: every data call goes through a
same-origin proxy to the backend (`../backend`, `/api/v1/dashboard/*`).

Cut down from the demo dashboard (`../../demo/rpt_frontend`, commit e1ce214): no Appointments page or
calendar, no booking card, no Keap panel, no Add lead (leads come only from the Google Sheet), no
Vinext/Cloudflare build. A Booked lead shows only "Booked (marked by staff)": there is no appointment record.

Runs as the `dashboard` container on the production server (`../docker-compose.yml`, `Dockerfile`,
`output: 'standalone'`), behind Caddy on `https://stride.aibolt.ai`. It reaches the backend inside Docker at
`http://api:8000`.

## Folder map

| Path | Contents | Has CLAUDE.md |
| --- | --- | --- |
| `app/` | All pages, UI, client helpers, unit tests | yes |
| `app/api/` | Server routes: login, logout, dashboard proxy | yes |
| `public/` | `favicon.svg`, `rausch-logo.webp` | |
| `Dockerfile`, `next.config.ts` | Production image (standalone Next server) | |

## Commands

```bash
npm ci
npm run dev        # next dev; needs a running backend and the env vars below
npm run lint
npm run typecheck
npm test           # all unit tests (node --test)
npm run build      # what the Docker image builds
```

## Environment (server-only; never prefix with NEXT_PUBLIC_)

On the server they live in `../dashboard.env` (template `../dashboard.env.example`), except
`DASHBOARD_API_ORIGIN`, which `docker-compose.yml` sets.

| Variable | Purpose |
| --- | --- |
| `DASHBOARD_API_ORIGIN` | Backend base URL: `http://api:8000` inside Docker. Elsewhere it must be HTTPS (a single-label host like `api` or `localhost` is the only exception). |
| `DASHBOARD_API_TOKEN` | Shared server-to-server token; must equal the backend's `DASHBOARD_API_TOKEN` |
| `DASHBOARD_USERS_JSON` | Staff roster: id, display name, password (≥12 chars), role; exactly one `super_admin` |
| `DASHBOARD_SESSION_SECRET` | ≥32 chars; signs the 12-hour `rpt_staff_session` cookie |

## Rules

- Backend and frontend share a contract (identity headers, response shapes in `app/dashboard-data.ts`,
  allowed proxy paths). Change both sides together and deploy them together.
- A new backend dashboard endpoint must be added to `ALLOWED_PATH` in
  `app/api/dashboard/[[...path]]/route.ts`.
- Roles are enforced by the backend; the UI only hides controls. Never rely on the UI for permissions.
