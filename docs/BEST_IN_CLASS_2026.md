# Best-in-Class Libraries for a Real-Time Trading Terminal (March 2026)

> Research compiled March 2026. Data from npm trends, GitHub, PyPI, and community benchmarks.
> Purpose: Inform FlintTrade technology choices with evidence, not vibes.

---

## 1. Charting for Trading Terminals

**Goal:** Real-time candlestick charts + technical indicators + drawing tools for an F&O terminal.

| Library | Bundle Size | GitHub Stars | npm Weekly DL | License | Last Updated |
|---|---|---|---|---|---|
| **TradingView Advanced Charts** | ~500 KB (proprietary blob) | N/A (closed source) | N/A (private npm) | Free for public web apps; no personal/internal use | Active (March 2026) |
| **Lightweight Charts v5** | **35 KB** (16% smaller than v4) | **13,300** | **225K** | Apache 2.0 | Dec 2025 (v5.1.0) |
| **Apache ECharts** | ~800 KB (tree-shakeable to ~300 KB) | 62K | 1.5M | Apache 2.0 | Active |
| **Highcharts Stock** | ~300 KB | 12K | 2M | **Commercial ($833+/yr)** | Active |
| **Recharts** | ~150 KB | 24K | 5M | MIT | Active |
| **D3.js** | ~250 KB | 110K | 8M | ISC | Active |
| **Plotly.js** | ~3.5 MB | 17K | 500K | MIT | Active |

### Analysis

- **TradingView Advanced Charts** is the gold standard -- 100+ built-in indicators, drawing tools, multi-pane, replay, the full TradingView experience. Free for public-facing web apps (no personal/internal use). Closed-source, delivered as a private npm package after license approval. If you qualify, nothing else comes close for feature completeness.
- **Lightweight Charts v5** is the open-source winner. 35 KB, canvas-based, multi-pane support (new in v5), yield curve and options chart types. No built-in indicators or drawing tools -- you implement them yourself via the enhanced plugin system. Perfect for teams that want full control.
- **ECharts** is the general-purpose powerhouse but not finance-native. Candlestick support exists but lacks the tick-level optimizations of LWC.
- **Highcharts Stock** is excellent but expensive. The $833/yr starting price is hard to justify when LWC v5 is free and purpose-built.
- **D3.js** is a DOM manipulation library, not a chart library. Building a trading chart from D3 is months of work. React DOM conflicts make it worse.
- **Recharts/Plotly** are dashboard charting tools. Neither handles real-time candlestick streaming at the performance level a terminal needs.

### VERDICT

**Lightweight Charts v5** for FlintTrade. Apache 2.0 license, 35 KB, multi-pane, canvas-rendered, purpose-built for financial data. Implement indicators and drawing tools via plugins. If FlintTrade ever goes commercial/public-facing, TradingView Advanced Charts becomes viable as a drop-in upgrade.

---

## 2. CSS Framework for Dense Data UIs

**Goal:** Developer speed + tiny bundle + dense layout for tables, grids, panels, real-time numbers.

| Library | Approach | Bundle Impact | GitHub Stars | npm Weekly DL | Learning Curve |
|---|---|---|---|---|---|
| **shadcn/ui + Tailwind** | Copy-paste components, Radix primitives | **Zero runtime** (just CSS + your code) | **110K** | 204K (CLI) | Low-Medium |
| **Tailwind CSS v4 raw** | Utility classes only | Zero runtime | 87K | 15M | Low |
| **DaisyUI v5 + Tailwind** | CSS class components | Zero JS runtime | 35K | 700K | Low |
| **Radix UI + Tailwind** | Unstyled accessible primitives | ~5-15 KB per component | 17K | 4M | Medium |
| **MUI (Material UI)** | Full component library | **200+ KB** runtime | 95K | 5.8M | Medium |
| **Ant Design** | Full component library | 200+ KB runtime | 93K | 1.5M | Medium |

