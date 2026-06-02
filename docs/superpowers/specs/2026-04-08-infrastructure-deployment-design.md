# FlintTrade — Infrastructure & Deployment Design Spec

> **Date:** 2026-04-08
> **Author:** Navaneesh + Claude Code (research agents + OpenAlgo analysis)
> **Status:** Draft — awaiting approval
> **Scope:** Production infrastructure, deployment, monitoring, logging, backups
> **Principle:** Mirror OpenAlgo's deployment model. 100% open source. Deploy anywhere.

---

## 1. Design Principles

1. **Mirror OpenAlgo** — same deployment patterns, same toolchain (Nginx, gunicorn, systemd, Docker)
2. **100% open source** — every component MIT, Apache, AGPL, or BSD. No BSL/SSPL.
3. **Deploy anywhere** — NAS, Raspberry Pi, cloud VM, bare metal, Docker
4. **Single-user first** — no Kubernetes, no Elasticsearch, no Redis. Lightweight.
5. **5-minute setup** — `git clone && make setup && make start` (current v0.6.0-alpha flow; OpenAlgo is optional)
6. **Zero vendor lock-in** — self-hosted everything, user owns all data

---

## 2. Service Architecture

```
Internet / VPN
    │
    ▼
┌─────────────────────────────────────────┐
│  Nginx (reverse proxy + SSL)            │
│  :80 → redirect to :443                 │
│  :443 → auto HTTPS (Let's Encrypt)      │
│  :443/ws → WebSocket upgrade            │
└─────────┬───────────┬───────────────────┘
          │           │
    ┌─────▼─────┐ ┌───▼────────────┐ ┌──────────────┐
    │ React     │ │ FlintTrade     │ │ OpenAlgo     │
    │ (static)  │ │ Backend        │ │ (submodule)  │
    │ /dist     │ │ :5100          │ │ :5000 + :8765│
    │ served by │ │ gunicorn +     │ │ gunicorn +   │
    │ Nginx     │ │ eventlet       │ │ eventlet     │
    └───────────┘ └───────┬────────┘ └──────┬───────┘
                          │                  │
              ┌───────────▼──────────────────▼───────┐
              │  Data Layer                          │
              │  ~/.flinttrade/                      │
              │  ├── auth.db (SQLite — credentials)  │
              │  ├── credentials.db (Fernet enc)     │
              │  ├── flint.duckdb (analytics)        │
              │  ├── chroma/ (vector store)           │
              │  ├── audit/ (JSONL — SEBI 5yr)       │
              │  ├── logs/ (JSON structured logs)    │
              │  └── jwt_secret (auto-generated)     │
              └──────────────────────────────────────┘
              
              ┌──────────────────────────────────────┐
              │  Monitoring Layer                    │
              │  ├── Uptime Kuma :3001 (MIT)         │
              │  ├── Glitchtip :8000 (MIT)           │
              │  └── /admin route (built-in)         │
              └──────────────────────────────────────┘
```

---

## 3. Technology Choices (with justification)

### 3.1 Reverse Proxy: Nginx (not Caddy)

**Why Nginx over Caddy:**
- OpenAlgo uses Nginx — same toolchain, shared configs, proven patterns
- OpenAlgo's install scripts generate Nginx configs automatically
- certbot for Let's Encrypt is battle-tested
- FlintTrade and OpenAlgo share ONE Nginx instance

**Nginx routes:**
```
/              → React static files (dist/)
/api/          → OpenAlgo Flask (:5000)
/ft-api/       → FlintTrade Flask (:5100) — strip /ft-api prefix
/ws            → OpenAlgo WebSocket (:8765) — upgrade
```

### 3.2 Process Management: gunicorn + eventlet + systemd

**Why (mirrors OpenAlgo exactly):**
- gunicorn with eventlet worker (single worker for WebSocket state)
- systemd service files for auto-restart, journal logging
- Docker Compose as alternative for container deployments

