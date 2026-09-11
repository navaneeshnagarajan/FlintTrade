# FlintTrade User Guide

This guide walks you from a fresh install to local setup, sandbox workflows,
and Live-mode safeguard verification. The default reading order is top-to-bottom
— every section builds on the one before it. If you already have FlintTrade running, jump to the
[Workspace tour](#workspace-tour) or use the section list in the sidebar.

> **Beta software.** FlintTrade `v0.0.1` is not production ready and
> does not provide financial advice. Read [disclaimer.md](../disclaimer.md)
> before connecting a broker or switching to Live mode.

> **Multiple workflows, one local app.** FlintTrade has route groups for order
> workflow testing, portfolio-style records, and guided learning. Pick `/trade`,
> `/invest`, or `/learn` from the top bar to switch workspaces without losing
> context.

---

## 1. Installation

FlintTrade runs on Windows, macOS, and Linux (including Raspberry Pi). It is
a **self-hosted web app first**: one backend process serves the full terminal
UI and API on a single origin (port 5100), usable from any browser. The
desktop apps are convenience wrappers around that same backend for people who
prefer a one-click install.

### One-line install (recommended — no prerequisites)

The web-app installer runs in the shell your OS already ships (bash or zsh on
macOS and Linux, built-in PowerShell on Windows) and needs no other toolchain:
no Python, no Node, no git and no make.

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash
```

```powershell
# Windows 10/11
# Run in a normal (non-Administrator) PowerShell window
irm https://flinttrade.vercel.app/web-install.ps1 | iex
```

It provisions a pinned, checksum-verified toolchain (`uv`, Python 3.12, Node
and pnpm) under `~/.flinttrade/tools`, builds FlintTrade from a managed source
checkout at `~/.flinttrade/web-src/FlintTrade`, and installs a `flinttrade-web`
launcher — `~/.local/bin/flinttrade-web` on macOS and Linux,
`%LOCALAPPDATA%\Programs\FlintTradeWeb\flinttrade-web.cmd` plus a **FlintTrade
Web** Start Menu shortcut on Windows. The Electron desktop shell keeps its own
launcher, Start Menu entry and source checkout, so the two installs never
collide and can be run in either order. Open http://127.0.0.1:5100 and follow the first-time Setup flow
— no `.env` file is required.

Removing it again is covered in [Uninstall](#13-uninstall).

#### If the site is unreachable (repo-direct fallback)

Use this whenever the command above fails. The hosted URLs are only a redirect
to the scripts in this repository, so a site outage or a deployment without an
immutable source commit answers `503` — and piping that error page into a shell
does nothing useful. These commands fetch the same script straight from GitHub
and depend on no deployment:

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-web-install.sh | bash
```

```powershell
# Windows 10/11
# Run in a normal (non-Administrator) PowerShell window
irm https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-web-install.ps1 | iex
```

To read the script before running it, clone the repository and run it from the
checkout instead:

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
bash scripts/install/flinttrade-web-install.sh
```

On Windows, run the checkout copy with
`powershell -ExecutionPolicy Bypass -File scripts\install\flinttrade-web-install.ps1`.

### Run from source (contributors)

Use this when you are developing FlintTrade itself. It expects you to supply
the toolchain yourself: git, Python 3.12+, Node 22.22.2+, `uv` and `pnpm`.

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
uv sync
pnpm install
pnpm --filter @flinttrade/terminal build
python scripts/ft.py start
```

The same six lines run unchanged in Windows PowerShell — do not join them with
`&&`, which Windows PowerShell 5.1 does not support.
`python scripts/ft.py <target>` is the cross-platform runner (no make and no
bash needed); `make <target>` is the POSIX alias.

The terminal build step is not optional: the backend serves the UI only when
`packages/apps/terminal/dist/index.html` exists, so skipping it leaves you with
an API and no interface.

Docker (`make docker-up`) is an advanced, POSIX-only path — it needs make and
Docker, so it is not a zero-prerequisite way in. A `.env` file is optional:
the default profile starts the backend, the terminal build and nginx, and the
UI is served at http://localhost:8080 (override with `FLINTTRADE_HTTP_PORT`).

### Native desktop (Electron convenience shell)

The desktop package is a small Electron shell. It verifies pinned tools and
builds an inspectable local source checkout on first launch instead of
downloading a frozen backend payload. Its release contract is one universal
macOS DMG, one Windows x64 NSIS installer, Linux x64 and ARM64 AppImages, and
`SHA256SUMS.txt`.

The public [download surface](https://flinttrade.vercel.app/download)
distinguishes the source-built web-app install above from Electron-shell
installers. It withholds Electron commands and downloads unless one release
contains all four canonical installers plus `SHA256SUMS.txt`. For a release
that passes that gate, the supported commands are:

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/install.sh | bash
```

```powershell
# Windows 10/11
irm https://flinttrade.vercel.app/install.ps1 | iex
```

If the site is unreachable, the same desktop installer runs repo-direct — swap
`flinttrade-web-install` for `flinttrade-install` in the fallback commands under
[If the site is unreachable](#if-the-site-is-unreachable-repo-direct-fallback).

The installed shell builds the hash-verified, integrity-locked source on first
launch (progress on the splash; needs internet), creates the OS workspace, and
opens Setup only after the source guardian is healthy. Source/runtime updates
are staged and health-proved separately from Electron-shell installer updates.
Manual downloads and per-OS caveats are covered in [DESKTOP.md](DESKTOP.md).

The matching desktop uninstall is in [Uninstall](#13-uninstall).

Contributors can package the shell locally (these lines run unchanged in bash,
zsh and Windows PowerShell):

```bash
pnpm install --frozen-lockfile
python scripts/ft.py desktop-test
python scripts/ft.py desktop-package
```

On POSIX, `make desktop-test` and `make desktop-package` are aliases for the
same targets. Install the generated package from
`packages/apps/desktop/release/electron/`, launch FlintTrade, and follow the
first-time Setup flow. Local macOS output is always ad-hoc sealed and has no
Developer ID trust. Only release CI can use complete Apple
distribution-signing and notarisation secrets.

### Terminal dev server (contributors)

When you are changing terminal code, run the Vite dev server alongside the
backend instead of the built UI. It requires Python 3.12+, Node.js 22.22.2+, Git,
and optionally Rust for `core/ticks`.

```bash
python scripts/ft.py setup
python scripts/ft.py dev
```

Open `http://localhost:5173` once the dev server is ready. On POSIX,
`make setup` and `make dev` are aliases for the same targets.

### Platform-specific setup

For step-by-step instructions tailored to each operating system, see:

- [Windows setup](setup/windows.md)
- [macOS setup](setup/macos.md)
- [Linux setup](setup/linux.md)
- [Raspberry Pi setup](setup/raspberry-pi.md)
- [Quick start (cross-platform)](setup/QUICKSTART.md)

![Welcome screen](screenshots/01-welcome.png)
*The /welcome route — first-time cinematic introduction with persona pickers.*

---

## 2. First broker connection

FlintTrade supports two broker paths: the recommended OpenAlgo-compatible bridge
for users who already run OpenAlgo, and a first-party native gateway that is
**not usable on this unreleased line**. Native broker HTTP is frozen until
Task 9D (account mutations) and Task 7C.2 (read-port cutover). That is an
accepted product decision: native broker UX stays down on `main` until those
tasks land. The terminal still calls the frozen routes, so Setup → Brokers and
Settings → Brokers will fail rather than connect or refresh a native session.

Use the OpenAlgo-compatible bridge for a working broker session. Do not treat
the native Brokers screen, `/api/v1/native/*` writes, or native HTTP account
reads as a working operator path.

### Steps

1. **Use the OpenAlgo path.** The community-tested bridge is the working
   operator path. The native gateway is catalogued (Dhan and Upstox are
   evidence-gated as connectable; brokers shown as "coming soon" stay
   disabled) but its HTTP connect and read surfaces are frozen.
2. **Configure your broker in OpenAlgo.** Open `http://localhost:5000`,
   choose your broker from the dropdown, paste your API key and secret, and
   complete the broker's login flow (TOTP / OAuth / OTP — depends on the
   broker). OpenAlgo persists the session. Skip this step for Explore mode
   and Practice mode.
3. **Optional: generate an OpenAlgo API key.** From the OpenAlgo dashboard,
   copy the generated API key. This is the key FlintTrade uses for the
   OpenAlgo-compatible bridge only (not your broker's key).
4. **Set the OpenAlgo key in FlintTrade.** Open Setup → OpenAlgo Bridge, or
   Settings → Broker Gateway, then paste the OpenAlgo URL and API key. The app
   stores these settings in the OS workspace and hot-reloads the backend client.
   If the URL does not include a port, set REST Port (default `5000`); the
   WebSocket Port defaults to `8765`.
5. **Verify the bridge.** Use the Test Connection button in the same UI. Source
   contributors can open `http://localhost:5173/setup`; desktop users use the
   in-app setup window.

**Native HTTP freeze.** Broker-account mutations (`/v1` account and auth
writes, native connect / login / set-primary / delete, and OAuth start /
callback) return `503` with `broker_account_cutover_unavailable` until Task 9D
migrates the handlers. Native HTTP account and market-data reads return `409`
with zero provider calls until the Task 7C.2 / 8B cutover onto the in-process
`BrokerReadPort`. Exact broker reads that already exist are that in-process
port, not a working terminal Brokers screen. Service connections are an inert
control plane only.

When native connect returns, only Dhan and Upstox are evidence-gated as
enabled. Upstox Developer Apps analytics tokens would connect as read-only
sessions. INDmoney uses a dashboard-generated token that resets at the
daily 06:00 IST dashboard cycle, but remains disabled until its smart-parent,
atomic reduce-only, and live order-safety blockers clear. Kotak Neo and Groww
retain their displayed activation blockers; Kotak Neo still needs live
login/read and order-safety proof, and Groww may also require approving the
API-key session in Groww Cloud before FlintTrade can mint a token.
Localhost postback URLs are for diagnostics unless you expose FlintTrade through
a broker-reachable tunnel or public URL.

The Brokers screen also shows **Broker MCP assistants** for OpenAlgo, Dhan,
Upstox, and Groww when catalogue metadata is available. These cards copy the
broker-hosted MCP URLs and client configurations, and label read-only surfaces
such as Upstox MCP. Broker MCP tools run in the external MCP client; FlintTrade
automation and live order placement still use the guarded OpenAlgo path while
native HTTP remains frozen.

### Why two layers?

The two-layer design lets existing OpenAlgo users keep their broker setup while
FlintTrade keeps its own backend, native sandbox, analytics, automation, and a
first-party broker gateway whose HTTP connect and read surfaces are frozen
until Task 9D and Task 7C.2.

---

## 3. First sandbox order (Practice mode)

Before enabling any order-capable integration, exercise the order path in
**Practice mode**. FlintTrade has a three-mode system:

| Mode | Order behaviour | Best for |
|---|---|---|
| **Explore** | Demo/sample data; no Live broker order authority. On `/trade`, Order Pad **Practice Buy** opens a Practice review and records a local sample fill (no broker) | First-time visitors, screenshots, docs |
| **Practice** | Orders simulated by FlintTrade's native sandbox | Strategy tests and integration checks |
| **Live** | Real orders sent through the configured broker path | Gated broker integration, only after user review |

The current mode is shown in the top bar and is server-enforced via the JWT
claim — switching to Live requires a deliberate confirmation step.

### Walkthrough

1. Open `/trade` (http://127.0.0.1:5100/trade on the installed web app;
   http://localhost:5173/trade on the Vite dev server).
2. If the badge shows **EXPLORE**, you can stay there and try Order Pad
   **Practice Buy** — Practice review, then a local sample fill (no broker).
   For the full native-sandbox path this walkthrough uses, click the
   badge once to switch to Practice. There is no confirmation dialog.
   The UI calls `POST /v1/auth/mode` so the JWT matches.
3. From the dock sidebar, drag the **Order Pad** widget into the workspace
   (or pick a preset that contains it).
4. Type `NIFTY` into the symbol field; FlintTrade autocompletes the current
   front-month future. Select it.
5. Set Quantity = 1 lot (50). Choose **MARKET**. Side = **BUY**.
6. Click **Practice Buy** and confirm the Practice review. The order
   appears in the **Positions** widget immediately; the **Orders**
   widget shows it as filled (simulated).
7. Close the position from the Positions widget. Confirm your simulated
   P&L is recorded in the **P&L Monitor** widget.

You have just exercised the full FlintTrade order path — front-end → JWT
guard → mode guard → FlintTrade sandbox → simulated fill → REST
refresh of Positions and Orders. No real money moved.

![Trade workspace](screenshots/04-trade.png)
*The /trade workspace with FlexLayout tabs, order pad, positions, and chart.*

On Explore `/trade` Positions → Heat, **Group by Exchange** and
**Group by Sector** draw a labelled band per group (name chip plus
exposure when there is room). Flat stays leaf-only. Positions with no
exchange metadata show `No exchange groups in these positions` instead
of an undifferentiated treemap.

### Learn → Practice Trading (OpenAlgo)

This is a different path from the native Practice-mode sandbox on
`/trade` above. Explore `/learn` → **Practice Trading** walks through
OpenAlgo broker Practice / sandbox setup (Dhan Sandbox Active, ₹10L
virtual funds; Kotak Neo Sandbox Planned). The tab shows "How to start
Practice Trading", helper text "Configure OpenAlgo in Settings → Broker
Gateway.", and an **Open Settings → Broker Gateway** button that
navigates to `/settings#api`. The CTA does not send operators to
Settings → Brokers (`/settings#brokers`). Point the Broker Gateway at
that OpenAlgo Practice instance, trade against virtual funds, review
P&L, then point OpenAlgo at live credentials when ready.

On Explore `/learn` → Glossary → Lot Size, the glossary teaches dated
Jan 2026 NSE-cycle index lots (`NIFTY 65 · BANKNIFTY 30 · FINNIFTY 60 ·
MIDCPNIFTY 120 (as of Jan 2026 NSE cycle)`) plus a **Verify on NSE**
link to circular NSE/FAOP/70616. Learn market facts that exchanges
revise must ship dated, not as forever hardcodes.

---

## 4. Live-mode safeguard verification

Live mode can send real orders through a configured broker path. This guide
does not recommend or instruct a live order; use this section to verify the
software safeguards, prompts, and recovery controls in a local setup.

### Pre-flight checklist

- [ ] Broker or OpenAlgo session is current if you are intentionally testing a
      live-capable integration.
- [ ] Your FlintTrade JWT is fresh — it expires daily at 8 AM IST.
- [ ] The authenticator is enrolled, or you will confirm a one-time
      authenticator code in the Live switch dialog (if you chose **Set up
      later** during setup). Explore and Practice stay password-only until
      enrolment.
- [ ] An **exactly 6-digit** Security PIN is set under Settings → Security
      (`/settings#security`). Live cannot be armed until this PIN exists.
- [ ] The 5-layer safety system is active (see
      [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md#safety-layers)).
- [ ] Daily P&L pause and hard-stop percentages are configured in Settings → Risk.
- [ ] You have read the risk and user-responsibility notes in
      [disclaimer.md](../disclaimer.md).

### Walkthrough

1. Click the **PRACTICE** badge in the top bar, or select **Live** on
   the welcome mode picker. The dialog warns that real orders will be
   placed and asks for an **authenticator code** and your **exactly
   6-digit PIN**. Live unlock requires both — a confirmed authenticator
   enrolment plus the PIN. If you deferred 2FA with **Set up later**,
   enter a one-time authenticator code in the dialog to enrol, then the
   PIN. `POST /v1/auth/pin` with `mode: "live"` refuses 403
   `totp_required` until the authenticator is enabled. The PIN
   alone is not enough. Set the PIN under Settings → Security
   (`/settings#security`) first if you have not already — see
   [Settings reference](#11-settings-reference).
2. Cancel the modal unless you are deliberately performing your own broker-side
   test outside this guide.
3. Confirm the UI clearly shows Live mode, the active account, and the
   configured safety thresholds before any order-capable action is available.
4. Return to **Practice** mode and repeat the order-path walkthrough in the
   sandbox before continuing development work.

If anything looks wrong during live-capable testing, hit the **Kill Switch** on
the `/trade` workspace (Live mode only). Activate and reset also live under
`/automate` → Settings. It cancels open orders and asks the configured broker
path to close positions via the supported close-position endpoint. The kill
switch fires only when you explicitly activate it from the UI, API, or
configured Telegram command. Layer 4 daily-loss thresholds block subsequent new
orders but do not cancel orders or flatten positions.

---

## 5. Workspace tour

FlintTrade's workspace is a [FlexLayout](https://github.com/caplin/FlexLayout)
canvas. Every widget is a panel you can drag, tab, stack, float, or pop out
into its own window. Layouts persist in `workspace.json` inside your
platform-specific workspace directory and sync across sessions:

| Platform | Workspace directory |
|---|---|
| Linux | `~/.flinttrade/` |
| macOS | `~/Library/Application Support/flinttrade/` |
| Windows | `%APPDATA%\flinttrade\` |
| Override | `FLINTTRADE_WORKSPACE_DIR`, then `FLINTTRADE_HOME` |

See [Settings reference](#11-settings-reference) for what else lives there.

### The main routes

| Route | Purpose |
|---|---|
| `/welcome` | First-time cinematic introduction. After the first visit it is also the daily login screen (password only until an authenticator is enrolled; then password + TOTP, or PIN). Password sign-in also offers **Forgot your password?** — an email OTP reset that sends mail only when SMTP or SES is configured (see [email setup](setup/email.md)). Welcome and sign-in also offer **Try with sample data** so Explore stays reachable if setup is unfinished. There is no `/login` URL. |
| `/explore` | On the hosted public demo (`/demo-app/`), the sample-data landing. Installed web and desktop builds redirect `/explore` to `/welcome`; enter Explore from Welcome → **Try with sample data**. |
| `/setup` | First-time 7-step linear wizard (Account → optional authenticator → Persona → Broker → Trading → Risk → Choose Mode). After account create, **Set up later** continues Explore/Practice without enrolling 2FA. Daily login stays password-only until enrolment; Live still requires the authenticator and PIN. `/setup-account` is a compatibility alias. |
| `/home` | Default post-login overview — a Bento dashboard of persona-adaptive cards (Alt+H). Read-only discovery; order controls live on `/trade`. |
| `/settings` | Standalone settings page (workspace.json editor with form UI). |
| `/trade` | Order-workflow workspace — FlexLayout canvas, widgets, and presets (Alt+T). `/terminal` redirects here. |
| `/invest` | Portfolio-record workspace — holdings, net worth, SIPs, and mutual-fund tracker. Deep-link hashes such as `#holdings`, `#sip`, `#networth`, `#mutual-funds`, and `#mf-optimizer` open the matching tab on load; an unknown hash falls back to Dashboard. |
| `/learn` | Learning workspace — courses, glossary, examples, and sandbox workflows. Practice Trading links to Settings → Broker Gateway (`/settings#api`) for OpenAlgo Practice setup, not native Brokers. |
| `/lab` | Strategy Lab — backtest, forward test, optimise, Options Builder. |
| `/automate` | Automation Hub — flows, cron, monitors, logs. Kill-switch activate/reset lives under Automate → Settings. |
| `/ai` | AI Centre — chat, Suggest, signals, sentiment, RAG. |
| `/ditto` | Multi-account management — mirror, margin, risk. |
| `/admin` | Admin panel (development builds only) — security, health, traffic. `/admin/observability` is the same gate. |

On Explore `/invest#mutual-funds`, Mutual Fund Explorer labels the static
fixture `Sample NAVs · as of 10-Sep-2026` (from `EXPLORE_SAMPLE_NAV_DATE`)
and does not claim "Updated daily after market close." The as-of is the
fixture date and does not auto-update. Practice and Live keep the live
AMFI sentence ("Updated daily after market close") when the live feed is
in use.

### The widgets (71)

Widgets are organised into three categories — Trading / Analysis / Utility —
under `packages/apps/terminal/src/widgets/`. The lists below are generated
from the widget registry
(`packages/apps/terminal/src/layout/widgetFactory.tsx`) and are exhaustive:

- **Trading** — Scalper, Positions, Fills, P&L Monitor, Orders, Holdings,
  Order Pad, Action Centre, Trade Copier, Smart Order, Portfolio Allocation,
  Quick Trade, Risk, Strategy Monitor, DOM / Ladder, Forever (GTT) Orders,
  Super Orders, and Conditional Triggers
- **Analysis** — Chart, Market Overview, Option Chain, Historical Chain, OI
  Analytics, Straddle & Implied Move, Greeks, Dealer Gamma, Arbitrage
  Scanner, Pattern Detection, Tape & Microstructure, Vol Surface, IV Smile &
  Skew, Straddle P&L, Order Flow, Portfolio Optimiser, Condition Scanner,
  Pivot Points, Volatility Cone, VWAP Bands, Correlation Pairs, Multi-
  Timeframe, PCR Trend, Instrument Compare, Greeks Matrix, Gap Analysis,
  Correlation Matrix, Delivery Data, DOM Heatmap, Portfolio Pivot, and
  Seasonality
- **Utility** — Watchlist, Index Strip, Calculator, News Feed, Ticker, AI
  Advisor, AI Backends, AI Team, Obsidian Vault, Price Alerts,
  Reconciliation, Funding Rates, Currency Converter, Earnings Calendar,
  Strategy Templates, Audit Trail, Economic Calendar, Expiry Countdown,
  Market Clock, Trade Ideas, Tick Speed, and Journal Entries
Every widget is registered in `packages/apps/terminal/src/layout/widgetFactory.tsx`.

News Feed loads headlines only through the FlintTrade backend (`GET /api/v1/news`).
There is no browser-side RSS or CORS-proxy fallback. If the backend cannot
serve articles, the widget reports that news is unavailable from the
FlintTrade backend. Publisher profiles are MoneyControl, ET Markets, and
LiveMint.

### The 17 workspace presets

A preset is a pre-built layout you can apply instantly from the command
palette (Ctrl + K → "preset"). Built-in presets include:

- **Scalper Zone** — chart, order ladder, order pad, positions, scalper panel.
- **Options Desk** — option chain, chart, Greeks, positions, straddle P&L.
- **Market Watch** — multi-symbol watchlist, chart, price ticker, indices.
- **Analysis** — chart with indicators, OI analytics, positions, news.
- **Risk Monitor** — indices, risk, P&L monitor, positions, orders.
- **Trading Desk** — indices, positions, risk and orders; the composition that
  replaced the old Dashboard widget.
- **Three Panel** — CE, index and PE charts with synchronised time scales on
  the nearest-expiry ATM strikes.
- **Investor View** — chart, watchlist, holdings, indices (SIPs, net worth
  and mutual funds live on the Invest page).
- … plus nine more.

Presets are declarative FlexLayout documents. You can save your own custom
preset from Settings → Workspace.

---

## 6. Screener walkthrough

The screener lives under the **Analysis** widget category and shares the
workspace with everything else — no separate route. Headline tools:

### Option Chain

Streaming option-chain widget rendered with
[Glide Data Grid](https://github.com/glideapps/glide-data-grid) for
60+ FPS updates even on a 50-strike chain. The header also shows a
Max Pain badge derived from the same chain.

1. Drag the **Option Chain** widget into the workspace.
2. Pick a symbol (e.g. `NIFTY`, `BANKNIFTY`, `RELIANCE`).
3. The expiry row auto-fills from OpenAlgo's `/expiry` endpoint.
4. Calls on the left, Puts on the right, ATM strike highlighted.
5. Hover any cell — sparkline shows the last-100-tick history.

### OI Analytics

One widget (`oichart`) with several views of the same chain read:
grouped OI bars, a CE/PE butterfly **OI profile**, a strike heat grid,
build-up/unwinding signals, and a **Max Pain** view (the strike at
which option writers lose the least if expiry hit right now). There is
no standalone Max Pain widget.

### IV Smile & Skew

Implied-volatility curve across strikes, with 25-delta skew and
term-structure indicators. Useful for spotting unusual options activity.

---

## 7. Strategy Lab walkthrough

Open `/lab`. The Strategy Lab includes Backtest, Forward Test, Optimise,
and Options Builder.

### Backtest

1. **Pick a template.** 94 ready-to-run template modules ship under
   `packages/services/backtest/src/flinttrade_backtest/strategies/` — ranging
   from simple EMA crossover to complex options-spreads strategies
   (`_indicators.py` and `_mixin.py` are shared helpers, not templates).
2. **Configure parameters.** Each template exposes a parameter form
   (built with `react-hook-form` + `zod`).
3. **Pick a date range.** Historical OHLCV data is sourced from your
   configured providers (OpenChart, yfinance, or a licensed feed).
4. **Run.** The backtest engine is FlintTrade's native event-driven simulator
   (pure Python by default). Install the optional VectorBT extra for
   vectorised exploration, or opt in to the Rust `ticks` engine for
   tick-level precision.
5. **Review.** Equity curve, Sharpe, Sortino, max drawdown, win rate,
   trade list, Monte Carlo confidence band.

### Forward Test

Same as Backtest, but runs in Practice mode against live ticks. Use it to
validate the software path before any Live-mode use.

### Optimise

Walk-forward optimisation across a parameter grid. Outputs a heatmap of
performance per parameter combination plus an out-of-sample evaluation.

### Options Builder

Payoff needs a premium before it shows numbers. Open `/lab` →
**Options Builder** → **Payoff**. Until every leg has a premium, Max
Profit, Max Loss, Net Premium, and BEP(s) show `—`. Helper:
`Enter premium to model payoff`. A blank premium is unknown, not
zero-risk.

On Explore, the **Long Call** template seeds a **sample premium** from
the sample-chain ATM CE LTP, labelled `Sample premium — edit to model`.
Edit the field if you want a different cost. Other templates leave
premium blank so Payoff stays on that helper instead of modelling ₹0.

Typing an explicit ₹0 is allowed. Payoff then treats cost as free and
warns `Premium is ₹0 — payoff treats cost as free`.

![Lab](screenshots/06-lab.png)

---

## 8. Automation Hub walkthrough

Open `/automate`. Three sub-tools:

### Flows

Visual flow builder (drag-and-drop nodes) for "when X happens, do Y"
automations. Nodes include market-data events, broker events, and actions such
as sending a notification or running a local script.

### Cron

Time-based automations. Examples:

- Run pre-market screener at 9:00 AM IST every weekday.
- Snapshot positions to a CSV at 3:30 PM IST.
- Write a daily P&L summary to local storage at end-of-day.

Cron jobs run inside the FlintTrade backend (`packages/services/automation`).

### Monitors

**Live Strategy Monitors** lists running strategies and auto-refreshes
about every 5 seconds. You can stop a running strategy from this view.
When none are running, the empty state shows "No strategies running"
and "Start a strategy from the Strategy Builder tool.", plus an
**Open Strategy Builder** outline link that navigates to `/lab`.

On Explore `/automate` → Settings → Telegram Alerts, **Send Test** is
disabled (click and Enter do not send). The prefilled message stays
visible as a preview-only sample. Helper: "Telegram tests are blocked in
Explore (sample-only). Switch to Practice or Live with Telegram configured
to send a real test." There is no confirm-and-send path from Explore.
Practice and Live arm Send Test only when Telegram is configured; otherwise
the helper is "Configure Telegram first".

![Automate](screenshots/07-automate.png)

---

## 9. AI Centre walkthrough

Open `/ai`. Chat, Signals, Sentiment, and RAG are backed by
`packages/services/ai`. Suggest is a local filter UI over an illustrative
strategy list — not a live AI fetch.

### Chat

Local AI analysis and debugging tools. The default local provider is FlintTrade's
managed Ollama sidecar on a backend-only dynamic loopback endpoint. Settings -> AI
requires separate confirmation before downloading the pinned runtime or any model;
cloud and custom providers remain optional. Runtime update, rollback and uninstall
are offered only while Ollama is stopped. Uninstall preserves models and accepted
digests. The model inventory can delete one unselected model name or prune only
unused digest-locked aliases created by FlintTrade; configured models are protected.
If a timed-out mutation has an outcome FlintTrade cannot prove, Settings blocks
later runtime changes and shows the exact operation and admission IDs. Explicit
acknowledgement records that the unknown result was reviewed; it does not retry
the action or label it successful.

Chat itself needs a configured LLM via Settings → AI. The badge and composer
align with Settings → AI / `#llm` hydration as well as advisor status
(including Explore / `demo-user`), not a leftover local setting. When Explore
Settings `#llm` looks empty ("No LLM provider configured"), Chat shows
**Not configured** / **LLM not configured** — **Connected** must not appear
from an env-default advisor `configured` while Settings looks empty.
Returning to Chat after you save Settings → AI re-checks readiness (advisor
and Settings hydration), so the **Not configured** gate should not stay stuck
on an outdated result.

When unconfigured, the warning badge is **Not configured**, the empty state is
**LLM not configured**, the primary CTA **Open Settings → AI** opens
`/settings#llm`, and an outline **Retry** re-probes advisor status and
Settings `#llm` hydration. Composer input and Send stay disabled; there is no
send-then-no-reply path.

If leftover transcript messages hide that empty state while Chat is still
unconfigured, disconnected, or in error, the header still offers **Retry**
(re-check advisor status and Settings hydration) and **Open Settings → AI**.

A configured but broken probe shows **Error** or **Disconnected** with
**Retry** — never a green **Connected**. Explore does not show a fake
Connected sample advisor. Any later demo replies must be labelled
**Sample replies**. Signals **Live** / **Polling** stay separate from Chat
LLM readiness.

On Explore `/settings#llm`, a demo or unconfigured session shows the empty
state "No LLM provider configured" with **Retry** — not a broken load.
That Settings empty-state wording stays distinct from Chat's **LLM not
configured**; the two are aligned for readiness, so Chat also looks
unconfigured when Settings looks empty. Configure a provider in Live or
Practice on this machine; see
[Settings reference](#11-settings-reference).

### Suggest

**AI Strategy Suggestions** filters a local illustrative recommendation
list by Market Mood chips (**Volatile**, **Trending**, **Sideways**) and
your risk profile from persona and experience. Mood is a filter, not a
draft and not a live AI fetch.

Changing mood — a chip or **Next mood** — immediately replaces the
recommendation cards and clears any previously focused strategy card, so
chips, cards, and focus share one mood state. Selected mood chips use
`aria-pressed`.

When mood and risk match nothing, the empty state offers
**Try another mood**, which advances the mood filter.
**Deploy to Strategy Lab** opens `/lab?strategy=<registryKey>` for that
card.

### Signals

Rule-based and ML-derived software outputs. Includes an executor that runs
multiple generators in parallel and aggregates diagnostics. These outputs are
educational and are not financial advice.

### Sentiment

The Sentiment Analysis view scores submitted text for a symbol through the
configured LLM or rule-based fallback. Separate summary and ticker endpoints
synchronously analyse the static RSS publisher profiles (MoneyControl,
ET Markets, LiveMint). Production composition starts neither a background news
scheduler nor a social-media source.

### RAG

Retrieval-augmented question answering over local user-provided documents
(for example notes, statements, or research PDFs). The runtime is off by
default. The local sqlite3/NumPy vector store is built in; embedding libraries
are loaded only when installed locally and RAG is enabled, so ordinary launches
do not download models, embed documents, or carry optional AI dependencies. Set
`FLINTTRADE_RAG_ENABLED=true` when you want the RAG runtime available, or
`FLINTTRADE_RAG_AUTO_INDEX=true` when you intentionally want `docs/` indexed at
startup.

![AI](screenshots/08-ai.png)

---

## 10. Ditto multi-account walkthrough

Open `/ditto`. Ditto is FlintTrade's multi-account orchestration module for
testing account relationships, sizing rules, and risk overrides in one local
workspace.

### Three views

- **Mirror** — set up follower → master relationships, choose
  proportional or fixed-lot sizing.
- **Margin** — pre-trade margin calculator across all linked accounts.
- **Risk** — per-account risk limits, kill-switch propagation, trailing
  stop-loss governor.

On Explore `/ditto` Risk, **Kill All Positions** is disabled when there are
no managed accounts (empty state "No managed accounts"; no confirm). The
control stays armed when accounts are listed or the risk snapshot fails.

Position mirroring patterns originally came from AlgoMirror; they now run
in-process inside `packages/services/ditto/` (no external service required).

![Ditto](screenshots/09-ditto.png)

---

## 11. Settings reference

FlintTrade has two layers of configuration:

### Layer 1: `workspace.json` (user preferences and integration settings)

Lives in your platform-specific workspace directory:

| Platform | Path |
|---|---|
| Linux | `~/.flinttrade/workspace.json` |
| macOS | `~/Library/Application Support/flinttrade/workspace.json` |
| Windows | `%APPDATA%\flinttrade\workspace.json` |
| Override | `FLINTTRADE_WORKSPACE_DIR`, then `FLINTTRADE_HOME` (in that precedence order) |

The Setup and Settings UI write `workspace.json`. Key
Settings panels:

| Settings panel | Maps to | Configures |
|---|---|---|
| **Appearance** | `ui.theme` plus the theme / density stores | Theme (Graphite / Midnight / Ember), light / dark / system, UI density. |
| **Data Paths** | `storage.fast`, `storage.archive` | SSD vs HDD paths for tick data vs archive. |
| **LLM Config** | `llm.provider`, `llm.host`, `llm.model` | Catalogue-driven LLM profiles generated into the terminal from `llm_provider_profiles.py`: managed Ollama, cloud providers including NVIDIA NIM (intentionally blank unpinned default model), Hermes, and custom endpoints. |
| **Telegram** | `notifications.telegram_enabled`, `notifications.telegram_chat_id`, `notifications.telegram_bot_token_ref` | Bot enable and chat ID. The token is a hardened file under `<workspace>/secrets/`; `workspace.json` holds only the `secret://` reference. Enabling the bot applies the saved config to the running Telegram alert / kill-switch bot. A test send lives on Automate → Settings → Telegram Alerts (**Send Test**); Explore keeps that control disarmed. |
| **Risk Limits** | `safety.pnl_pause_pct`, `safety.pnl_kill_pct` | Daily P&L percentages for a reversible new-order pause and a latched new-order hard stop; neither activates Layer 5. `POST /api/v1/safety/config` accepts those same names as `pnl_pause_pct` / `pnl_kill_pct`. The Settings form's TypeScript fields are `daily_loss_pause_pct` / `daily_loss_kill_pct`; `updateSafetyConfig` remaps them to the wire fields before posting. |

On `/settings#security`, **Quick-unlock PIN** is the Live-arming
re-auth factor (it can also unlock an idle session). The PIN is optional
at account setup, but Live cannot be armed until one exists. New and
Confirm accept digits only (`maxLength` 6). **Set PIN** / **Change PIN**
stays disabled until the account password is present, both fields are
exactly six digits, and they match. Leaving (blur) a field with 1–5
digits shows `PIN must be exactly 6 digits`; leaving Confirm when both
fields are filled and different shows `PINs do not match`.
`POST /v1/auth/pin/set` rejects anything that is not `^[0-9]{6}$`.

On Explore `/settings` → **LLM Config**, a demo or unconfigured session
shows the empty state "No LLM provider configured", with **Retry** and
guidance that Explore cannot load or persist LLM secrets. This is not a
broken session; configure a provider in Live or Practice on this machine.
Live and Practice still disable editing on a real load failure ("AI
settings could not be loaded") to protect a saved configuration, and
offer **Retry**.

Settings → **Report Bug** prepares a GitHub issue without background telemetry.
The form keeps runtime/error diagnostics out of the public draft by default;
enable the diagnostic-summary switch only after reviewing the displayed
metadata. **Download diagnostics** writes a local JSON bundle that excludes raw
request bodies, messages, tracebacks, account/user identifiers, entry ids and
URL queries. Opening GitHub sends the displayed draft in the URL. Oversized
drafts are copied for manual pasting, and security reports open the private
GitHub Security Advisory form instead of a public issue.

### Layer 2: `.env` (advanced dev/server fallback)

Native desktop users do not need `.env`. The repo-root `.env.example` exists
only for Docker/systemd deployments, CI experiments, and contributor fallback
testing when a setting cannot be supplied through the app UI.

Secrets are stored as `_ref` fields — `secret://` references to hardened
files under `<workspace>/secrets/`. They are never written to
`workspace.json` in clear text.

![Settings](screenshots/10-settings.png)

---

## 12. Troubleshooting

### "Connection refused" on the OpenAlgo port

OpenAlgo is not running, or it is bound to a different port. In Settings →
Broker Gateway, keep the port in the Gateway URL or set REST Port when the URL
omits it.

```bash
python scripts/ft.py status   # FlintTrade backend health and optional OpenAlgo status
make start-openalgo           # POSIX only: boots the optional local-dev OpenAlgo clone
```

`python scripts/ft.py status` works on every OS; `make status` is the POSIX
alias. `make start-openalgo` needs bash, so on Windows start the OpenAlgo clone
with its own launcher instead.

If you installed OpenAlgo separately, start it via its own start script
(`python app.py` from the OpenAlgo repo root, or its systemd unit).

### "Port 5100 already in use"

FlintTrade's backend listens on port 5100 (deliberately separate from
OpenAlgo's multi-instance range 5000-5009). Find and kill the conflicting
process:

```bash
# Linux / macOS
lsof -i :5100
kill <pid>

# Windows (PowerShell)
Get-NetTCPConnection -LocalPort 5100 | Select-Object OwningProcess
Stop-Process -Id <pid>
```

### "No LLM provider configured" or "AI settings could not be loaded"

On Explore `/settings` → LLM Config, the empty state "No LLM provider
configured" is expected for a demo or unconfigured session. Explore
cannot load or persist LLM secrets. Use **Retry**, or configure a
provider in Live or Practice on this machine.

On Live or Practice, "AI settings could not be loaded" disables editing
to protect a saved configuration. Use **Retry**.

On `/ai` Chat, an unconfigured LLM shows **LLM not configured** (badge
**Not configured**) with **Open Settings → AI** and an outline **Retry**
that re-probes advisor status and Settings `#llm` hydration. Composer
input and Send stay disabled. Chat also looks unconfigured when Explore
Settings `#llm` looks empty ("No LLM provider configured") — **Connected**
must not appear from an env-default advisor `configured` while Settings
looks empty. If leftover transcript messages hide that empty state, the
header still offers **Retry** and **Open Settings → AI**. The Settings
empty-state wording stays distinct from Chat's **LLM not configured**; they
are aligned for readiness. A configured but broken probe shows
**Error** or **Disconnected** with **Retry**. Returning to Chat after
saving Settings → AI re-checks readiness (advisor and Settings hydration),
so the gate should not stay stuck on an outdated **Not configured**.

### "Token expired" when placing an order

FlintTrade JWTs expire daily at 8 AM IST. Refresh the token by signing in
again — the front-end will redirect you to `/welcome` automatically
when it detects the 401.

### Orders not arriving / silently dropped

1. Check the mode badge in the top bar. **Explore** has no Live broker
   order authority — Live-intent submits are blocked. Order Pad
   **Practice Buy** on `/trade` records a local sample fill after Practice
   review (no broker). Switch to **Practice** for the native sandbox
   path, or unlock **Live** for a real broker order.
2. Open the **Orders** widget and look at the rejection reason column.
3. Check the FlintTrade backend logs — the console where you ran
   `python scripts/ft.py start` (or `make start`) — every rejected order is
   logged with the safety-layer that blocked it.

### Front-end shows stale prices

The OpenAlgo price WebSocket on port 8765 has dropped. The top bar status
indicator turns red when this happens. FlintTrade auto-reconnects with
exponential back-off; if the indicator stays red for more than 30 seconds,
restart the optional OpenAlgo process — POSIX `make start-openalgo` for
the local-dev clone, or OpenAlgo's own launcher (`python app.py` from that
repo, or its systemd unit) if you installed it separately. See
["Connection refused" on the OpenAlgo port](#connection-refused-on-the-openalgo-port).
`python scripts/ft.py start` only starts the FlintTrade backend on port
5100 and cannot restore that socket. `python scripts/ft.py dev` is the
contributor Vite + backend pair, not an OpenAlgo restart.

### "Cannot find module '@/...'"

The path alias `@` → `packages/apps/terminal/src/` is configured in
`tsconfig.json` and `vite.config.ts`. If your editor's TypeScript server
disagrees, restart it. If `vitest` complains, the Vitest config lives
inside `vite.config.ts` and inherits that alias — there is no separate
`vitest.config.ts`.

### Settings page won't save

`workspace.json` may be read-only or in a folder the process cannot write
to. Check the path printed in the FlintTrade backend startup log and
ensure the running user has write access.

### Where to get help

- **Settings → Report Bug** — prepare a bounded issue draft and optional local
  diagnostic bundle from inside FlintTrade.
- **Question issue template** — for focused usage questions and setup help.
- **GitHub Issues** — for bugs and feature requests (use the templates in
  `.github/ISSUE_TEMPLATE/`).
- **security.md** — for security issues (private disclosure via GitHub
  Security Advisories).

If your issue requires a backend log, attach the relevant lines from the
console where you ran `python scripts/ft.py start`, or from the persistent
log at `<workspace>/logs/flinttrade.log` (redact any broker account IDs or
tokens first).

---

## 13. Uninstall

Uninstalling is one command on every OS, and it is the same command for a
web-app install and a desktop install. The plain uninstall removes only the
installed application and its launcher integration; your workspace, managed
source, toolchain and data are retained so a reinstall can recover them.

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash
```

```powershell
# Windows 10/11
irm https://flinttrade.vercel.app/uninstall.ps1 | iex
```

### Removing your data as well

Add the purge flag — `--purge` on macOS/Linux, `-Purge` on Windows — to also
delete recognised FlintTrade data (workspace, managed source and tools).
Purge is irreversible and asks for typed or explicit scripted confirmation.

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash -s -- --purge
```

```powershell
# Windows 10/11
& ([scriptblock]::Create((irm https://flinttrade.vercel.app/uninstall.ps1))) -Purge
```

Ordinary backup archives bhavcopy CSVs only. It does not capture workspace
settings or credentials — see [Backup and restore](setup/backup.md).

### If the site is unreachable

Use this whenever an uninstall command above fails: the hosted URLs are only a
redirect to the scripts in this repository, and a site outage answers `503`
rather than the script. Fetch the same uninstaller straight from GitHub:

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-uninstall.sh | bash
```

```powershell
# Windows 10/11
irm https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-uninstall.ps1 | iex
```

Or, from a clone or from the managed source checkout
(`~/.flinttrade/web-src/FlintTrade` for the web app,
`~/.flinttrade/src/FlintTrade` for the desktop shell), run them directly:

```bash
# macOS / Linux
bash scripts/install/flinttrade-uninstall.sh
```

```powershell
# Windows 10/11
powershell -ExecutionPolicy Bypass -File scripts\install\flinttrade-uninstall.ps1
```

Both accept the same purge flag (`--purge` / `-Purge`).
