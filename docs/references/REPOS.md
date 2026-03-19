# FlintTrade — Complete Repository Knowledge Base

> This file contains every GitHub repository, library, tool, and skill
> discussed across all FlintTrade planning and build sessions.
> Place this at `docs/references/REPOS.md` in the FlintTrade repo.
> Claude Code and other agents should read this for full context.

---

## A. Git Submodules (bundled in infra/)

| # | Repo | GitHub URL | Role in FlintTrade |
|---|---|---|---|
| 1 | **openalgo** | github.com/marketcalls/openalgo | Core broker gateway. REST API port 5000, WebSocket port 8765. 30+ Indian brokers. FlintTrade NEVER modifies this. |
| 2 | **algomirror** | github.com/marketcalls/algomirror | Multi-account trade routing, trailing SL, Supertrend exits, margin calculator, trade quality grading. Patterns absorbed into `ditto` package. |
| 3 | **openclaw** | github.com/openclaw/openclaw | AI agent gateway. Telegram/WhatsApp/Discord channels, persistent memory, heartbeats, cron, skills. Patterns absorbed into `automation` package. |

## B. Marketcalls / OpenAlgo Ecosystem (patterns absorbed into packages)

| # | Repo | GitHub URL | Absorbed into | What we take |
|---|---|---|---|---|
| 4 | **openalgo-portfoliogreeks** | github.com/marketcalls/openalgo-portfoliogreeks | `screener` | Black-Scholes portfolio Greeks, lot-based, position-aware signs |
| 5 | **openalgo-pinets** | github.com/marketcalls/openalgo-pinets | `terminal` | PineTS indicators + TradingView Lightweight Charts integration |
| 6 | **fastscalper-tauri** | github.com/marketcalls/fastscalper-tauri | `terminal` | Tauri scalper UI, LE/LX/SE/SX buttons, voice alerts, 380x300 quick-action panel |
| 7 | **openengine** | github.com/marketcalls/openengine | `backtest-engine` | Backtester class, YahooFinance/OpenAlgo connectors, live trader |
| 8 | **openadvisor** | github.com/marketcalls/openadvisor | `ai` | Portfolio advisor, rebalancing logic |
| 9 | **OpenTerminal** | github.com/marketcalls/OpenTerminal | `terminal` | Terminal UI patterns, layout reference |
| 10 | **finnews-ai** | github.com/marketcalls/finnews-ai | `ai` | Financial news sentiment analysis |
| 11 | **openchart** | github.com/marketcalls/openchart | `historical` | Free NSE/NFO data without broker API (pip install openchart) |
| 12 | **openalgo-flow** | github.com/marketcalls/openalgo-flow | `integration` | Visual strategy builder (N8N-style, React), ChartInk payload parsing |
| 13 | **openalgo-chrome** | github.com/marketcalls/openalgo-chrome | `integration` (future) | Chrome extension with floating LE/LX/SE/SX buttons |
| 14 | **OpenAlgo-Excel** | github.com/marketcalls/OpenAlgo-Excel | `integration` (future) | C#/Excel-DNA add-in, WebSocket streaming in cells |
| 15 | **OpenAlgoPlugin** | github.com/marketcalls/OpenAlgoPlugin | `integration` (future) | Amibroker data plugin |
| 16 | **openalgo-desktop** | github.com/marketcalls/openalgo-desktop | Reference only | Tauri 2.0 desktop app, OS keychain AES-256-GCM, Argon2id |
| 17 | **openalgo-mobile** | github.com/marketcalls/openalgo-mobile | Reference (future) | Flutter mobile app |
| 18 | **openquest** | github.com/marketcalls/openquest | Reference only | Real-time tick aggregation into QuestDB |
| 19 | **fyers-websockets** | github.com/marketcalls/fyers-websockets | Reference only | WebSocket connection patterns |
| 20 | **vectorbt-backtesting-skills** | github.com/marketcalls/vectorbt-backtesting-skills | `backtest-engine` | 12 strategy templates, TA-Lib indicators, QuantStats tearsheets |