**FlintTrade systemd service:**
```ini
[Unit]
Description=FlintTrade Backend
After=network.target openalgo.service

[Service]
User=www-data
WorkingDirectory=/opt/flinttrade
Environment="FLINTTRADE_DEV=0"
Environment="OPENBLAS_NUM_THREADS=2"
ExecStart=/opt/flinttrade/venv/bin/gunicorn \
  --worker-class eventlet -w 1 \
  --bind 127.0.0.1:5100 \
  --timeout 300 \
  packages.core.src.app:create_flask_app()
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3.3 Error Tracking: Glitchtip (MIT)

**Why Glitchtip (not Sentry):**
- MIT licence (Sentry server is BSL — not open source)
- Sentry SDK compatible — use `sentry-sdk` (MIT) for both Python and React
- Self-hosted via Docker: app container + worker + PostgreSQL
- ~256MB RAM, polished error dashboard
- Captures stack traces, user context, breadcrumbs, performance metrics

**Integration:**
- Python: `sentry_sdk.init(dsn="http://glitchtip:8000/...")` in app.py
- React: `Sentry.init()` in main.tsx with ErrorBoundary
- Same Sentry DSN format — just change the URL

### 3.4 Structured Logging: structlog (MIT)

**Why structlog:**
- Zero-dependency, drop-in replacement for stdlib logging
- JSON output with request context (user, mode, endpoint, timing)
- Processors chain: add timestamp → add request ID → add user → JSON format
- Integrates with Flask's request context

**Log pipeline:**
```
Flask request → structlog → JSON → ~/.flinttrade/logs/flinttrade.log
                                  → rotate daily (logrotate)
                                  → view in /admin (WebSocket stream)
                                  → backup via Restic
```

### 3.5 Monitoring: Netdata (GPL-3) + Uptime Kuma (MIT)

**Why two tools (they complement each other):**

**Netdata (GPL-3.0)** — system + application metrics:
- Per-second granularity, zero config, install and see everything
- CPU, RAM, disk, network, Python process metrics, Docker stats
- 88% less RAM than Prometheus, 36% less CPU
- Built-in alerting (Telegram, email, Slack, Discord)
- ~100-300MB RAM

**Uptime Kuma (MIT)** — endpoint monitoring + status page:
- MIT licence, single Docker container, SQLite
- ~128MB RAM, 90+ notification integrations
- Beautiful public/private status page
- Checks every 60s: OpenAlgo :5000, FlintTrade :5100, WS :8765, Nginx :443

### 3.6 Log Aggregation: VictoriaLogs (Apache 2.0)

**Why VictoriaLogs:**
- Apache 2.0 licence, single zero-config binary
- Auto-indexes ALL log fields (including high-cardinality: order_id, trace_id)
- 30x less RAM than Elasticsearch, significantly less than Loki
- Runs on a Raspberry Pi (~256-512MB RAM)
- Built-in query UI, or pair with Grafana
- Loki cannot handle high-cardinality fields (order IDs) — VictoriaLogs can

**Log pipeline:**
```
structlog → JSON → VictoriaLogs → query via UI or Grafana
                 → also written to ~/.flinttrade/logs/ as backup
```

### 3.6 Backup: Restic + Rclone (BSD-2)

**Why Restic:**
- Encrypted (AES-256), deduplicated, incremental
- Targets: local, S3, GCS, SFTP, Backblaze B2, any cloud via Rclone
- Tiny binary (~15MB), cross-platform
- Retention policy: 7 daily, 4 weekly, 12 monthly

**What's backed up:**
```
~/.flinttrade/          (auth.db, credentials.db, DuckDB, chroma, configs)
~/.flinttrade/audit/    (SEBI 5-year audit trail)
~/.flinttrade/logs/     (structured JSON logs)
/opt/flinttrade/.env    (environment config — encrypted at rest)
```

**Cron schedule:** Daily at 02:00 IST

### 3.7 CORS: flask-cors (MIT)

**Configuration:**
```python
CORS(app, origins=["https://your-domain.com"], 
     methods=["GET", "POST"], 
     allow_headers=["Content-Type", "X-API-Key", "X-FlintTrade-Mode"])
