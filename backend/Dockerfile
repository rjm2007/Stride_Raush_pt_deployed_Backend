FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app

# Exact versions from uv.lock (requirements.txt is `uv export` of it), so the server runs what the
# tests ran. Re-export after any dependency change (see CLAUDE.md).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps . \
    && rm -f pyproject.toml README.md requirements.txt

# supabase/ holds the migrations `rpt migrate` applies; supabase/dev/ holds the SQL
# `rpt test-lead` needs. Tests and scripts are not needed.
COPY supabase ./supabase
RUN mkdir -p /app/logs

CMD ["uvicorn", "rpt_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
