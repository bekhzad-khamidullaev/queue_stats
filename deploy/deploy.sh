#!/usr/bin/env bash
set -euo pipefail

HOST="${DEPLOY_HOST:-tshttaster}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/opt/queue_stats}"
SERVICE="${DEPLOY_SERVICE:-backend}"
PORT="${DEPLOY_PORT:-8000}"
SKIP_SYNC="0"
SKIP_BUILD="0"

usage() {
  cat <<EOF
Unified deployment script for queue_stats.

Usage:
  ./deploy/deploy.sh [options]

Options:
  --host <ssh_host>         SSH host alias or user@host (default: tshttaster)
  --remote-dir <path>       Remote project directory (default: /opt/queue_stats)
  --service <name>          Compose service to build/restart (default: backend)
  --port <port>             Local container-exposed HTTP port for health-check (default: 8000)
  --skip-sync               Skip rsync source sync step
  --skip-build              Skip compose build/restart step
  -h, --help                Show this help

Environment overrides:
  DEPLOY_HOST, DEPLOY_REMOTE_DIR, DEPLOY_SERVICE, DEPLOY_PORT
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:?missing value for --host}"; shift 2 ;;
    --remote-dir)
      REMOTE_DIR="${2:?missing value for --remote-dir}"; shift 2 ;;
    --service)
      SERVICE="${2:?missing value for --service}"; shift 2 ;;
    --port)
      PORT="${2:?missing value for --port}"; shift 2 ;;
    --skip-sync)
      SKIP_SYNC="1"; shift ;;
    --skip-build)
      SKIP_BUILD="1"; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2 ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() {
  printf "[%s] %s\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

run_remote() {
  ssh "$HOST" "$@"
}

if [[ "$SKIP_SYNC" != "1" ]]; then
  log "Syncing source to ${HOST}:${REMOTE_DIR}"
  run_remote "mkdir -p '$REMOTE_DIR'"
  rsync -az --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'backend/node_modules' \
    --exclude 'frontend/node_modules' \
    "$ROOT_DIR/" "${HOST}:${REMOTE_DIR}/"
  log "Sync completed"
else
  log "Skipping rsync (--skip-sync)"
fi

if [[ "$SKIP_BUILD" != "1" ]]; then
  log "Building and restarting docker compose service: ${SERVICE}"
  run_remote "cd '$REMOTE_DIR' && docker compose up -d --build '$SERVICE'"
  log "Compose update completed"
else
  log "Skipping compose build/restart (--skip-build)"
fi

log "Container status"
run_remote "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'"

log "HTTP health-check (http://127.0.0.1:${PORT}/login/)"
run_remote "curl -sSI 'http://127.0.0.1:${PORT}/login/' | head -n 8"

log "Recent backend logs"
run_remote "docker logs --tail 40 queue-stats-backend 2>&1"

log "Deploy finished successfully"