```

### 3.8 Rate Limiting: flask-limiter (MIT)

**Limits:**
- Auth endpoints: 5/minute per IP
- Order endpoints: 10/second (matches OpenAlgo)
- General API: 50/second
- Storage: in-memory (single-user, no Redis needed)

---

## 4. Port Map (Final)

| Port | Service | Owner | Exposed | Notes |
|------|---------|-------|---------|-------|
| 80 | HTTP redirect | Nginx | Public | → 443 |
| 443 | HTTPS | Nginx | Public | Let's Encrypt auto |
| 5000 | Flask | OpenAlgo | Internal | Primary instance |
| 5001-5009 | Flask | OpenAlgo | Internal | Multi-broker |
| 5100 | Flask | FlintTrade | Internal | No IANA conflict |
| 5173 | Vite | FlintTrade | Dev only | Not in production |
| 5555 | ZMQ | OpenAlgo | Internal | Inter-process |
| 8765 | WebSocket | OpenAlgo | Internal | Market data |
| 3001 | HTTP | Uptime Kuma | Internal | Endpoint monitoring |
| 8000 | HTTP | Glitchtip | Internal | Error tracking |
| 9090 | HTTP | VictoriaLogs | Internal | Log aggregation |
| 19999 | HTTP | Netdata | Internal | System metrics |
| 51820 | UDP | WireGuard | Public | VPN tunnel |

---

## 5. Deployment Patterns (mirrors OpenAlgo)

### Pattern A: Docker Compose (recommended)

```yaml
services:
  openalgo:
    image: python:3.12-slim
    ports: ["127.0.0.1:5000:5000", "127.0.0.1:8765:8765"]
    volumes: [openalgo_db:/app/db]
    
  flinttrade:
    image: python:3.12-slim
    ports: ["127.0.0.1:5100:5100"]
    volumes: [flinttrade_data:/data]
    depends_on: [openalgo]
    
  terminal:
    build: ./packages/apps/terminal
    # Static build served by Nginx, no runtime container needed
    
  nginx:
    image: nginx:alpine
    ports: ["80:80", "443:443"]
    volumes: [./infra/nginx:/etc/nginx/conf.d, certbot_data:/etc/letsencrypt]
    
  uptime-kuma:
    image: louislam/uptime-kuma:1
    ports: ["127.0.0.1:3001:3001"]
    volumes: [kuma_data:/app/data]
    restart: unless-stopped
    
  glitchtip:
    image: glitchtip/glitchtip:latest
    ports: ["127.0.0.1:8000:8000"]
    depends_on: [glitchtip-db]
    environment:
      - DATABASE_URL=postgres://glitchtip:glitchtip@glitchtip-db:5432/glitchtip
      - SECRET_KEY=${GLITCHTIP_SECRET_KEY}
    restart: unless-stopped
    
  glitchtip-worker:
    image: glitchtip/glitchtip:latest
    command: bin/run-celery-with-beat.sh
    depends_on: [glitchtip-db]
    environment:
      - DATABASE_URL=postgres://glitchtip:glitchtip@glitchtip-db:5432/glitchtip
      - SECRET_KEY=${GLITCHTIP_SECRET_KEY}
    restart: unless-stopped
    
  glitchtip-db:
    image: postgres:16-alpine
    volumes: [glitchtip_pg:/var/lib/postgresql/data]
    environment:
      - POSTGRES_USER=glitchtip
      - POSTGRES_PASSWORD=glitchtip
      - POSTGRES_DB=glitchtip
    restart: unless-stopped
    
  victorialogs:
    image: victoriametrics/victoria-logs:latest
    ports: ["127.0.0.1:9090:9090"]
    volumes: [victorialogs_data:/vlogs]
    restart: unless-stopped
    
  netdata:
    image: netdata/netdata:latest
    ports: ["127.0.0.1:19999:19999"]
    cap_add: [SYS_PTRACE, SYS_ADMIN]
    security_opt: [apparmor=unconfined]
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    restart: unless-stopped
```

### Pattern B: Bare Metal (systemd)

```bash
# 1. Install
git clone https://github.com/navaneeshnagarajan/FlintTrade.git /opt/flinttrade
cd /opt/flinttrade && make setup

# 2. Configure
cp .env.example .env && nano .env

# 3. Install services
sudo make install-native  # installs current FlintTrade service scripts

