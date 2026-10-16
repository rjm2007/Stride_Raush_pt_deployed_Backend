# app — pages, UI and client helpers

The dashboard is effectively a single-page app: `page.tsx` (`/`) and the catch-all `[...route]/page.tsx`
both check the session server-side, redirect to `/login` if missing, then render `DashboardShell`, which
picks the page from the URL on the client.

| File | Purpose |
| --- | --- |
| `dashboard-shell.tsx` (~1250 lines) | The whole UI. `DashboardShell` (layout, nav, data loading via `/api/dashboard/snapshot`, actions) and every page component: Home, Leads (list + Kanban board with drag-and-drop stage moves), Review queue, Analytics, Administration (cadence studio, SMS templates), and the lead workspace (overview, SMS, calls, cadence runs with reschedule, activity). |
| `dashboard-data.ts` | TypeScript types for backend responses (`Lead`, `LeadDetail`, `Snapshot`, `CadenceVersion`, `ActivityEntry`, …) and `emptySnapshot`. Keep in sync with `routes/dashboard.py` in the backend. |
| `dashboard-client.ts` | `dashboardFetch()` wrapper for calls to the proxy (handles session expiry). |
| `display.ts` | Formatting: clinic timezone (America/Los_Angeles), enum labels, status tones, activity descriptions, operational error messages. |
| `cadence.ts` | Cadence helpers: split events into runs, step names, run summaries, call naming, step reordering. |
| `assistant.tsx` | Staff assistant UI (dock + full page), up to 3 leads per chat, streaming answers; chats kept in browser `localStorage`. |
| `dashboard-origin.ts` | Server-only: which backend origin the proxy may call (HTTPS, or http only to `api`/`localhost` inside Docker). Tested in `dashboard-origin.test.ts`. |
| `session.ts` | Server-only auth: parses `DASHBOARD_USERS_JSON`, verifies passwords, signs/reads the session cookie, `getStaffUser()`. |
| `layout.tsx`, `globals.css` | Root layout (theme bootstrap from `localStorage`) and all styles. |
| `login/` | Login page and form (employee ID + password → `POST /api/auth/login`). |
| `[...route]/page.tsx` | Catch-all route that renders the shell for every dashboard URL. |
| `api/` | Server routes (see `api/CLAUDE.md`). |
| `*.test.ts` | Node test runner unit tests (`npm test`). |

## URL → page

`/` home · `/leads` (list/board, `?stage=` filter) · `/leads/{id}` and its tabs (conversations/sms,
conversations/calls, cadence, activity) · `/review` · `/analytics` · `/administration`,
`/administration/cadence`, `/administration/templates` · `/assistant`

## Notes

- The board column comes from the backend's `lead.stage`; the frontend does not compute stages.
- Add new pages inside `DashboardShell`'s path routing, not as new Next.js route folders, unless they need
  server-side logic.
- Booked is set by staff (Google Sheet or the board); a booked lead has no appointment data to show.
