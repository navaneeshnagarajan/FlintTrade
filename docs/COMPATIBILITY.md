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
| Python | `>=3.12` | 3.12 on every per-push lane; 3.14 on the nightly target leg | The one-line installer provisions its own 3.12. sklearn / LightGBM extras can still fail to import on Windows 3.14 — those tests skip rather than define the floor. |
| Node | `>=22.22.2` | 22.x on per-push lanes; 24 on the nightly target leg | Floor is jsdom 30's engine requirement. Required for the terminal, site, desktop, and Playwright. |
| Operating system | Any platform that can provide Python `>=3.12` (Ubuntu 24.04 LTS is the Linux system-interpreter floor) | Per-push: Ubuntu (`ubuntu-latest` plus Electron on `ubuntu-24.04`). Nightly: macOS, Windows, and a fail-soft `ubuntu-26.04` preview. Desktop-release Linux build legs still use `ubuntu-22.04` images with a managed toolchain. | Ubuntu 22.04's *system* Python is 3.10 and cannot meet the source-install floor. The one-line installer sidesteps this by provisioning `~/.flinttrade/tools`. |

The Electron 44 desktop shell additionally requires **macOS 13 (Ventura) or
later** on Apple Silicon and Intel. Electron 44 dropped macOS 12 support; this
desktop requirement is separate from the Python/Node requirements for the
source-built web app. See [Desktop App](DESKTOP.md) and the
[Electron 44 release notes](https://www.electronjs.org/blog/electron-44-0).

For library purposes and exact resolved versions, see
[Technology Stack and Dependencies](TECH_STACK.md).

## Brokers

Broker connections use six native adapters: Dhan, Upstox, Kotak Neo,
INDmoney, Groww, and Delta Exchange. Availability remains evidence-gated. Native broker HTTP
mutations and reads remain frozen until Task 9D and Task 7C.2; a broker session
cannot currently be established through the terminal. Practice uses the local
sandbox. Funded Live placement remains unproven and fail-closed.

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
