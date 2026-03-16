# FlintTrade — The Definitive Plan

**Date:** March 14, 2026
**Author:** Navaneesh Nagarajan + Claude (claude.ai)
**Status:** Foundation complete. Core build starts tonight.

---

## 1. What FlintTrade Is

FlintTrade is a self-hosted, open-source algorithmic and manual trading platform for Indian F&O markets. It replaces every paid subscription (Sensibull, Tradetron, TradingView paid, data feeds) with one repo that runs on personal hardware.

One clone. One command. Full trading infrastructure.

```
git clone --recursive https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
cp .env.example .env
make setup
make start
```

FlintTrade is the WHOLE HOUSE — not just the app. It bundles the application, infrastructure, AI, deployment, security, and monitoring into one monorepo. KalamIQ (the previous personal infrastructure project) is absorbed entirely. There is no separate KalamIQ repo going forward.

---

## 2. Hardware (Unchanged)

| Machine | Specs | Role |
|---|---|---|
| Custom PC (Ubuntu 24.04 LTS) | i3-9350KF, RX 6600 XT 8GB, 32GB RAM, 512GB NVMe + 5TB HDD, 32" monitor | Production server. ALL live trades originate here. 24/7 uptime. SEBI static IP. |
| Acer Nitro (Fedora KDE or Win11) | i5-13420H, RTX 5050 8GB, 16GB RAM | Primary development machine. Claude Code + Antigravity. |
| MacBook Air M4 15" | M4, 16GB unified, 256GB SSD | Secondary dev + testing + travel access via VPN. |

Network: TP-Link ER605 dual WAN (ACT 500Mbps primary, BSNL 200Mbps failover), Deco X60 mesh, WireGuard VPN (10.10.10.0/24), DDNS via kalamiq.ddns.net, fail2ban + UFW.

---

## 3. Repo Structure

```
github.com/navaneeshnagarajan/FlintTrade

FlintTrade/
├── packages/
│   ├── core/            → OpenAlgo API client, config, models, logger (absorbs openalgo-python-library)
│   ├── engine/          → Strategy execution, safety layers, order routing (absorbs openengine)
│   ├── terminal/        → Scalper, option chain, DOM, charts (absorbs fastscalper + OpenTerminal + pinets + fyers-websockets)
│   ├── dashboard/       → P&L, portfolio, market overview (absorbs stock-market-dashboard + openalgo-mobile)
│   ├── ai/              → LLM chat, RAG, ML signals, news (absorbs openalgo-mcp + openadvisor + finnews-ai)
│   ├── data/            → Tick capture, audit logs (absorbs openquest)
│   ├── historical/      → Historical download, DuckDB/Parquet (absorbs historify + openchart)
│   ├── screener/        → OI spurt, PCR, max pain, portfolio Greeks (absorbs openalgo-portfoliogreeks)
│   ├── backtest/        → Backtest UI (React)
│   ├── backtest-engine/ → Simulation engine (absorbs openengine + vectorbt-backtesting-skills)
│   ├── integration/     → TradingView, ChartInk, webhooks (absorbs openalgo-flow + chrome + excel + amibroker)
│   ├── automation/      → ML pipeline, cron, Telegram, OpenClaw, TOTP auto-login
│   └── ditto/           → Multi-broker, multi-account (absorbs algomirror)
│
├── infra/
│   ├── openalgo/        → git subtree (managed service, port 5000)
│   ├── openclaw/        → git subtree (AI agent, port 18789)
│   ├── nginx/           → reverse proxy config
│   ├── systemd/         → service files
│   ├── scripts/         → deploy, rollback, backup, health, setup-ubuntu
│   ├── wireguard/       → VPN configs
│   ├── security/        → fail2ban, UFW configs
│   └── cron/            → TOTP login, health check, backup, DDNS watcher
│
├── bugs/                → git-native bug tracking (single-writer-per-file)
├── docs/                → architecture, operations, SEBI, machine configs, references
│   └── references/      → OPENALGO_API.md, TOOLS_AND_DEPS.md, both blueprints
├── tests/               → shared test infrastructure
└── .github/             → CI workflows, PR templates, issue templates, CODEOWNERS
```

