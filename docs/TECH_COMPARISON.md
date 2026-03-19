# FlintTrade Tech Stack Comparison vs Reference Repos

> Generated 2026-03-19. Compares FlintTrade's current tech choices against every
> reference repository in `.reference/repos/`.

---

## FlintTrade Baseline (packages/terminal)

| Dimension | Current Choice |
|---|---|
| **UI Framework** | React 19, functional components |
| **Language** | JavaScript (no TypeScript) |
| **CSS** | Tailwind CSS v4 (`@tailwindcss/vite` plugin), custom dark theme via `@theme` |
| **Charting** | Lightweight Charts v5 (financial), Recharts v2 (non-financial) |
| **State Mgmt** | React Context / local state (no external library) |
| **Build Tool** | Vite 6 |
| **Layout** | FlexLayout-React v0.8 (dockable panels) |
| **Icons** | lucide-react v0.577 |
| **Component Lib** | None (custom Tailwind components) |
| **Testing** | Vitest 3 |
| **Backend (Python)** | Flask (via OpenAlgo), DuckDB (data pkg) |
| **Indicators** | py-vollib-vectorized, mibian, nsepython |
| **Backtesting** | quantstats, custom engine |
| **Data Sources** | OpenAlgo API, openchart, yfinance, jugaad-data |

---

## Repo-by-Repo Comparison

### 1. openalgo-chart (crypt0inf0) -- Tier: External

**What it is:** Full-featured charting terminal with PineScript editor, option chain,
depth of market, position tracking, alerts, multi-chart grid, replay, command palette.
Most mature and complex reference.