### Analysis

- **shadcn/ui** is the 2026 consensus pick for new React projects. You own the component source code (no hidden dependencies), it's built on Radix primitives (WCAG accessible), and the Tailwind v4 integration means zero runtime CSS overhead. The ecosystem is exploding with community blocks, themes, and AI-friendly patterns.
- **Tailwind v4 raw** is what FlintTrade already uses. Works perfectly for custom components. shadcn/ui is essentially a "starter kit" on top of Tailwind -- you get pre-built data tables, dialogs, dropdowns, command palettes, and resizable panels.
- **DaisyUI v5** ships zero JS and is excellent for rapid prototyping, but requires manual work for advanced accessibility patterns. Less control than shadcn/ui for custom data-heavy layouts.
- **MUI** has the broadest component set (data grids, date pickers, tree views) but carries 200+ KB of runtime and enforces Material Design opinions that conflict with dense trading UIs.
- **Ant Design** is enterprise-grade but similarly heavy and opinionated toward admin dashboards rather than real-time terminals.

### VERDICT

**shadcn/ui + Tailwind CSS v4**. Zero runtime overhead, full code ownership, Radix-powered accessibility, and the fastest-growing component ecosystem in React. FlintTrade already uses Tailwind v4 -- adopting shadcn/ui is additive, not a rewrite. Specifically useful: `data-table`, `command`, `dialog`, `popover`, `resizable`, `tooltip` components.

---

## 3. Layout/Docking System

**Goal:** Groww 915-style customizable workspace -- drag tabs, split panes, floating panels, save/restore layouts.

| Library | Bundle Size | GitHub Stars | npm Weekly DL | Zero Deps | Framework Support | Last Updated |
|---|---|---|---|---|---|---|
| **Dockview** | ~50 KB | **3,100** | **39K** | **Yes** | React, Vue, Angular, Vanilla | March 2026 (v5.1.0) |
| **FlexLayout-React** | ~80 KB | 1,300 | 58K | No | React only | Stale (forks active) |
| **Golden Layout** | ~100 KB | **6,700** | 14K | No | Framework-agnostic | Maintenance mode |
| **react-mosaic** | ~60 KB | 4K | 30K | No | React only | Low activity |
| **react-resizable-panels** | ~15 KB | 4.5K | **2.8M** | Yes | React only | Active |
| **Allotment** | ~20 KB | 1.5K | 114K | No | React only | Active |

### Analysis

- **Dockview v5** is the clear winner for IDE/terminal-style docking. Zero dependencies, full serialization/deserialization, tabs, groups, grids, splitviews, drag-and-drop, floating panels, and popout windows. Multi-framework support means if FlintTrade ever adds a Vue or Angular variant, the layout system carries over. Active development (v5.1.0 released days ago).
- **FlexLayout-React** has the most npm downloads but the original repo has maintenance issues. Active forks exist but introduce uncertainty. React-only.
- **Golden Layout** has the highest star count (battle-tested), but is in maintenance mode. No major releases. The API feels dated compared to Dockview.
- **react-resizable-panels** is the most downloaded (2.8M/week) but is a simpler split-panel library, not a full docking system. No tabs, no drag-to-dock, no floating panels. Good for simple layouts, insufficient for a trading workspace.
- **react-mosaic** is a tiling window manager -- closer to what we need than resizable-panels, but less feature-rich than Dockview and lower activity.

### VERDICT

**Dockview v5**. Zero dependencies, full docking (tabs + groups + grids + floating + popout), layout serialization, active development, multi-framework. This is what trading terminals need. Use **react-resizable-panels** for simpler sub-layouts within individual widgets if needed.

---

## 4. Data Grid for Trading Tables

**Goal:** 500+ row option chains with real-time Greek/IV/price updates, 10-50 updates per second.