# 4. Start
make start  # starts the FlintTrade backend; start OpenAlgo separately only if enabled
```

### Pattern C: Home Server + VPN

Same as Pattern A or B, plus:
- WireGuard tunnel for remote access
- Self-signed cert OR Let's Encrypt via DDNS
- Access from phone/laptop via VPN IP

---

## 6. Setup Flow — git clone to running

```
1. git clone https://github.com/navaneeshnagarajan/FlintTrade.git
2. cd FlintTrade
3. make setup                    # installs Python + Node deps, builds React
4. cp .env.example .env          # configure optional integrations only when needed
5. make start                    # starts the FlintTrade backend
6. make start-openalgo           # optional: start a local-dev OpenAlgo clone when present
```

For Docker:
```
1. git clone ...
2. cp .env.example .env
3. docker compose up -d
4. open https://localhost
```

---

## 7. Auto-Update

**Note:** Watchtower was archived December 2025 — do NOT use.

**Docker:** What's Up Docker / WUD (MIT) — dashboard with click-to-update, notifications
**Bare metal:** GitHub webhook + deploy script:
  1. GitHub sends webhook on push to `main`
  2. Lightweight receiver (`webhook` — Go binary, 5MB, MIT) catches it
  3. Script: `git pull && pip install -r requirements.txt && npm run build && sudo systemctl restart flinttrade.target`
**Manual:** `make update` → same as above without webhook
**Database migrations:** auto-run on every startup (idempotent)

---

## 8. Live Log System

### Backend (Python)
- structlog → JSON → `~/.flinttrade/logs/flinttrade.log`
- Request context: user, mode, endpoint, duration, status code
- Rotate daily via logrotate

### Frontend (React)
- ErrorBoundary catches uncaught errors → POST /ft-api/v1/errors
- Console errors captured by Sentry SDK → Glitchtip

### /admin Live Viewer
- WebSocket stream from backend → /admin route
- Tail last 100 log entries
- Filter by level (ERROR, WARNING, INFO)
- Search by request ID, user, endpoint

---

## 9. Bug Tracking

- **GitHub Issues** — primary bug tracker (open source project)
- **Glitchtip** — automatic error capture with stack traces
- **In-app bug report** — Settings → Report Bug → pre-fills system info → creates GitHub issue via `gh` CLI or API

---

## 10. Files to Create

### New Files
- `infra/nginx/flinttrade.conf` — Nginx reverse proxy config
- `infra/systemd/flinttrade.service` — systemd unit
- `infra/systemd/openalgo.service` — systemd unit (mirrors OpenAlgo's)
- `infra/docker/Dockerfile` — multi-stage build
- `infra/docker/Dockerfile.terminal` — React build stage
- `infra/backup/backup.sh` — Restic backup script
- `infra/backup/restore.sh` — Restic restore script
- `infra/install/install-docker.sh` — Docker deployment installer
- `infra/install/install-native.sh` — Bare metal installer
- `Caddyfile` — REMOVED (using Nginx to match OpenAlgo)
- `docker-compose.yml` — UPDATED with correct ports + monitoring services

### Modified Files
- `packages/core/core/src/app.py` — add structlog, flask-cors, flask-limiter, Sentry
- `packages/apps/terminal/src/main.tsx` — add Sentry.init()
- `requirements.txt` — add structlog, flask-cors, flask-limiter, sentry-sdk
- `packages/apps/terminal/package.json` — add @sentry/react
- `Makefile` — add install-native, update, backup targets
- `.env.example` — add GLITCHTIP_DSN, BACKUP_TARGET, DOMAIN, VICTORIALOGS_URL

---

## 11. Licence Audit (Final)

Every component is verifiably open source:

| Component | Licence | Verified |
|-----------|---------|----------|
| Nginx | BSD-2 | ✅ |
| gunicorn | MIT | ✅ |
| eventlet | MIT | ✅ |
| certbot | Apache 2.0 | ✅ |
| Glitchtip | MIT | ✅ |
| sentry-sdk | MIT | ✅ |
| VictoriaLogs | Apache 2.0 | ✅ |
| Netdata | GPL-3.0 | ✅ |
| structlog | MIT | ✅ |
| flask-cors | MIT | ✅ |
| flask-limiter | MIT | ✅ |
| Uptime Kuma | MIT | ✅ |
| Restic | BSD-2 | ✅ |
| Rclone | MIT | ✅ |
| Watchtower | Apache 2.0 | ✅ |
| WUD (What's Up Docker) | MIT | ✅ |

**Zero BSL/SSPL/proprietary server components.**

---

## 12. Resource Requirements

| Deployment | Min RAM | Min Disk | CPU |
|-----------|---------|----------|-----|
| Dev (Windows / macOS) | 4GB | 2GB | 4 cores |
| Production (minimal) | 2GB | 5GB | 2 cores |
| Production (with monitoring) | 4GB | 10GB | 2 cores |
| Raspberry Pi 4 | 4GB | 16GB SD | 4 cores (ARM) |

---

*This spec supersedes all prior infrastructure discussions. Approved by user before implementation.*