## C. Community OpenAlgo Projects

| # | Repo | GitHub URL | Absorbed into | What we take |
|---|---|---|---|---|
| 21 | **openalgo-backtrader** | github.com/p2c2e/openalgo-backtrader | `backtest-engine` | Backtrader integration for OpenAlgo |

## D. OpenAlgo SDKs (we use Python SDK, rest are reference)

| # | Repo | Language | Status |
|---|---|---|---|
| 22 | **openalgo** (PyPI) | Python | `pip install openalgo` — used in `core` package |
| 23 | **openalgo-go** | Go | Reference only |
| 24 | **openalgo-node** | Node.js | Reference only |
| 25 | **openalgo-java** | Java | Reference only |
| 26 | **openalgo-rust** | Rust | Reference only |
| 27 | **openalgo-dotnet** | .NET | Reference only |

## E. AI/ML Trading Repos (reference for building `ai` package)

| # | Repo | GitHub URL | What we learn |
|---|---|---|---|
| 28 | **FinRL** | github.com/AI4Finance-Foundation/FinRL | RL agent architecture, OpenAI Gym trading environments |
| 29 | **FinMem** | github.com/AI4Finance-Foundation/FinMem | Layered memory design for trading agents |
| 30 | **TradingAgents** | github.com/TradingAgents-AI/TradingAgents | Multi-agent roles (analyst, risk, portfolio, trader) |
| 31 | **agency-agents** | github.com/msitarzewski/agency-agents | 156 agent personalities for Claude Code and OpenClaw |
| 32 | **PrimoGPT** | GitHub | LLM + RL + QLoRA combo approach for trading |
| 33 | **LLM-TradeBot** | GitHub | Dashboard patterns, LLM-driven trading UI |
| 34 | **Stockagent** | GitHub | LLM simulation patterns for market behavior |
| 35 | **autoresearch / autoresearch-mlx** | GitHub | Overnight autonomous optimization pipeline |

## F. Tools (use directly, not bundled)

| # | Tool | GitHub URL | What it does | When to use |
|---|---|---|---|---|
| 36 | **unsloth** | github.com/unslothai/unsloth | QLoRA fine-tuning, 4-bit, Flash Attention 2 | Future: WSL2 CUDA or native Linux |
| 37 | **GitNexus** | GitHub (10K stars) | Codebase knowledge graph, auto-generates AGENTS.md | Now: index FlintTrade + OpenAlgo |
| 38 | **CLI-Anything** | github.com/HKUDS/CLI-Anything | Auto-generate CLI from codebase | DROPPED — OpenClaw native skills replace this |

## G. Indian Market Data Repos (reference for `screener` and `historical`)

| # | Repo | GitHub URL | What we learn |
|---|---|---|---|
| 39 | **NSE-Option-Chain-Analyzer** | GitHub | OI analysis, PCR dynamics, max pain patterns |
| 40 | **Banknifty-Straddle** | GitHub | Straddle strategy logic for BANKNIFTY |

## H. Pip Libraries (installed, not cloned)

| # | Library | Used by | Install |
|---|---|---|---|
| 41 | `openalgo` | core | `pip install openalgo` |
| 42 | `duckdb` | historical, data | `pip install duckdb` |
| 43 | `chromadb` | ai | `pip install chromadb` |
| 44 | `lightgbm` | ai, backtest-engine | `pip install lightgbm` |
| 45 | `py_vollib_vectorized` | screener, backtest-engine | `pip install py_vollib_vectorized` |
| 46 | `quantstats` | backtest-engine, dashboard | `pip install quantstats` |
| 47 | `ta-lib` | engine, backtest-engine | `pip install TA-Lib` (requires C library) |
| 48 | `vectorbt` | backtest-engine | `pip install vectorbt` |
| 49 | `optionlab` | backtest-engine | `pip install optionlab` |
| 50 | `jugaad-data` | historical | `pip install jugaad-data` |
| 51 | `yfinance` | historical | `pip install yfinance` |
| 52 | `numba` | ditto | `pip install numba` |
| 53 | `sentence-transformers` | ai | `pip install sentence-transformers` |

