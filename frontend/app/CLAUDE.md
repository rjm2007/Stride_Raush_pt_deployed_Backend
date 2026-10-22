# app — pages, UI and client helpers

The dashboard is effectively a single-page app. `(dashboard)/layout.tsx` checks the session server-side,
redirects to `/login` if missing, and renders `DashboardShell`, which picks the screen from the URL on the
client. Because the shell is in the layout it stays mounted between screens. `(dashboard)/page.tsx` (`/`) and
`(dashboard)/[...route]/page.tsx` render nothing but re-check the session on each navigation the server
sees; `(dashboard)/loading.tsx` (empty) lets a click switch screens at once while that check streams in.
`next.config.ts` `staleTimes` reuses a visited (empty) page for 5 min. That is safe only because no page
renders patient data: every read and write goes through the `/api/dashboard` proxy, which checks the session
on each call (401 → cache and chats cleared → `/login`). Keep it that way.

| File | Purpose |
| --- | --- |
| `dashboard-shell.tsx` (~1250 lines) | The whole UI. `DashboardShell` (layout, nav, data loading via `/api/dashboard/snapshot`, actions) and every page component: Home, Leads (list + Kanban board with drag-and-drop stage moves), Review queue, Analytics, Administration (cadence studio, SMS templates), and the lead workspace (overview, SMS, calls, cadence runs with reschedule, activity). |
| `dashboard-data.ts` | TypeScript types for backend responses (`Lead`, `LeadDetail`, `Snapshot`, `CadenceVersion`, `ActivityEntry`, …) and `emptySnapshot`. Keep in sync with `routes/dashboard.py` in the backend. |
| `dashboard-client.ts` | `dashboardFetch()` wrapper for every call to the proxy: session expiry (clears the cache), and every successful write invalidates the cached reads it changed. |
| `query-cache.ts` | In-memory stale-while-revalidate cache for GETs (no browser storage; scoped per staff member; cleared on 401 and sign-out). `mutationTargets()` maps each write to the reads it changes: update it with every new endpoint. Tested in `query-cache.test.ts`. |
| `use-cached.ts` | `useCached()` hook, `cacheKeys` / `cachedFetchers`, hover prefetch for lead records. |
| `staff-session.ts` | Server-only: `React.cache()` around `getStaffUser()` so layout + page share one check per request. |
| `display.ts` | Formatting: clinic timezone (America/Los_Angeles), enum labels, status tones, activity descriptions, operational error messages. |
| `cadence.ts` | Cadence helpers: split events into runs, step names, run summaries, call naming, step reordering. |
| `assistant.tsx` | Staff assistant UI (dock + full page), up to 3 leads per chat, streaming answers. History via `assistant-store.ts`. |
| `assistant-store.ts` | Chat history: this tab's `sessionStorage`, tagged with the staff member, cleared on sign-out and 401; deletes the old `localStorage` copy. Tested in `assistant-store.test.ts`. |
| `dashboard-origin.ts` | Server-only: which backend origin the proxy may call (HTTPS, or http only to `api`/`localhost` inside Docker). Tested in `dashboard-origin.test.ts`. |
| `session.ts` | Server-only auth: parses `DASHBOARD_USERS_JSON`, verifies passwords, signs/reads the session cookie, `getStaffUser()`. |
| `layout.tsx`, `globals.css` | Root layout (theme bootstrap from `localStorage`) and all styles. |
| `login/` | Login page and form (employee ID + password → `POST /api/auth/login`). |
| `(dashboard)/` | Layout (shell + session check), the two pages (session check only) and `loading.tsx`. |
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
