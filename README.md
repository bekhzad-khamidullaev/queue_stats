# Queue Stats (Django Monolith)

Единый Django-монолит без отдельного frontend-сервиса:
- Django Templates + HTMX
- WebSocket (Django Channels) для real-time обновлений
- Источник real-time данных: Asterisk AMI
- Источник отчётов и CDR: MySQL (одна `default` БД, без второго DB alias)
- Экспорт отчётов и CDR: Excel (`.xlsx`) и PDF

## Запуск локально

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# настройте DB_* и AMI_* переменные окружения
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Открыть UI: [http://localhost:8000/login/](http://localhost:8000/login/)

## Docker

```bash
docker compose up --build
```

## Экспорт

На странице дашборда доступны кнопки:
- `Answered XLSX/PDF`
- `CDR XLSX/PDF`

## Realtime

Дашборд подключается к `/ws/htmx-realtime/` и получает HTML OOB-фрагменты для живого обновления блоков очередей и активных звонков.

## Deploy

Production deploy script and guide are in `deploy/`:
- `deploy/deploy.sh`
- `deploy/README.md`