| Library | Rendering | Bundle Size | GitHub Stars | npm Weekly DL | License | Real-time Perf |
|---|---|---|---|---|---|---|
| **AG Grid** | DOM (virtualized) | ~200 KB (Community) | **15,100** | **3M+** | MIT (Community) / Commercial (Enterprise) | Excellent |
| **TanStack Table v8** | Headless (you render) | ~30 KB total | **27,800** | **7.9M** | MIT | Good (<10K rows) |
| **Glide Data Grid** | **Canvas** | ~100 KB | 4,500 | 95K | MIT | **Best** (100K+ updates/sec) |
| **MUI X DataGrid** | DOM (virtualized) | ~150 KB | 3K | 1M | MIT (Community) / Commercial | Good |

### Analysis

- **Glide Data Grid** is purpose-built for real-time: canvas-based rendering, handles hundreds of thousands of updates per second, supports millions of rows, MIT licensed. The canvas approach means updates bypass React's reconciliation entirely -- critical for option chains where 20+ columns update every tick. The trade-off: smaller ecosystem, fewer built-in features (no pivot tables, no Excel export).
- **AG Grid Community** (MIT) is the industry standard with the broadest feature set: sorting, filtering, grouping, column pinning, cell editing, CSV export. Enterprise adds pivot tables, tree data, Excel export, server-side row model. Real-time performance is excellent with virtualization, but DOM-based rendering means it can't match Glide's raw update throughput.
- **TanStack Table v8** is headless -- logic only, you render the UI. Maximum flexibility, zero opinions. Struggles past 10K rows without virtualization libraries. Not ideal for real-time heavy tables where you need canvas-level performance.
- **MUI X DataGrid** is solid but tied to the MUI ecosystem and styling opinions.

### VERDICT

**Glide Data Grid** for the option chain and any table with high-frequency real-time updates. Its canvas rendering handles the update rates that option chain Greeks/IV demand. Use **TanStack Table v8** for static or low-frequency tables (order book history, trade log) where you want full UI control with minimal bundle cost.

---

## 5. State Management for Real-Time Data

**Goal:** High-frequency WebSocket data (LTP, quotes, depth) flowing to 10+ widgets simultaneously.

| Library | Model | Bundle Size | GitHub Stars | npm Weekly DL | Re-render Control |
|---|---|---|---|---|---|
| **Zustand** | Centralized store + hooks | **~1.5 KB** | **57,200** | **24M** | Manual (selectors) |
| **Jotai** | Atomic (bottom-up) | **~2 KB** | 20,900 | 2.5M | **Automatic** (atom-level) |
| **Valtio** | Proxy-based mutable | ~3 KB | 9,500 | 700K | **Automatic** (proxy tracking) |
| **Redux Toolkit** | Centralized + reducers | ~11 KB | 61K | 10M | Manual (selectors) |
| **TanStack Query** | Server-state cache | ~13 KB | 43K | 10M | Automatic (query-level) |

### Analysis

For a trading terminal, the critical requirement is **fine-grained reactivity**: when NIFTY's LTP updates, only the widgets displaying NIFTY should re-render, not the entire app.

- **Zustand** is the 2026 default for most React apps. Tiny (~1.5 KB), simple API, great devtools. For trading: create a store per data domain (quotes, positions, orders), use selectors to subscribe to specific instruments. Manual selector optimization is needed but straightforward.
- **Jotai** has the best architecture for real-time trading data. Each instrument's quote can be an atom. Derived atoms compute Greeks, P&L, signals. Components subscribe to exactly the atoms they need -- re-renders are surgically precise. The atomic model maps perfectly to "subscribe to NIFTY LTP" / "subscribe to BANKNIFTY depth" patterns.
- **Valtio** offers the simplest mental model (mutate state directly, snapshots are immutable). Auto-tracks which properties each component reads. Great for rapid development. Slightly less control than Jotai for complex derived state.
- **Redux Toolkit** is battle-tested but verbose. The 11 KB bundle and boilerplate overhead are hard to justify when Zustand does the same with 1.5 KB.
- **TanStack Query** is the standard for REST API caching (funds, orderbook, tradebook) but is not designed for WebSocket streams. Use it alongside a client-state library, not instead of one.

