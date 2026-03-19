> **HISTORICAL SNAPSHOT** — This audit was conducted before the 2026-03-19 v2 migration.
> All issues listed here have been addressed. See PLAN.md for current status.

# FlintTrade — Comprehensive Gap Analysis

> **Audit Date:** 2026-03-19
> **Sources compared:** CLAUDE.md, PLAN.md, RESTRUCTURE.md, CORE1_SUMMARY.md, CORE2_SUMMARY.md, and actual codebase
> **Method:** All 5 documents cross-referenced against each other and verified against the live file tree

---

## 1. VISION vs REALITY

### 1.1 "The Whole House" vision vs current state

**Promised (CORE1 MSG 593):** FlintTrade should be "the whole house" — a single unified platform, not a collection of separate tools. Institutional-level algo and manual trading platform that "will beat everything else in the market."

**Reality:** The codebase has:
- 10 Python packages: all have source files and tests (670 passing), but most are scaffolded implementations not yet battle-tested with live trading
- 1 functional React app (terminal) with a FlexLayout widget system partially implemented
- 2 stub React apps (dashboard, backtest) that RESTRUCTURE.md says to DELETE but they still exist
- Only 1 confirmed live trade ever placed (via broker sandbox)
- No live strategy has been run during actual market hours

### 1.2 Widget system — claimed vs actual

**RESTRUCTURE.md claims 20 widgets.** Actual widget files that exist:

| Widget | File Exists | Functional | Notes |
|--------|-------------|------------|-------|
| Dashboard | YES | YES | Live API data, indices, funds, positions |
| Scalper | YES | YES | 3-panel charts, order execution, keyboard shortcuts |
| Positions | YES | YES | Live positions from API |
| Orders | YES | YES | Live orders from API |
| Holdings | YES | YES | Live holdings from API |
| TradeBook | YES | YES | Live tradebook from API |
| OrderPad | YES | YES | Order entry form |
| Chart | YES | YES | TradingView Lightweight Charts |
| OptionChain | YES | YES | 3 views (LTP/OI/Greeks), auto-refresh |
| OIChart | YES | PARTIAL | File exists, needs market verification |
| Straddle | YES | PARTIAL | File exists, needs market verification |
| Depth | YES | YES | 5-level depth, auto-refresh |
| Greeks | YES | YES | Portfolio-level Greeks from positions |
| Watchlist | YES | YES | Search, multi-quote, sparklines |
| **Sector Map** | NO | NO | Planned in RESTRUCTURE.md, not built |
| **Ticker** | NO | NO | Planned in RESTRUCTURE.md (TickerBar exists but is chrome, not a widget) |
| **Calculator** | NO | NO | Planned in RESTRUCTURE.md, not built |
| **News** | NO | NO | Planned in RESTRUCTURE.md, not built |
| **AI Advisor** | NO | NO | Planned in RESTRUCTURE.md, not built |
| **MTM Monitor** | NO | NO | Planned in RESTRUCTURE.md, not built |
| **Risk Panel** | NO | NO | Planned in RESTRUCTURE.md, not built |

**Result:** 14 of 20 widgets exist as files. 7 missing entirely. The `widgetFactory.jsx` only registers 13 widgets (Greeks widget is missing from factory despite file existing).

### 1.3 Full-page tools — claimed vs actual

**RESTRUCTURE.md claims 7 tools.** Actual state:

| Tool | File Exists | Functional | Notes |
|------|-------------|------------|-------|
| Settings | YES | PARTIAL | General/API/Trading/Risk sections work; Keyboard, LLM, Telegram, Ditto, Automation, Layouts, About are stubs |
| Backtest Lab | YES | STUB | Shows "Coming in Phase 3-4" placeholder |
| Trade Journal | YES | STUB | Placeholder only |
| Strategy Builder | YES | STUB | Placeholder only |
| P&L Dashboard | YES | STUB | Placeholder only |
| Market Intelligence | YES | STUB | Placeholder only |
| Flow Builder | YES | STUB | Placeholder only |

**Result:** All 7 tool files exist but only Settings has any real functionality. The other 6 are empty shells with "Coming Soon" text.

