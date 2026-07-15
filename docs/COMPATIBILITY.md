# FlintTrade — Supported Versions

> What FlintTrade is known to work with at runtime. These projects are
> NOT bundled with FlintTrade — you install them separately. This page
> tells you which versions are safe to install.

## External services

| Service | Role | Minimum | Latest tested | Upstream |
|---|---|---|---|---|
| **OpenAlgo** | Optional broker gateway (32 brokers, REST + WebSocket) | v2.0.0 | `7e48b2e8` (v2.0.1.1, 2026-05-21) | [marketcalls/openalgo](https://github.com/marketcalls/openalgo) |

**OpenAlgo minimum (v2.0.0):** required only when you enable the optional
OpenAlgo-compatible integration path. FlintTrade expects OpenAlgo's v2 API
surface there — depth mode 4 (50-level book), structured `closeposition`
with strategy id, `optionchain` greeks endpoint, and rate-limit headers
(`X-RateLimit-Remaining`). v1 deployments will fail the OpenAlgo integration
sanity check.

**AI-agent features are native.** FlintTrade drives agent backends in-process
via the `flinttrade_ai.agent_backends` registry (Claude Code, Cerebras, Codex,
and catalogued CLI/ACP runtimes). There is no external agent gateway to install
— the former OpenClaw bridge was removed and reimplemented natively.

**AlgoMirror is not on this list.** Its multi-account mirroring patterns are
reimplemented natively in `packages/services/ditto/` (PositionMirror,
TrailingSLManager, MarginCalculator, RiskManager — our own code) and run
in-process — FlintTrade does not call AlgoMirror at runtime. The upstream repo
is not tracked or pulled.

## Runtime stack

| Component | Minimum | Tested | Notes |
|---|---|---|---|
| Python | 3.12 | 3.12.x | 3.13/3.14 partially supported (sklearn / lightgbm import issues on Windows 3.14) |
| Node | 22 | 22.x | required for the terminal package, site package, and Playwright |
| Operating system | Windows 11, macOS 14, Ubuntu 22.04 | same | tested matrix in CI |

## Brokers

FlintTrade supports two broker paths: the recommended OpenAlgo-compatible bridge
and the native FlintTrade gateway. OpenAlgo is the primary/community-tested
broker path; the native path is beta and connectability is gated per broker by
live evidence. Dhan and Upstox are currently enabled in the app after
login/read verification against real accounts and emergency-planner coverage.
INDmoney is read-verified and its fail-closed emergency planner is locally
verified, but it remains disabled because INDstocks does not expose an authoritative
restart-time discriminator for active regular MARKET/LIMIT rows versus smart parents;
it also lacks a broker-atomic reduce-only close primitive, and a funded/live-market
order-safety proof is pending. Kotak Neo's fail-closed emergency planner is
locally verified, but the broker remains disabled pending its live TOTP/MPIN
login/read probe and funded/market-hours order-safety proof;
Groww remains disabled until its broker-specific blockers clear. Dhan and
Upstox use native SDK/API clients, Groww has the official
`growwapi` SDK pinned for attestation/reference parity while production calls use
FlintTrade's tested REST transport, and its approved-key probe now proves native
login/account reads while market-data/API permission, static IP, and order-safety
evidence remain pending. INDmoney is REST-only with a dashboard-generated token
that resets at the daily 06:00 IST dashboard cycle. Upstox Developer Apps
Analytics Access Tokens are treated as read-only native sessions; trading still
needs the OAuth/trading-capable token path. INDstocks' FAQ advertises an
`indstocks-sdk`, but no matching PyPI or npm
package exists yet, so there is deliberately no SDK pin for it. Kotak Neo has
adapter/mapping coverage plus a pinned-SDK-grounded emergency planner, but no
promoted native connect or live order proof yet. `uv run python scripts/sync_broker_sdk_refs.py --fail-on-drift` refreshes local SDK
source mirrors and PyPI artifacts under the gitignored `.local/sdk-audit/` cache
and fails if a locked SDK is behind upstream metadata; `uv.lock` and
`brokers.lock` remain the only tracked install/attestation sources. The
credential-replay login step, in-app credential capture (Settings →
Brokers), OAuth connect flow, and daily session refresh are built.
Closed-market/no-funds verification does not prove funded order execution; keep
order-placement claims scoped to the evidence collected.

For the OpenAlgo path, whatever broker version OpenAlgo supports is the
compatibility boundary. The broker list lives in [`flint.toml`](../flint.toml)
under `[packages]` / gateway metadata. The 2026-05 sync added
**IIFL Capital** as a distinct entry alongside the existing **IIFL** adapter.

### Surface added in v2.0.1.1

- **GTT (Good Till Triggered) orders** — `placegttorder`, `modifygttorder`,
  `cancelgttorder`, `gttorderbook`. Live broker support: Dhan + Zerodha.
  Other brokers return a clean 501 ("GTT orders are not supported for
  broker 'X' yet"). FlintTrade exposes these through the safety proxy
  at `/api/v1/orders/gtt-{place,modify,cancel}`.
- **New exchanges** — `NCO` (NSE Commodities), `MCX_INDEX`, `GLOBAL_INDEX`.
- **WhatsApp bot** — `POST /api/v1/whatsapp/notify`. FlintTrade exposes
  the outbound test endpoint at `/ft-api/api/v1/alerts/whatsapp/test`
  (blueprint prefix `/api/v1`, so the WSGI `/ft-api` strip resolves it to
  `/api/v1/alerts/whatsapp/test`).
- **opengreeks** — Rust-based replacement for `py_vollib`. Same response
  shape, ~12× faster on option-chain refresh. No FlintTrade change.

### Sandbox terminology

Upstream renamed "virtual / paper trading" to "sandbox trading" in
v2.0.0.6. API field names (`analyzer_status`, `analyzer_toggle`) were
left intact, so FlintTrade's client wrappers needed only docstring
updates. FlintTrade's own Explore / Practice / Live tri-mode is a
separate concept and stays named "Practice".

### Deployment security — `TRUST_PROXY_HEADERS`

Set `TRUST_PROXY_HEADERS=1` **only** when a trusted reverse proxy
(nginx, Caddy, Cloudflare) terminates the connection in front of
FlintTrade. The proxy MUST strip any client-supplied `X-Forwarded-For`
and append its own hop. When the env is unset (default) FlintTrade
reads `request.remote_addr` directly and the rate limiter,
brute-force tracker, and 404 abuse guard all see the real source IP.

> **Do not** enable this flag without a real reverse proxy in front.
> If you do, any client can send `X-Forwarded-For: 1.2.3.4` and
> trivially evade per-IP login lockout, rate limits, and the 404
> flood guard. The hop-count knobs are configurable via
> `TRUST_PROXY_HEADERS_X_FOR` (default `1`), `_X_PROTO` (default `1`),
> `_X_HOST` (default `0`), `_X_PORT` (default `0`), `_X_PREFIX`
> (default `0`). Match these to your proxy chain depth.

Mirrors the same security gate OpenAlgo added in v2.0.0.7 for its
`utils/ip_helper.py` (commit `d3e2e0ef`).

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
```

Install / refresh:

```bash
bash scripts/setup-test-deps.sh           # clone at "Latest tested" pins
bash scripts/setup-test-deps.sh --latest  # clone at HEAD of upstream main
bash scripts/setup-test-deps.sh --update  # git pull existing clones
```