### VERDICT

**Zustand + Jotai hybrid**. Zustand for global app state (connection status, selected instrument, layout config, user preferences). Jotai for real-time market data (one atom per instrument, derived atoms for computed values). TanStack Query for REST API calls (funds, orderbook, holdings). This is the "composed specialized tools" pattern that the React community has converged on in 2026.

---

## 6. Python Indicator Library

**Goal:** Fastest computation of 50+ indicators for both batch (backtest) and streaming (live) use cases.

| Library | Language | Indicators | Streaming | Speed vs pandas | GitHub Stars | Status |
|---|---|---|---|---|---|---|
| **TA-Lib (C + Python wrapper)** | C (Cython bindings) | **200+** | No (batch only) | **2-4x faster** | 11,400 | Active (v0.6.5+, binary wheels) |
| **pandas-ta** | Python (NumPy/Numba) | 150+ | No (batch only) | 1x (baseline) | 5,500 | **Archiving July 2026** |
| **ta-numba** | Python (Numba JIT + Rust/PyO3) | 55 streaming + 50 bulk | **Yes** | ~2-3x faster | <500 | Active |
| **streaming_indicators** | Pure Python | 30+ | **Yes** | Slower (Python loop) | <200 | Active |
| **Custom NumPy/Numba** | Python | As needed | Yes | 2-4x faster | N/A | N/A |

### Analysis

- **TA-Lib** remains the gold standard for batch indicator computation. The C implementation with Cython bindings is 2-4x faster than pure Python alternatives. 200+ indicators, heavily battle-tested across the quant community. Binary wheels (v0.6.5+) finally solve the infamous installation nightmare. Limitation: batch-only, no streaming/incremental API.
- **pandas-ta** was the go-to Python-native alternative with 150+ indicators and a clean Pandas extension API. However, the maintainer announced it will be **archived by July 2026** unless significant funding materializes. Do not build on a library with a known sunset date.
- **ta-numba** is the emerging contender: Numba JIT + optional Rust/PyO3 backend, 55 streaming indicators, dependency-free installation. Perfect for real-time use cases where you need incremental updates without recomputing the entire series.
- **streaming_indicators** is a pure Python library for stateful incremental computation. Simple and correct, but Python-loop performance limits it to moderate update rates.
- **Custom NumPy/Numba** is always an option for the 5-10 indicators you actually use in production. A JIT-compiled SMA/EMA/RSI in Numba matches TA-Lib speed.

### VERDICT

**TA-Lib** for batch computation (backtesting, historical analysis). **ta-numba** or custom Numba implementations for streaming/real-time indicators. Avoid pandas-ta for new code given the July 2026 archival deadline.

---

## 7. Python Backtesting Engine

**Goal:** Options backtesting with tick data, multi-leg strategies, realistic fills, Indian F&O specifics.

| Engine | Architecture | Speed | Options Support | GitHub Stars | License | Status |
|---|---|---|---|---|---|---|
| **VectorBT (open-source)** | Vectorized (NumPy/Numba) | **Millions of trades/sec** | Basic | 5,900 | MIT | Active (v0.28.4, Jan 2026) |
| **VectorBT PRO** | Vectorized (NumPy/Numba) | Millions of trades/sec | Better | N/A (proprietary) | **Commercial** | Active |
| **NautilusTrader** | Event-driven (Rust core + Python) | Very fast (Rust) | **Full** (order book replay) | **21,200** | LGPL-2.1 | Active |
| **Backtrader** | Event-driven (Python) | Slow (Python loop) | Basic | 14K | GPL-3.0 | **Maintenance mode** |
| **Zipline-reloaded** | Event-driven (Python) | Slow | None | 2K | Apache 2.0 | Limited maintenance |
| **Custom event-driven** | Event-driven | Variable | Full control | N/A | N/A | N/A |

