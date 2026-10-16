# Server commands, explained

What each command we ran on the production server (`ssh stride`) does, in the order we ran them.
Short version first, details after.

## 1. Get the code

| Command | What it does |
| --- | --- |
| `git clone https://github.com/rjm2007/Stride_Raush_pt_deployed_Backend.git ~/rpt-production` | Downloads the production code (backend + dashboard + server files) into the folder `~/rpt-production`. |

## 2. The Google key (lets the backend read and write the Sheet)

| Command | What it does |
| --- | --- |
| `mkdir -p ~/rpt-secrets && chmod 700 ~/rpt-secrets` | Makes a private folder for secret files. `700` = only the `ubuntu` user can open it. |
| `ls -l ~/stride-secrets/` | Shows the Google service-account key we already had. |
| `cp … ~/rpt-secrets/google-sheet-sa.json` | Copies that key to the place the new setup reads it from. |
| `chmod 600 ~/rpt-secrets/google-sheet-sa.json` | Only the `ubuntu` user can read the key file. |

## 3. Settings (.env and dashboard.env)

| Command | What it does |
| --- | --- |
| `bash scripts/make-server-env.sh ~/aws_deployed_raush_pt_stride_keap/.env` | Creates the two settings files. Copies the Vapi, Twilio and OpenAI keys and the Sheet id from the old settings file, and makes new random passwords (dashboard token, login cookie key, admin password). It never prints a secret. |
| `nano .env` | Opens the backend settings in a text editor. We added the production database link (`SUPABASE_DB_URL`). |
| `grep -qE '^SUPABASE_DB_URL=.*sslmode=require' .env && echo "db url ok"` | Checks the database link is filled in and uses an encrypted connection. Prints `db url ok` if yes. |
| `grep -qE '^GOOGLE_SHEET_ID=.{20,}' .env && echo "sheet id ok"` | Checks the Sheet id is filled in. |

## 4. Room on the server

| Command | What it does |
| --- | --- |
| `free -h` | Shows memory (RAM) and swap: total, used, free. |
| `df -h /` | Shows disk space: size, used, available. |
| `docker system df` | Shows how much disk Docker images, containers and build cache use. |
| `sudo du -sh /srv/sftp /srv/stride /var/log` | Shows the size of the old Stride upload folders and the system logs. |

## 5. Remove the old (demo) setup

| Command | What it does |
| --- | --- |
| `install -m 600 ~/aws_deployed_raush_pt_stride_keap/.env ~/old-demo.env` | Keeps a private copy of the old settings (needed later to set up the demo on Render). `600` = only you can read it. |
| `docker compose -f docker-compose.prod.yml down --volumes --rmi all` | Stops the old containers and deletes them, their images and their stored data (old Caddy certificates). The site goes down here. |
| `sudo rm -rf /home/ubuntu/aws_deployed_raush_pt_stride_keap` | Deletes the old code folder. `sudo` was needed because the old containers wrote their log files as the admin user. |
| `sudo rm -f /etc/cron.d/mock-stride-timer /root/.mock-stride-cron-header` | Stops the Mock Stride timer that uploaded test files to this server every 5 minutes (nothing reads them any more). |
| `docker system prune -af` | Deletes every Docker image, container and network that is not in use. |
| `docker builder prune -af` | Deletes Docker's build cache (leftovers from old builds). |
| `sudo journalctl --vacuum-size=100M` | Shrinks the system logs to 100 MB. |
| `sudo find /srv/sftp/stride/incoming /srv/stride/archive /srv/stride/error -type f -delete` | Deletes the old fake Stride CSV files. |

## 6. Swap (extra memory on disk)

