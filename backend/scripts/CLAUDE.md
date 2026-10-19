# scripts — ops utilities

| File | Purpose |
| --- | --- |
| `vapi_export.py` | Read-only: saves the live outreach agent (prompt, settings, tools) into `config/` with secrets masked. Needs `VAPI_API_KEY`. |
| `sheet_load_test.py` | Sheet sync under load: N pasted Start rows through the real code, an in-memory Sheet and a LOCAL Postgres (refuses any other DB); checks exactly-once and reports timings. No provider is called. |
| `test_agent_chat.py` | Tests the live outreach agent case by case by text chat (Vapi Chat API, no phone call): 15 scripted patients, checks what it says and the outcome it reports; callback cases follow the clinic hours and the current California time. `python scripts/test_agent_chat.py` lists the cases, `… 3 7` runs some, `… all` runs every one. Needs `VAPI_API_KEY` (`--env`). |
| `generate_test_usage_report.py` | Builds the test-usage cost report (`usage_report.py`). |

The server-side env builder is `../../scripts/make-server-env.sh` (repo root).
