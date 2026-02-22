#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="/opt/queue_stats"
APP_PORT="8000"
DJANGO_DEBUG="false"
DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1"
DJANGO_TIME_ZONE="UTC"

DB_HOST="127.0.0.1"
DB_PORT="3306"
DB_NAME="asteriskcdrdb"
DB_USER="queue_stats"
DB_PASSWORD=""

AMI_HOST="127.0.0.1"
AMI_PORT="5038"
AMI_USER="admin"
AMI_PASSWORD=""

ASTERISK_MONITOR_HOST_PATH="/var/spool/asterisk/monitor"
ASTERISK_MONITOR_PATH="/var/spool/asterisk/monitor/"
ASTERISK_AJAM_URL="http://127.0.0.1:8088/asterisk/rawman"
ASTERISK_AJAM_USERNAME="ajamuser"
ASTERISK_AJAM_SECRET=""
ASTERISK_AJAM_AUTHTYPE="plaintext"

ADMIN_USERNAME="admin"
ADMIN_EMAIL="admin@localhost"
ADMIN_PASSWORD=""

log() {
  printf "[%s] %s\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

if [[ "${EUID}" -ne 0 ]]; then
  die "Запусти скрипт от root (sudo ./deploy/install_tui.sh)."
fi

UI_BACKEND="plain"
if have_cmd whiptail; then
  UI_BACKEND="whiptail"
elif have_cmd dialog; then
  UI_BACKEND="dialog"
fi

ui_msg() {
  local title="${1:?title}"
  local text="${2:?text}"
  if [[ "$UI_BACKEND" == "whiptail" ]]; then
    whiptail --title "$title" --msgbox "$text" 12 78
  elif [[ "$UI_BACKEND" == "dialog" ]]; then
    dialog --title "$title" --msgbox "$text" 12 78
  else
    echo
    echo "[$title] $text"
    echo
  fi
}

ui_input() {
  local __var_name="${1:?var_name}"
  local title="${2:?title}"
  local text="${3:?text}"
  local default_value="${4:-}"
  local value

  if [[ "$UI_BACKEND" == "whiptail" ]]; then
    value="$(whiptail --title "$title" --inputbox "$text" 12 90 "$default_value" 3>&1 1>&2 2>&3)" || return 1
  elif [[ "$UI_BACKEND" == "dialog" ]]; then
    value="$(dialog --stdout --title "$title" --inputbox "$text" 12 90 "$default_value")" || return 1
  else
    read -r -p "$title - $text [$default_value]: " value
    value="${value:-$default_value}"
  fi

  printf -v "$__var_name" "%s" "$value"
}

ui_password() {
  local __var_name="${1:?var_name}"
  local title="${2:?title}"
  local text="${3:?text}"
  local value

  if [[ "$UI_BACKEND" == "whiptail" ]]; then
    value="$(whiptail --title "$title" --passwordbox "$text" 12 90 3>&1 1>&2 2>&3)" || return 1
  elif [[ "$UI_BACKEND" == "dialog" ]]; then
    value="$(dialog --stdout --title "$title" --insecure --passwordbox "$text" 12 90)" || return 1
  else
    read -r -s -p "$title - $text: " value
    echo
  fi

  printf -v "$__var_name" "%s" "$value"
}

ui_yesno() {
  local title="${1:?title}"
  local text="${2:?text}"
  local default="${3:-yes}"

  if [[ "$UI_BACKEND" == "whiptail" ]]; then
    if [[ "$default" == "no" ]]; then
      whiptail --defaultno --title "$title" --yesno "$text" 12 90
    else
      whiptail --title "$title" --yesno "$text" 12 90
    fi
  elif [[ "$UI_BACKEND" == "dialog" ]]; then
    if [[ "$default" == "no" ]]; then
      dialog --defaultno --title "$title" --yesno "$text" 12 90
    else
      dialog --title "$title" --yesno "$text" 12 90
    fi
  else
    local answer
    if [[ "$default" == "no" ]]; then
      read -r -p "$title - $text [y/N]: " answer
      [[ "$answer" =~ ^[Yy]$ ]]
    else
      read -r -p "$title - $text [Y/n]: " answer
      [[ ! "$answer" =~ ^[Nn]$ ]]
    fi
  fi
}

mask_secret() {
  local value="${1:-}"
  if [[ -z "$value" ]]; then
    echo "<empty>"
  elif [[ "${#value}" -le 4 ]]; then
    echo "****"
  else
    echo "${value:0:2}****${value: -2}"
  fi
}

install_dependencies() {
  if ! have_cmd apt-get; then
    die "Поддерживается только Debian/Ubuntu (нужен apt-get)."
  fi

  log "Installing OS dependencies..."
  apt-get update
  apt-get install -y ca-certificates curl git rsync

  if ! have_cmd docker; then
    apt-get install -y docker.io
  fi

  if ! docker compose version >/dev/null 2>&1; then
    apt-get install -y docker-compose-plugin || true
  fi

  if ! docker compose version >/dev/null 2>&1 && ! have_cmd docker-compose; then
    apt-get install -y docker-compose
  fi

  if ! have_cmd whiptail && ! have_cmd dialog; then
    apt-get install -y whiptail || true
  fi

  systemctl enable docker >/dev/null 2>&1 || true
  systemctl start docker >/dev/null 2>&1 || true
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
    return 0
  fi
  if have_cmd docker-compose; then
    docker-compose "$@"
    return 0
  fi
  die "Docker Compose не найден."
}

ensure_required() {
  [[ -n "$INSTALL_DIR" ]] || die "INSTALL_DIR не должен быть пустым."
  [[ -n "$APP_PORT" ]] || die "APP_PORT не должен быть пустым."
  [[ -n "$DJANGO_ALLOWED_HOSTS" ]] || die "DJANGO_ALLOWED_HOSTS не должен быть пустым."

  [[ -n "$DB_HOST" ]] || die "DB_HOST не должен быть пустым."
  [[ -n "$DB_PORT" ]] || die "DB_PORT не должен быть пустым."
  [[ -n "$DB_NAME" ]] || die "DB_NAME не должен быть пустым."
  [[ -n "$DB_USER" ]] || die "DB_USER не должен быть пустым."
  [[ -n "$DB_PASSWORD" ]] || die "DB_PASSWORD не должен быть пустым."

  [[ -n "$AMI_HOST" ]] || die "AMI_HOST не должен быть пустым."
  [[ -n "$AMI_PORT" ]] || die "AMI_PORT не должен быть пустым."
  [[ -n "$AMI_USER" ]] || die "AMI_USER не должен быть пустым."
  [[ -n "$AMI_PASSWORD" ]] || die "AMI_PASSWORD не должен быть пустым."

  [[ -n "$ASTERISK_MONITOR_HOST_PATH" ]] || die "ASTERISK_MONITOR_HOST_PATH не должен быть пустым."
  [[ -n "$ASTERISK_MONITOR_PATH" ]] || die "ASTERISK_MONITOR_PATH не должен быть пустым."

  [[ -n "$ADMIN_USERNAME" ]] || die "ADMIN_USERNAME не должен быть пустым."
  [[ -n "$ADMIN_EMAIL" ]] || die "ADMIN_EMAIL не должен быть пустым."
  [[ -n "$ADMIN_PASSWORD" ]] || die "ADMIN_PASSWORD не должен быть пустым."
}

collect_inputs() {
  ui_msg "Queue Stats Installer" "Интерактивная установка Queue Stats и настройка интеграции с Asterisk PBX."

  ui_input INSTALL_DIR "Путь установки" "Куда установить проект на сервере?" "$INSTALL_DIR" || exit 1
  ui_input APP_PORT "HTTP порт" "Порт приложения на сервере." "$APP_PORT" || exit 1
  ui_input DJANGO_ALLOWED_HOSTS "ALLOWED_HOSTS" "Список хостов через запятую (для Django)." "$DJANGO_ALLOWED_HOSTS" || exit 1
  ui_input DJANGO_TIME_ZONE "Timezone" "Таймзона Django (например, UTC или Asia/Tashkent)." "$DJANGO_TIME_ZONE" || exit 1

  if ui_yesno "DEBUG" "Включить DJANGO_DEBUG=true?" "no"; then
    DJANGO_DEBUG="true"
  else
    DJANGO_DEBUG="false"
  fi

  ui_input DB_HOST "Asterisk DB Host" "Хост MySQL с таблицами cdr/queuelog." "$DB_HOST" || exit 1
  ui_input DB_PORT "Asterisk DB Port" "Порт MySQL." "$DB_PORT" || exit 1
  ui_input DB_NAME "Asterisk DB Name" "Имя БД Asterisk." "$DB_NAME" || exit 1
  ui_input DB_USER "Asterisk DB User" "Пользователь БД." "$DB_USER" || exit 1
  ui_password DB_PASSWORD "Asterisk DB Password" "Пароль БД." || exit 1

  ui_input AMI_HOST "AMI Host" "Хост Asterisk AMI (manager.conf)." "$AMI_HOST" || exit 1
  ui_input AMI_PORT "AMI Port" "Порт AMI." "$AMI_PORT" || exit 1
  ui_input AMI_USER "AMI User" "Пользователь AMI." "$AMI_USER" || exit 1
  ui_password AMI_PASSWORD "AMI Password" "Пароль AMI." || exit 1

  ui_input ASTERISK_MONITOR_HOST_PATH "Recordings Host Path" "Путь к записям на хосте (Asterisk monitor)." "$ASTERISK_MONITOR_HOST_PATH" || exit 1
  ui_input ASTERISK_MONITOR_PATH "Recordings Container Path" "Путь к записям внутри контейнера." "$ASTERISK_MONITOR_PATH" || exit 1
  ui_input ASTERISK_AJAM_URL "AJAM URL" "URL для AJAM (если используется)." "$ASTERISK_AJAM_URL" || exit 1
  ui_input ASTERISK_AJAM_USERNAME "AJAM Username" "Пользователь AJAM." "$ASTERISK_AJAM_USERNAME" || exit 1
  ui_password ASTERISK_AJAM_SECRET "AJAM Secret" "Пароль/secret AJAM." || exit 1
  ui_input ASTERISK_AJAM_AUTHTYPE "AJAM AuthType" "Тип авторизации AJAM (обычно plaintext)." "$ASTERISK_AJAM_AUTHTYPE" || exit 1

  ui_input ADMIN_USERNAME "Admin Username" "Логин администратора Queue Stats." "$ADMIN_USERNAME" || exit 1
  ui_input ADMIN_EMAIL "Admin Email" "Email администратора." "$ADMIN_EMAIL" || exit 1
  ui_password ADMIN_PASSWORD "Admin Password" "Пароль администратора." || exit 1
}

write_env_file() {
  local env_path="${INSTALL_DIR}/.env"
  umask 077
  cat >"$env_path" <<EOF
APP_PORT=${APP_PORT}
DJANGO_DEBUG=${DJANGO_DEBUG}
DJANGO_ALLOWED_HOSTS=${DJANGO_ALLOWED_HOSTS}
DJANGO_TIME_ZONE=${DJANGO_TIME_ZONE}
DB_ENGINE=mysql
DB_HOST=${DB_HOST}
DB_PORT=${DB_PORT}
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
ASTERISK_MONITOR_HOST_PATH=${ASTERISK_MONITOR_HOST_PATH}
ASTERISK_MONITOR_PATH=${ASTERISK_MONITOR_PATH}
ASTERISK_AJAM_URL=${ASTERISK_AJAM_URL}
ASTERISK_AJAM_USERNAME=${ASTERISK_AJAM_USERNAME}
ASTERISK_AJAM_SECRET=${ASTERISK_AJAM_SECRET}
ASTERISK_AJAM_AUTHTYPE=${ASTERISK_AJAM_AUTHTYPE}
EOF
  chmod 600 "$env_path"
}

sync_project() {
  mkdir -p "$INSTALL_DIR"
  rsync -az --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'backend/node_modules' \
    --exclude 'frontend/node_modules' \
    "${PROJECT_ROOT}/" "${INSTALL_DIR}/"
}

run_compose_stack() {
  cd "$INSTALL_DIR"
  compose up -d --build backend
  compose exec -T backend python manage.py migrate
}

ensure_admin() {
  cd "$INSTALL_DIR"
  compose exec -T \
    -e "SU_USERNAME=${ADMIN_USERNAME}" \
    -e "SU_EMAIL=${ADMIN_EMAIL}" \
    -e "SU_PASSWORD=${ADMIN_PASSWORD}" \
    backend python manage.py shell -c "import os; from django.contrib.auth import get_user_model; U=get_user_model(); u,created=U.objects.get_or_create(username=os.environ['SU_USERNAME'], defaults={'email': os.environ['SU_EMAIL'], 'is_staff': True, 'is_superuser': True}); u.email=os.environ['SU_EMAIL']; u.is_staff=True; u.is_superuser=True; u.set_password(os.environ['SU_PASSWORD']); u.save(); print(f'SUPERUSER_READY created={created}')"
}

seed_general_settings() {
  cd "$INSTALL_DIR"
  compose exec -T \
    -e "QS_DB_HOST=${DB_HOST}" \
    -e "QS_DB_PORT=${DB_PORT}" \
    -e "QS_DB_NAME=${DB_NAME}" \
    -e "QS_DB_USER=${DB_USER}" \
    -e "QS_DB_PASSWORD=${DB_PASSWORD}" \
    -e "QS_AMI_HOST=${AMI_HOST}" \
    -e "QS_AMI_PORT=${AMI_PORT}" \
    -e "QS_AMI_USER=${AMI_USER}" \
    -e "QS_AMI_PASSWORD=${AMI_PASSWORD}" \
    backend python manage.py shell -c "import os; from settings.models import GeneralSettings; s,_=GeneralSettings.objects.get_or_create(pk=1); s.db_host=os.environ['QS_DB_HOST']; s.db_port=int(os.environ['QS_DB_PORT']); s.db_name=os.environ['QS_DB_NAME']; s.db_user=os.environ['QS_DB_USER']; s.db_password=os.environ['QS_DB_PASSWORD']; s.ami_host=os.environ['QS_AMI_HOST']; s.ami_port=int(os.environ['QS_AMI_PORT']); s.ami_user=os.environ['QS_AMI_USER']; s.ami_password=os.environ['QS_AMI_PASSWORD']; s.save(); print('GENERAL_SETTINGS_UPDATED')"
}

health_check() {
  local url="http://127.0.0.1:${APP_PORT}/login/"
  local i
  for i in {1..20}; do
    if curl -fsS -o /dev/null "$url"; then
      log "Health check OK: $url"
      return 0
    fi
    sleep 2
  done
  die "Сервис не отвечает по $url"
}

show_summary() {
  local text
  text=$(
    cat <<EOF
Установка завершена.

Путь: ${INSTALL_DIR}
URL: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${APP_PORT}/login/

DB: ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}
DB_PASSWORD: $(mask_secret "$DB_PASSWORD")

AMI: ${AMI_USER}@${AMI_HOST}:${AMI_PORT}
AMI_PASSWORD: $(mask_secret "$AMI_PASSWORD")

AJAM: ${ASTERISK_AJAM_URL}
AJAM_USER: ${ASTERISK_AJAM_USERNAME}
AJAM_SECRET: $(mask_secret "$ASTERISK_AJAM_SECRET")

Admin: ${ADMIN_USERNAME} (${ADMIN_EMAIL})
EOF
  )
  ui_msg "Queue Stats Installer" "$text"
}

main() {
  collect_inputs
  ensure_required

  if ! ui_yesno "Подтверждение" "Начать установку с указанными параметрами?" "yes"; then
    die "Установка отменена пользователем."
  fi

  install_dependencies
  sync_project
  write_env_file
  run_compose_stack
  ensure_admin
  seed_general_settings
  health_check
  show_summary
}

main "$@"
