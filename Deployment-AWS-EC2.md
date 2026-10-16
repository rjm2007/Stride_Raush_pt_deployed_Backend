# Deploying Rausch PT production on AWS EC2

A step-by-step guide. Follow the steps in order and do not skip the checks. Every command says where it
runs: **[Mac]** = your laptop's terminal, **[Server]** = after `ssh stride`, **[Browser]** = a website.

## 0. What we are doing

We reuse the client's existing EC2 server and the same domain. Only three things change:

1. The code: the new **production** repo (backend + dashboard in one repo) replaces the demo stack.
2. The database: the client's **production** Supabase instead of the demo one.
3. The Google Sheet is read directly by the backend with a Google service account (no n8n). For now this
   is the **current** Sheet and service account; the client's own come later (step 4).

Everything else stays the same: domain `stride.aibolt.ai`, HTTPS certificate (Caddy renews it), the Vapi
voice agent and its links, the clinic's Twilio/Vapi phone number.

| Thing | Value |
| --- | --- |
| Server | EC2, `ubuntu@34.225.188.32`, SSH alias `stride` (key in `~/Desktop/Stride/keys/`) |
| Domain | `https://stride.aibolt.ai` (DNS already points at the server; nothing to change in Namecheap) |
| Old demo stack | `~/aws_deployed_raush_pt_stride_keap` on the server — **deleted** at step 10 (owner's decision) |
| New production stack | `~/rpt-production` on the server, from `github.com/rjm2007/Stride_Raush_pt_deployed_Backend` (backend + dashboard in one repo) |
| Production database | Supabase project `taimrfktweamsnbbatux` (region Singapore) |
| Voice agent | Vapi assistant `540ddb07-711e-4060-8753-f82d848b9a25` ("Outreach Agent - Test") |
| Containers | `rpt-api`, `rpt-worker`, `rpt-sheet-worker`, `rpt-dashboard`, `rpt-caddy` |

**Downtime:** about 10 minutes at step 10 (the old stack is removed, then the new one is built and started).

**Safety switches:** the new stack starts with `OUTBOUND_ENABLED=false`, so it cannot call or text anyone
until you turn it on in step 13. `TESTING_MODE=true` makes new Sheet leads test leads (one minute per
cadence day, calling hours ignored) for the end-to-end test; set it back to `false` before real patients.

## 1. Before you start: what you need

- [ ] SSH works: **[Mac]** `ssh stride` opens the server.
- [ ] A GitHub account/organisation for the production repo (private repo).
- [ ] A Google account that can create a Google Cloud project and the new Google Sheet.
- [ ] Supabase access to the production project (`taimrfktweamsnbbatux`) and its database password.
- [ ] Twilio console access (the clinic's number) and Vapi dashboard access (only to check, step 11).
- [ ] n8n access (https://n8n.aibolt.ai), to switch the old Sheet workflows off.
- [ ] The booking link the agent should text (if it changes from today's Stride scheduling link).
- [ ] The staff who need dashboard logins (id, name, role).

## 2. The code on GitHub

The production folder is pushed to `https://github.com/rjm2007/Stride_Raush_pt_deployed_Backend`
(branch `main`). Later changes: commit in `~/Desktop/Stride/production` and `git push`.

Check: on GitHub you see `backend/`, `frontend/`, `docker-compose.yml`, `Caddyfile`, `.env.example`,
`dashboard.env.example`, `scripts/`, `Deployment-AWS-EC2.md`. There must be **no** `.env` or `dashboard.env`.

## 3. Let the server read the repo (deploy key) [Server]

First try the same access the old repo used (same GitHub owner):

```bash
ssh stride
git -C ~/aws_deployed_raush_pt_stride_keap remote get-url origin    # how the old repo was cloned
git clone https://github.com/rjm2007/Stride_Raush_pt_deployed_Backend.git ~/rpt-production
```

If that clone works, skip the rest of this step. If it asks for a password or says "not found", use a
deploy key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/rpt_production_deploy -N "" -C "rpt-production deploy key"
cat ~/.ssh/rpt_production_deploy.pub
cat >> ~/.ssh/config <<'EOF'
Host github-rpt
    HostName github.com
    User git
    IdentityFile ~/.ssh/rpt_production_deploy
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
```

**[Browser]** GitHub → the repo → Settings → Deploy keys → Add deploy key → title `stride server`, paste the
`.pub` line, leave "Allow write access" **off** → Add key.

```bash
# [Server]
ssh -T git@github-rpt            # answer "yes" once; it should greet the repo
git clone git@github-rpt:rjm2007/Stride_Raush_pt_deployed_Backend.git ~/rpt-production
ls ~/rpt-production              # backend  frontend  docker-compose.yml  Caddyfile  ...
```

## 4. Google service account and the Sheet [Browser]

**For now:** use the current Sheet and the current service account. Skip 4a and 4b, copy the existing key
as in step 4c (on the server it is usually `~/stride-secrets/google-sheet-sa.json`), and do 4d. When the
client sends her own service account and Sheet, do 4a–4c with them, put the new id in `GOOGLE_SHEET_ID`, and
run `docker compose up -d --force-recreate sheet-worker`.

### 4a. Service account (the backend's Google login)

1. Open https://console.cloud.google.com → top bar project picker → **New project** → name
   `rausch-pt-outreach` → Create → select it.
2. **APIs & Services → Library** → search **Google Sheets API** → **Enable**. Then search
   **Google Drive API** → **Enable** too (the Google library asks for Drive access when it signs in).
3. **IAM & Admin → Service Accounts → Create service account** → name `rpt-sheet-sync` → Create and
   continue → skip the roles → Done.
4. Click the new account → **Keys → Add key → Create new key → JSON → Create**. A `.json` file downloads.
   This file is a password: never email it, never put it in git.
5. Copy the account's email (looks like `rpt-sheet-sync@rausch-pt-outreach.iam.gserviceaccount.com`).

### 4b. The new Sheet

1. Create a new Google Sheet. Keep the first tab named **`Sheet1`**.
2. Row 1: anything (a title). **Row 2: these column names, exactly** (spelling, capitals and spaces matter;
   order does not):

```text
Name | Phone Number | Email | Date Of Birth | Location | Case | Action | Lead Status | Cadence Day | Outcome Status | Call Outcome | Message Outcome | Email Outcome | Transcript Link | Action Request ID | Action Started At | Lead ID
```

   Tip: copy row 2 from the current Sheet so it is identical.
3. Action column dropdown: select the Action column from row 3 down → **Data → Data validation → Add rule →
   Dropdown** with exactly: `Start cadence`, `Restart cadence`, `Do Not Contact`, `Booked`.
4. **Share** → paste the service account email → **Editor** → untick "Notify people" → Share.
5. The Sheet id is the long part of its URL: `https://docs.google.com/spreadsheets/d/<THIS_PART>/edit`.
   Keep it for step 6.

The full Sheet rules (commands, labels, re-running a row) are in `backend/docs/GOOGLE_SHEET.md`.

### 4d. Clear old rows out of the tab [Browser]

The production database starts empty, so old rows in `Sheet1` mean nothing to it, and a row whose Action is
still pending (blank Outcome Status, or stuck in "Processing") would run again and could start a cadence.
In the Sheet: add a tab named `Old rows`, cut every row from row 3 down out of `Sheet1` and paste it there.
Keep rows 1 and 2 (title and column names) in `Sheet1`. The backend reads only `Sheet1`.

### 4c. Copy the key to the server [Mac]

```bash
ssh stride 'mkdir -p ~/rpt-secrets && chmod 700 ~/rpt-secrets'
scp ~/Downloads/<the-downloaded-key>.json stride:/home/ubuntu/rpt-secrets/google-sheet-sa.json
ssh stride 'chmod 600 ~/rpt-secrets/google-sheet-sa.json && ls -l ~/rpt-secrets'
```

Then delete the downloaded file from your Mac (`rm ~/Downloads/<the-downloaded-key>.json`).

## 5. The production database URL [Browser]

Supabase → project **taimrfktweamsnbbatux** → **Connect** (or Project Settings → Database) →
**Session pooler** connection string (port **5432**). Put the database password in it and add
`?sslmode=require` at the end:

```text
postgresql://postgres.taimrfktweamsnbbatux:<DB_PASSWORD>@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require
```

- If the password has special characters (`@ : / ? # %`), URL-encode them (`@` → `%40`, `#` → `%23`, …).
- If it contains `$`, put the whole value in single quotes in `.env`:
  `SUPABASE_DB_URL='postgresql://…'` (Docker would otherwise read `$` as a variable).

## 6. Create the server settings (.env and dashboard.env) [Server]

The script copies the Vapi/Twilio values from the old server `.env` (same clinic numbers), creates new
random secrets, and never prints a secret.

```bash
cd ~/rpt-production
bash scripts/make-server-env.sh ~/aws_deployed_raush_pt_stride_keap/.env
nano .env
```

In `nano`, set these two lines, then save (Ctrl+O, Enter) and exit (Ctrl+X):

- `SUPABASE_DB_URL=` the URL from step 5
- `GOOGLE_SHEET_ID=` the Sheet id from step 4b

Leave `OUTBOUND_ENABLED=false` for now.

Staff logins: the script made one admin login (id `admin`, password inside `dashboard.env`). To give staff
their own logins, edit the `DASHBOARD_USERS_JSON` line in `dashboard.env`: one line of JSON **inside single
quotes** (`DASHBOARD_USERS_JSON='[…]'`), exactly one `super_admin`, passwords 12+ characters and without a
single quote. To keep today's logins, copy that variable's value from the Vercel project
(rpt-frontend → Settings → Environment Variables) and paste it between the single quotes.

Check (prints only names, never values):

```bash
grep -cE '^[A-Z_]+=.+' .env dashboard.env
grep -E '^(APP_ENV|OUTBOUND_ENABLED|SHEET_SYNC_ENABLED|GOOGLE_SHEET_TAB|GOOGLE_SHEET_HEADER_ROW|PUBLIC_BASE_URL|VAPI_ASSISTANT_ID)=' .env
grep -qE '^SUPABASE_DB_URL=postgresql://postgres\.taimrfktweamsnbbatux:.+sslmode=require' .env && echo "db url ok"
grep -qE '^GOOGLE_SHEET_ID=.{20,}' .env && echo "sheet id ok"
ls -l .env dashboard.env    # both -rw------- (600)
```

## 7. Make room on the server [Server]

The dashboard build needs memory. Check, and add swap if the server has less than 4 GB of RAM:

```bash
free -h          # look at "Mem: total"
df -h /          # need at least 5 GB free
# only if Mem total is under 4 GB and "Swap" shows 0:
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h          # Swap now shows 4.0G
```

## 8. Build the images and update the database [Server]

The old stack keeps running during this step.

```bash
cd ~/rpt-production
docker compose build                      # 5-10 minutes the first time
docker compose run --rm api rpt migrate   # adds the 10 missing schema updates (036-045) to production
docker compose run --rm api rpt verify    # the list must end with 045_sheet_stage_trigger.sql
```

If `migrate` fails with a connection error, the `SUPABASE_DB_URL` line is wrong (step 5).

## 9. Clean the production database (owner's go-ahead) [Browser]

Production was filled with a copy of the demo database on 2026-10-10 (17 test leads, demo booking data,
3 test blocked numbers). This removes that and keeps the setup (cadence, message templates, settings).
It stops by itself, changing nothing, if a real (non-test) lead exists or step 8 was not done.

1. Supabase → production project → **SQL Editor** → New query.
2. Paste the whole file `backend/supabase/prod/2026-10-16_clear_demo_copy.sql` → **Run**.
3. The last result must show `leads 0`, `blocked_numbers 0`, `active_cadences 1`, `message_templates`
   above 0, and `assistant 540ddb07-711e-4060-8753-f82d848b9a25` (the script sets it: the database value
   wins over `.env`). If any value differs, **stop** and do not continue to step 10.

If the booking link changes, set it now (same SQL Editor):

```sql
update practice_settings set booking_link_url = 'https://<NEW BOOKING LINK>', updated_at = now()
where practice_id = (select id from practices where slug = 'rausch-pt');
```

## 10. Switch over (about 10 minutes of downtime) [Browser + Server]

Do it when no demo call is in progress. Steps 6 and 8 must be done first (step 6 reads the old `.env`).

1. **[Browser]** n8n (https://n8n.aibolt.ai) → switch **off** (deactivate) all four Sheet workflows:
   "lead intake Final ONE (PRoduction)", "sheet-db-sync-flow(Production - safety)",
   "webhook-flow (Production)", "Lead-sync-flow (Production Name change feature one)". After the switch
   they would only get errors from the new backend.
2. **[Server]** keep a private copy of the old settings (needed later to move the demo to Render), remove the
   old stack completely, then preview and start the new one:

```bash
install -m 600 ~/aws_deployed_raush_pt_stride_keap/.env ~/old-demo.env
cd ~/aws_deployed_raush_pt_stride_keap && docker compose -f docker-compose.prod.yml down --volumes --rmi all
cd ~ && rm -rf ~/aws_deployed_raush_pt_stride_keap
docker system prune -f
cd ~/rpt-production
docker compose run --rm sheet-worker rpt sheet-check   # preview of the first Sheet poll; changes nothing
docker compose up -d
docker compose ps        # all 5 "Up"; rpt-api "(healthy)"
```

3. Checks:

```bash
curl -fsS https://stride.aibolt.ai/health; echo     # {"status":"ok",...}
curl -s https://stride.aibolt.ai/ready; echo        # {"status":"ready",...}
docker compose logs --tail=30 sheet-worker           # no "error"; it polls every 30 s
docker compose logs --tail=30 worker                 # starts; no calls while OUTBOUND_ENABLED=false
docker compose logs --tail=30 caddy                  # "certificate obtained" (first start only)
```

The new stack has its own Caddy storage, so Caddy gets a fresh HTTPS certificate on its first start (it
takes a few seconds; ports 80 and 443 must be reachable). If the log shows a certificate error, check the
EC2 security group (80 and 443 open) and that the old `stride-caddy` container is gone (`docker ps`).

If `/ready` says `not_ready`, it lists exactly what is missing; fix `.env`, then
`docker compose up -d --force-recreate api worker sheet-worker`.

4. **[Browser]** open https://stride.aibolt.ai → staff login → the board loads (empty is correct).

## 11. Provider settings [Browser]

**Twilio** (the clinic's number): Console → Phone Numbers → Manage → Active numbers → the clinic number →
**Messaging configuration** → "A message comes in" → **Webhook**, `https://stride.aibolt.ai/api/v1/twilio/inbound-sms`,
HTTP **POST** → Save. Do not touch the Voice section (Vapi uses it). This makes patient replies such as STOP
reach the backend (today they go to Vapi and are lost).

**Vapi**: nothing to change; only check. Assistants → "Outreach Agent - Test" → Advanced → Server URL is
`https://stride.aibolt.ai/api/v1/vapi/webhook`; Tools → `update_lead_status` → Server URL
`https://stride.aibolt.ai/api/v1/webhooks/vapi/lead-status`. Do **not** use the "Outreach Booking Agent"
until the demo has its own server (its tools also point at this domain).

## 12. Staff logins and the Sheet [Browser]

- Each staff member signs in at https://stride.aibolt.ai with their id and password from `dashboard.env`.
- In the new Sheet, the sheet-worker writes Lead Status, Outcome Status, Lead ID and so on by itself.

## 13. Turn calls and texts on, then test with your own phone [Server + Browser]

Test in testing mode (one minute per cadence day, any time of day), then switch to real mode. First
put the test numbers in `.env` (`nano .env`): `TEST_TWILIO_ACCOUNT_SID`, `TEST_TWILIO_AUTH_TOKEN`,
`TEST_TWILIO_FROM_NUMBER`, `TEST_VAPI_PHONE_NUMBER_ID`. While testing mode is on, every call and text uses
them; with it off, the live number is used. In the **test** Twilio account, point the test number's
Messaging webhook at `https://stride.aibolt.ai/api/v1/twilio/inbound-sms` too.

```bash
cd ~/rpt-production
sed -i 's/^OUTBOUND_ENABLED=false/OUTBOUND_ENABLED=true/; s/^TESTING_MODE=false/TESTING_MODE=true/' .env
grep -E '^(OUTBOUND_ENABLED|TESTING_MODE)=' .env   # both true
docker compose up -d --force-recreate api worker sheet-worker
```

The dashboard shows a yellow "Testing mode is on" banner. In testing mode the whole cadence (Day 0 call
and text, Day 1 text, Day 3 call, … Day 14 call) runs in about 15 minutes, at any hour. Without it, calls
happen only Mon–Fri 9:00–17:00 California time.

1. Sheet: new row with **your own** name and phone, a date of birth, a Location (e.g. Laguna Niguel), a
   Case (e.g. Ortho), Action `Start cadence`. Within about 2 minutes: Outcome Status `Cadence started`,
   Lead ID filled, Lead Status `In cadence`. The dashboard shows the lead in **In Cadence**.
2. The Day 0 call comes within a minute or two. Ask for the booking link → the text arrives about
   2 minutes after the call; the next steps follow one minute per cadence day.
3. Sheet: set Action to `Booked` on that row → Outcome Status `Booked`, Lead Status `Booked`; the dashboard
   card moves to **Booked**; no more calls or texts.
4. Optional: reply `STOP` to a text → the number is opted out (dashboard shows it).
5. Clean up: dashboard → each test lead → Delete lead (admin); if you sent STOP, unblock the number from the
   lead page first. Then delete the test rows from the Sheet (their Lead IDs point at deleted leads).
6. **Go live:** switch testing mode off (calls stay on):

```bash
cd ~/rpt-production
sed -i 's/^TESTING_MODE=true/TESTING_MODE=false/' .env && grep '^TESTING_MODE' .env   # TESTING_MODE=false
docker compose up -d --force-recreate api worker sheet-worker
```

   The banner disappears. From now on every new Sheet row is a real patient with the normal 14-day cadence.

## 14. Everyday commands [Server]

```bash
cd ~/rpt-production
docker compose ps                                    # status
docker compose logs -f api                           # or worker / sheet-worker / dashboard / caddy
docker compose restart worker                        # restart one service

# Deploy a new version (after pushing to GitHub from the Mac):
git pull
docker compose build
docker compose run --rm api rpt migrate
docker compose up -d

# Emergency stop of all calls and texts (dashboard and Sheet keep working):
sed -i 's/^OUTBOUND_ENABLED=true/OUTBOUND_ENABLED=false/' .env && docker compose up -d --force-recreate worker api

# After editing .env or dashboard.env:
docker compose up -d --force-recreate api worker sheet-worker dashboard

# Preview what the next Sheet poll would do (changes nothing):
docker compose run --rm sheet-worker rpt sheet-check
```

Disk housekeeping (monthly): `docker image prune -f` removes old images. Container logs rotate by
themselves (10 MB × 5 per container).

## 15. If something breaks

The old stack is deleted (owner's decision), so there is no switch back: fix forward.
- Stop all calls and texts at once: the emergency command in step 14.
- Read the error: `docker compose logs --tail=100 <service>` and `curl -s https://stride.aibolt.ai/ready`.
- Go back one code version: `git log --oneline -5`, `git checkout <previous commit>`,
  `docker compose build && docker compose up -d`, then `git checkout main` once fixed.
- The old demo settings are in `~/old-demo.env` (mode 600) for moving the demo to Render.

## 16. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `docker compose build` killed / "out of memory" | Add swap (step 7) and run the build again |
| `/ready` → `SUPABASE_DB_URL must set sslmode=require` | Add `?sslmode=require` to the URL (step 5) |
| `/ready` → `database unavailable` | Wrong password or URL; use the **Session pooler** string, port 5432 |
| sheet-worker log: `GOOGLE_SHEET_CREDENTIALS_FILE does not point to a readable key file` | The key is not at `/home/ubuntu/rpt-secrets/google-sheet-sa.json` (step 4c) |
| sheet-worker log: permission / 403 from Google | The Sheet is not shared with the service account email as Editor, or the Sheets / Drive API is not enabled (step 4a) |
| Google Cloud refuses to create a key ("key creation is disabled") | The Google Workspace has the policy `iam.disableServiceAccountKeyCreation`; an organisation admin must allow it for this project |
| heartbeat / log: `missing column` | A row-2 column name is misspelled (step 4b) |
| A Sheet row never starts | Outcome Status is not empty, or the row was still being edited (it waits 60 s unchanged) |
| Dashboard login page says unavailable | `dashboard.env` roster is not valid JSON or has no / two `super_admin` |
| Dashboard shows "The dashboard service is unavailable" | The api is down (`docker compose ps`), or `DASHBOARD_API_TOKEN` differs between `.env` and `dashboard.env` (the dashboard log says "backend rejected the server token") |
| Caddy cannot get a certificate | Ports 80/443 closed in the EC2 security group, or the old caddy is still running (`docker ps`) |
| Calls come every minute at night | `TESTING_MODE=true` is still on (yellow banner): step 13.6 |
| Calls never start | `OUTBOUND_ENABLED=false`, outside business hours, or the number is blocked |

---

## 17. Make the server bigger (disk or RAM)

Today: 2 GB RAM + 4 GB swap, 15 GB disk. That is enough for this setup (the five containers use well under
1 GB when running). Check from time to time:

```bash
free -h                     # "available" should stay above ~300 MB; "Swap used" should stay low
docker stats --no-stream    # memory per container
df -h /                     # keep at least 3 GB "Avail"; run `docker image prune -f` after deploys
```

Grow the **disk** if `Avail` drops under 3 GB. Grow the **RAM** if `available` is often under 300 MB or swap
use keeps rising outside builds.

### 17a. Bigger disk (no downtime) [Browser + Server]

1. **[Browser]** AWS Console → EC2 → Instances → the server → **Storage** tab → click the root volume id.
2. **Actions → Modify volume** → Size `30` (GiB), type `gp3` → Modify → Modify. Wait until the state shows
   `optimizing` or `completed` (a few minutes). The server keeps running.
3. **[Server]** let Linux use the new space:

```bash
lsblk                                   # find the disk and partition, e.g. nvme0n1 and nvme0n1p1 (or xvda / xvda1)
df -hT /                                # the "Type" column: ext4 (usual) or xfs
sudo growpart /dev/nvme0n1 1            # disk name and partition NUMBER from lsblk (xvda: sudo growpart /dev/xvda 1)
sudo resize2fs /dev/nvme0n1p1           # ext4; for xfs use: sudo xfs_growfs -d /
df -h /                                 # Size now about 30G
```

### 17b. More RAM (about 2 minutes of downtime) [Browser + Server]

Changing the instance type needs the server stopped and started. **Check the IP first:** a stop/start gives
the server a new public IP unless it has an **Elastic IP**, and a new IP breaks `stride.aibolt.ai` until the
DNS A record (Namecheap) is changed.

1. **[Browser]** EC2 → **Elastic IPs**: is `34.225.188.32` listed and associated with this instance?
   - **Yes:** the IP stays the same. Continue.
   - **No:** stop here. Do this only when someone can update the Namecheap A record right after (or first
     allocate an Elastic IP, associate it, and point the A record at it).
2. **[Server]** stop calls cleanly: `cd ~/rpt-production && docker compose down`
3. **[Browser]** EC2 → Instances → the server → **Instance state → Stop instance**. Wait for `Stopped`.
4. **Actions → Instance settings → Change instance type** → `t3.medium` (4 GB RAM; about double the price
   of `t3.small`) → Apply.
5. **Instance state → Start instance**. Wait for `Running` and both status checks to pass.
6. **[Mac]** `ssh stride`, then:

```bash
cd ~/rpt-production
docker compose up -d
docker compose ps
free -h                     # Mem total now about 3.8Gi
curl -s https://stride.aibolt.ai/ready; echo
```

## Appendix. Security notes

- `.env`, `dashboard.env` and the Google key exist only on the server (mode 600). Never commit, email or
  paste them in chat.
- Secrets that were pasted in chats earlier (the Twilio auth token, the n8n MCP token) should be rotated.
  After rotating the Twilio auth token, put the new value in `.env` and recreate api and worker.
- Keep the SSH security-group rule limited to your IP.
- Supabase: production holds real patient data from go-live; only the owner runs SQL there.