---

## 4. Git Branching

3 permanent branches. Everything else is temporary.

| Branch | Permanent | Purpose | PR from | Merge method |
|---|---|---|---|---|
| main | Yes | Production. Ubuntu pulls from here. | dev only | Squash and merge |
| dev | Yes | Integration. Features merge here. | feature/*, fix/* | Squash and merge |
| feature/{pkg}-{name} | No | New features. Auto-deleted after merge. | (created by developer) | Squash into dev |
| fix/{pkg}-{name} | No | Bug fixes. Auto-deleted after merge. | (created by developer) | Squash into dev |
| hotfix/{name} | No | Emergency. PRs to main + backport to dev. | (created by anyone) | Squash into main |
| release/{version} | No | Version prep. PRs to main. | dev | Squash into main |

GitHub rulesets:
- protect-main: PR required, CI must pass, linear history, block force push, restrict deletions
- protect-dev: PR required, 1 approval (community gate), block force push, restrict deletions

Auto-delete head branches enabled.

---

## 5. Development Workflow

### Tools and Their Roles

| Tool | What | Role |
|---|---|---|
| VS Code | Editor | Always open. FlintTrade folder. Browse, review, manual edits. |
| Claude Code (in VS Code terminal) | AI coding agent | DEVELOPMENT. Builds features. Reads CLAUDE.md automatically. |
| Antigravity (separate window, same repo) | Multi-agent IDE | TESTING. Writes tests for what Claude Code built. Finds bugs. Reads AGENTS.md automatically. |
| Claude Desktop — Chat tab | Planning conversations | This conversation. Architecture decisions. File generation. |
| Claude Desktop — Cowork tab | Autonomous file agent | Bulk tasks: "check all CLAUDE.md files for consistency", "find hardcoded broker references" |
| OpenAlgo MCP | Doc search | Search OpenAlgo docs from within Claude.ai or Claude Desktop |

### Why Claude Code = dev, Antigravity = test

Two different usage quotas. Claude Code (Claude Max) builds. Antigravity (Gemini Pro) tests. They don't share quota. This doubles throughput without hitting limits.

### Daily Development Flow

```
Nitro (after market hours):

1. VS Code open → FlintTrade folder
2. Terminal 1: git checkout dev && git pull && git checkout -b feature/core-client
3. Terminal 1: claude
   → "Build packages/core/src/openalgo_client.py. Read packages/core/CLAUDE.md."
   → Claude Code writes code
4. Review in VS Code editor panes
5. Antigravity (separate window, same branch):
   → "Read packages/core/CLAUDE.md. Write comprehensive tests for packages/core/src/openalgo_client.py in packages/core/tests/test_core.py. Test every endpoint, error handling, rate limiting, retries."
   → Antigravity writes tests, finds bugs, pushes fixes
6. Terminal 2: make test && make lint
7. Terminal 2: git add . && git commit -m "feat(core): OpenAlgo API client" && git push
8. GitHub: PR feature/core-client → dev → squash and merge
```

---

## 6. What Gets Absorbed From Where

"Absorb" = rewrite the logic into FlintTrade's architecture using the original repo as reference. NOT copy-paste.

### marketcalls repos (25 relevant out of 146)

| Repo | Absorbed into | What we take |
|---|---|---|
| openalgo | infra/openalgo/ (subtree) | Runs as managed service. Never modify. |
| openalgo-python-library | core | SDK patterns, 80+ indicators, API wrapper |
| openengine | backtest-engine | Event-driven backtest, BaseStrategy, live trader |
| algomirror | ditto | Multi-account routing, margin calc, trailing SL, risk manager |
| historify | historical | DuckDB pipeline, data management, scheduler |
| openchart | historical | Free NSE/NFO data (no broker API needed) |
| openquest | data | QuestDB tick aggregation, multi-exchange streaming |
| fastscalper-tauri | terminal | Scalper UI patterns, one-click execution |
| OpenTerminal | terminal | Trading terminal patterns |
| openalgo-pinets | terminal | PineTS indicators, TradingView Lightweight Charts v5 |
| fyers-websockets | terminal + data | 50-level DOM, order flow analytics, TBT data |
| tradingview-yahoo-finance | terminal | TradingView chart integration |
| openalgo-portfoliogreeks | screener | Portfolio-level Black-Scholes Greeks |
| openalgo-mcp | ai | MCP natural language trading (15+ tools) |
| openadvisor | ai | CatBoost ML stock recommendations |
| finnews-ai | ai | Financial news sentiment |
| openalgo-flow | integration | Visual strategy builder (N8N-style) |
| openalgo-chrome | integration | Chrome extension trading widget |
| OpenAlgo-Excel | integration | Excel add-in with WebSocket streaming |
| OpenAlgoPlugin | integration | Amibroker data plugin |
| vectorbt-backtesting-skills | backtest-engine | 12 strategy templates, agent skills, QuantStats |
| stock-market-dashboard | dashboard | React dashboard patterns |
| trading-dashboard | dashboard | React dashboard patterns |
| openalgo-mobile | dashboard | Flutter UI → React responsive patterns |
| openalgo-desktop | future | Tauri 2.0 wrapper (after web is done) |

### External AI/ML repos (reference for implementation)

| Repo | What we implement from it | Package | Timeline |
|---|---|---|---|
| FinRL | RL agent architecture | ai | Week 10-12 |
| FinMem | Layered memory for trading LLM | ai | Week 12 |
| TradingAgents | Multi-agent roles (analyst, trader, risk) | ai | Week 7 |
| agency-agents | Agent personality patterns | automation | Week 3 |
| autoresearch / autoresearch-mlx | Overnight autonomous optimization | ai | Week 19 |
| unsloth | QLoRA fine-tuning on trading data | ai | Week 19 |
| optionlab | Options strategy analysis | backtest-engine | Week 2 |
| NSE-Option-Chain-Analyzer | OI trend analysis patterns | screener | Week 3 |

### Pip libraries (install, don't clone)

| Library | What | Package |
|---|---|---|
| openalgo | Official Python SDK | core |
| duckdb | Analytical database | historical, data |
| chromadb | Vector DB for RAG | ai |
| lightgbm | Gradient boosting signals | ai, backtest-engine |
| py_vollib_vectorized | Fastest options pricing + Greeks | screener, backtest-engine |
| quantstats | Portfolio analytics, tearsheets | backtest-engine, dashboard |
| ta-lib | 150+ technical indicators | engine, backtest-engine |
| vectorbt | Backtesting framework | backtest-engine |
| optionlab | Options strategy analysis | backtest-engine |
| lightweight-charts | TradingView charts (npm) | terminal |
| recharts | React charts (npm) | dashboard, backtest |

---

## 7. Build Timeline

### Track 1: Live Trading (during market hours, using broker terminal)

| Day | What |
|---|---|
| Done | Static IPs registered with all brokers |
| Day 1 | Configure TOTP auto-login cron on Ubuntu |
| Day 2 | First live trade via broker terminal (small qty) |
| Day 3+ | Trade daily 9:15-3:30 using broker terminal |
| When FlintTrade terminal is ready | Switch from broker terminal to FlintTrade |

### Track 2: FlintTrade Build (after market hours + weekends)

| Week | Package | Tool | What gets built |
|---|---|---|---|
| Week 1 (Mar 17-21) | core | Claude Code builds, Antigravity tests | OpenAlgo client, config, models, logger, exceptions |
| Week 1 | data | Claude Code builds, Antigravity tests | Audit logger, tick recorder (SEBI compliance) |
| Week 2 (Mar 24-28) | engine | Claude Code builds, Antigravity tests | Safety layers, order routing, scheduler, base strategy |
| Week 2 | terminal | Claude Code builds, Antigravity tests | Scalper panel, option chain, TradingView charts |
| Week 3 (Mar 31-Apr 4) | historical + screener | Claude Code builds, Antigravity tests | DuckDB pipeline, OI spurt, PCR, max pain |
| Week 3 | integration | Claude Code builds, Antigravity tests | TradingView webhook, ChartInk |
| Week 4+ | backtest-engine, ai, dashboard, automation, ditto | All tools | Simulation, ML signals, portfolio UI, Telegram, multi-account |

### SEBI Deadline: April 1, 2026

| Requirement | Status |
|---|---|
| Static IP registered | Done |
| 10 OPS rate limit | OpenAlgo handles + engine enforces |
| Kill switch | Telegram + UI (automation package, Week 3) |
| 5-year audit logs | data package (Week 1) |
| Algo registration with broker | After first strategy is built |

---

## 8. Deploy Freeze & Operations

| Time (IST) | What |
|---|---|
| 8:30 AM | Auto-login cron fires |
| 9:10 AM | Health check |
| 9:15 AM | MARKET OPEN — deploy freeze starts |
| 9:15-3:30 | NO deploys on production. Trade using broker terminal. Dev machines build FlintTrade freely. |
| 3:30 PM | MARKET CLOSE |
| 3:45-6:00 PM | Maintenance window — deploy, restart, sync branches |
| 6:00 PM+ | Full development — Claude Code + Antigravity on Nitro |

Emergency during market hours: OpenAlgo Action Center → disable strategy. NEVER restart OpenAlgo with open positions. Log in bugs/live.md. Fix after 3:30 PM.

---

## 9. DEVLOG & Tracking

Every code change → append to DEVLOG.md:
```
## YYYY-MM-DD HH:MM IST | Machine | @username | AgentName | Branch | Summary
```

Agents:
- `Claude Code` — development
- `Antigravity/AgentName` — testing
- `Cowork` — bulk file tasks
- `Manual` — human edits

Bug lifecycle: bugs/live.md → in_progress.md → in_testing.md → resolved.md

---

## 10. What To Do RIGHT NOW

### Step 1: Push the v2 zip (5 minutes)
```powershell
cd "$env:USERPROFILE\Documents\GitHub\FlintTrade"
Get-ChildItem -Force | Where-Object { $_.Name -ne '.git' } | Remove-Item -Recurse -Force
# Extract FlintTrade-foundation.zip here
git checkout dev
git add -A
git commit -m "feat: FlintTrade foundation — complete rebuild with 25+ absorbed repos, KalamIQ infra, CI fixes"
git push origin dev
```
PR dev → main → squash and merge.

### Step 2: Update protect-dev ruleset
Settings → Rules → Rulesets → protect-dev → Required approvals: 1 → Require review from code owners: ON

### Step 3: Enable auto-delete
Settings → General → Pull Requests → Automatically delete head branches: ON

### Step 4: Start core build (tonight)
```powershell
git checkout dev && git pull
git checkout -b feature/core-openalgo-client
```

VS Code terminal:
```
claude
```
Then say:
> Build packages/core/src/openalgo_client.py — the shared OpenAlgo REST + WebSocket client. Read packages/core/CLAUDE.md and docs/references/OPENALGO_API.md for all endpoints.

Antigravity (separate window, same branch):
> Read packages/core/CLAUDE.md. Write tests for whatever Claude Code builds in packages/core/src/. Test every method, every error path, every edge case. Push to the same branch.

### Step 5: After core is done
PR feature/core-openalgo-client → dev → squash and merge.
Then: feature/engine-safety-layers and feature/data-audit-logger in parallel.

---

## 11. What KalamIQ Becomes

Nothing. KalamIQ repo stays on GitHub as historical archive. All its infrastructure (WireGuard, DDNS, fail2ban, cron, OpenClaw config, machine configs) lives inside FlintTrade/infra/ now. The only thing that remains personal is your .env file with API keys and TOTP secrets.

---

## 12. The Vision

FlintTrade replaces:
- Sensibull (₹800/month) → packages/screener + terminal
- Tradetron (₹2,500/month) → packages/engine + integration
- TradingView paid (₹1,100/month) → packages/terminal (Lightweight Charts v5, free)
- Data feeds (₹499/month Dhan) → packages/historical (openchart = free NSE data)
- Multiple broker terminals → packages/terminal (one UI, any broker via OpenAlgo)

Total saved: ₹5,000-15,000/month. Total cost: ₹0 (hardware already owned, brokers already have accounts).

One repo. One clone. Full house.
