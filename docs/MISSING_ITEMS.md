# FlintTrade — Missing Items Audit

> Cross-referenced: REPOS.md, CORE1_SUMMARY.md, CORE2_SUMMARY.md, .reference/repos/, ~/.claude/skills/, ~/.claude/agents/, package.json, requirements.txt files
> Generated: 2026-03-19

---

## Summary

| Category | Discussed | Present | Missing |
|----------|-----------|---------|---------|
| Repos (REPOS.md A-G) | ~40 | ~35 | ~5 |
| Claude Skills (npx) | 18 | 1 | 17 |
| MCP Servers | 7 | 3 | 4 |
| Pip Libraries | 13 | 9 | 4 |
| NPM Libraries | 3 | 3 | 0 |
| Agents (agency-agents) | 172 | 172+ | 0 |
| Plugins | 6 | 4 | 2 |

---

## 1. REPOS — Discussed but NOT Cloned in .reference/repos/

### Missing from .reference/repos/

| # | Repo | REPOS.md # | Where mentioned | Priority | Action |
|---|------|-----------|-----------------|----------|--------|
| 1 | **NSE-Option-Chain-Analyzer** (VarunS2002) | #39 | REPOS.md Section G, screener CLAUDE.md | Low | Clone for OI analysis patterns when building screener |
| 2 | **Banknifty-Straddle** | #40 | REPOS.md Section G | Low | Clone for straddle strategy logic when building backtest-engine |
| 3 | **agency-agents** (msitarzewski) | #31 | REPOS.md Section E | Already installed | Agents are in ~/.claude/agents/ — no need to clone separately |
| 4 | **autoresearch / autoresearch-mlx** | #35 | REPOS.md Section E | Low | Clone when starting AI overnight optimization pipeline |
| 5 | **GitNexus** | #37 | REPOS.md Section F | Medium | Should use now to index FlintTrade + OpenAlgo codebase |

### Already Cloned (confirmed present)

**tier1-core**: openalgo, openalgo-flow, openalgo-pinets, openalgo-portfoliogreeks, openadvisor, finnews-ai, fyers-websockets, openquest, historify, Algomirror, OpenTerminal, openalgo-mcp, fastscalper-tauri, openengine, openchart

**tier2-ecosystem**: openalgo-desktop, openalgo-chrome, openalgo-indicator-skills, vectorbt-backtesting-skills, stock-market-dashboard, trading-dashboard, tradingview-yahoo-finance, openalgo-chatbot, openalgo-claude-plugin, openalgo-voice-based-orders, option-chain, opendash, openscreener, trading-strategies-openalgo, trading-journal, EquiCharts, order-flow-chart, sector-rotation-map

**tier3-ai-research**: StockSharp, AlgoTrading, FinRL, FinMem-LLM-StockTrading, TradingAgents, MiroFish, freqtrade

**tier4-community**: openalgo-backtrader, openalgo-mobile, openalgo-chart, openalgostratagies, openalgo-tradingview-scalper, trading-strategies-openalgo

**external-all**: FinRL-Trading, Stockagent, PrimoGPT, LLM-TradeBot, FinRL_Contest_2025, Autonomous-Agents, algo_trading_strategies_india, fully-automated-nifty-options-trading, ccxt, openalgo-backtrader, openalgo-chart, openalgostratagies, openalgo-tradingview-scalper, openalgo-chatbot, Openalgo_Wheel_Strategy, openalgo-multiuser, openalgo-rust-mcp, trading-strategies-openalgo, awesome-systematic-trading, awesome-quant, mcporter, uv, llm-rl-finance-trader

**marketcalls-all**: ALL marketcalls repos cloned (includes OpenAlgo-Excel, OpenAlgoPlugin, openalgo-go, openalgo-rust, fastscalper, and many more)

### REPOS.md items NOT cloned but intentionally skipped

| Repo | REPOS.md # | Reason |
|------|-----------|--------|
| CLI-Anything (HKUDS) | #38 | Explicitly DROPPED in REPOS.md — "OpenClaw native skills replace this" |
| openalgo-go, openalgo-node, openalgo-java, openalgo-dotnet | #23-27 | Reference only SDKs; Go and Rust are in marketcalls-all |
| unsloth | #36 | Tool, not a repo to clone — installed via pip on WSL2 when needed |

---

