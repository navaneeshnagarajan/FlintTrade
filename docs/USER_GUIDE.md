# FlintTrade User Guide

This guide walks you from a fresh install to placing your first live order.
The default reading order is top-to-bottom — every section builds on the one
before it. If you already have FlintTrade running, jump to the
[Workspace tour](#workspace-tour) or use the section list in the sidebar.

> **Alpha software.** FlintTrade `v0.6.0-alpha` is not production ready and
> does not provide financial advice. Read [disclaimer.md](../disclaimer.md)
> before connecting a broker or switching to Live mode.

> **Three personas, one app.** FlintTrade serves traders (intraday F&O),
> investors (mutual funds, SIPs, holdings), and beginners (learning, paper
> trading) from the same workspace. The routes are persona-shaped — pick
> `/trade`, `/invest`, or `/learn` from the top bar to switch persona without
> losing context.

---

## 1. Installation

FlintTrade runs on Windows, macOS, and Linux (including Raspberry Pi). The
quickest path is `make setup` from a fresh clone — it installs Python and
Node dependencies, creates the `~/.flinttrade/` workspace, and prepares
FlintTrade's backend for connection.

### Prerequisites

- **Python 3.12+** (every package declares `requires-python >=3.12,<3.14`).
- **Node.js 20+** (24 recommended for current LTS parity).
- **Git**.
- **Broker access.** FlintTrade can use its own broker gateway as adapters
  mature, and it can also connect to an existing OpenAlgo-compatible server.

### Quick install (any platform)

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
make setup
cp .env.example .env       # optional; configure integrations when needed
make start                 # starts the FlintTrade backend
cd packages/apps/terminal && npm install && npm run dev
```

Open `http://localhost:5173` once the dev server is ready. You should land on
`/welcome` — the first-time cinematic intro.

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

FlintTrade supports two broker paths: the native FlintTrade gateway for
first-party adapters, and an OpenAlgo-compatible server for users who already
run OpenAlgo.

### Steps

1. **Choose a path.** Use the FlintTrade gateway as native adapters become
   available, or install OpenAlgo separately if you want the OpenAlgo
   integration path.
2. **Optional: configure your broker in OpenAlgo.** Open `http://localhost:5000`,
   choose your broker from the dropdown, paste your API key and secret, and
   complete the broker's login flow (TOTP / OAuth / OTP — depends on the
   broker). OpenAlgo persists the session. Skip this step for Explore mode,
   Practice mode, and native FlintTrade gateway work that does not use the
   OpenAlgo-compatible bridge.