## I. NPM Libraries (installed, not cloned)

| # | Library | Used by | Install |
|---|---|---|---|
| 54 | `lightweight-charts` | terminal | `npm install lightweight-charts` |
| 55 | `recharts` | dashboard, backtest | `npm install recharts` |
| 56 | `lucide-react` | all React packages | `npm install lucide-react` |

## J. Reading Lists (never cloned, just reference)

| # | Repo | What |
|---|---|---|
| 57 | **awesome-systematic-trading** | Curated list of systematic trading resources |
| 58 | **awesome-quant** | Curated list of quant finance resources |

---

## K. Claude Code Skills (installed globally on all machines)

### Skills (via npx skills add)

| # | Skill | Source | Install |
|---|---|---|---|
| 59 | **vercel-react-best-practices** | github.com/vercel-labs/agent-skills | `npx skills add https://github.com/vercel-labs/agent-skills` |
| 60 | **web-design-guidelines** | github.com/vercel-labs/agent-skills | Same as above |
| 61 | **vercel-composition-patterns** | github.com/vercel-labs/agent-skills | Same as above |
| 62 | **deploy-to-vercel** | github.com/vercel-labs/agent-skills | Same as above |
| 63 | **vercel-react-native-skills** | github.com/vercel-labs/agent-skills | Same as above |
| 64 | **find-skills** | github.com/vercel-labs/skills | `npx skills add https://github.com/vercel-labs/skills` |
| 65 | **planning-with-files** | github.com/OthmanAdi/planning-with-files | `npx skills add https://github.com/OthmanAdi/planning-with-files` |
| 66 | **pi-planning-with-files** | github.com/OthmanAdi/planning-with-files | Same as above |
| 67 | **gstack** | github.com/garrytan/gstack | `npx skills add https://github.com/garrytan/gstack` |
| 68 | **taste-skill** | github.com/Leonxlnx/taste-skill | `git clone` + copy to `~/.claude/skills/` |
| 69-76 | **firecrawl** (8 skills) | github.com/firecrawl/cli | `npx -y firecrawl-cli@latest init --all --browser` |

### Plugins (via /plugin in Claude Code)

| # | Plugin | Marketplace | Install |
|---|---|---|---|
| 77 | **superpowers** | obra/superpowers-marketplace | `/plugin marketplace add obra/superpowers-marketplace` then `/plugin install` |
| 78 | **frontend-design** | anthropics/claude-code | `/plugin marketplace add anthropics/claude-code` |
| 79 | **skill-creator** | anthropics/claude-code | Same marketplace |
| 80 | **claude-md-management** | anthropics/claude-code | Same marketplace |
| 81 | **voltagent-meta** | VoltAgent/awesome-claude-code-subagents | `/plugin marketplace add VoltAgent/awesome-claude-code-subagents` |
| 82 | **voltagent-lang** | VoltAgent/awesome-claude-code-subagents | Same marketplace |

### Agents (installed to ~/.claude/agents/)

| # | Collection | Source | Count |
|---|---|---|---|
| 83 | **agency-agents** | github.com/msitarzewski/agency-agents | 156 agents across engineering, design, testing, product, strategy, specialized, marketing, sales, support, academic, game-dev, spatial-computing, project-mgmt, paid-media |

### MCP Servers (via claude mcp add)