### Analysis

- **VectorBT** is unmatched for signal discovery and parameter optimization. Millions of trades simulated per second. The vectorized approach is perfect for "test 10,000 parameter combinations across 500 instruments." Limitation: options support is basic (no multi-leg, no assignment/exercise modeling, no realistic spread fills).
- **NautilusTrader** is the production-grade answer. Rust-native core with Python bindings (migrating from Cython to PyO3). Deterministic event-driven architecture with nanosecond resolution. Order book replay, latency modeling, exchange-accurate fills. Full options support. The 21K GitHub stars reflect serious institutional adoption. Trade-off: steep learning curve, heavier setup.
- **Backtrader** is the "classic" choice with a loyal community, but it's in maintenance mode with no major releases. Python event loop means it's slow at scale. Not viable for tick-level options backtesting.
- **Zipline-reloaded** was built for equities research. No options support. Python 3.5-era architecture. Installation requires workarounds.

### Recommended Workflow for FlintTrade

The community consensus for 2026 is a **two-stage pipeline**:
1. **VectorBT** for high-throughput exploration, parameter sweeps, and robustness testing
2. **NautilusTrader** for realistic replay, order semantics, latency modeling, and production-parity execution

### VERDICT

**VectorBT** (open-source) for rapid strategy exploration and parameter optimization. **NautilusTrader** for realistic options backtesting with tick data and production deployment. Build FlintTrade's `backtest-engine` package to wrap both, abstracting the two-stage workflow behind a unified API.

---

## 8. Icon Library

**Goal:** Trading-relevant icons (charts, orders, positions, arrows, indicators) + smallest possible bundle.

| Library | Icons | Bundle (50 icons) | Bundle (200 icons) | npm Weekly DL | Tree-shaking |
|---|---|---|---|---|---|
| **lucide-react** | 1,500+ | **5.16 KB** | **15.72 KB** | **35M** | Excellent (ESM) |
| **Heroicons** | 290+ | 3.49 KB | 19.09 KB | 2M | Good |
| **@tabler/icons-react** | **5,900+** | ~8 KB | ~25 KB | 500K | Good |
| **phosphor-react** | 9,000+ (6 weights) | 33.91 KB | 102.27 KB | 100K | Poor |
| **radix-icons** | 300+ | ~4 KB | ~12 KB | 200K | Good |

### Analysis

- **lucide-react** dominates: 35M weekly downloads (market leader), ESM-first architecture, 1.5x growth rate, and the best bundle-to-icon ratio at scale. At 200 icons, it's 15.72 KB -- Phosphor would be 102 KB for the same count. The icon set covers charts, arrows, settings, filters, grids, and most trading UI needs. It's also the default for shadcn/ui.
- **Heroicons** is lighter at low icon counts (3.49 KB for 50) but grows faster and has only 290 icons total -- you'll hit gaps for trading-specific needs.
- **@tabler/icons-react** has the broadest set (5,900 icons) with strong coverage for dashboards and data-heavy UIs. Good fallback for icons lucide doesn't have.
- **phosphor-react** has 9,000 icons in 6 weights but the bundle cost is catastrophic. 34 KB for just 50 icons due to poor tree-shaking.
- **radix-icons** is tiny but only 300 icons. Too limited for a full trading terminal.

### VERDICT

**lucide-react** as the primary icon library (already used by FlintTrade). Supplement with **@tabler/icons-react** for any trading-specific icons lucide lacks. Do not adopt phosphor-react -- the bundle penalty is unacceptable.

---

## 9. React Version

**Goal:** Determine whether to use React 19 or stay on React 18 for a real-time trading terminal.