### 1.4 Layout presets — claimed vs actual

**RESTRUCTURE.md claims 8 presets (Part 5) + 4 more from Part 12 = 12 total.**

Actual presets in `packages/terminal/src/layout/presets/`:
- `minimal.json` (exists, simple Chart + Positions)
- `scalper-zone.json` (exists)
- `analysis-desk.json` (exists)
- `volatility-trading.json` (exists)
- `market-watch.json` (exists)
- `risk-monitor.json` (exists)
- `blank.json` (exists)

**Missing:** `data-cruncher.json` (listed in RESTRUCTURE.md Part 5). None of the Part 12 persona-based presets exist (Beginner, Investor, Research, Commodity, Crypto, Research Lab, Developer).

**Note:** RESTRUCTURE.md says presets go in `public/layouts/` but they are actually in `src/layout/presets/`. The `public/layouts/` directory does not exist.

### 1.5 AI features — promised vs built

**Promised (CORE1 MSG 45, 47):** "Fully automatic" AI that knows everything about trading, creates strategies from patterns, LightGBM signals, RAG pipelines, RL-based position management, AI chat.

**CORE2 Summary:** Self-learning AI app that continuously analyses live market data, sends notifications, has an "Update Knowledge" button that connects to Claude Opus.

**Reality:**
- `packages/ai/` has source files (LLM client, RAG pipeline, ML signals, sentiment)
- Tests pass (part of 670)
- No AI Advisor widget in the terminal
- No integration between AI package and terminal UI
- No live AI signals have been generated
- No self-learning loop exists
- No "Update Knowledge" feature exists

### 1.6 NIFTY lot size discrepancy

