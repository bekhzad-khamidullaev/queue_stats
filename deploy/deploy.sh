#!/usr/bin/env bash
set -euo pipefail

HOST="${DEPLOY_HOST:-tshttaster}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/opt/queue_stats}"
SERVICE="${DEPLOY_SERVICE:-backend}"
PORT="${DEPLOY_PORT:-8000}"
DB_HOST="${DEPLOY_DB_HOST:-}"
DB_NAME="${DEPLOY_DB_NAME:-}"
DB_USER="${DEPLOY_DB_USER:-}"
DB_PASSWORD="${DEPLOY_DB_PASSWORD:-}"
SUPERUSER_USERNAME="${DEPLOY_SUPERUSER_USERNAME:-admin}"
SUPERUSER_EMAIL="${DEPLOY_SUPERUSER_EMAIL:-admin@localhost}"
SUPERUSER_PASSWORD="${DEPLOY_SUPERUSER_PASSWORD:-}"
SKIP_SYNC="0"
SKIP_BUILD="0"
SKIP_SUPERUSER="0"

usage() {
  cat <<EOF
Unified deployment script for queue_stats.

Usage:
  ./deploy/deploy.sh [options]

Options:
  --host <ssh_host>         SSH host alias or user@host (default: tshttaster)
  --remote-dir <path>       Remote project directory (default: /opt/queue_stats)
  --service <name>          Compose service to build/restart (default: backend)
  --port <port>             Host HTTP port bind + health-check port (default: 8000)
  --db-host <host>          Override DB_HOST for compose runtime (default: use compose value)
  --db-name <name>          Override DB_NAME for compose runtime (default: use compose value)
  --db-user <user>          Override DB_USER for compose runtime (default: use compose value)
  --db-password <pass>      Override DB_PASSWORD for compose runtime (default: use compose value)
  --superuser-username <u>  Superuser username to ensure after deploy (default: admin)
  --superuser-email <email> Superuser email to ensure after deploy (default: admin@localhost)
  --superuser-password <p>  Optional superuser password; if omitted, set only on first creation
  --skip-sync               Skip rsync source sync step
  --skip-build              Skip compose build/restart step
  --skip-superuser          Skip superuser ensure step
  -h, --help                Show this help

Environment overrides:
  DEPLOY_HOST, DEPLOY_REMOTE_DIR, DEPLOY_SERVICE, DEPLOY_PORT,
  DEPLOY_DB_HOST, DEPLOY_DB_NAME, DEPLOY_DB_USER, DEPLOY_DB_PASSWORD,
  DEPLOY_SUPERUSER_USERNAME, DEPLOY_SUPERUSER_EMAIL, DEPLOY_SUPERUSER_PASSWORD
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
    --db-host)
      DB_HOST="${2:?missing value for --db-host}"; shift 2 ;;
    --db-name)
      DB_NAME="${2:?missing value for --db-name}"; shift 2 ;;
    --db-user)
      DB_USER="${2:?missing value for --db-user}"; shift 2 ;;
    --db-password)
      DB_PASSWORD="${2:?missing value for --db-password}"; shift 2 ;;
    --superuser-username)
      SUPERUSER_USERNAME="${2:?missing value for --superuser-username}"; shift 2 ;;
    --superuser-email)
      SUPERUSER_EMAIL="${2:?missing value for --superuser-email}"; shift 2 ;;
    --superuser-password)
      SUPERUSER_PASSWORD="${2:?missing value for --superuser-password}"; shift 2 ;;
    --skip-sync)
      SKIP_SYNC="1"; shift ;;
    --skip-build)
      SKIP_BUILD="1"; shift ;;
    --skip-superuser)
      SKIP_SUPERUSER="1"; shift ;;
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
  local cmd="${1:?missing remote command}"
  ssh "$HOST" "sh -lc $(printf '%q' "$cmd")"
}

