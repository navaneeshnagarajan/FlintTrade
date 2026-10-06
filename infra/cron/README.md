# Cron Jobs

Broker session refresh is managed by the native gateway lifecycle.

| Job | Schedule | Purpose |
|-----|----------|---------|
| health-check | Every 5 min | Ping FlintTrade backend health |
| backup | Daily 4:00 AM | Archive DuckDB files and audit logs |
| ddns-watcher | Every 15 min | Update dynamic DNS if IP changes |