| Aspect | React 18 | React 19 |
|---|---|---|
| **Concurrent Rendering** | Opt-in (useTransition, startTransition) | Automatic + refined scheduling |
| **Memoization** | Manual (React.memo, useMemo, useCallback) | **React Compiler auto-memoizes** |
| **Server Components** | Experimental | Stable (but controversial) |
| **Form Handling** | onSubmit + preventDefault | Actions API (server-bound forms) |
| **Memory Usage** | Baseline | Optimized for large component trees |
| **Ecosystem Compatibility** | Universal | ~48% adoption; 41% still on React 18 |
| **JSX Transform** | Old + new supported | **New JSX transform mandatory** |

### Analysis

**React 19 is the right choice for new projects in 2026, but with caveats:**

- The **React Compiler** (auto-memoization) is a significant win for real-time UIs. No more manual useMemo/useCallback for every price update handler. This alone justifies the upgrade.
- **Concurrent rendering improvements** help prioritize user interactions (clicking buttons, typing orders) over background data updates (price ticks).
- **Memory optimization** for large component trees matters when you have 10+ widgets each managing hundreds of data points.

**Gotchas for trading terminals:**
1. **Library compatibility**: Some libraries still have peer dependency issues with React 19. Check every dependency before adopting. Recoil is dead on React 19. MUI required version bumps.
2. **Server Components are irrelevant**: FlintTrade is a client-side SPA. Ignore Server Components entirely. The CVE-2025-55182 RCE vulnerability in Server Components is not a concern.
3. **npm peer dependency strictness**: npm v7+ throws on peer dependency mismatches. Use `--legacy-peer-deps` during the transition period if needed.
4. **No Create React App**: CRA is officially deprecated and broken on React 19. Use Vite (which FlintTrade already does).

### VERDICT

**React 19**. The React Compiler's auto-memoization and improved concurrent rendering are material benefits for real-time trading UIs. FlintTrade uses Vite (not CRA), so the CRA deprecation is irrelevant. Test all dependencies for React 19 compatibility before upgrading. Key libraries to verify: lightweight-charts wrapper, dockview-react, any charting plugins.

---

## 10. Build Tool

**Goal:** Fastest dev server (HMR) + fastest production build for a React trading terminal.

| Tool | Language | Dev HMR | Cold Start | Prod Build | npm Weekly DL | GitHub Stars | Status |
|---|---|---|---|---|---|---|---|
| **Vite 8** (Rolldown) | **Rust** (Rolldown) | <50 ms | 300-500 ms | **10-30x faster than Rollup** | **49M** | **77,200** | **Stable (March 2026)** |
| **Rspack** | Rust | 20-30 ms | 2-3 s | 5-10x faster than Webpack | 3.4M | 12,600 | Stable (v1.7.8) |
| **Turbopack** | Rust | **<10 ms** | <1 s | Stable (Next.js 16+) | N/A (bundled) | N/A (in Next.js repo) | Next.js only |
| **esbuild** | Go | N/A (no HMR) | ~100 ms | Very fast | 30M | 38K | Stable |

### Analysis

- **Vite 8 with Rolldown** is the 2026 game-changer. Rolldown (Rust-based) replaces both esbuild (dev) and Rollup (prod) with a single unified bundler. 10-30x faster production builds than Rollup. The broadest plugin ecosystem of any bundler. 49M weekly downloads and 77K stars make it the undisputed community standard. FlintTrade already uses Vite -- upgrading to Vite 8 is the path of least resistance with the biggest performance gain.
- **Rspack** is excellent for Webpack-to-Rust migrations (5-10x faster than Webpack with near-identical config). Not relevant for FlintTrade since we're already on Vite.
- **Turbopack** has the fastest HMR (<10ms) but is **Next.js-only** as of March 2026. Not framework-agnostic. Irrelevant for FlintTrade's Vite + React SPA architecture.
- **esbuild** is fast for compilation but lacks a dev server, HMR, and plugin ecosystem. Vite 8's Rolldown now matches esbuild's speed while providing everything esbuild doesn't.

### VERDICT

