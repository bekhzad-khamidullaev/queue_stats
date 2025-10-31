# Production Deployment Guide

## Prerequisites

- Python 3.8+
- Node.js 18+
- Redis 6+ (for WebSocket scaling)
- MySQL/MariaDB (for Asterisk data)
- Asterisk PBX with AMI enabled

## Backend Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Environment Variables

Create `.env` file in backend directory:

```bash
DJANGO_ENV=production
SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=your-domain.com,www.your-domain.com

# Redis for Channel Layers
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# Database (will be configured via Django admin)
DATABASE_ENGINE=mysql  # or sqlite for testing
```

### 3. Database Migrations

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4. Configure Asterisk Connection

1. Access Django admin: `http://your-domain/admin/`
2. Navigate to **General Settings**
3. Configure:
   - **AMI Host**: localhost (or Asterisk server IP)
   - **AMI Port**: 5038
   - **AMI Username**: Your AMI username
   - **AMI Password**: Your AMI password
   - **Database settings** for Asterisk CDR/Queue logs

### 5. Run with Gunicorn + Daphne

**For HTTP (Django):**
```bash
gunicorn queue_stats_backend.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 4 \
  --timeout 120
```

**For WebSocket (Channels):**
```bash
daphne -b 0.0.0.0 -p 8001 queue_stats_backend.asgi:application
```

### 6. Nginx Configuration

```nginx
upstream django {
    server 127.0.0.1:8000;
}

upstream channels {
    server 127.0.0.1:8001;
}

server {
    listen 80;
    server_name your-domain.com;

    # Static files
    location /static/ {
        alias /path/to/backend/staticfiles/;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://channels;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Django API
    location / {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Frontend Setup

### 1. Build Production Bundle

```bash
cd frontend
npm install
npm run build
```

### 2. Serve Static Files

Copy `dist/` contents to your web server or use Nginx:

```nginx
server {
    listen 80;
    server_name your-frontend-domain.com;

    root /path/to/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy API requests to backend
    location /api/ {
        proxy_pass http://your-backend-domain:8000;
    }

    location /ws/ {
        proxy_pass http://your-backend-domain:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## Asterisk Configuration

### manager.conf

```ini
[general]
enabled = yes
port = 5038
bindaddr = 127.0.0.1

[queue_stats_user]
secret = your_secure_password_here
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.0
read = system,call,log,verbose,command,agent,user,config,dtmf,reporting,cdr,dialplan
write = system,call,log,verbose,command,agent,user,config,dtmf,reporting,cdr,dialplan
writetimeout = 5000
```

Reload configuration:
```bash
asterisk -rx "manager reload"
```

## Redis Setup

### Install Redis

```bash
# Ubuntu/Debian
sudo apt install redis-server

# CentOS/RHEL
sudo yum install redis

# Start Redis
sudo systemctl start redis
sudo systemctl enable redis
```

### Test Redis Connection

```bash
redis-cli ping
# Should return: PONG
```

## Systemd Services

### Django (Gunicorn)

Create `/etc/systemd/system/queue-stats-django.service`:

```ini
[Unit]
Description=Queue Stats Django Application
After=network.target redis.service

[Service]
Type=notify
User=www-data
WorkingDirectory=/path/to/backend
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/gunicorn \
  --bind 127.0.0.1:8000 \
  --workers 4 \
  queue_stats_backend.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

### Channels (Daphne)

Create `/etc/systemd/system/queue-stats-channels.service`:

```ini
[Unit]
Description=Queue Stats WebSocket Application
After=network.target redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/backend
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/daphne \
  -b 127.0.0.1 -p 8001 \
  queue_stats_backend.asgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

### Start Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable queue-stats-django queue-stats-channels
sudo systemctl start queue-stats-django queue-stats-channels
sudo systemctl status queue-stats-django queue-stats-channels
```

## Security Considerations

1. **AMI Access**
   - Never expose port 5038 to public internet
   - Use strong passwords
   - Limit permissions to minimum required

2. **Django Secret Key**
   - Generate secure random key: `python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'`
   - Never commit to version control

3. **HTTPS**
   - Use Let's Encrypt for SSL certificates
   - Force HTTPS in production

4. **CORS**
   - Configure allowed origins in Django settings
   - Limit to your frontend domain

5. **Database**
   - Use separate credentials for Asterisk DB (read-only if possible)
   - Encrypt sensitive data

## Monitoring

### Check Service Logs

```bash
# Django logs
sudo journalctl -u queue-stats-django -f

# Channels logs
sudo journalctl -u queue-stats-channels -f

# Redis logs
sudo journalctl -u redis -f
```

### Health Checks

- AMI Connection: `GET /api/ami/ping/`
- WebSocket: Check connection status in frontend
- Database: Monitor query performance

## Troubleshooting

### WebSocket Not Connecting

1. Check Redis is running: `redis-cli ping`
2. Verify Daphne service: `systemctl status queue-stats-channels`
3. Check Nginx WebSocket proxy configuration
4. Verify CHANNEL_LAYERS settings in Django

### AMI Connection Failed

1. Test AMI manually: `telnet localhost 5038`
2. Check Asterisk manager.conf
3. Verify credentials in Django admin
4. Check firewall rules

### High Memory Usage

1. Reduce Gunicorn workers
2. Limit event history in frontend (currently 100 events)
3. Monitor Redis memory usage
4. Check for WebSocket connection leaks

## Backup

### Database

```bash
# SQLite
cp backend/db.sqlite3 backup/db.sqlite3.$(date +%Y%m%d)

# MySQL
mysqldump -u user -p queue_stats > backup/queue_stats_$(date +%Y%m%d).sql
```

### Configuration

```bash
tar -czf backup/config_$(date +%Y%m%d).tar.gz \
  backend/queue_stats_backend/settings.py \
  backend/.env \
  /etc/systemd/system/queue-stats-*.service
```

## Scaling

### Multiple Workers

1. Install Redis (already done)
2. Set `DJANGO_ENV=production` in environment
3. Increase Gunicorn workers based on CPU: `workers = (2 x CPU cores) + 1`
4. Run multiple Daphne instances behind load balancer

### Load Balancing

Use Nginx upstream for multiple Daphne instances:

```nginx
upstream channels {
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
    server 127.0.0.1:8003;
}
```

## Maintenance

### Update Dependencies

```bash
cd backend
pip install -U -r requirements.txt
python manage.py migrate
sudo systemctl restart queue-stats-django queue-stats-channels
```

### Clear Old Events

Frontend automatically limits to 100 events. For backend cleanup, implement periodic task if storing events in database.

## Performance Tips

1. Enable Django's caching for API responses
2. Use CDN for static files
3. Compress WebSocket messages
4. Monitor and optimize database queries
5. Use connection pooling for MySQL
