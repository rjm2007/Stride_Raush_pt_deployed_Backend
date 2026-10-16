#!/usr/bin/env bash
# Builds .env and dashboard.env on the production server, from .env.example /
# dashboard.env.example. Run it ON THE SERVER, from the repo folder:
#
#   bash scripts/make-server-env.sh ~/aws_deployed_raush_pt_stride_keap/.env
#
# - Copies the Vapi / Twilio / OpenAI values and the Google Sheet id from the old server .env.
# - Generates new random secrets (dashboard token, session secret, fingerprint key, admin password).
# - Never prints a secret. Both files are created with mode 600.
# - Refuses to overwrite an existing .env or dashboard.env.
# Afterwards you still fill in SUPABASE_DB_URL (and GOOGLE_SHEET_ID if the old file had none).
set -euo pipefail

OLD="${1:?usage: bash scripts/make-server-env.sh /path/to/old/.env}"
cd "$(dirname "$0")/.."
[ -f "$OLD" ] || { echo "Old .env not found: $OLD" >&2; exit 1; }
for file in .env dashboard.env; do
  if [ -e "$file" ]; then
    echo "$file already exists here. Move it away first (it is never overwritten)." >&2
    exit 1
  fi
done
umask 077

# The value after KEY= (also "export KEY="), without a Windows line ending.
old_value() { grep -m1 -E "^(export[[:space:]]+)?$1=" "$OLD" | cut -d= -f2- | tr -d '\r' || true; }
random_secret() { openssl rand -base64 64 | tr -dc 'A-Za-z0-9' | cut -c1-48; }

# Replace KEY=... in a file with a value passed through the environment (never on argv).
set_value() {
  KEY="$1" VALUE="$2" FILE="$3" python3 - <<'PY'
import os, re, sys
key, value, path = os.environ["KEY"], os.environ["VALUE"], os.environ["FILE"]
text = open(path, encoding="utf-8").read()
pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
if not pattern.search(text):
    sys.exit(f"{key} is missing from {path}")
open(path, "w", encoding="utf-8").write(pattern.sub(lambda _: f"{key}={value}", text, count=1))
PY
}

cp .env.example .env
for key in VAPI_API_KEY VAPI_PHONE_NUMBER_ID VAPI_WEBHOOK_SECRET VAPI_HMAC_SECRET \
           TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_FROM_NUMBER OPENAI_API_KEY GOOGLE_SHEET_ID; do
  set_value "$key" "$(old_value "$key")" .env
done
TOKEN="$(random_secret)"
set_value DASHBOARD_API_TOKEN "$TOKEN" .env
set_value PHONE_FINGERPRINT_SECRET "$(random_secret)" .env

cp dashboard.env.example dashboard.env
set_value DASHBOARD_API_TOKEN "$TOKEN" dashboard.env
set_value DASHBOARD_SESSION_SECRET "$(random_secret)" dashboard.env
ADMIN_PASSWORD="$(random_secret | cut -c1-20)"
# Single-quoted so Docker never reads $ or # inside the JSON (see dashboard.env.example).
set_value DASHBOARD_USERS_JSON \
  "'[{\"id\":\"admin\",\"name\":\"Clinic Admin\",\"password\":\"${ADMIN_PASSWORD}\",\"role\":\"super_admin\"}]'" \
  dashboard.env
chmod 600 .env dashboard.env

echo "Created .env and dashboard.env (mode 600)."
echo "Dashboard login: id 'admin'. Its password is in dashboard.env (DASHBOARD_USERS_JSON); read it with:"
echo "  grep DASHBOARD_USERS_JSON dashboard.env"
echo
echo "Copied from the old .env (empty means the old file did not have it):"
for key in VAPI_API_KEY VAPI_PHONE_NUMBER_ID VAPI_WEBHOOK_SECRET VAPI_HMAC_SECRET \
           TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_FROM_NUMBER OPENAI_API_KEY GOOGLE_SHEET_ID; do
  if grep -qE "^${key}=.+" .env; then echo "  ok     $key"; else echo "  EMPTY  $key"; fi
done
echo
echo "Fill these in by hand now (nano .env):"
grep -qE '^SUPABASE_DB_URL=postgresql://postgres\.PROJECT_REF' .env && echo "  SUPABASE_DB_URL  (production Supabase session pooler URL + ?sslmode=require)"
grep -qE '^GOOGLE_SHEET_ID=$' .env && echo "  GOOGLE_SHEET_ID  (the Sheet's id)"
echo "Keep OUTBOUND_ENABLED=false until the checks in the deployment guide pass."
