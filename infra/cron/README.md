# Cron Jobs

Scheduled system tasks. Broker authentication is handled by OpenAlgo (not by cron jobs here).

| Job | Schedule | Purpose |
|-----|----------|---------|
| health-check | Every 5 min | Ping OpenAlgo /api/v1/ping, alert on failure |
| backup | Daily 4:00 AM | Archive DuckDB files and audit logs |
| ddns-watcher | Every 15 min | Update dynamic DNS if IP changes |

Note: Broker login is NOT automated here. Re-authenticate daily via the OpenAlgo web UI at http://127.0.0.1:5000.
