# RPT outreach backend (production)

FastAPI service for the Rausch PT 14-day patient outreach cadence: Google Sheet intake, Vapi voice calls,
Twilio texts, staff dashboard API. Cadence-only production build: no Stride, no Keap, no n8n.

- What it does and why: `context/PROJECT_CONTEXT.md`
- Working rules and layout: `CLAUDE.md`
- The Google Sheet contract: `docs/GOOGLE_SHEET.md`
- Deploying: `../Deployment-AWS-EC2.md`

```bash
~/.local/bin/uv sync --frozen --extra dev --python 3.12
~/.local/bin/uv run --frozen python -m pytest -q
~/.local/bin/uv run --frozen ruff check src tests scripts
```