| Dimension | FlintTrade | openalgo-chart | Better | Recommendation |
|---|---|---|---|---|
| **React version** | 19 | 19.2 | Tie | Keep ours |
| **Language** | JavaScript | TypeScript | **openalgo-chart** -- type safety catches bugs at compile time, especially critical in financial apps | **SWITCH to TypeScript** -- this is the single highest-impact improvement we can make |
| **CSS approach** | Tailwind v4 | CSS Modules (92+ `.module.css` files) | FlintTrade | Keep Tailwind -- CSS Modules require more boilerplate, no utility-first ergonomics |
| **Charting** | Lightweight Charts v5 | Lightweight Charts v5.0.9 + PineTS (pinets v0.8.4) | **openalgo-chart** -- PineTS adds TradingView indicator language support | **ADOPT PineTS** when we build the Scalper/Strategy modules |
| **State mgmt** | Context/local | Zustand v5 (workspaceStore, marketDataStore) | **openalgo-chart** -- Zustand is minimal, performant, perfect for trading state | **SWITCH to Zustand** -- we need global state for positions, watchlists, settings |
| **Build tool** | Vite 6 | Vite 7.2 | **openalgo-chart** (newer) | Keep Vite, upgrade when stable |
| **Layout** | FlexLayout-React | None (custom CSS grid) | FlintTrade | Keep FlexLayout -- dockable panels are essential for trading UIs |
| **Icons** | lucide-react 0.577 | lucide-react 0.555 | Tie | Keep ours (same lib) |
| **Component lib** | Custom | Custom (shared/* components) | Tie | Adopt their shared component pattern (BaseModal, BaseTable, BaseDialog, BaseContextMenu) |
| **Testing** | Vitest 3 | Vitest 4 + Playwright E2E + Testing Library + MSW | **openalgo-chart** -- complete test pyramid | **ADOPT** Playwright for E2E, MSW for API mocking |
| **Code editor** | None | Monaco Editor (@monaco-editor/react) | **openalgo-chart** | Adopt for Strategy/PineScript module |
| **Screenshot** | None | html2canvas | **openalgo-chart** | Nice-to-have for sharing charts |

**Key takeaway:** openalgo-chart is the gold standard. We should adopt TypeScript,
Zustand, PineTS, and their testing infrastructure. Our Tailwind + FlexLayout choices
are actually better for our use case.

---

### 2. openalgo-flow -- Tier: Tier 1 Core

**What it is:** Visual flow builder for OpenAlgo strategies with node-based UI.
Uses the shadcn/ui pattern (Radix + Tailwind + CVA).

| Dimension | FlintTrade | openalgo-flow | Better | Recommendation |
|---|---|---|---|---|
| **React version** | 19 | 18.3 | FlintTrade | Keep ours |
| **Language** | JavaScript | TypeScript | **openalgo-flow** | SWITCH (confirmed by 2nd repo) |
| **CSS approach** | Tailwind v4 | Tailwind v3 + tailwind-merge + CVA | Tie (different needs) | **ADOPT tailwind-merge and CVA** for reusable component variants |
| **Charting** | LWC v5 + Recharts | None (flow-builder, not charting) | N/A | N/A |
| **State mgmt** | Context | Zustand v5 + TanStack React Query v5 | **openalgo-flow** | **ADOPT React Query** for server state (API calls, caching, refetching) |
| **Build tool** | Vite 6 | Vite 6 | Tie | Keep |
| **Layout** | FlexLayout | @xyflow/react (node graph) | Different use cases | Consider @xyflow for Strategy Builder module |
| **Icons** | lucide-react | lucide-react | Tie | Keep |
| **Component lib** | Custom | shadcn/ui pattern (Radix primitives + CVA) | **openalgo-flow** | **ADOPT shadcn/ui pattern** -- accessible, composable, Tailwind-native |
| **Forms** | None yet | react-hook-form + @hookform/resolvers + zod | **openalgo-flow** | **ADOPT** for order forms, settings, strategy config |
| **Routing** | None | react-router-dom v7 | **openalgo-flow** | Adopt when we add multi-page navigation |

**Key takeaway:** The shadcn/ui stack (Radix + CVA + tailwind-merge) and
React Query + react-hook-form + zod are the modern standard. Adopt all of them.

---

### 3. etftracker (marketcalls) -- Tier: marketcalls-all

**What it is:** Multi-dashboard ETF analytics app with 10 dashboards. Full-stack
with React + FastAPI + SQLite.

| Dimension | FlintTrade | etftracker | Better | Recommendation |
|---|---|---|---|---|
| **React version** | 19 | 19.2 | Tie | Keep |
| **Language** | JavaScript | TypeScript | **etftracker** | SWITCH (confirmed by 3rd repo) |
| **CSS approach** | Tailwind v4 | Custom CSS vars (dark theme, DM Sans font) | FlintTrade | Keep Tailwind -- their raw CSS vars approach is more fragile |
| **Charting** | LWC v5 + Recharts | Plotly.js v3 (react-plotly.js) | **Depends** -- Plotly is better for scientific/heatmap charts, LWC better for financial OHLC | **HYBRID**: Keep LWC for price charts, **CONSIDER Plotly** for heatmaps/correlation/quilt charts |
| **State mgmt** | Context | None visible (prop drilling) | FlintTrade | Keep ours |
| **Build tool** | Vite 6 | Vite 8 | etftracker (newer) | Upgrade when stable |
| **Backend** | Flask (via OpenAlgo) | FastAPI + uvicorn | **etftracker** | FlintTrade Python packages should **USE FastAPI** for any new backend services |
| **Database** | DuckDB | aiosqlite (async SQLite) | **FlintTrade** -- DuckDB is faster for analytics | Keep DuckDB |
| **Data source** | OpenAlgo + openchart + yfinance | yfinance | FlintTrade (more sources) | Keep ours |
| **HTTP client** | httpx | axios | FlintTrade | Keep httpx (Python), but **ADOPT axios** on frontend for API calls |
| **Routing** | None | react-router-dom v7 | **etftracker** | Adopt (confirmed by 2nd repo) |

**Key takeaway:** Plotly is excellent for heatmaps, correlation matrices, and quilt
charts that LWC cannot do well. Consider adding plotly.js for non-candlestick
visualizations. Their FastAPI + async SQLite backend pattern is cleaner than Flask.

---

### 4. pyindicators (marketcalls) -- Tier: marketcalls-all

**What it is:** Pure Python technical indicators library using Numba JIT compilation.
No frontend.

| Dimension | FlintTrade | pyindicators | Better | Recommendation |
|---|---|---|---|---|
| **Indicators** | py-vollib-vectorized + mibian + nsepython | Custom Numba-JIT indicators (numpy + numba) | **pyindicators** for raw speed; FlintTrade for options-specific | **ADOPT pyindicators** as a dependency -- Numba-JIT indicators are 10-100x faster than pandas-ta |
| **Dependencies** | numpy, pandas, scipy (via vollib) | numpy + numba only (minimal) | **pyindicators** (lighter) | Use pyindicators for momentum/trend/volatility/volume; keep vollib for options Greeks |
| **Testing** | pytest | pytest + pytest-benchmark | **pyindicators** | Add benchmark tests for our indicator calculations |
| **Code quality** | ruff | black + ruff + mypy | **pyindicators** | **ADOPT mypy** for Python type checking |

**Key takeaway:** Numba-JIT indicators are the performance play. pyindicators should
be a dependency of our screener and backtest-engine packages. We should add it to
our requirements and delegate SMA/EMA/RSI/MACD/Bollinger/ATR to it instead of
pandas-ta or manual calculation.

---

### 5. trading-strategies-openalgo -- Tier: Tier 2 Ecosystem

**What it is:** Backtesting engine with web dashboard. Uses FastAPI for the
backtest API and Flask for the grid/supertrend trading bot dashboards.

| Dimension | FlintTrade | trading-strategies | Better | Recommendation |
|---|---|---|---|---|
| **Backend** | Flask (OpenAlgo) | FastAPI (backtest) + Flask (bots) | Tie (both use both) | Standardize on FastAPI for new services |
| **Backtesting** | quantstats, custom | Custom engine (events, metrics, portfolio, tax calc, order sim) | **trading-strategies** (more complete) | Study their tax_calculator.py (India STT/CTT), order_simulator, and walk-forward patterns |
| **Charting** | LWC + Recharts | Plotly v5 (Jinja2 templates) | FlintTrade (React-based) | Keep ours |
| **Data** | DuckDB + openchart + yfinance | pyarrow + Parquet | Tie (both columnar) | Keep DuckDB (superset of Parquet reads) |
| **Indicators** | vollib + mibian | ta v0.10.2 (TA-Lib wrapper) + scikit-learn | **Depends** -- ta has 150+ indicators; scikit-learn adds ML | **ADOPT ta** (pure Python TA-Lib) for breadth of indicators; scikit-learn for ML signals |
| **Visualization** | React SPA | matplotlib + seaborn (server-rendered) | FlintTrade | Keep React-based charting |
| **Real-time** | WebSocket (via OpenAlgo) | flask-socketio + eventlet | FlintTrade (native WS) | Keep ours |

**Key takeaway:** Their backtest engine architecture (events, portfolio, order sim,
tax calculator for India) is excellent reference. The `ta` library has more
indicators than what we currently use. Their India-specific tax calculator
(STT, CTT, GST, stamp duty) is something we must build.

---

### 6. option-chain -- Tier: Tier 2 Ecosystem

**What it is:** Flask-based option chain viewer with SSE live updates.
Server-rendered HTML with Tailwind + DaisyUI.

| Dimension | FlintTrade | option-chain | Better | Recommendation |
|---|---|---|---|---|
| **UI approach** | React SPA | Flask + Jinja2 server-rendered | FlintTrade | Keep React -- we need client-side interactivity for trading |
| **CSS** | Tailwind v4 | Tailwind v3 + DaisyUI v4 | **option-chain** for rapid prototyping | Keep Tailwind v4 -- DaisyUI is a crutch that limits customization |
| **Data streaming** | WebSocket | Server-Sent Events (SSE) | FlintTrade | Keep WebSocket -- bidirectional, lower latency for trading |
| **Backend** | (via OpenAlgo) | Flask with WebSocket manager | Tie | Study their `ProfessionalWebSocketManager` pattern |
| **Component lib** | Custom | DaisyUI (pre-built components) | FlintTrade (more control) | Keep custom -- trading UIs need pixel-level control |

**Key takeaway:** Their WebSocket manager pattern and option chain data manager
are good reference for our screener package. But their tech choices (server-rendered,
DaisyUI, SSE) are inferior for a real-time trading terminal.

---

### 7. openalgo-portfoliogreeks -- Tier: Tier 1 Core

**What it is:** Flask app for portfolio-level option Greeks using mibian.
Server-rendered with Tailwind CDN + DaisyUI.

| Dimension | FlintTrade | portfoliogreeks | Better | Recommendation |
|---|---|---|---|---|
| **UI approach** | React SPA | Flask + Jinja2 + Tailwind CDN + DaisyUI v4 | FlintTrade | Keep React |
| **Greeks engine** | py-vollib-vectorized + mibian | mibian only | FlintTrade | Keep vollib for vectorized batch Greeks; mibian for simple pricing |
| **Backend** | (via OpenAlgo) | Flask + Flask-WTF (CSRF) | Tie | Their CSRF pattern is good for forms |
| **Data storage** | DuckDB | JSON files | FlintTrade | Keep DuckDB |
| **Greeks math** | Planned in screener pkg | mibian.BS() for IV + Greeks | **Tie** -- same mibian library | Already absorbed -- our screener package uses the same mibian approach |

**Key takeaway:** We have already absorbed the essential parts of this repo
(mibian for Greeks, position-aware signs, lot-size-multiplied portfolio totals).
Our screener package is more capable with py-vollib-vectorized for batch computation.

---

### 8. sector-rotation-map -- Tier: Tier 2 Ecosystem

**What it is:** Interactive Relative Rotation Graph (RRG) dashboard.
Vanilla JS + D3.js + FastAPI backend.

| Dimension | FlintTrade | sector-rotation-map | Better | Recommendation |
|---|---|---|---|---|
| **UI framework** | React | Vanilla JS (no framework) | FlintTrade | Keep React |
| **Charting** | LWC + Recharts | D3.js v7 (scatter + animated tails) | **sector-rotation-map** for this specific viz | **CONSIDER D3** for RRG/scatter plots in our Futures OI Quadrant module |
| **CSS** | Tailwind v4 | Custom CSS (Inter + JetBrains Mono, same dark theme) | Tie (same aesthetic) | Keep Tailwind |
| **Backend** | Flask (OpenAlgo) | FastAPI + uvicorn | **sector-rotation** | Use FastAPI for new services (confirmed by 3rd repo) |
| **Data** | Multiple sources | OpenAlgo + pandas + numpy | Tie | Keep ours |
| **Fonts** | Inter + JetBrains Mono | Inter + JetBrains Mono | Identical | Validates our font choices |

**Key takeaway:** D3.js is the right tool for custom scatter/RRG visualizations
that neither LWC nor Recharts handle well. The same dark theme palette
(#0a0a0f bg, Inter font, green/red P&L) validates our design system choices.
Their use of FastAPI again confirms we should standardize on it.

---

### 9. trading-journal -- Tier: Tier 2 Ecosystem

**What it is:** Full-stack trade journal with Next.js frontend and FastAPI backend.
Most sophisticated architecture of all reference repos.

| Dimension | FlintTrade | trading-journal | Better | Recommendation |
|---|---|---|---|---|
| **UI framework** | React 19 (Vite) | React 18 (Next.js 14) | **Tie** -- Vite for SPA, Next for SSR | Keep Vite -- trading terminals are SPAs, not content sites |
| **Language** | JavaScript | TypeScript | **trading-journal** | SWITCH (confirmed by 4th repo) |
| **CSS** | Tailwind v4 | Tailwind v3 + tailwind-merge + tailwindcss-animate | **trading-journal** | **ADOPT tailwindcss-animate** for smooth micro-interactions |
| **Charting** | LWC + Recharts | Recharts v2 | Tie | Already using Recharts |
| **State mgmt** | Context | Zustand v4 | **trading-journal** | SWITCH to Zustand (confirmed by 3rd repo) |
| **Component lib** | Custom | shadcn/ui (Radix + CVA + clsx) + next-themes | **trading-journal** | ADOPT shadcn/ui (confirmed by 2nd repo) |
| **Icons** | lucide-react | lucide-react | Tie | Keep |
| **Backend** | Flask | FastAPI + SQLAlchemy + Pydantic | **trading-journal** | ADOPT this pattern for Journal module backend |
| **Database** | DuckDB | SQLite (via SQLAlchemy + aiosqlite) | **Depends** -- DuckDB for analytics, SQLite+ORM for CRUD | **HYBRID**: DuckDB for market data analytics, SQLAlchemy for user data (journal entries, portfolios) |
| **Auth** | None | bcrypt + python-jose (JWT) + passlib | **trading-journal** | Adopt when we add multi-user support |
| **Date handling** | Native | date-fns v3 | **trading-journal** | **ADOPT date-fns** for consistent date formatting across the terminal |
| **HTTP client** | fetch | axios | **trading-journal** | Consider axios for interceptors and cancel tokens |

**Key takeaway:** This repo validates the shadcn/ui + Zustand + Recharts stack.
Their FastAPI + SQLAlchemy backend is the right pattern for CRUD-heavy features
like journals and portfolios. date-fns is a must-have for trading date formatting.

---

## Consolidated Recommendations

### MUST DO (High impact, low risk)

| Priority | Change | Why | Effort |
|---|---|---|---|
| 1 | **Add TypeScript** | 4/4 reference React repos use TS. Financial apps need type safety. Catches API shape errors at compile time. | Medium (incremental, `.tsx` per file) |
| 2 | **Add Zustand v5** | 3/4 React repos use it. We need global state for positions, watchlists, market data, settings. Context doesn't scale. | Low (add package, create stores) |
| 3 | **Add React Query (TanStack Query v5)** | openalgo-flow uses it. Perfect for API calls with auto-refetching, caching, loading/error states. Replaces manual `useEffect` + `fetch`. | Low-Medium |
| 4 | **Adopt shadcn/ui pattern** | Radix primitives + CVA + tailwind-merge. 2 repos use it. Accessible, composable, Tailwind-native. Not a library -- copy/paste components. | Medium (set up once, use everywhere) |
| 5 | **Add react-hook-form + zod** | openalgo-flow uses it. Essential for OrderPad, strategy config, settings forms. Type-safe validation. | Low |
| 6 | **Add date-fns** | Trading needs consistent date formatting (expiry dates, trade timestamps, session times). | Trivial |

### SHOULD DO (High impact, medium effort)

| Priority | Change | Why | Effort |
|---|---|---|---|
| 7 | **Add PineTS (pinets)** | openalgo-chart uses it. Enables TradingView Pine Script indicators on LWC v5. Huge feature differentiator. | Medium |
| 8 | **Add Playwright E2E tests** | openalgo-chart has full E2E test suite. Trading UIs need integration testing. | Medium |
| 9 | **Add MSW (Mock Service Worker)** | openalgo-chart uses it. Mock OpenAlgo API during development and testing. | Low |
| 10 | **Adopt pyindicators (Numba-JIT)** | 10-100x faster than pandas-ta for indicator computation. Direct drop-in for our screener. | Low (pip install) |
| 11 | **Add `ta` library** | trading-strategies uses it. 150+ indicators vs our current mibian+vollib. | Low (pip install) |
| 12 | **Standardize on FastAPI** | 4/4 Python backend repos with new code use FastAPI. Async, Pydantic validation, auto-docs. | Medium (new services only) |

### CONSIDER (Nice to have)

| Priority | Change | Why | Effort |
|---|---|---|---|
| 13 | **Add Plotly.js** | etftracker uses it for heatmaps, correlation, quilt charts. LWC can't do these. Bundle size concern (~3MB). | Medium |
| 14 | **Add D3.js** | sector-rotation-map uses it for RRG. Best for custom scatter/force/tree visualizations. | Medium (per-chart) |
| 15 | **Add Monaco Editor** | openalgo-chart uses it for PineScript editing. Needed for Strategy Builder module. | Low (when needed) |
| 16 | **Add html2canvas** | openalgo-chart uses it. Chart screenshot sharing. | Trivial |
| 17 | **Add tailwindcss-animate** | trading-journal uses it. Smooth transitions for panels, modals, toasts. | Trivial |
| 18 | **Add SQLAlchemy** | trading-journal uses it. Needed for CRUD-heavy features (journal, portfolios). | Medium |
| 19 | **Add axios** | etftracker + trading-journal use it. Interceptors, cancel tokens, better error handling than fetch. | Low |

### KEEP (Our choices are correct)

| Dimension | Our Choice | Validation |
|---|---|---|
| **Tailwind CSS v4** | Better than CSS Modules (openalgo-chart), raw CSS (sector-rotation), or CDN Tailwind (portfoliogreeks) |
| **Lightweight Charts v5** | Used by openalgo-chart (the most advanced reference). Industry standard for financial charts. |
| **Recharts** | Used by trading-journal. Good for non-financial charts. Keep alongside LWC. |
| **FlexLayout-React** | No reference repo has dockable panels. This is our differentiator for professional trading UIs. |
| **lucide-react** | Used by 3/4 React repos. Consistent, tree-shakeable, active. |
| **Vite** | All React repos use Vite (except trading-journal which uses Next.js). Fastest build tool. |
| **DuckDB** | Better than SQLite for analytics workloads. Columnar, vectorized, reads Parquet natively. |
| **Inter + JetBrains Mono** | Validated by sector-rotation-map (identical font stack). Professional trading aesthetic. |
| **Dark theme palette** | `#0a0a0f` bg used by etftracker too. `#22c55e`/`#ef4444` for P&L is universal. |
| **vollib + mibian** | portfoliogreeks uses mibian. vollib adds vectorized batch computation we need. |

### DO NOT ADOPT

| Technology | Used By | Why Not |
|---|---|---|
| **Next.js** | trading-journal | Trading terminals are SPAs, not content sites. SSR adds complexity with no benefit for us. |
| **DaisyUI** | option-chain, portfoliogreeks | Pre-built component library limits customization. Trading UIs need pixel-level control. shadcn/ui is the right abstraction level. |
| **CSS Modules** | openalgo-chart | 92 separate `.module.css` files is maintenance overhead. Tailwind utilities are faster to write and more consistent. |
| **Server-rendered (Jinja2)** | option-chain, portfoliogreeks, sector-rotation | Client-side React is essential for real-time trading interactivity. |
| **Plotly as primary** | etftracker | ~3MB bundle size. Use only for specific charts (heatmaps, correlation) that LWC/Recharts cannot do. |
| **Flask-SocketIO** | trading-strategies | Native WebSocket (via OpenAlgo port 8765) is more performant. |
| **axios** (as mandatory) | etftracker, trading-journal | fetch API + React Query handles 95% of cases. axios only if we need interceptors. |

---

## Bundle Size Impact Analysis

Current `flint-terminal` has 6 dependencies. Adding the recommended stack:

| Package | Gzipped Size | Category |
|---|---|---|
| zustand | ~1.5 KB | Must do |
| @tanstack/react-query | ~13 KB | Must do |
| tailwind-merge | ~3 KB | Must do |
| class-variance-authority | ~1 KB | Must do |
| clsx | ~0.3 KB | Must do |
| zod | ~13 KB | Must do |
| react-hook-form | ~9 KB | Must do |
| date-fns | ~6 KB (tree-shakeable) | Must do |
| pinets | ~15 KB (estimate) | Should do |
| **Total "Must Do"** | **~47 KB gzipped** | Acceptable |

For context, React + React DOM alone are ~45 KB gzipped. Adding ~47 KB for a
complete trading terminal infrastructure is excellent value.

---

## Migration Path

### Phase 1: Foundation (before next feature build)
1. `npm i zustand @tanstack/react-query` -- add state management
2. `npm i tailwind-merge class-variance-authority clsx` -- component variants
3. `npm i zod react-hook-form @hookform/resolvers` -- form validation
4. `npm i date-fns` -- date formatting
5. Create `src/stores/` directory with `marketStore.ts`, `workspaceStore.ts`
6. Create `src/lib/utils.ts` with `cn()` helper (clsx + tailwind-merge)
7. Begin `.tsx` migration incrementally (rename files, add types)

### Phase 2: Component Library (during F2-F8 build)
8. Set up Radix primitives as needed (Dialog, Select, Dropdown, Tooltip, Toast)
9. Create shared components following openalgo-chart's pattern
10. Add `pinets` for TradingView indicator support

### Phase 3: Testing & Quality (ongoing)
11. `npm i -D @playwright/test msw @testing-library/react`
12. `pip install pyindicators ta` in relevant Python packages
13. Add Playwright E2E tests for critical flows (connect, place order, view positions)

### Phase 4: Python Backend (when building new services)
14. Use FastAPI + Pydantic for any new backend endpoints
15. Add SQLAlchemy for CRUD features (journal, portfolios)
16. Add mypy to Python CI pipeline

---

## Summary Matrix

```
                     FT   oac  oaf  etf  pyi  tso  oc   opg  srm  tj
React               19   19   18   19   --   --   --   --   --   18
TypeScript          NO   YES  YES  YES  --   --   --   --   --   YES
Tailwind            v4   NO   v3   NO   --   --   v3   CDN  NO   v3
Zustand             NO   v5   v5   NO   --   --   --   --   --   v4
React Query         NO   NO   v5   NO   --   --   --   --   --   NO
LWC                 v5   v5   NO   NO   --   --   --   --   --   NO
Recharts            v2   NO   NO   NO   --   --   --   --   --   v2
Plotly              NO   NO   NO   v3   --   v5   --   --   --   NO
D3                  NO   NO   NO   NO   --   --   --   --   v7   NO
shadcn/Radix        NO   NO   YES  NO   --   --   --   --   --   YES
DaisyUI             NO   NO   NO   NO   --   --   YES  YES  --   NO
FlexLayout          YES  NO   NO   NO   --   --   --   --   --   NO
Vite                v6   v7   v6   v8   --   --   --   --   --   NO
FastAPI             NO   --   --   YES  --   YES  --   --   YES  YES
Flask               YES  --   --   NO   --   YES  YES  YES  --   NO
DuckDB              YES  --   --   NO   --   NO   --   --   --   NO
SQLAlchemy          NO   --   --   NO   --   NO   --   --   --   YES
Numba               NO   --   --   --   YES  --   --   --   --   --
mibian              YES  --   --   --   --   --   --   YES  --   --
```

Legend: FT=FlintTrade, oac=openalgo-chart, oaf=openalgo-flow, etf=etftracker,
pyi=pyindicators, tso=trading-strategies-openalgo, oc=option-chain,
opg=portfoliogreeks, srm=sector-rotation-map, tj=trading-journal.
`--` = not applicable (backend-only or frontend-only repo).