| Command | What it does |
| --- | --- |
| `sudo fallocate -l 4G /swapfile` | Reserves a 4 GB file on the disk. |
| `sudo chmod 600 /swapfile` | Only the system can read it. |
| `sudo mkswap /swapfile && sudo swapon /swapfile` | Turns the file into swap and switches it on. When the 2 GB of RAM is full, Linux moves idle data there instead of killing programs. Slower than RAM, but it keeps builds from crashing. |
| `echo '/swapfile none swap sw 0 0' \| sudo tee -a /etc/fstab` | Turns swap on again automatically after a reboot. |

## 7. Build and update the database

| Command | What it does |
| --- | --- |
| `docker compose build` | Builds the two programs as Docker images from the code: `rpt-backend` (api, worker, sheet-worker all use it) and `rpt-dashboard`. |
| `docker compose run --rm api rpt migrate` | Brings the production **database structure** up to date (see below). `--rm` deletes the one-off container afterwards. |
| `docker compose run --rm api rpt verify` | Lists every database update that has been applied, with its time. The last one must be `045_sheet_stage_trigger.sql`. |

**Why the migration was needed.** The production database was copied from demo on 2026-10-10, when demo
was at update 035. The code needs 10 later updates (036–045): for example the table where the Sheet worker
remembers each row (`sheet_row_state`) and the trigger that tells the Sheet when a lead's status changes.
Without them the Sheet worker would fail. They change the structure (new tables, columns, indexes, a
trigger), not your data. `rpt migrate` only applies updates that are missing, so running it again is safe.

## 8. Clean the database (Supabase SQL Editor, not the server)

`backend/supabase/prod/2026-10-16_clear_demo_copy.sql` removes the 17 test leads copied from demo and
everything linked to them, plus demo booking data and old logs. It keeps the cadence, message templates,
settings and case types, and makes calls use the outreach agent. It refuses to run if a real (non-test)
lead exists.

## 9. Start and check (next)

| Command | What it does |
| --- | --- |
| `docker compose run --rm sheet-worker rpt sheet-check` | Reads the Sheet and shows what the first poll would do. Changes nothing. |
| `docker compose up -d` | Starts all 5 containers in the background: `api`, `worker`, `sheet-worker`, `dashboard`, `caddy`. |
| `docker compose ps` | Shows each container and whether it is running (`Up`) and healthy. |
| `curl -s https://stride.aibolt.ai/ready` | Asks the backend whether its settings and database are OK. `"status":"ready"` = good. |
| `grep DASHBOARD_USERS_JSON dashboard.env` | Shows the dashboard login list, including the admin password the script made. |

## 10. Test, then go live

| Command | What it does |
| --- | --- |
| `sed -i 's/^OUTBOUND_ENABLED=false/OUTBOUND_ENABLED=true/; s/^TESTING_MODE=false/TESTING_MODE=true/' .env` | Edits two lines in `.env`: turns calls and texts on, and turns testing mode on (one minute per cadence day). |
| `docker compose up -d --force-recreate api worker sheet-worker` | Restarts those containers so they read the changed settings. |
| `docker compose logs -f worker` | Shows the worker's log live (calls and texts being sent). Ctrl+C to stop watching; the worker keeps running. |
| `sed -i 's/^TESTING_MODE=true/TESTING_MODE=false/' .env` + the same `up -d --force-recreate` | Go live: testing mode off, normal 14-day cadence. |

## Everyday

| Command | What it does |
| --- | --- |
| `docker compose ps` | Is everything running? |
| `docker compose logs --tail=100 api` | Last 100 log lines of one container (`api`, `worker`, `sheet-worker`, `dashboard`, `caddy`). |
| `git pull && docker compose build && docker compose run --rm api rpt migrate && docker compose up -d` | Deploy a new version. |
| `docker image prune -f` | After a deploy: deletes the old, now unused images (frees disk). |
| `sed -i 's/^OUTBOUND_ENABLED=true/OUTBOUND_ENABLED=false/' .env && docker compose up -d --force-recreate worker api` | Emergency: stop all calls and texts at once. |
| `free -h`, `df -h /`, `docker stats --no-stream` | Memory, disk, and memory per container. |
