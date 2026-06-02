# Multi-User Mode

FlintTrade is primarily a personal-use, single-operator trading workstation.
The multi-user code path exists as an opt-in scaffold for contributors and lab
setups; it is not a hosted SaaS boundary.

## Enablement

Set:

```bash
FLINTTRADE_MULTI_USER=1
```

When enabled, the backend registers `/v1/users/*` routes and stores users in
`~/.flinttrade/auth.db`.

## Current Boundary

| Area | Current state |
|---|---|
| Users and roles | `admin`, `trader`, and `viewer` records are supported. |
| Passwords | Argon2 password hashes in SQLite. |
| Broker credentials | Do not share a live broker account across multiple untrusted users. |
| Data isolation | Full per-user workspace and broker-credential isolation is still a follow-up architecture item. |

Use multi-user mode only when every user is trusted with the machine and its
local data. For public or managed deployments, add per-user database isolation,
secret isolation, audit review, and operational runbooks before enabling live
broker support.