**CORE1 SUMMARY (user's strategy):** "Lot sizes: NIFTY 25, BANKNIFTY 15, FINNIFTY 25, MIDCPNIFTY 50"

**Scalper widget code:** `NIFTY: { lotSize: 75 }, BANKNIFTY: { lotSize: 30 }, FINNIFTY: { lotSize: 40 }, MIDCPNIFTY: { lotSize: 50 }`

**Reality:** The user stated their personal preferred lot sizes in the conversation, but the actual NSE lot sizes as of 2025+ are different. NIFTY lot size was changed from 50 to 75 (then later revisions). The code may need dynamic lot size fetching from the broker rather than hardcoded values.

---

## 2. DOC CONTRADICTIONS

### 2.1 TOTP auto-login — the biggest contradiction

| Document | Says |
|----------|------|
| **CLAUDE.md line 36** | "TOTP auto-login NOT implemented. OpenAlgo handles broker auth." |
| **CLAUDE.md line 76** | "No TOTP auto-login (OpenAlgo handles broker auth)" |
| **CLAUDE.md line 188** | "Add TOTP auto-login" (in the DO NOT list) |
| **CORE1 SUMMARY** | "Don't implement TOTP auto-login (OpenAlgo handles broker auth)" |
| **CORE2 SUMMARY** | "Add TOTP auto-login (OpenAlgo handles broker auth)" (in DON'T list) |
| **docs/THE_PLAN.md line 57** | `automation/ → ML pipeline, cron, Telegram, OpenClaw, TOTP auto-login` |
| **docs/THE_PLAN.md line 210** | "Day 1: Configure TOTP auto-login cron on Ubuntu" |
| **docs/SEBI_COMPLIANCE.md** | "Daily session management: TOTP auto-login cron in infra/cron/" |
| **flint.toml** | `automation = { description = "ML pipeline, cron, Telegram, OpenClaw agent, TOTP auto-login" }` |
| **CHANGELOG.md** | "TOTP auto-login, cron manager (5 jobs), Telegram bot with /kill switch" |
| **packages/automation/README.md** | "ML pipeline, cron, Telegram bot, OpenClaw agent, TOTP auto-login, post-market analysis" |
| **Actual code** | `totp_login.py` exists but is a stub that returns "NOT IMPLEMENTED" |
| **DEVLOG.md** | Logged as a feature: "feat(automation): TOTP auto-login..." |

**The contradiction:** CLAUDE.md explicitly forbids TOTP auto-login, but THE_PLAN.md, SEBI_COMPLIANCE.md, flint.toml, CHANGELOG.md, automation README, and DEVLOG all reference it as if it's a feature. The code has the file but it's a no-op stub. The DEVLOG claims it was built as a feature.

### 2.2 Git submodule vs subtree

| Document | Says |
|----------|------|
| **CLAUDE.md** | "Git submodules: infra/openalgo, infra/algomirror, infra/openclaw" |
| **docs/ARCHITECTURE.md** | "infra/openalgo/ (git subtree)" / "infra/openclaw/ (git subtree)" / "infra/algomirror/ (git submodule)" |
| **docs/THE_PLAN.md** | "git subtree" for openalgo and openclaw |
| **docs/references/MASTER_BLUEPRINT.md** | Recommends git subtree over submodules |
| **.gitmodules (actual)** | All three are git **submodules** |
| **RESTRUCTURE.md Part 11** | "Git infra: Clarify: submodule or subtree? Pick one, update all docs" |

**The contradiction:** `.gitmodules` proves all three are submodules. ARCHITECTURE.md calls two of them subtrees. THE_PLAN.md calls them subtrees. RESTRUCTURE.md itself identified this contradiction but it was never resolved.

### 2.3 Terminal CLAUDE.md is severely outdated

`packages/terminal/CLAUDE.md` contains:
- **Port 3001** — should be **5173** (changed in CORE2 conversation)
- **Branch: feature/terminal-{description}** — should be **main only** (decided in CORE1 MSG 666)
- **F1-F9 fixed module architecture** — RESTRUCTURE.md says "DELETE the concept of F1-F10 fixed modules with a sidebar" and replace with widget-composable workspace
- **TradePulse v0.3 UI reference** — outdated, RESTRUCTURE.md replaced this with Groww 915 / flexlayout-react architecture
- Lists `F1 Dashboard, F2 Scalper, F3 Option Chain...F9 Settings` — these no longer match the widget system

### 2.4 PLAN.md vs RESTRUCTURE.md — completely different roadmaps

**PLAN.md "Next" items (F-key based):**
1. Terminal Option Chain module (F3)
2. Terminal Scalper module (F2)
3. Terminal Charts module (F4)
4. Terminal Screener module (F5)
5. Terminal Settings module (F8)
6. WebSocket integration
7. Dashboard package (port 5174)
8. Backtest package (port 5175)

**RESTRUCTURE.md roadmap (widget-based):**
1. Delete dashboard/ and backtest/ stubs
2. Install flexlayout-react
3. Build Chrome shell
4. Build 20 widgets across 4 phases
5. Build 7 full-page tools

**These are fundamentally different architectures.** PLAN.md still uses F-key module naming and references dashboard/backtest as separate packages. RESTRUCTURE.md says delete those packages and absorb everything into terminal.

The actual code follows RESTRUCTURE.md's architecture (flexlayout-react, widget system) while PLAN.md has not been updated.

### 2.5 Module count contradiction

| Document | Count |
|----------|-------|
| **CLAUDE.md** | "13 packages" (10 Python + 3 React) |
| **RESTRUCTURE.md** | "Keep all 10 Python, ADD 1 (indicators), DELETE 2 React stubs = 11 Python + 1 React = 12" |
| **Actual codebase** | 10 Python + 3 React = 13 (stubs not deleted, indicators not created) |

### 2.6 `.env.example` not fully blank

**CLAUDE.md rule:** ".env.example has ALL values blank"

**Actual `.env.example`:**
```
OPENALGO_HOST=http://127.0.0.1:5000
OPENALGO_PORT=5000
```

The HOST and PORT have default values, not blank. Only API_KEY is blank. The dashboard and backtest `.env.example` files also have `VITE_OPENALGO_HOST=http://127.0.0.1:5000` pre-filled.

**Exception:** The terminal's `.env.example` correctly has `VITE_OPENALGO_HOST=` (blank).

### 2.7 DEVLOG format mismatch

**CLAUDE.md says:** `## YYYY-MM-DD HH:MM IST | Machine | @username | IDE/Tool | AI Model/Agent | Branch | Summary`

**CORE2 SUMMARY says:** Same format but adds machine hostname with spec.

**Global `~/.claude/CLAUDE.md` says:** `## YYYY-MM-DD HH:MM IST | Nitro | AgentName | Summary` (much shorter format)

Three different DEVLOG formats defined across docs.

### 2.8 Keyboard shortcuts conflict

**Terminal CLAUDE.md says:** F1=Dashboard, F2=Scalper, F3=Option Chain... (module navigation)

**RESTRUCTURE.md says:** DELETE F1-F10 concept entirely. Scalper widget uses Shift+arrow when focused.

**Actual code:** `useGlobalKeys.js` exists but Scalper widget uses its own keyboard handler only when focused. No F-key navigation exists in the widget architecture.

### 2.9 React packages count

**CLAUDE.md:** "React packages (3): terminal (5173), dashboard (5174), backtest (5175)"

**RESTRUCTURE.md Part 7:** "Delete packages/dashboard/ and packages/backtest/ stubs"

**Reality:** Both dashboard and backtest still exist with full source code and node_modules. They were never deleted.

### 2.10 Broker-specific reference in Current State

**CLAUDE.md:** Previously contained a broker-specific sandbox reference in Current State section.

**Status:** Fixed — replaced with generic "Tested with broker sandbox."

---

## 3. MISSING FEATURES

Features discussed in conversations but not tracked in PLAN.md or RESTRUCTURE.md:

### 3.1 From CORE1 conversation — not in any plan

| Feature | Where Discussed | Status in Plans |
|---------|----------------|-----------------|
| Pine Script support for custom indicators | CORE1 MSG 14, 17 | RESTRUCTURE.md mentions PineTS converter but not in PLAN.md |
| Exit positions by percentage (individual) | CORE1 MSG 14, 17 | RESTRUCTURE.md has partial exit buttons, PLAN.md does not |
| MTM-based stoploss and target | CORE1 MSG 14, 17 | RESTRUCTURE.md has MTM Monitor widget, PLAN.md does not |
| Order by fund amount (auto-calculate from LTP) | CORE1 MSG 14, 17 | Not in any plan document |
| Fund in use + fund balance with percentage | CORE1 MSG 14, 17 | Dashboard shows this but Scalper does not |
| Expired option contracts (5-11 years) | CORE1 MSG 45, 47 | PLAN.md "Future" mentions it, no task |
| Trade Journal — determine behavior, suggest improvements | CORE1 MSG 14, 17 | RESTRUCTURE.md has it, PLAN.md does not |
| OI data overlay on charts for index and futures | CORE1 MSG 14, 17, 20 | Not in any plan |
| Historical data from multiple brokers, merged | CORE1 MSG 45, 47 | Not in any plan (only single-broker fetch exists) |

### 3.2 From CORE2 conversation — not in any plan

| Feature | Where Discussed | Status in Plans |
|---------|----------------|-----------------|
| AI "Update Knowledge" button (Claude Opus consultation) | CORE2 Section 2 | Not in PLAN.md or RESTRUCTURE.md |
| Self-learning AI that continuously learns strategies | CORE2 Section 2 | Not in any plan |
| AI approval workflow (suggest -> approve -> execute) | CORE2 Section 2 | Not in any plan |
| Docker deployment testing | CORE2 Section 3 | PLAN.md "Future" list only |
| Feature flags: ENABLE_BACKTEST, ENABLE_AI | CORE2 Section 3 | Added to .env.example concept but not functional |

### 3.3 User's personal strategy — not captured anywhere

From CORE2 Section 2: EMA Short 20, Long 50; Supertrend Length 10, Factor 3; DEMA 15 with specific SL/target logic. This strategy is described in detail in the conversation but there is no strategy template, no configuration file, and no reference to it in PLAN.md or RESTRUCTURE.md.

### 3.4 Investor personas and widgets — not in PLAN.md

RESTRUCTURE.md Part 12 defines 16 personas and 8 additional investor widgets (Mutual Fund Explorer, SIP Calculator, Portfolio Tracker, Financials, Stock Screener, Learn, ETF Tracker, IPO). None of these appear in PLAN.md.

---

## 4. ARCHITECTURE DRIFT

### 4.1 F-key modules to widget system — incomplete migration

The code has migrated to the FlexLayout widget architecture (RESTRUCTURE.md), but:
- `packages/terminal/CLAUDE.md` still describes F1-F9 module architecture
- `PLAN.md` still uses F-key references (F2, F3, F4, F5, F8)
- `AGENTS.md` still references the old architecture
- The actual App.jsx properly implements Chrome + FlexLayout + Tools pattern

### 4.2 Dashboard/backtest packages still exist

RESTRUCTURE.md Part 7 says DELETE both. They still exist with full source code and installed node_modules, consuming disk space and creating confusion about which is the canonical codebase.

### 4.3 DataBus architecture — partially implemented

RESTRUCTURE.md Part 8 specifies a centralized DataBus singleton to prevent API bombardment. The code has:
- `dataBus.js` — exists, basic pub/sub
- `dataConnector.js` — exists, connects WebSocket + API polling to DataBus
- `rateLimiter.js` — exists, token-bucket implementation
- `dataCache.js` — does NOT exist (listed in RESTRUCTURE.md)
- `storage.js` — does NOT exist (listed in RESTRUCTURE.md)

Some widgets (DashboardWidget, OptionChainWidget) make direct API calls via `services/api.js` instead of going through the DataBus, which violates the "NEVER call any API without going through DataBus" rule from RESTRUCTURE.md Part 8.

### 4.4 `packages/indicators/` — never created

RESTRUCTURE.md Part 6 says to add a new `indicators` package with "100+ Numba indicators + PineTS converter." This package does not exist. The widget count in CLAUDE.md was never updated to reflect this planned addition.

### 4.5 CLI-Anything — contradictory status

RESTRUCTURE.md Part 13 says CLI-Anything is "DROPPED" per REPOS.md entry #38, then immediately describes 3 CLI-Anything integrations. The resolution says "dropped as core dependency" but "build manual Click CLIs" — this is unclear and not captured in PLAN.md.

### 4.6 `public/layouts/` vs `src/layout/presets/`

RESTRUCTURE.md Part 7 file structure shows layout presets in `public/layouts/`. The actual code puts them in `src/layout/presets/` and imports them as JSON modules. The `public/layouts/` directory does not exist.

### 4.7 Greeks widget missing from widgetFactory

`packages/terminal/src/widgets/analysis/Greeks/GreeksWidget.jsx` exists as a functional component but is NOT registered in `widgetFactory.jsx`. Users cannot add it to their layout through the WidgetPicker.

---

## 5. USER PREFERENCES VIOLATED

### 5.1 No mock data rule — tools violate this

The 6 stub tools (BacktestLab, TradeJournal, StrategyBuilder, PnLDashboard, MarketIntelligence, FlowBuilder) show "Coming in Phase X" placeholder text. While this is not "mock data" per se, the user was "furious" about placeholder content. These should either be functional or not shown in the TOOLS dropdown.

### 5.2 DEVLOG not consistently followed

CORE2 Summary Section 7.6: "User insisted on DEVLOG entries after every prompt."
DEVLOG.md has entries but there are significant gaps — many code changes (like the RESTRUCTURE migration to flexlayout) appear to have been done without DEVLOG entries.

### 5.3 Commit messages — Dhan reference persists

CORE2 rule: "Do not include private data in commit messages (fund amounts, order IDs, broker names)"
Previously contained broker-specific sandbox reference — now fixed.

### 5.4 Test on dev machine first

CORE2 rule: "Testing on Ubuntu prematurely is idiotic — build properly on dev machine first"
No evidence of systematic dev-machine testing before deployment. The terminal has not been verified to work with live market data during market hours on the dev machine.

### 5.5 `.env.example` values not all blank

See contradiction 2.6 above. Root `.env.example` has `OPENALGO_HOST=http://127.0.0.1:5000` pre-filled. Dashboard and backtest `.env.example` files also have pre-filled values.

### 5.6 MCX and Crypto support incomplete

CORE1 explicitly requests MCX commodities and Delta Exchange crypto support. The terminal CLAUDE.md documents crypto requirements (24/7 charts, funding rates, fractional lots, liquidation price, INR settlement). None of this is implemented in any widget. The Scalper widget only supports equity index options (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX, BANKEX).

---

## 6. PRIORITY CONFLICTS

### 6.1 PLAN.md vs RESTRUCTURE.md — what to build next

**PLAN.md says next:**
1. Terminal Option Chain module (F3)
2. Terminal Scalper module (F2)
3. Terminal Charts module (F4)

**These are already built** as widgets (OptionChainWidget, ScalperWidget, ChartWidget). PLAN.md is completely out of date.

**RESTRUCTURE.md says next:**
1. Delete dashboard/ and backtest/ stubs
2. Build remaining 7 widgets
3. Build DataBus properly
4. Build 7 full-page tools

### 6.2 Separate React apps vs single terminal

**PLAN.md items 7-8:** "Dashboard package (port 5174)" and "Backtest package (port 5175)" — build these as separate apps.

**RESTRUCTURE.md:** DELETE these packages, absorb into terminal as tools.

Direct conflict. The code currently has both: stubs still exist AND the tools exist as stubs in terminal.

### 6.3 CLAUDE.md "In Progress" is stale

PLAN.md "In Progress" section says:
- "Terminal: verify dashboard shows live data during market hours"
- "Terminal: .env needs to be created per-machine"

These have been in "In Progress" since the terminal was first built. Meanwhile, a massive restructure happened (flexlayout migration). The "In Progress" section does not reflect actual current work.

### 6.4 RESTRUCTURE.md timeline vs reality

RESTRUCTURE.md Part 10 gives a 16-week timeline starting from "Week 1-2: Foundation." The document is dated 2026-03-18 (yesterday). The code already has many Phase 1-2 items done (flexlayout installed, Chrome shell built, widget factory exists). But the timeline does not account for what already exists.

---

## 7. RECOMMENDED FIXES

### Critical (do immediately)

| # | Fix | Files to Change |
|---|-----|----------------|
| C1 | **Rewrite PLAN.md** completely to match RESTRUCTURE.md architecture. Remove all F-key references. Mark existing widgets as done. Set next tasks to: remaining 7 widgets, Greeks factory registration, DataBus enforcement, tool implementations. | `PLAN.md` |
| C2 | **Rewrite terminal CLAUDE.md** — port 3001 to 5173, remove branch strategy, remove F1-F9 modules, document widget architecture, remove TradePulse reference. | `packages/terminal/CLAUDE.md` |
| C3 | **Resolve TOTP contradiction** — Remove all "TOTP auto-login" references from THE_PLAN.md, SEBI_COMPLIANCE.md, flint.toml, CHANGELOG.md, automation README. The code already handles this correctly (stub that says NOT IMPLEMENTED). | Multiple files |
| C4 | **Resolve git submodule/subtree** — All three are submodules per `.gitmodules`. Update ARCHITECTURE.md and THE_PLAN.md to say "submodule" not "subtree". | `docs/ARCHITECTURE.md`, `docs/THE_PLAN.md` |
| C5 | **Register Greeks widget** in `widgetFactory.jsx` — it exists but users cannot add it. Add `greeks: lazy(() => import('../widgets/analysis/Greeks/GreeksWidget'))` and add to `widgetCatalog`. | `packages/terminal/src/layout/widgetFactory.jsx` |
| C6 | **Blank `.env.example` values** — Remove `http://127.0.0.1:5000` default from root, dashboard, and backtest `.env.example` files. Terminal's is already correct. | `.env.example`, `packages/dashboard/.env.example`, `packages/backtest/.env.example` |
| C7 | **Remove broker-specific sandbox reference** from CLAUDE.md Current State section. Replace with generic "Tested with broker sandbox." | `CLAUDE.md` — **DONE** |

### Important (do this week)

| # | Fix | Files to Change |
|---|-----|----------------|
| I1 | **Delete dashboard/ and backtest/ packages** as RESTRUCTURE.md directs. Their functionality is absorbed into terminal tools. Update CLAUDE.md package count from 13 to 11. | `packages/dashboard/`, `packages/backtest/`, `CLAUDE.md` |
| I2 | **Create data-cruncher preset** — listed in RESTRUCTURE.md Part 5 but missing from presets directory. | `packages/terminal/src/layout/presets/data-cruncher.json` |
| I3 | **Enforce DataBus pattern** — DashboardWidget and OptionChainWidget call API directly instead of through DataBus. Refactor to use `useDataBus` hook. Add missing `dataCache.js` and `storage.js` services. | Multiple terminal files |
| I4 | **Build missing risk widgets** — MTM Monitor and Risk Panel are core to the user's scalping workflow (exit on MTM limits, per-position SL). These should be prioritized over utility widgets. | New files in `packages/terminal/src/widgets/risk/` |
| I5 | **Unify DEVLOG format** — Pick one format and put it in CLAUDE.md only. Remove conflicting definitions from global CLAUDE.md. | `CLAUDE.md`, `~/.claude/CLAUDE.md` |
| I6 | **Archive docs/THE_PLAN.md** — RESTRUCTURE.md Part 11 says to move it to `docs/references/historical/`. It contains outdated references (TOTP, subtrees, Fedora, old timeline). | `docs/THE_PLAN.md` -> `docs/references/historical/THE_PLAN_V1.md` |
| I7 | **Update CLAUDE.md Current State** section to reflect widget architecture, flexlayout migration, and actual number of working widgets (14 files, 13 registered). | `CLAUDE.md` |

### Backlog (track for later)

| # | Fix | Notes |
|---|-----|-------|
| B1 | **Create packages/indicators/** — RESTRUCTURE.md calls for 100+ Numba indicators + PineTS converter. Not blocking anything now but needed for Chart widget indicator overlay. |
| B2 | **MCX commodity support** in Scalper — user explicitly requested MCX. Scalper currently only supports equity index options. Need commodity symbol format, different market hours, different lot sizes. |
| B3 | **Crypto (Delta Exchange) support** — terminal CLAUDE.md documents requirements but nothing is implemented. 24/7 charts, funding rates, fractional lots, liquidation prices. |
| B4 | **User's personal EMA/Supertrend strategy** — documented in CORE2 but not captured as a strategy template in backtest-engine or engine package. Create a template file. |
| B5 | **Investor persona widgets** — RESTRUCTURE.md Part 12 lists Mutual Fund Explorer, SIP Calculator, Portfolio Tracker, Financials, Stock Screener, Learn, ETF Tracker, IPO. None exist. Not blocking traders but important for TAM expansion. |
| B6 | **AI Advisor widget** — the AI package exists but has no UI surface. Build the widget, connect to LLM client, add natural language query capability. |
| B7 | **Dynamic lot sizes** — Scalper hardcodes lot sizes. These change periodically (NSE announces). Should fetch from OpenAlgo or maintain a config. |
| B8 | **Order by fund amount** — user requested ordering by fund value (auto-calculate lots from available capital and LTP). Not in any widget. |
| B9 | **Multi-broker data merging** — user wants historical data from multiple brokers merged into unified database. Only single-broker fetch exists. |
| B10 | **OI data overlay on charts** — user explicitly asked for OI data overlaid on price charts for indices and futures. Not implemented. |

---

## Summary Statistics

| Metric | Count |
|--------|-------|
| Documents with contradictions | 5 of 5 |
| Unique contradictions found | 10 |
| Widgets claimed vs existing | 20 vs 14 (7 missing, Greeks unregistered) |
| Tools claimed vs functional | 7 vs 1 (6 are stubs) |
| Missing features from conversations | 14+ |
| Files needing immediate update | 8+ |
| Architecture decisions unresolved | 3 (submodule/subtree, separate apps, TOTP) |

**Bottom line:** The codebase has made real progress — flexlayout works, 14 widgets exist, 670 tests pass, live API integration is functional. But the documentation is fractured across at least 5 conflicting sources. PLAN.md is so outdated it will actively mislead any Claude Code session that reads it. The RESTRUCTURE.md is the most current and accurate vision document, but it has not been reconciled with CLAUDE.md or PLAN.md. Until these are unified, every new session risks building against an outdated plan.
