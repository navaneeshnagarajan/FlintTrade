# FlintTrade — Supported Versions

> What FlintTrade is known to work with at runtime. These projects are
> NOT bundled with FlintTrade — you install them separately. This page
> tells you which versions are safe to install.

## Runtime stack

Floors and targets are declared once in `flint.toml`'s `[requirements]` table.
`tests/test_minimum_requirements_single_source.py` fails if a tracked manifest
disagrees. Per-push CI runs the **floor**; nightly
`nightly-cross-platform.yml` exercises the **target** (fail-soft).

| Component | Floor (must work) | What actually runs | Notes |
|---|---|---|---|
| Python | `>=3.14` | 3.14 on every lane | The one-line installer provisions its own Python 3.14. Optional sklearn / LightGBM extras can still skip when a platform wheel is missing; that does not lower the floor. |
| Node | `>=22.23.4` | 22.x on per-push lanes; 24 on the nightly target leg | Floor is the supported Node 22 release. Electron 45.2.3 bundles Node 24.22.2. Required for the terminal, site, desktop, and Playwright. |
| Operating system | Ubuntu 26.04 LTS | Per-push and release Linux legs: `ubuntu-26.04` (and `ubuntu-26.04-arm` for the arm64 installer). Nightly: macOS and Windows as well. Target 26.04. | The OS floor is the release that ships Python 3.14. The one-line installer provisions its own interpreter under `~/.flinttrade/tools`. |

The Electron 45 desktop shell additionally requires **macOS 13 (Ventura) or
later** on Apple Silicon and Intel. macOS 12 (Monterey) is not supported; this
desktop requirement is separate from the Python/Node requirements for the
source-built web app. See [Desktop App](DESKTOP.md) and the
[Electron 45 release notes](https://www.electronjs.org/blog/electron-45-0).

For library purposes and exact resolved versions, see
[Technology Stack and Dependencies](TECH_STACK.md).

## Brokers

Broker connections use six native adapters: Dhan, Upstox, Kotak Neo,
INDmoney, Groww, and Delta Exchange. A broker session cannot be started from the terminal today. Practice mode and example data work without a broker. Broker writes return 503 and broker reads return 409. Live order placement stays disabled unless it is explicitly unlocked and every safety layer passes.

INDmoney tokens reset at the daily 06:00 IST dashboard cycle. INDmoney and
Groww remain disabled until their existing activation blockers are cleared.
Delta Exchange stays disabled until live order-safety proof and a deadman
runtime proof exist. India and Global keys are not interchangeable.

### Sandbox terminology

FlintTrade Modes are Practice, Connected (read), and Live.
Example is sample data, not a Mode. Simulated fills stay named Practice.

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
