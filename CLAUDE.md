# Rausch PT outreach — production

The client's **production** system, cadence only. New leads from the clinic's Google Sheet get a 14-day
cadence of AI voice calls (Vapi) and texts (Twilio). The voice agent offers the booking link, transfers to
the front desk, or books a callback; staff mark the lead **Booked** in the Sheet. No Stride, no Keap, no n8n.

This folder is one git repo (backend + dashboard + server config), remote
`https://github.com/rjm2007/Stride_Raush_pt_deployed_Backend` (branch `main`). It was cut down from the demo
code in `../demo/` on 2026-10-16; the demo stays the place where new work is built and tested first.

## Folders and files

| Path | What it is | Has CLAUDE.md |
| --- | --- | --- |
| `backend/` | Python/FastAPI: api, cadence worker, Google Sheet worker | yes |
| `frontend/` | Next.js staff dashboard | yes |
| `docker-compose.yml` | The whole server: `api`, `worker`, `sheet-worker`, `dashboard`, `caddy` | |
| `Caddyfile` | HTTPS for `stride.aibolt.ai`; `/api/v1/*` → api, everything else → dashboard | |
| `.env.example` | Backend settings template (server file: `.env`) | |
| `dashboard.env.example` | Dashboard settings template (server file: `dashboard.env`) | |
| `scripts/make-server-env.sh` | Builds `.env` and `dashboard.env` on the server from the old server `.env` | |
| `Deployment-AWS-EC2.md` | Step-by-step deploy guide (also for a fresh EC2) | |

## How the pieces connect

```text
Google Sheet  <--service account-->  sheet-worker  -->  Supabase (client's production project)
Browser  -->  Caddy (stride.aibolt.ai)  -->  dashboard  --http://api:8000-->  api
worker  -->  Vapi (calls) / Twilio (texts)
Vapi, Twilio  -->  Caddy  -->  api webhooks (/api/v1/...)
```

## Production facts

- Server: the client's EC2 `ssh stride` (ubuntu@34.225.188.32), repo at `~/rpt-production`, domain
  `https://stride.aibolt.ai`. The old demo stack is deleted at cutover (owner's decision; no rollback); its
  settings are kept privately in `~/old-demo.env` for moving the demo to Render.
- Database: Supabase project `taimrfktweamsnbbatux` (Singapore). MCP server `supabase-production`.
- Vapi: outreach agent `540ddb07-711e-4060-8753-f82d848b9a25`, its tools and webhook point at
  `stride.aibolt.ai`. Same clinic phone number (Vapi + Twilio) as the demo used.
- Google Sheet: for now the current (demo-era) Sheet and service account; the client will send her own,
  then only `GOOGLE_SHEET_ID` and the key file change.
- `TESTING_MODE=true` makes new Sheet leads test leads (one minute per cadence day, no calling hours or daily
  limits) for end-to-end checks on the live server; the dashboard shows a banner. Real use: `false`.
- Secrets on the server only: `.env`, `dashboard.env` (mode 600) and
  `/home/ubuntu/rpt-secrets/google-sheet-sa.json`.

## Working rules

- Production data is real patient data. Never print names, phone numbers or message bodies in full.
- Never write to the production database, Vapi, Twilio or the live Sheet without the owner's go-ahead for
  that change. Read-only checks are fine.
- Build and test a change in `../demo/` first, then bring the same change here (same migration file names,
  so both databases keep one schema). Run the backend tests (`backend/`) and the dashboard checks
  (`frontend/`) before every deploy.
- Backend and dashboard share a contract (identity headers, response shapes, proxy allow-list): change and
  deploy them together.
- Never put secrets in code, docs, commits or chat output.
- The owner prefers short, plain answers (one change per line). Hotfixes: commit to `main` and deploy.
