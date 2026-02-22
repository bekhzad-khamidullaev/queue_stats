# Queue Stats (Django Monolith)

Queue Stats is a unified Django monolith for Asterisk call-center analytics.

It provides:
- Django server-rendered UI (no separate frontend service)
- Real-time updates via WebSocket (Django Channels + HTMX)
- AMI integration for live queue/call state
- Reporting from Asterisk MySQL data (`cdr`, `queuelog`, and runtime tables)
- Queue/operator mapping (system names -> display names)
- Operator payout calculations
- XLSX/PDF export for reports and dashboards

## Architecture

Single service (`backend`) includes:
- Django app + templates
- Channels (ASGI) for WebSocket endpoints
- AMI sync worker for realtime tables
- Chart rendering via static JS (`Chart.js`) in templates

Main runtime routes:
- UI: `/login/`, `/`, `/reports/*`, `/dashboards/*`, `/analytics/`, `/realtime/`, `/settings/`
- WebSocket:
  - `/ws/realtime/` (JSON AMI stream)
  - `/ws/htmx-realtime/` (HTMX OOB HTML stream)

## Tech Stack

- Python 3.12
- Django 5.2
- Channels 4 + Daphne
- MySQL (single `default` database)
- HTMX
- Tailwind CSS (locally built static CSS)
- OpenPyXL + ReportLab for exports

## Project Layout

- `backend/` — Django project
- `backend/stats/` — reports, dashboards, AMI integration, realtime logic
- `backend/settings/` — system settings and mappings
- `backend/templates/stats/` — Django templates/pages/partials
- `backend/static/` — CSS/JS assets
- `docker-compose.yml` — containerized run
- `deploy/deploy.sh` — unified deployment script
- `deploy/README.md` — deployment guide

## Prerequisites

- Docker + Docker Compose plugin
- Network access from app host to Asterisk MySQL and AMI
- AMI credentials with required permissions

## Configuration

`docker-compose.yml` uses environment variables for DB and app settings.

Common variables:
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DB_ENGINE` (`mysql`)
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`

AMI/settings values are managed from UI settings page (`/settings/`) and stored in DB.

## Run with Docker

From repository root:

```bash
docker compose up -d --build
```

Check:

```bash
docker ps
curl -I http://127.0.0.1:8000/login/
```

## Local Development (without Docker)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# set DB_* env vars
python manage.py migrate

# ASGI run (recommended)
daphne -b 0.0.0.0 -p 8000 queue_stats_backend.asgi:application
```

Open:
- `http://localhost:8000/login/`

## Realtime Data Flow

1. App connects to AMI using credentials from `GeneralSettings`.
2. Realtime worker syncs queue/member data into runtime tables.
3. UI page `/realtime/` subscribes to `/ws/htmx-realtime/`.
4. Server pushes OOB HTML fragments every few seconds.

Realtime counters include:
- Active calls
- Waiting calls
- Active operators

## Reporting & Analytics

Available pages:
- `Summary`
- `Answered`
- `Unanswered`
- `CDR` (with recording playback)
- `Dashboards` (Traffic / Queues / Operators)
- `Analytics`
- `Payouts`

Exports:
- XLSX and PDF for reports and dashboards
- Dashboard PDF exports include plots/charts

## Mapping and Naming

- Queue mapping: `QueueDisplayMapping`
- Agent mapping: `AgentDisplayMapping`
- Agent payout rate: `OperatorPayoutRate`

Display priority:
1. Manual mapping from UI (highest priority)
2. Auto-created mapping from AMI/PJSIP callerid sync

## Internationalization

Supported UI languages:
- `ru`
- `en`
- `uz`

Language is selected in `/settings/` (`ui_language`) and applied by middleware.

## Deployment

Use the unified deploy script:

```bash
./deploy/deploy.sh
```

Custom target example:

```bash
./deploy/deploy.sh --host tshttaster --remote-dir /opt/queue_stats --service backend --port 8000
```

Full deploy documentation:
- `deploy/README.md`

## TUI Server Install (Asterisk PBX Integration)

For first-time server installation with interactive setup (DB + AMI + AJAM + recordings path), run:

```bash
sudo ./deploy/install_tui.sh
```

What it does:
- asks all required integration values in TUI (`whiptail`/`dialog`, with CLI fallback)
- installs Docker/Compose dependencies on Debian/Ubuntu
- syncs project to target directory (default `/opt/queue_stats`)
- generates `.env` for `docker compose`
- starts backend, runs migrations, creates/updates admin user
- writes AMI/DB values into `GeneralSettings`

## Troubleshooting

### WebSocket shows 404
- Ensure backend runs ASGI (`daphne`), not `runserver` WSGI mode.
- Check container logs for `Listening on TCP address ...` from daphne.

### AMI connection error
- Verify AMI host/port/user/password in `/settings/`.
- Check Asterisk `manager.conf` permissions.
- Confirm network access to AMI port.

### Realtime page shows empty data
- Confirm AMI connection is successful.
- Verify there are active calls/queue events at that moment.
- Check logs for AMI event parsing/sync warnings.

### Session data corrupted after deploy
- Expected when old browser session cookie format/key mismatches new runtime.
- Re-login in browser.

## Security Notes

- Do not expose AMI publicly.
- Rotate credentials if shared in plaintext.
- Use HTTPS in production.
- Restrict `DJANGO_ALLOWED_HOSTS` to trusted hosts.