## 2. CLAUDE CODE SKILLS — Discussed but NOT Installed

CLAUDE.md and REPOS.md list 18 skills to install. Only **taste-skill** is present in `~/.claude/skills/`.

**NOTE**: Skills installed via `npx skills add` may have been superseded by the plugin system. The superpowers plugin IS installed (v5.0.5) which provides brainstorm, write-plan, execute-plan, TDD, debugging, code-review, git-worktrees, parallel-agents. The frontend-design plugin is also installed via the official marketplace.

| # | Skill | REPOS.md # | Install command | Status | Action |
|---|-------|-----------|-----------------|--------|--------|
| 1 | **vercel-react-best-practices** | #59 | `npx skills add https://github.com/vercel-labs/agent-skills` | NOT INSTALLED | Install — needed for React terminal development |
| 2 | **web-design-guidelines** | #60 | Same as above | NOT INSTALLED | Install — needed for UI work |
| 3 | **vercel-composition-patterns** | #61 | Same as above | NOT INSTALLED | Low priority — reference only |
| 4 | **deploy-to-vercel** | #62 | Same as above | NOT INSTALLED | Skip — FlintTrade doesn't use Vercel |
| 5 | **vercel-react-native-skills** | #63 | Same as above | NOT INSTALLED | Skip — no React Native in FlintTrade |
| 6 | **find-skills** | #64 | `npx skills add https://github.com/vercel-labs/skills` | NOT INSTALLED | Install — useful for skill discovery |
| 7 | **planning-with-files** | #65 | `npx skills add https://github.com/OthmanAdi/planning-with-files` | NOT INSTALLED | Install — useful for plan management |
| 8 | **pi-planning-with-files** | #66 | Same as above | NOT INSTALLED | Install — comes with planning-with-files |
| 9 | **gstack** | #67 | `npx skills add https://github.com/garrytan/gstack` | NOT INSTALLED | Install — stack analysis useful for monorepo |
| 10 | **taste-skill** | #68 | Manual clone to ~/.claude/skills/ | INSTALLED | Already present |
| 11-18 | **firecrawl** (8 skills) | #69-76 | `npx -y firecrawl-cli@latest init --all --browser` | NOT INSTALLED | Install — useful for web scraping research |

### Skills Provided by Installed Plugins (no separate install needed)

| Skill | Provided by | Status |
|-------|-------------|--------|
| brainstorm, write-plan, execute-plan | superpowers plugin (v5.0.5) | WORKING |
| TDD, debugging, code-review | superpowers plugin | WORKING |
| git-worktrees, parallel-agents | superpowers plugin | WORKING |
| frontend-design | claude-plugins-official marketplace | WORKING |
| skill-creator | claude-plugins-official marketplace | WORKING |
| claude-md-management | claude-plugins-official marketplace | WORKING |

---

## 3. MCP SERVERS — Discussed but NOT Configured

| # | MCP Server | REPOS.md # | Status | Action |
|---|------------|-----------|--------|--------|
| 1 | **context7** | #84 | INSTALLED (cached) | Working |
| 2 | **playwright** | #86 | INSTALLED (cached) | Working |
| 3 | **github** | #88 | INSTALLED (cached) | Working |
| 4 | **memory** | #85 | NOT INSTALLED | Install — `claude mcp add --transport stdio memory -- npx -y @modelcontextprotocol/server-memory` |
| 5 | **sequential-thinking** | #87 | NOT INSTALLED | Install — `claude mcp add --transport stdio sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking` |
| 6 | **firecrawl** | #90 | NOT INSTALLED | Install with firecrawl CLI |
| 7 | **OpenAlgo MCP** | #89 | Cloud only (Claude.ai) | Cannot install locally — read-only cloud MCP; openalgo-mcp repo IS cloned for reference |

---

## 4. PIP LIBRARIES — Listed in REPOS.md but NOT in any requirements.txt

| # | Library | REPOS.md # | Used by | Status | Action |
|---|---------|-----------|---------|--------|--------|
| 1 | **vectorbt** | #48 | backtest-engine | NOT in requirements.txt | Add to `packages/backtest-engine/requirements.txt` when building vectorbt strategies |
| 2 | **TA-Lib** | #47 | engine, backtest-engine | NOT in requirements.txt | Add when needed — requires C library installation first |
| 3 | **optionlab** | #49 | backtest-engine | NOT in requirements.txt | Add to `packages/backtest-engine/requirements.txt` when building options backtester |
| 4 | **ccxt** | mentioned in CLAUDE.md, screener CLAUDE.md | screener (crypto), historical (crypto) | NOT in requirements.txt | Add when building Delta Exchange / crypto support |

