# Queue Stats

Queue Stats is a modernized call-center analytics dashboard:
- `backend/` - Django API and WebSocket services
- `frontend/` - React + Vite single-page application

Legacy PHP UI and related static assets were removed from this repository.

## Local Development

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend default URL: `http://localhost:5173`  
Backend default URL: `http://localhost:8000`

## Docker

```bash
docker compose up --build
```

## Tests

```bash
# backend
cd backend && python3 manage.py test

# frontend
cd frontend && npm run test -- --run
```

