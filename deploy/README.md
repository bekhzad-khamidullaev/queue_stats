# Deploy README

## What it does
`deploy/deploy.sh` is a single deployment entrypoint that:
1. Syncs the current workspace to the remote server via `rsync`.
2. Rebuilds and restarts Docker Compose service(s).
3. Prints container status, HTTP health-check, and recent logs.

## Default target
- SSH host: `tshttaster`
- Remote project dir: `/opt/queue_stats`
- Compose service: `backend`
- Health-check URL: `http://127.0.0.1:8000/login/`

## Prerequisites
- Local machine has: `ssh`, `rsync`, `docker` client.
- Remote server has: Docker + Docker Compose plugin.
- SSH access to target host (for example via `~/.ssh/config` alias `tshttaster`).

## Usage
From repo root:

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

## Options

```bash
./deploy/deploy.sh \
  --host tshttaster \
  --remote-dir /opt/queue_stats \
  --service backend \
  --port 8000
```

- `--skip-sync`: skip `rsync` step
- `--skip-build`: skip `docker compose up -d --build`

## Environment overrides
You can set these instead of flags:
- `DEPLOY_HOST`
- `DEPLOY_REMOTE_DIR`
- `DEPLOY_SERVICE`
- `DEPLOY_PORT`

Example:

```bash
DEPLOY_HOST=tshttaster DEPLOY_REMOTE_DIR=/opt/queue_stats ./deploy/deploy.sh
```

## Notes
- `rsync --delete` is used intentionally to keep the remote tree identical to the local one.
- `.git`, `.venv`, and `node_modules` are excluded from sync.
- The script is safe to run repeatedly (idempotent for normal deploy flow).