### Already Present in requirements.txt

| Library | Where |
|---------|-------|
| openalgo (via httpx) | core uses direct API calls, not the pip package |
| duckdb | root + historical + data |
| chromadb | ai |
| lightgbm | ai |
| py_vollib_vectorized | screener |
| quantstats | backtest-engine |
| jugaad-data | root + historical |
| yfinance | historical |
| numba | ditto |
| sentence-transformers | ai |

### Note on `openalgo` pip package (#41)
REPOS.md says `pip install openalgo` is used in core, but the actual codebase uses a custom `openalgo_client.py` with direct httpx calls. The pip package is NOT in any requirements.txt. This is intentional — FlintTrade wraps all OpenAlgo API calls in its own async client.

---

## 5. NPM LIBRARIES — All Present

| Library | Status |
|---------|--------|
| lightweight-charts | In terminal package.json |
| recharts | In terminal package.json |
| lucide-react | In terminal package.json |

---

## 6. PLUGINS — Status

| # | Plugin | REPOS.md # | Status |
|---|--------|-----------|--------|
| 1 | superpowers | #77 | INSTALLED (v5.0.5, cached) |
| 2 | frontend-design | #78 | INSTALLED (via claude-plugins-official) |
| 3 | skill-creator | #79 | INSTALLED (via claude-plugins-official) |
| 4 | claude-md-management | #80 | INSTALLED (via claude-plugins-official) |
| 5 | voltagent-meta | #81 | INSTALLED (via voltagent-subagents marketplace) |
| 6 | voltagent-lang | #82 | INSTALLED (via voltagent-subagents marketplace) |

All plugins are installed.

---

## 7. AGENTS — All Installed

The `~/.claude/agents/` directory contains 172+ agent files from the agency-agents collection (msitarzewski), covering: academic, design, engineering, game-dev, marketing, paid-media, product, project-mgmt, sales, spatial-computing, specialized, strategy, support, testing categories. Also includes coordination templates, playbooks, and runbooks.

---

## 8. ADDITIONAL ITEMS from Conversations Not in REPOS.md

| Item | Where Mentioned | Status | Action |
|------|----------------|--------|--------|
| **crypt0inf0/openalgo-chart** | CORE1 MSG 668, CORE2 | CLONED in tier4-community and external-all | Already present |
| **MiroFish** (666ghj) | CORE1 MSG 668, ai CLAUDE.md | CLONED in tier3-ai-research | Already present |
| **StockSharp** | User explicitly asked to check | CLONED in tier3-ai-research | Already present |
| **wshobson/claude-code-workflows** | CORE2 appendix | Not a repo to clone — it's a plugin marketplace | Installed as part of superpowers ecosystem |
| **antigravity-awesome-skills** | REPOS.md #91 | NOT CHECKED | Install via `npx antigravity-awesome-skills` if using Antigravity |

---

## Recommended Immediate Actions

### High Priority (install now)
1. Install `vercel-react-best-practices` and `web-design-guidelines` skills — needed for terminal UI work
2. Install `memory` MCP server — persistent knowledge graph helps across sessions
3. Install `sequential-thinking` MCP server — structured problem-solving for complex decisions
4. Install `planning-with-files` skill — needed for plan management workflow

### Medium Priority (install before relevant work)
5. Install `gstack` skill — useful for monorepo stack analysis
6. Install `firecrawl` skills + MCP — useful for web scraping and research
7. Clone `GitNexus` — index FlintTrade + OpenAlgo codebase for knowledge graph
8. Add `vectorbt` to backtest-engine requirements.txt when building strategies
9. Add `TA-Lib` to engine/backtest-engine when indicator work begins

### Low Priority (defer until needed)
10. Clone `NSE-Option-Chain-Analyzer` — when building screener OI features
11. Clone `Banknifty-Straddle` — when building straddle strategy
12. Clone `autoresearch` — when building AI overnight optimization
13. Add `optionlab` to backtest-engine — when building options backtester
14. Add `ccxt` to screener/historical — when building crypto support
15. Install `find-skills` — useful for discovering new skills