| # | MCP Server | What it does | Install |
|---|---|---|---|
| 84 | **context7** | Live, version-specific library docs (stops API hallucination) | `claude mcp add --transport stdio context7 -- npx -y @upstash/context7-mcp@latest` |
| 85 | **memory** | Persistent knowledge graph across sessions | `claude mcp add --transport stdio memory -- npx -y @modelcontextprotocol/server-memory` |
| 86 | **playwright** | Headless browser testing for UI automation | `claude mcp add --transport stdio playwright -- npx -y @anthropic/mcp-playwright` |
| 87 | **sequential-thinking** | Structured problem-solving for complex decisions | `claude mcp add --transport stdio sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking` |
| 88 | **github** | GitHub API access (repos, PRs, issues, code search) | `claude mcp add --transport stdio github -- npx -y @modelcontextprotocol/server-github` |
| 89 | **OpenAlgo MCP** | OpenAlgo documentation search (cloud, read-only) | Connected via Claude.ai project settings |
| 90 | **firecrawl** | Web scraping and browser automation | Installed with firecrawl CLI |

### Antigravity Skills

| # | Collection | Source | Install |
|---|---|---|---|
| 91 | **antigravity-awesome-skills** | github.com/anthropic-community/awesome-agent-skills | `npx antigravity-awesome-skills` |

---

## L. Skill Registries and Curated Lists (for discovery)

| # | Registry | URL | What |
|---|---|---|---|
| 92 | **skills.sh** | skills.sh | Official skill registry with install counts |
| 93 | **SkillsMP** | skillsmp.com | Community marketplace, 7,000+ skills |
| 94 | **SkillHub** | skillhub.club | 7,000+ AI-evaluated skills |
| 95 | **awesome-claude-skills (travisvn)** | github.com/travisvn/awesome-claude-skills | Curated, organized by category |
| 96 | **awesome-claude-skills (BehiSecc)** | github.com/BehiSecc/awesome-claude-skills | Security-focused curation |
| 97 | **Anthropic Official Skills** | github.com/anthropics/skills | Reference implementations |
| 98 | **wshobson/agents** | github.com/wshobson/agents | 112 agents, 146 skills, 16 orchestrators, 79 tools |
| 99 | **alirezarezvani/claude-skills** | github.com/alirezarezvani/claude-skills | 192 skills, 11-platform compatible |
| 100 | **tech-leads-club/agent-skills** | github.com/tech-leads-club/agent-skills | Security-scanned, hardened skills |

---

## M. Built-in Claude Code Commands (no install needed)

| # | Command | What it does |
|---|---|---|
| 101 | `/simplify` | 3 parallel review agents on changed files |
| 102 | `/review` | Code review with security, performance, correctness |
| 103 | `/batch` | Process multiple files/tasks in parallel |
| 104 | `/loop` | Iterative refinement until condition met |
| 105 | `/debug` | Structured debugging workflow |
| 106 | `/compact` | Compress conversation history |
| 107 | `/diff` | Interactive diff viewer of all changes |
| 108 | `/brainstorm` | Socratic questioning, design docs (from superpowers) |
| 109 | `/write-plan` | Structured implementation plans (from superpowers) |
| 110 | `/execute-plan` | Build from plans (from superpowers) |

---

## N. Infrastructure Tools (not repos, but referenced in conversations)

| # | Tool | What | Where |
|---|---|---|---|
| 111 | **LM Studio** | Local LLM inference, LM Link for multi-machine sharing | All machines |
| 112 | **Ollama** | Local LLM inference (ROCm or CUDA) | Dev machines |
| 113 | **WireGuard** | VPN mesh (private subnet) | Server + dev machines as clients |
| 114 | **gunicorn + eventlet** | Production WSGI server for OpenAlgo | Production server |
| 115 | **DuckDB** | Analytical database for Historify and data storage | All machines |
| 116 | **Docker** | Container deployment | Production server |
| 117 | **fail2ban + UFW** | Security hardening | Production server |
| 118 | **GitHub Desktop** | Git operations (Mac + Windows) | Dev machines |
| 119 | **Claude Desktop** | Claude + MCP for live trading operations | Dev machines |
| 120 | **VS Code + Claude Code** | Development IDE with AI agent | All machines |
