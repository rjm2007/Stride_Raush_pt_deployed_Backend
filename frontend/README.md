# RPT staff dashboard (production)

Internal dashboard for the Rausch PT outreach cadence: lead board and list, lead workspace (conversations,
calls, cadence, activity), review queue, analytics, cadence and SMS template studio, blocked numbers, staff
roles. Leads come only from the clinic's Google Sheet; Booked is set by staff.

Requires the backend in `../backend`; both run on one server with `../docker-compose.yml`
(see `../Deployment-AWS-EC2.md`). Working rules: `CLAUDE.md`.

```bash
npm ci
npm run lint && npm run typecheck && npm test
npm run build
```
