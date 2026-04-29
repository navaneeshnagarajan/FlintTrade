# FlintTrade — Supported Versions

> What FlintTrade is known to work with at runtime. These projects are
> NOT bundled with FlintTrade — you install them separately. This page
> tells you which versions are safe to install.

## External services

| Service | Role | Minimum | Latest tested | Upstream |
|---|---|---|---|---|
| **OpenAlgo** | Broker gateway (33 brokers, REST + WebSocket) | v2.0.0 | `08c2a553` (2026-04-23) | [marketcalls/openalgo](https://github.com/marketcalls/openalgo) |
| **OpenClaw** | Optional AI agent gateway (Telegram / WhatsApp) | (any) | `8c4ecf42` (2026-04-19) | [openclaw/openclaw](https://github.com/openclaw/openclaw) |
| **AlgoMirror** | Multi-account mirroring patterns (reference only) | (n/a) | `fa063e2` (2026-04-19) | [marketcalls/algomirror](https://github.com/marketcalls/algomirror) |

**OpenAlgo minimum (v2.0.0):** required for the v2 API surface FlintTrade
relies on — depth mode 4 (50-level book), structured `closeposition` with
strategy id, `optionchain` greeks endpoint, and the rate-limit headers
(`X-RateLimit-Remaining`). v1 deployments will fail FlintTrade's startup
sanity check.

**AlgoMirror — reference only:** FlintTrade does not call AlgoMirror at
runtime. Patterns from upstream were absorbed into `packages/ditto/`.
The "latest tested" column is the version those patterns were ported
from; bumping it has no end-user impact.

**OpenClaw — optional:** only needed when AI-agent features are enabled
in `~/.flinttrade/workspace.json`. Default install does not require it.

## Runtime stack

| Component | Minimum | Tested | Notes |
|---|---|---|---|
| Python | 3.11 | 3.12.x | 3.13/3.14 partially supported (sklearn / lightgbm import issues on Windows 3.14) |
| Node | 20 | 22.x | required for the terminal package + Playwright |
| Operating system | Windows 11, macOS 14, Ubuntu 22.04 | same | tested matrix in CI |

## Brokers

FlintTrade itself does not connect to brokers — OpenAlgo does. Whatever
broker version OpenAlgo supports, FlintTrade supports. The 33-broker
list lives in [`flint.toml`](../flint.toml) under `[brokers]`.

## Bumping these

The "Latest tested" column is what we last verified end-to-end. There is
**no automated drift check** in CI — bumping a pin is a manual action:

1. Pull the new upstream version locally (`cd .local/external/<svc> && git pull`).
2. Run FlintTrade's integration test paths against it.
3. If green, update the commit hash + date in this file.
4. If anything broke, either patch FlintTrade or roll back and file an
   issue.

The defaults in `scripts/setup-test-deps.sh` should match the "Latest
tested" column.

## Where the local clones live

Cloned to `.local/external/` (gitignored). Not shipped, not required —
they exist for contributors who want to run the integration test paths.

```
.local/external/openalgo/
.local/external/algomirror/
.local/external/openclaw/
```

Install / refresh:

```bash
bash scripts/setup-test-deps.sh           # clone at "Latest tested" pins
bash scripts/setup-test-deps.sh --latest  # clone at HEAD of upstream main
bash scripts/setup-test-deps.sh --update  # git pull existing clones
```
