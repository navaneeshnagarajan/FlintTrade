# Cron Jobs

Scheduled system tasks. Broker authentication is handled by FlintTrade's broker
gateway or by an optional external OpenAlgo-compatible bridge, not by cron jobs
here.

| Job | Schedule | Purpose |
|-----|----------|---------|
| health-check | Every 5 min | Ping FlintTrade backend health, warn if the optional OpenAlgo bridge is unavailable |
| backup | Daily 4:00 AM | Archive DuckDB files and audit logs |
| ddns-watcher | Every 15 min | Update dynamic DNS if IP changes |

Note: Broker login is NOT automated here. Re-authenticate in FlintTrade's broker
gateway, or in the OpenAlgo web UI only when you have configured that optional
bridge.