3. **Optional: generate an OpenAlgo API key.** From the OpenAlgo dashboard,
   copy the generated API key. This is the key FlintTrade uses for the
   OpenAlgo-compatible bridge only (not your broker's key).
4. **Optional: set the OpenAlgo key in FlintTrade.** Edit `.env` in the
   FlintTrade repo root:

   ```env
   OPENALGO_HOST=http://127.0.0.1:5000
   OPENALGO_PORT=5000
   OPENALGO_API_KEY=<paste-here>
   OPENALGO_WS_PORT=8765
   ```

5. **Restart the terminal.** Kill the `npm run dev` server, run it again,
   and open `http://localhost:5173/setup`. Walk through the wizard — it will
   verify the OpenAlgo connection on the last step when you configure that
   bridge.

### Why two layers?

The two-layer option lets existing OpenAlgo users keep their broker setup
while FlintTrade keeps its own backend, native sandbox, analytics, automation,
and first-party broker gateway.

---

## 3. First paper trade (Practice mode)

Before risking real money, place a paper trade in **Practice mode**.
FlintTrade has a three-mode system:

| Mode | Order behaviour | Best for |
|---|---|---|
| **Explore** | No orders sent; demo data only | First-time visitors, screenshots, docs |
| **Practice** | Orders simulated by FlintTrade's native sandbox | Strategy testing, before-market practice |
| **Live** | Real orders to your broker | Production trading |

The current mode is shown in the top bar and is server-enforced via the JWT
claim — switching to Live requires a deliberate confirmation step.

### Walkthrough

1. Open `http://localhost:5173/trade`.
2. Click the mode badge in the top bar → choose **Practice**. A modal
   confirms the switch.
3. From the dock sidebar, drag the **Order Pad** widget into the workspace
   (or pick a preset that contains it — for example "Scalper Zone" or
   "Options Desk").
4. Type `NIFTY` into the symbol field; FlintTrade autocompletes the current
   front-month future. Select it.
5. Set Quantity = 1 lot (50). Choose **MARKET**. Side = **BUY**.
6. Click **Place Order**. The order appears in the **Positions** widget
   immediately; the **Orderbook** widget shows it as filled (simulated).
7. Close the position from the Positions widget. Confirm your simulated
   P&L is recorded in the **P&L Dashboard** tool.

You have just exercised the full FlintTrade order path — front-end → JWT
guard → mode guard → FlintTrade sandbox → simulated fill →
WebSocket back to the front-end. No real money moved.

![Trade workspace](screenshots/04-trade.png)
*The /trade workspace with Dockview tabs, order pad, positions, and chart.*

---

## 4. First live trade (Live mode)

Once your strategy is paper-trade-clean for at least a session, switch to
Live.

### Pre-flight checklist

- [ ] OpenAlgo session is current (the broker token has not expired).
- [ ] Your FlintTrade JWT is fresh — it expires daily at 8 AM IST.
- [ ] The 5-layer safety system is active (see
      [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md#safety-layers)).
- [ ] Daily P&L kill switch is configured in Settings → Risk.
- [ ] You have read and accepted the SEBI compliance notes in
      [SEBI_COMPLIANCE.md](SEBI_COMPLIANCE.md).

### Walkthrough

1. Click the mode badge in the top bar → choose **Live**. A modal warns
   that real orders will be placed and asks for password re-entry.
2. Place a single-lot, in-the-money order through the Order Pad as a
   smoke test (the smallest possible position).
3. Watch the **Positions** widget — it should reflect the broker's real
   position book within one tick.
4. Close the position from the broker's terminal *or* from the Positions
   widget. Confirm both reconcile.

If anything looks wrong, hit the **Kill Switch** in the top bar — it
cancels every open order and squares off every position via OpenAlgo's
`closeposition` endpoint. The kill switch also fires automatically when
the daily P&L breach threshold is hit (default 3% pause, 15% kill).

---

## 5. Workspace tour

FlintTrade's workspace is a [Dockview](https://github.com/mathuo/dockview)
canvas. Every widget is a panel you can drag, tab, stack, float, or pop out
into its own window. Layouts persist in `~/.flinttrade/workspace.json` and
sync across sessions.

### The 12 routes

| Route | Purpose |
|---|---|
| `/welcome` | First-time cinematic introduction (smart-redirects after first visit). |
| `/explore` | Demo mode with sample data — no broker connection needed. |
| `/setup` | First-time wizard (Quick / Guided / Advanced paths). |
| `/settings` | Standalone settings page (workspace.json editor with form UI). |
| `/trade` | Trader workspace — Dockview canvas, 83 widgets, 13 presets. |
| `/invest` | Investor dashboard — holdings, net worth, SIPs, mutual-fund tracker. |
| `/learn` | Beginner centre — courses, glossary, strategies, paper trading. |
| `/lab` | Strategy Lab — backtest, forward test, optimise. |
| `/automate` | Automation Hub — flows, cron, monitors, logs. |
| `/ai` | AI Centre — chat, signals, sentiment, RAG. |
| `/ditto` | Multi-account management — mirror, margin, risk. |
| `/admin` | Admin panel (development builds only) — security, health, traffic. |

### The 83 widgets

Widgets are organised into three categories under
`packages/apps/terminal/src/widgets/`:

- **Trading (22)** — Dashboard, Scalper, Positions, Orders, Holdings,
  Trade Book, Order Pad, Intraday P&L, MTM Monitor, Risk Panel, Action
  Center, Position Heat Map, Trade Copier, Portfolio Allocation, Quick
  Trade, Session Stats, Risk Dashboard, Trade Log, Trade Performance,
  Strategy Monitor, Net Positions, and Order Ladder.
- **Analysis (39)** — Chart, Multi Chart, Option Chain, OI Chart,
  Straddle, Depth, Greeks, Sector Map, GEX Dashboard, Vol Surface, IV
  Smile, Straddle P&L, OI Profile, Order Flow, Depth Heatmap,
  Three-Panel Chart, OI Heatmap, Greeks Surface, Pivot Points, Order
  Book Replay, Market Breadth, Volatility Cone, Heat Calendar, VWAP
  Bands, Correlation Pairs, Multi-Timeframe, PCR Trend, Instrument
  Compare, Spread View, Greeks Heatmap, Gap Analysis, Implied Move,
  Options Flow, Market Microstructure, Correlation Matrix, IV Skew,
  Sector Performance, Footprint Chart, and DOM Heatmap.
- **Utility (22)** — Watchlist, Calculator, News Feed, Ticker, AI
  Advisor, Pre-Market Scanner, Price Alerts, System Health, Funding
  Rates, Currency Converter, Earnings Calendar, Global Indices,
  Strategy Templates, Audit Trail, Economic Calendar, Profit Target
  Calc, Expiry Countdown, Position Sizing, Market Clock, Trade Ideas,
  Tick Speed, and Market Summary.

Every widget is registered in `packages/apps/terminal/src/layout/widgetFactory.tsx`.

### The 13 workspace presets

A preset is a pre-built layout you can apply instantly from the command
palette (Ctrl + K → "preset"). Built-in presets include:

- **Scalper Zone** — chart, level-2 depth, order pad, recent trades.
- **Options Desk** — option chain, payoff diagram, Greeks, straddle P&L.
- **Market Watch** — multi-symbol watchlist, heatmap, news ticker.
- **Analysis** — chart with multiple indicators, regime detector, correlation
  matrix.
- **Risk Monitor** — P&L dashboard, exposure, kill-switch status, funds.
- **Investor View** — holdings, SIPs, net worth, mutual-fund tracker.
- … plus seven more.

Presets are serialised via the Dockview API. You can save your own custom
preset from Settings → Workspace.

---

## 6. Screener walkthrough

The screener lives under the **Analysis** widget category and shares the
workspace with everything else — no separate route. The four headline tools:

### Option Chain

Streaming option-chain widget rendered with
[Glide Data Grid](https://github.com/glideapps/glide-data-grid) for
60+ FPS updates even on a 50-strike chain.

1. Drag the **Option Chain** widget into the workspace.
2. Pick a symbol (e.g. `NIFTY`, `BANKNIFTY`, `RELIANCE`).
3. The expiry row auto-fills from OpenAlgo's `/expiry` endpoint.
4. Calls on the left, Puts on the right, ATM strike highlighted.
5. Hover any cell — sparkline shows the last-100-tick history.

### OI Profile

Plots Open Interest changes by strike across CE and PE legs. Useful for
spotting where the smart-money "walls" are setting up.

### Max Pain

Calculates the strike at which option writers lose the least if expiry hit
right now. Updates every minute from OpenAlgo's `optionchain` feed.

### IV Smile

Implied-volatility curve across strikes, with skew and term-structure
indicators. Useful for spotting unusual options activity.

---

## 7. Strategy Lab walkthrough

Open `/lab`. The Strategy Lab is split into three sub-tools:

### Backtest

1. **Pick a template.** 94 templates ship under
   `packages/services/backtest/src/flinttrade_backtest/strategies/` — ranging
   from simple EMA crossover to complex options-spreads strategies.
2. **Configure parameters.** Each template exposes a parameter form
   (built with `react-hook-form` + `zod`).
3. **Pick a date range.** Historical OHLCV data is sourced from your
   configured providers (OpenChart, yfinance, or a paid feed).
4. **Run.** The backtest engine processes ticks vector-wise (VectorBT for
   exploration, Rust/PyO3 `tick-engine` for tick-level precision when
   you opt in).
5. **Review.** Equity curve, Sharpe, Sortino, max drawdown, win rate,
   trade list, Monte Carlo confidence band.

### Forward Test

Same as Backtest, but runs in Practice mode against live ticks. Useful for
a final sanity check before going live.

### Optimise

Walk-forward optimisation across a parameter grid. Outputs a heatmap of
performance per parameter combination plus an out-of-sample evaluation.

![Lab](screenshots/06-lab.png)

---

## 8. Automation Hub walkthrough

Open `/automate`. Three sub-tools:

### Flows

Visual flow builder (drag-and-drop nodes) for "when X happens, do Y"
automations. Nodes include market events (OI breach, price level, IV
spike), broker events (order filled, position breach), and actions
(place order, send Telegram, run script).

### Cron

Time-based automations. Examples:

- Run pre-market screener at 9:00 AM IST every weekday.
- Snapshot positions to a CSV at 3:30 PM IST.
- Post a daily P&L summary to Telegram at end-of-day.

Cron jobs run inside the FlintTrade backend (`packages/services/automation`).

### Monitors

Watchdog rules that fire alerts (Telegram, sound, on-screen). Lighter
than Flows — single-event triggers without action chains.

![Automate](screenshots/07-automate.png)

---

## 9. AI Centre walkthrough

Open `/ai`. Four sub-tools backed by `packages/services/ai`:

### Chat

LLM-powered trading assistant. Wired to LM Studio by default
(`http://127.0.0.1:1234`) but switchable to OpenAI, Anthropic, Groq, or a
local Ollama instance from Settings → AI.

### Signals

Rule-based + ML-derived signals. Includes a swarm executor that runs
multiple signal generators in parallel and aggregates verdicts.

### Sentiment

News and social-media sentiment scoring per symbol. Driven by a
news-scheduler that polls RSS, Twitter (X), and Reddit on a configurable
interval.

### RAG

Retrieval-augmented question answering over your own trading documents
(strategy notes, broker statements, research reports). Indexed in
ChromaDB with sentence-transformer embeddings. Startup auto-indexing is off by
default, and the RAG runtime itself is also off unless enabled, so the backend
does not download or embed documents during ordinary local launches. Set
`FLINTTRADE_RAG_ENABLED=true` when you want the RAG runtime available, or
`FLINTTRADE_RAG_AUTO_INDEX=true` when you intentionally want `docs/` indexed at
startup.

![AI](screenshots/08-ai.png)

---

## 10. Ditto multi-account walkthrough

Open `/ditto`. Ditto is FlintTrade's multi-account orchestrator — mirror
one master account to many followers with per-leg margin / lot-size /
risk overrides.

### Three views

- **Mirror** — set up follower → master relationships, choose
  proportional or fixed-lot sizing.
- **Margin** — pre-trade margin calculator across all linked accounts.
- **Risk** — per-account risk limits, kill-switch propagation, trailing
  stop-loss governor.

Position mirroring patterns originally came from AlgoMirror; they now run
in-process inside `packages/services/ditto/` (no external service required).

![Ditto](screenshots/09-ditto.png)

---

## 11. Settings reference

FlintTrade has two layers of configuration:

### Layer 1: `.env` (infrastructure)

Lives in the repo root, never committed. OpenAlgo variables are only needed
when you enable the OpenAlgo-compatible bridge:

| Variable | Purpose |
|---|---|
| `OPENALGO_HOST` | OpenAlgo server URL (default `http://127.0.0.1:5000`) |
| `OPENALGO_PORT` | OpenAlgo server port (default `5000`) |
| `OPENALGO_API_KEY` | The API key copied from OpenAlgo's dashboard |
| `OPENALGO_WS_PORT` | OpenAlgo WebSocket port (default `8765`) |

### Layer 2: `workspace.json` (user preferences)

Lives in your platform-specific workspace directory:

| Platform | Path |
|---|---|
| Linux | `~/.flinttrade/workspace.json` |
| macOS | `~/Library/Application Support/flinttrade/workspace.json` |
| Windows | `%APPDATA%/flinttrade/workspace.json` |
| Override | `FLINTTRADE_HOME` environment variable |

The `/settings` route exposes a form UI over `workspace.json`. Key
sections:

| Section | Maps to | Configures |
|---|---|---|
| **General** | `ui.theme`, `ui.density` | Theme (Graphite / Midnight / Ember), light / dark / system, UI density. |
| **Workspace** | `storage.fast`, `storage.archive` | SSD vs HDD paths for tick data vs archive. |
| **AI** | `llm.provider`, `llm.host`, `llm.model` | LLM client (LM Studio, OpenAI, Anthropic, Ollama, Groq). |
| **Notifications** | `telegram.*`, `whatsapp.*` | Telegram bot token, chat ID, kill-switch enable. |
| **Risk** | `risk.daily_pnl_pause_pct`, `risk.daily_pnl_kill_pct` | Daily P&L thresholds for auto-pause and auto-kill. |
| **SEBI** | `sebi.audit_retention_days`, `sebi.rate_limit_*` | Audit retention (5 years default), per-endpoint rate limits. |

Secrets are stored as `_ref` fields — references to the OS keyring or to
environment variables. They are never written to `workspace.json` in clear
text.

![Settings](screenshots/10-settings.png)

---

## 12. Troubleshooting

### "Connection refused" on the OpenAlgo port

OpenAlgo is not running, or it is bound to a different port.

```bash
make status          # shows FlintTrade backend health and optional OpenAlgo status
make start-openalgo  # boots the optional local-dev OpenAlgo clone when present
```

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

### "Token expired" when placing an order

FlintTrade JWTs expire daily at 8 AM IST. Refresh the token by signing in
again — the front-end will redirect you to the login screen automatically
when it detects the 401.

### Orders not arriving / silently dropped

1. Check the mode badge in the top bar. If it says **Explore**, no orders
   are sent at all (by design).
2. Open the **Orderbook** widget and look at the rejection reason column.
3. Check the FlintTrade backend logs (where you ran `python
   packages/core/core/src/app.py` or `make start`) — every rejected order is
   logged with the safety-layer that blocked it.

### Front-end shows stale prices

The WebSocket on port 8765 has dropped. The top bar status indicator turns
red when this happens. FlintTrade auto-reconnects with exponential
back-off; if the indicator stays red for more than 30 seconds, restart the
terminal (`Ctrl-C` then `npm run dev`).

### "Cannot find module '@/...'"

The path alias `@` → `packages/apps/terminal/src/` is configured in
`tsconfig.json` and `vite.config.ts`. If your editor's TypeScript server
disagrees, restart it. If `vitest` complains, ensure
`packages/apps/terminal/vitest.config.ts` extends the same alias.

### Settings page won't save

`workspace.json` may be read-only or in a folder the process cannot write
to. Check the path printed in the FlintTrade backend startup log and
ensure the running user has write access.

### Where to get help

- **GitHub Discussions** — for usage questions and ideas.
- **GitHub Issues** — for bugs and feature requests (use the templates in
  `.github/ISSUE_TEMPLATE/`).
- **security.md** — for security issues (private disclosure via GitHub
  Security Advisories).

If your issue requires a backend log, run with
`FLINTTRADE_LOG_LEVEL=DEBUG` and attach the relevant lines (redact any
broker account IDs or tokens first).