compose_cmd() {
  run_remote "if docker compose version >/dev/null 2>&1; then echo 'docker compose'; elif command -v docker-compose >/dev/null 2>&1; then echo 'docker-compose'; else exit 127; fi"
}

ensure_superuser() {
  local su_user_q su_email_q su_password_q py_cmd_q
  su_user_q="$(printf '%q' "$SUPERUSER_USERNAME")"
  su_email_q="$(printf '%q' "$SUPERUSER_EMAIL")"
  su_password_q="$(printf '%q' "$SUPERUSER_PASSWORD")"
  py_cmd_q="$(printf '%q' "import os,secrets;from django.contrib.auth import get_user_model;User=get_user_model();username=os.environ['SU_USERNAME'];email=os.environ.get('SU_EMAIL','');raw_password=os.environ.get('SU_PASSWORD','');defaults={'email':email,'is_staff':True,'is_superuser':True};user,created=User.objects.get_or_create(username=username,defaults=defaults);changed=False;generated=bool(created and not raw_password);effective_password=(raw_password if raw_password else (secrets.token_urlsafe(16) if created else ''));changed=changed or (user.email!=email);user.email=email;changed=changed or (not user.is_staff);user.is_staff=True;changed=changed or (not user.is_superuser);user.is_superuser=True;has_role=hasattr(user,'role');changed=changed or (has_role and getattr(user,'role',None)!='admin');has_role and setattr(user,'role','admin');password_needed=bool(created or raw_password);password_needed and user.set_password(effective_password);changed=changed or password_needed;changed and user.save();print(f'SUPERUSER_READY username={username} created={created} password_set={password_needed}');generated and print(f'SUPERUSER_PASSWORD_GENERATED={effective_password}')")"

  log "Ensuring Django superuser: ${SUPERUSER_USERNAME}"
  run_remote "SU_USERNAME=${su_user_q} SU_EMAIL=${su_email_q} SU_PASSWORD=${su_password_q} docker exec -e SU_USERNAME -e SU_EMAIL -e SU_PASSWORD queue-stats-backend python manage.py shell -c ${py_cmd_q}"
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
  COMPOSE_CMD="$(compose_cmd)"
  COMPOSE_ENV="APP_PORT='${PORT}'"
  if [[ -n "$DB_HOST" ]]; then
    COMPOSE_ENV="DB_HOST='${DB_HOST}' ${COMPOSE_ENV}"
  fi
  if [[ -n "$DB_NAME" ]]; then
    COMPOSE_ENV="DB_NAME='${DB_NAME}' ${COMPOSE_ENV}"
  fi
  if [[ -n "$DB_USER" ]]; then
    COMPOSE_ENV="DB_USER='${DB_USER}' ${COMPOSE_ENV}"
  fi
  if [[ -n "$DB_PASSWORD" ]]; then
    COMPOSE_ENV="DB_PASSWORD='${DB_PASSWORD}' ${COMPOSE_ENV}"
  fi
  log "Building and restarting docker compose service: ${SERVICE}"
  run_remote "stale_ids=\$(docker ps -aq --filter 'name=queue-stats-backend' || true); if [ -n \"\$stale_ids\" ]; then docker rm -f \$stale_ids >/dev/null 2>&1 || true; fi"
  run_remote "cd '$REMOTE_DIR' && ${COMPOSE_ENV} ${COMPOSE_CMD} up -d --build '$SERVICE'"
  log "Compose update completed"
else
  log "Skipping compose build/restart (--skip-build)"
fi

log "Container status"
run_remote "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'"

if [[ "$SKIP_SUPERUSER" != "1" ]]; then
  ensure_superuser
else
  log "Skipping superuser ensure step (--skip-superuser)"
fi

log "HTTP health-check (http://127.0.0.1:${PORT}/login/)"
run_remote "curl -sSI 'http://127.0.0.1:${PORT}/login/' | head -n 8"

log "Recent backend logs"
run_remote "docker logs --tail 40 queue-stats-backend 2>&1"

log "Deploy finished successfully"
