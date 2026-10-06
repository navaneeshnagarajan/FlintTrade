# FlintTrade — Infrastructure & Deployment Design Spec

---

## 1. Design Principles

---

## 2. Service Architecture

---

## 3. Technology Choices (with justification)

### 3.1 Reverse Proxy: Nginx (not Caddy)

### 3.2 Process Management: gunicorn + eventlet + systemd

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
~/.flinttrade/audit/    (local audit trail)
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

---

## 4. Port Map (Final)

| Port | Service | Owner | Exposed | Notes |
|------|---------|-------|---------|-------|
| 80 | HTTP redirect | Nginx | Public | → 443 |
| 443 | HTTPS | Nginx | Public | Let's Encrypt auto |
| 5100 | Flask | FlintTrade | Internal | No IANA conflict |
| 5173 | Vite | FlintTrade | Dev only | Not in production |
| 3001 | HTTP | Uptime Kuma | Internal | Endpoint monitoring |
| 8000 | HTTP | Glitchtip | Internal | Error tracking |
| 9090 | HTTP | VictoriaLogs | Internal | Log aggregation |
| 19999 | HTTP | Netdata | Internal | System metrics |
| 51820 | UDP | WireGuard | Public | VPN tunnel |

---

### Pattern A: Docker Compose (recommended)

### Pattern B: Bare Metal (systemd)

### Pattern C: Home Server + VPN

Same as Pattern A or B, plus:
- WireGuard tunnel for remote access
- Self-signed cert OR Let's Encrypt via DDNS
- Access from phone/laptop via VPN IP

---

## 6. Setup Flow — git clone to running

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
