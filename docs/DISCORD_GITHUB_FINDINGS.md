# OpenAlgo Discord & GitHub Findings (2026-03-18)

## Common Issues from GitHub Issues (30 most recent)

### Critical Bugs We Must Handle
1. **SQLite concurrent access** — DatabaseError on order placement. OpenAlgo uses SQLite which doesn't handle concurrent writes well. FlintTrade should use the API layer, never touch OpenAlgo's DB directly.
2. **Sandbox mode sends real orders** — `In sandbox mode it sends order directly to broker terminal`. We MUST verify sandbox isolation before live testing.
3. **closeposition ignores strategy parameter** — closes ALL positions instead of strategy-specific. Our Safety System must track positions per-strategy.
4. **WebSocket ping/heartbeat missing** — connections drop silently. We need our own heartbeat logic in websocket.js.
5. **MCX symbol format inconsistency** — history API vs options API use different formats. Our symbol resolver must normalize.
6. **PNL calculation incorrect** — realized vs unrealized wrong for some brokers. Calculate ourselves, don't trust broker PNL.

### Feature Requests We Should Implement
1. **Daily Target and Daily Loss** (issue #) — exactly our MTM feature
2. **Historical option chain** — past dates data. Our historical package covers this.
3. **Standard WebSocket Ping/Heartbeat** — enhancement request. We should implement this.

### Language/SDK Issues
- Python SDK is the primary, most tested
- Java, Go, .NET, Node.js, Rust SDKs exist but less community support
- Most community issues are Python-related
- Excel Add-In has active users

## OpenAlgo Official Language Support
From docs.openalgo.in:
- **Python** — primary SDK, `pip install openalgo`
- **Node.js** — `npm install openalgo`
- **Go** — openalgo-go
- **Rust** — openalgo-rust (with WebSocket)
- **.NET** — OpenAlgo.NET via NuGet
- **Java** — OpenAlgo-Java
- **MetaTrader 5** — EA integration
- **Excel** — Add-In with formulas
- **Google Sheets** — Apps Script

## FlintTrade Language Stack Decision
| Layer | Language | Rationale |
|-------|----------|-----------|
| Backend | Python 3.12 | OpenAlgo ecosystem, all packages, community |
| Frontend | React 19 + JavaScript | Already built, OpenAlgo frontend is React |
| Data | DuckDB + SQLite | Lightweight, fast analytics |
| Indicators | Python + Numba JIT | pyindicators pattern |
| Future perf | Rust (raptorbt pattern) | Only if backtesting speed is bottleneck |

**NO C++, NO Java, NO Go in FlintTrade codebase.** Python + React only.

## Discord Channel Structure
- #help-and-suggestions — user support
- #developers — dev discussion
- #llm-and-agents — AI/MCP integration
- #python — Python-specific issues
- #algoregulations — SEBI compliance
- #algomirror — multi-account
- #openalgo-charts — charting library
- #openalgo-flow — visual automation
- #fosshack2026 — hackathon (active community)