**Vite 8** (with Rolldown). Already the FlintTrade build tool -- upgrade to v8 for Rolldown's 10-30x faster production builds. No reason to switch to Rspack (Webpack migration tool) or Turbopack (Next.js-only).

---

## Summary: FlintTrade Recommended Stack

| Category | Choice | Why |
|---|---|---|
| **Charting** | Lightweight Charts v5 | 35 KB, Apache 2.0, multi-pane, finance-native, plugin system |
| **CSS/Components** | shadcn/ui + Tailwind CSS v4 | Zero runtime, code ownership, Radix accessibility, fastest-growing ecosystem |
| **Layout/Docking** | Dockview v5 | Zero deps, full docking, serialization, active dev, multi-framework |
| **Data Grid (real-time)** | Glide Data Grid | Canvas rendering, 100K+ updates/sec, MIT, built for high-frequency updates |
| **Data Grid (static)** | TanStack Table v8 | Headless, 30 KB, MIT, full UI control for order history/trade logs |
| **State (app)** | Zustand | 1.5 KB, 24M downloads, simple selectors for global state |
| **State (market data)** | Jotai | Atomic model, auto fine-grained reactivity, perfect for per-instrument subscriptions |
| **State (server)** | TanStack Query | REST API caching for funds/orderbook/holdings |
| **Indicators (batch)** | TA-Lib | C speed, 200+ indicators, binary wheels, battle-tested |
| **Indicators (streaming)** | ta-numba / Custom Numba | JIT-compiled, streaming API, zero deps |
| **Backtesting (explore)** | VectorBT | Millions of trades/sec, parameter sweeps, MIT |
| **Backtesting (realistic)** | NautilusTrader | Rust core, tick replay, order book, production-grade |
| **Icons** | lucide-react | 35M DL/week, 15 KB for 200 icons, shadcn/ui default |
| **React** | React 19 | Auto-memoization compiler, improved concurrent rendering |
| **Build** | Vite 8 (Rolldown) | 10-30x faster builds, unified Rust bundler, 49M DL/week |

### What Changes from Current FlintTrade

| Current | Proposed | Migration Effort |
|---|---|---|
| Tailwind CSS v4 (raw) | Add shadcn/ui on top | Low (additive, not a rewrite) |
| Custom layout (CSS grid) | Dockview v5 | Medium (new dependency, layout refactor) |
| HTML tables | Glide Data Grid + TanStack Table | Medium (replace table components) |
| Custom DataBus pub/sub | Zustand + Jotai + TanStack Query | Medium (refactor state layer) |
| Vite (current version) | Vite 8 (Rolldown) | Low (version bump + config review) |
| React 18 (if current) | React 19 | Low-Medium (dependency audit needed) |
| pandas-ta | TA-Lib + ta-numba | Low (swap imports, same indicator names) |

---

## Sources

