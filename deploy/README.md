# Deployment Guide

## 1) Interactive server installation (recommended for first run)

Run on target server:

```bash
sudo ./deploy/install_tui.sh
```

This installer:
- asks for DB, AMI, AJAM and recordings-path parameters
- installs Docker/Compose dependencies (Debian/Ubuntu)
- syncs project to install directory
- generates `.env`
- starts backend and runs migrations
- creates/updates Django admin user
- writes DB/AMI values to `GeneralSettings`

## 2) Routine deploy/update to remote host

Use:

```bash
./deploy/deploy.sh
```

Common example:

```bash
./deploy/deploy.sh --host user@server --remote-dir /opt/queue_stats --service backend --port 8000
```