### Charting
- [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/)
- [Lightweight Charts v5 Announcement](https://www.tradingview.com/blog/en/tradingview-lightweight-charts-version-5-50837/)
- [TradingView Advanced Charts](https://www.tradingview.com/advanced-charts/)
- [TradingView Product Comparison](https://www.tradingview.com/charting-library-docs/latest/getting_started/product-comparison/)
- [Chart.js vs LWC vs TradingView 2026](https://www.index.dev/skill-vs-skill/tradingview-vs-lightweight-charts-vs-chartjs)

### CSS/Components
- [React UI Libraries 2025](https://makersden.io/blog/react-ui-libs-2025-comparing-shadcn-radix-mantine-mui-chakra)
- [shadcn/ui vs MUI vs Ant Design 2026](https://adminlte.io/blog/shadcn-ui-vs-mui-vs-ant-design/)
- [DaisyUI vs shadcn/ui](https://windframe.dev/blog/daisyui-vs-shadcn-ui)
- [Best React Component Libraries 2026](https://designrevision.com/blog/best-react-component-libraries)

### Layout/Docking
- [Dockview](https://dockview.dev/)
- [npm trends: dockview vs flexlayout vs golden-layout](https://npmtrends.com/dockview-vs-flexlayout-react-vs-golden-layout-vs-rc-dock)
- [Dockview GitHub](https://github.com/mathuo/dockview)

### Data Grid
- [TanStack Table vs AG Grid 2025](https://www.simple-table.com/blog/tanstack-table-vs-ag-grid-comparison)
- [Top AG Grid Alternatives 2026](https://www.thefrontendcompany.com/posts/ag-grid-alternatives)
- [Glide Data Grid GitHub](https://github.com/glideapps/glide-data-grid)
- [React Data Grid Libraries 2026](https://www.syncfusion.com/blogs/post/top-react-data-grid-libraries)

### State Management
- [Zustand vs Redux Toolkit vs Jotai](https://betterstack.com/community/guides/scaling-nodejs/zustand-vs-redux-toolkit-vs-jotai/)
- [Zustand vs Jotai vs Valtio Performance 2025](https://www.reactlibraries.com/blog/zustand-vs-jotai-vs-valtio-performance-guide-2025)
- [State Management in 2025](https://www.developerway.com/posts/react-state-management-2025)
- [TanStack Query vs Redux](https://www.alexisdata.com/2025/12/30/tanstack-query-vs-redux-complete-comparison-guide-for-state-management/)

### Python Indicators
- [TA-Lib Python GitHub](https://github.com/TA-Lib/ta-lib-python)
- [pandas-ta](https://www.pandas-ta.dev/)
- [Comparing TA-Lib to pandas-ta](https://www.slingacademy.com/article/comparing-ta-lib-to-pandas-ta-which-one-to-choose/)
- [Faster Alternative to TA-Lib](https://medium.com/@jpolec_72972/enhancing-technical-analysis-our-faster-alternative-to-ta-lib-f224d3db6b1e)

### Backtesting
- [Python Backtesting Landscape 2026](https://python.financial/)
- [Backtrader vs NautilusTrader vs VectorBT vs Zipline](https://autotradelab.com/blog/backtrader-vs-nautilusttrader-vs-vectorbt-vs-zipline-reloaded)
- [VectorBT](https://vectorbt.dev/)
- [NautilusTrader GitHub](https://github.com/nautechsystems/nautilus_trader)

### Icons
- [React Icon Libraries Bundle Size Benchmark](https://medium.com/codetodeploy/the-hidden-bundle-cost-of-react-icons-why-lucide-wins-in-2026-1ddb74c1a86c)
- [Lucide Comparison](https://lucide.dev/guide/comparison)
- [Best React Icon Libraries 2026](https://mighil.com/best-react-icon-libraries)

### React Version
- [React 18 vs 19 Performance](https://www.creolestudios.com/react-18-vs-react-19-boosting-rendering-performance/)
- [React 19 Upgrade Breakages](https://medium.com/@quicksilversel/i-upgraded-three-apps-to-react-19-heres-what-broke-648087c7217b)
- [State of React 2025-2026](https://strapi.io/blog/state-of-react-2025-key-takeaways)
- [React 19 Upgrade Guide](https://react.dev/blog/2024/04/25/react-19-upgrade-guide)

### Build Tool
- [Build Tools Performance Benchmarks](https://github.com/rstackjs/build-tools-performance)
- [Vite 8 Rolldown Announcement](https://vite.dev/blog/announcing-vite8)
- [Vite 10-30x Faster Builds](https://www.theregister.com/2026/03/16/vite_8_rolldown/)
- [Vite vs Turbopack vs Rspack 2025](https://dev.to/mrakdon/vite-vs-turbopack-vs-rspack-which-build-tool-wins-the-modern-frontend-race-2jpg)
- [Rspack vs Webpack 2026](https://www.pkgpulse.com/blog/rspack-vs-webpack-2026)
