# FlintTrade v2 Foundation Sprint — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox syntax for tracking.

**Goal:** Migrate FlintTrade terminal from JavaScript/FlexLayout/DataBus to TypeScript/Dockview/Zustand+Jotai+TanStack with shadcn/ui components.

**Architecture:** Complete tech stack migration preserving all 14 existing widgets while upgrading to institutional-grade tooling. One React app with route-based separation for 3 personas.

**Tech Stack:** TypeScript 5.x, React 19, Vite 6.4, Dockview v5, shadcn/ui, Zustand v5, Jotai, TanStack Query v5, Glide Data Grid, Lightweight Charts v5, Tailwind CSS v4

---

## Source Files Inventory (49 JS/JSX files to migrate)

Before starting, here is the complete list of files that will be converted from `.js`/`.jsx` to `.ts`/`.tsx`:

| # | Current Path | Target Path |
|---|---|---|
| 1 | `src/main.jsx` | `src/main.tsx` |
| 2 | `src/App.jsx` | `src/App.tsx` |
| 3 | `src/services/api.js` | `src/services/api.ts` |
| 4 | `src/services/websocket.js` | `src/services/websocket.ts` |
| 5 | `src/services/dataBus.js` | **DELETE** (replaced by Zustand/Jotai) |
| 6 | `src/services/dataConnector.js` | **DELETE** (replaced by TanStack Query + Jotai WS) |
| 7 | `src/services/rateLimiter.js` | `src/services/rateLimiter.ts` |
| 8 | `src/hooks/useDataBus.js` | **DELETE** (replaced by Zustand/Jotai hooks) |
| 9 | `src/hooks/useWebSocket.js` | `src/hooks/useWebSocket.ts` |
| 10 | `src/hooks/useGlobalKeys.js` | `src/hooks/useGlobalKeys.ts` |
| 11 | `src/layout/layoutStore.js` | **REWRITE** as `src/stores/layoutStore.ts` (Zustand) |
| 12 | `src/layout/LayoutManager.jsx` | **REWRITE** as `src/layout/DockviewLayout.tsx` |
| 13 | `src/layout/widgetFactory.jsx` | `src/layout/widgetFactory.tsx` |
| 14 | `src/chrome/TopBar.jsx` | `src/chrome/TopBar.tsx` |
| 15 | `src/chrome/TickerBar.jsx` | `src/chrome/TickerBar.tsx` |
| 16 | `src/chrome/WidgetPicker.jsx` | `src/chrome/WidgetPicker.tsx` |
| 17 | `src/chrome/ToolsDropdown.jsx` | `src/chrome/ToolsDropdown.tsx` |
| 18 | `src/widgets/trading/Dashboard/DashboardWidget.jsx` | `src/widgets/trading/Dashboard/DashboardWidget.tsx` |
| 19 | `src/widgets/trading/Scalper/ScalperWidget.jsx` | `src/widgets/trading/Scalper/ScalperWidget.tsx` |
| 20 | `src/widgets/trading/Positions/PositionsWidget.jsx` | `src/widgets/trading/Positions/PositionsWidget.tsx` |
| 21 | `src/widgets/trading/Orders/OrdersWidget.jsx` | `src/widgets/trading/Orders/OrdersWidget.tsx` |
| 22 | `src/widgets/trading/Holdings/HoldingsWidget.jsx` | `src/widgets/trading/Holdings/HoldingsWidget.tsx` |
| 23 | `src/widgets/trading/TradeBook/TradeBookWidget.jsx` | `src/widgets/trading/TradeBook/TradeBookWidget.tsx` |
| 24 | `src/widgets/trading/OrderPad/OrderPadWidget.jsx` | `src/widgets/trading/OrderPad/OrderPadWidget.tsx` |
| 25 | `src/widgets/analysis/Chart/ChartWidget.jsx` | `src/widgets/analysis/Chart/ChartWidget.tsx` |
| 26 | `src/widgets/analysis/OptionChain/OptionChainWidget.jsx` | `src/widgets/analysis/OptionChain/OptionChainWidget.tsx` |
| 27 | `src/widgets/analysis/OIChart/OIChartWidget.jsx` | `src/widgets/analysis/OIChart/OIChartWidget.tsx` |
| 28 | `src/widgets/analysis/Straddle/StraddleWidget.jsx` | `src/widgets/analysis/Straddle/StraddleWidget.tsx` |
| 29 | `src/widgets/analysis/Depth/DepthWidget.jsx` | `src/widgets/analysis/Depth/DepthWidget.tsx` |
| 30 | `src/widgets/analysis/Greeks/GreeksWidget.jsx` | `src/widgets/analysis/Greeks/GreeksWidget.tsx` |
| 31 | `src/widgets/utility/Watchlist/WatchlistWidget.jsx` | `src/widgets/utility/Watchlist/WatchlistWidget.tsx` |
| 32 | `src/components/Chart.jsx` | `src/components/Chart.tsx` |
| 33 | `src/tools/Settings/SettingsTool.jsx` | `src/tools/Settings/SettingsTool.tsx` |
| 34 | `src/tools/BacktestLab/BacktestLabTool.jsx` | `src/tools/BacktestLab/BacktestLabTool.tsx` |
| 35 | `src/tools/TradeJournal/TradeJournalTool.jsx` | `src/tools/TradeJournal/TradeJournalTool.tsx` |
| 36 | `src/tools/StrategyBuilder/StrategyBuilderTool.jsx` | `src/tools/StrategyBuilder/StrategyBuilderTool.tsx` |
| 37 | `src/tools/PnLDashboard/PnLDashboardTool.jsx` | `src/tools/PnLDashboard/PnLDashboardTool.tsx` |
| 38 | `src/tools/MarketIntelligence/MarketIntelligenceTool.jsx` | `src/tools/MarketIntelligence/MarketIntelligenceTool.tsx` |
| 39 | `src/tools/FlowBuilder/FlowBuilderTool.jsx` | `src/tools/FlowBuilder/FlowBuilderTool.tsx` |
| 40-46 | `src/layout/presets/*.json` (7 files) | Convert to Dockview serialization format |
| 47 | `src/services/__tests__/dataBus.test.js` | **DELETE** (DataBus removed) |
| 48 | `src/services/__tests__/rateLimiter.test.js` | `src/services/__tests__/rateLimiter.test.ts` |
| 49 | `vite.config.js` | `vite.config.ts` |

**Total:** 39 files to convert/rewrite, 4 files to delete, 7 presets to reformat = 50 operations

---

## Phase 1: Foundation Setup (Days 1-3)

### 1.1 Install new dependencies

- [ ] **1.1.1** Install TypeScript and type definitions
  - **File:** `packages/terminal/package.json`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm install -D typescript @types/react @types/react-dom
    ```
  - **Expected:** `typescript`, `@types/react`, `@types/react-dom` added to devDependencies
  - **Verify:** `npx tsc --version` prints `Version 5.x.x`

- [ ] **1.1.2** Install Dockview v5
  - **File:** `packages/terminal/package.json`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm install dockview dockview-react
    ```
  - **Pre-check:** Use context7 MCP: `resolve-library-id("dockview")` then `query-docs` for React integration API
  - **Expected:** `dockview` and `dockview-react` in dependencies
  - **Verify:** `node -e "require('dockview/package.json').version"` prints `5.x.x`

- [ ] **1.1.3** Install Zustand v5
  - **File:** `packages/terminal/package.json`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm install zustand
    ```
  - **Pre-check:** Use context7 MCP: `resolve-library-id("zustand")` then `query-docs` for v5 store creation API
  - **Expected:** `zustand` `^5.x` in dependencies

- [ ] **1.1.4** Install Jotai
  - **File:** `packages/terminal/package.json`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm install jotai
    ```
  - **Pre-check:** Use context7 MCP: `resolve-library-id("jotai")` then `query-docs` for atom/useAtom API
  - **Expected:** `jotai` in dependencies

- [ ] **1.1.5** Install TanStack Query v5
  - **File:** `packages/terminal/package.json`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm install @tanstack/react-query
    npm install -D @tanstack/react-query-devtools
    ```
  - **Pre-check:** Use context7 MCP: `resolve-library-id("@tanstack/react-query")` then `query-docs` for QueryClient + useQuery API
  - **Expected:** `@tanstack/react-query` `^5.x` in dependencies

- [ ] **1.1.6** Install TanStack Table v8
  - **File:** `packages/terminal/package.json`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm install @tanstack/react-table
    ```
  - **Expected:** `@tanstack/react-table` `^8.x` in dependencies

- [ ] **1.1.7** Install Glide Data Grid
  - **File:** `packages/terminal/package.json`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm install @glideapps/glide-data-grid
    ```
  - **Pre-check:** Use context7 MCP: `resolve-library-id("@glideapps/glide-data-grid")` then `query-docs` for DataEditor API
  - **Expected:** `@glideapps/glide-data-grid` in dependencies

- [ ] **1.1.8** Install react-hook-form + zod
  - **File:** `packages/terminal/package.json`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm install react-hook-form zod @hookform/resolvers
    ```
  - **Expected:** All three in dependencies

- [ ] **1.1.9** Install date-fns
  - **File:** `packages/terminal/package.json`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm install date-fns
    ```
  - **Expected:** `date-fns` in dependencies

- [ ] **1.1.10** Remove old dependencies
  - **File:** `packages/terminal/package.json`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm uninstall flexlayout-react recharts autoprefixer postcss
    ```
  - **Expected:** `flexlayout-react`, `recharts`, `autoprefixer`, `postcss` removed from package.json
  - **Verify:** `npm ls flexlayout-react` shows "empty"

- [ ] **1.1.11** Verify all deps installed cleanly
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm ls --depth=0
    ```
  - **Expected:** No unmet peer dependencies, no errors
  - **Commit:** `feat(terminal): install v2 deps — dockview, zustand, jotai, tanstack-query, glide-data-grid, shadcn/ui`

### 1.2 Configure TypeScript

- [ ] **1.2.1** Create `tsconfig.json` with strict mode
  - **File:** `packages/terminal/tsconfig.json`
  - **Content:**
    ```json
    {
      "compilerOptions": {
        "target": "ES2022",
        "lib": ["ES2022", "DOM", "DOM.Iterable"],
        "module": "ESNext",
        "moduleResolution": "bundler",
        "jsx": "react-jsx",
        "strict": true,
        "noUnusedLocals": true,
        "noUnusedParameters": true,
        "noFallthroughCasesInSwitch": true,
        "forceConsistentCasingInFileNames": true,
        "resolveJsonModule": true,
        "isolatedModules": true,
        "esModuleInterop": true,
        "skipLibCheck": true,
        "noEmit": true,
        "baseUrl": ".",
        "paths": {
          "@/*": ["src/*"]
        },
        "types": ["vite/client"]
      },
      "include": ["src", "vite-env.d.ts"],
      "references": [{ "path": "./tsconfig.node.json" }]
    }
    ```
  - **Expected:** File created at `packages/terminal/tsconfig.json`

- [ ] **1.2.2** Create `tsconfig.node.json` for Vite config
  - **File:** `packages/terminal/tsconfig.node.json`
  - **Content:**
    ```json
    {
      "compilerOptions": {
        "target": "ES2022",
        "lib": ["ES2022"],
        "module": "ESNext",
        "moduleResolution": "bundler",
        "strict": true,
        "noEmit": true,
        "isolatedModules": true,
        "esModuleInterop": true,
        "skipLibCheck": true
      },
      "include": ["vite.config.ts"]
    }
    ```
  - **Expected:** File created at `packages/terminal/tsconfig.node.json`

- [ ] **1.2.3** Create `vite-env.d.ts` for Vite types
  - **File:** `packages/terminal/vite-env.d.ts`
  - **Content:**
    ```typescript
    /// <reference types="vite/client" />

    interface ImportMetaEnv {
      readonly VITE_OPENALGO_HOST: string
      readonly VITE_OPENALGO_API_KEY: string
      readonly VITE_OPENALGO_WS: string
      readonly DEV: boolean
      readonly MODE: string
    }

    interface ImportMeta {
      readonly env: ImportMetaEnv
    }
    ```
  - **Expected:** File created at `packages/terminal/vite-env.d.ts`

- [ ] **1.2.4** Rename `vite.config.js` to `vite.config.ts`
  - **File:** `packages/terminal/vite.config.js` -> `packages/terminal/vite.config.ts`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    mv vite.config.js vite.config.ts
    ```
  - **Edit:** Update content to TypeScript:
    ```typescript
    import { defineConfig } from "vite";
    import react from "@vitejs/plugin-react";
    import tailwindcss from "@tailwindcss/vite";
    import path from "path";

    export default defineConfig({
      plugins: [react(), tailwindcss()],
      resolve: {
        alias: {
          "@": path.resolve(__dirname, "src"),
        },
      },
      server: {
        host: true,
        port: 5173,
        proxy: {
          "/api": {
            target: process.env.VITE_OPENALGO_HOST || "http://127.0.0.1:5000",
            changeOrigin: true,
          },
          "/ws": {
            target: process.env.VITE_OPENALGO_WS || "ws://127.0.0.1:8765",
            ws: true,
            rewrite: (path) => path.replace(/^\/ws/, ""),
          },
        },
      },
    });
    ```
  - **Expected:** Vite config is now TypeScript with `@/` path alias

- [ ] **1.2.5** Add `tsc` script to package.json
  - **File:** `packages/terminal/package.json`
  - **Edit:** Add to scripts:
    ```json
    "typecheck": "tsc --noEmit",
    "build": "tsc --noEmit && vite build"
    ```
  - **Expected:** `npm run typecheck` can be run independently
  - **Commit:** `feat(terminal): configure TypeScript strict mode with path aliases`

### 1.3 Initialize shadcn/ui

- [ ] **1.3.1** Initialize shadcn/ui with Tailwind CSS v4
  - **Pre-check:** Use context7 MCP: `resolve-library-id("shadcn/ui")` then `query-docs` for Tailwind v4 setup + CLI init
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npx shadcn@latest init
    ```
  - **Interactive prompts (expected answers):**
    - Style: Default
    - Base color: Zinc
    - CSS variables: Yes
  - **Expected:** Creates `components.json`, updates `src/index.css` with CSS variables, creates `src/lib/utils.ts`
  - **Verify:** `components.json` exists with `tailwindcss` config

- [ ] **1.3.2** Install core shadcn/ui components needed for migration
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npx shadcn@latest add button input label select dialog dropdown-menu tabs card badge separator tooltip scroll-area sheet popover command table
    ```
  - **Expected:** Components created in `src/components/ui/` directory
  - **Verify:** `ls src/components/ui/` shows all component files

- [ ] **1.3.3** Merge FlintTrade dark theme with shadcn/ui CSS variables
  - **File:** `packages/terminal/src/index.css`
  - **Edit:** Merge existing FlintTrade theme colors into the shadcn/ui CSS variable system. Map:
    - `--color-surface-base: #0a0a0f` -> `--background`
    - `--color-surface-card: #12121a` -> `--card`
    - `--color-border-default: #1e1e2e` -> `--border`
    - `--color-accent: #3b82f6` -> `--primary`
    - `--color-profit: #22c55e` -> custom `--profit`
    - `--color-loss: #ef4444` -> custom `--loss`
    - `--color-warning: #eab308` -> custom `--warning`
  - **Expected:** shadcn/ui components render with FlintTrade's dark theme
  - **Verify:** Run `npm run dev`, open browser, shadcn button renders with dark theme

- [ ] **1.3.4** Remove all FlexLayout CSS overrides from `index.css`
  - **File:** `packages/terminal/src/index.css`
  - **Edit:** Delete lines 35-148 (all `.flexlayout__*` CSS rules)
  - **Expected:** No FlexLayout CSS in the file
  - **Commit:** `feat(terminal): init shadcn/ui with FlintTrade dark theme, remove FlexLayout CSS`

### 1.4 Delete stub packages

- [ ] **1.4.1** Delete `packages/dashboard/` entirely
  - **Command:**
    ```bash
    rm -rf C:/Users/navan/Documents/GitHub/FlintTrade/packages/dashboard/
    ```
  - **Expected:** Directory removed (was a stub with recharts, no real functionality)
  - **Verify:** `ls packages/dashboard/` returns "No such file or directory"

- [ ] **1.4.2** Delete `packages/backtest/` entirely
  - **Command:**
    ```bash
    rm -rf C:/Users/navan/Documents/GitHub/FlintTrade/packages/backtest/
    ```
  - **Expected:** Directory removed (was a stub with recharts, no real functionality)
  - **Verify:** `ls packages/backtest/` returns "No such file or directory"
  - **Commit:** `chore: delete stub packages — dashboard/ and backtest/ (now integrated into terminal)`

### 1.5 Fix .env.example and package-lock.json

- [ ] **1.5.1** Fix `.env.example` — blank all values, 4 vars only
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/.env.example`
  - **Edit:** Replace content with:
    ```
    # FlintTrade — Environment Configuration
    # Copy to .env and fill in your values. NEVER commit .env.
    #
    # This file contains ONLY infrastructure connection settings.
    # User preferences (paths, modules, UI, LLM, Telegram) are in:
    #   ~/.flinttrade/workspace.json
    #
    # Broker credentials are configured in OpenAlgo, not here.

    # --- OpenAlgo connection ---
    OPENALGO_HOST=
    OPENALGO_PORT=
    OPENALGO_API_KEY=
    OPENALGO_WS_PORT=
    ```
  - **Expected:** All values blank (currently `OPENALGO_HOST=http://127.0.0.1:5000` has a default)

- [ ] **1.5.2** Remove `package-lock.json` from `.gitignore`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/.gitignore`
  - **Edit:** Remove the line `package-lock.json`
  - **Expected:** `package-lock.json` is now tracked by git

- [ ] **1.5.3** Stage and commit `package-lock.json`
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade
    git add packages/terminal/package-lock.json .gitignore .env.example
    ```
  - **Commit:** `chore: track package-lock.json, blank .env.example values`

### 1.6 Create type definitions

- [ ] **1.6.1** Create shared types file for OpenAlgo API shapes
  - **File:** `packages/terminal/src/types/api.ts`
  - **Content:** Define interfaces for all API response shapes:
    ```typescript
    // OpenAlgo API response types

    export interface ApiResponse<T> {
      status: "success" | "error";
      message?: string;
      data?: T;
    }

    // --- Market Data ---
    export interface Quote {
      symbol: string;
      exchange: string;
      ltp: number;
      open: number;
      high: number;
      low: number;
      close: number;
      volume: number;
      change?: number;
      pct?: number;
    }

    export interface DepthLevel {
      price: number;
      quantity: number;
      orders: number;
    }

    export interface MarketDepth {
      buy: DepthLevel[];
      sell: DepthLevel[];
    }

    export interface OHLCVBar {
      time: number;
      open: number;
      high: number;
      low: number;
      close: number;
      volume: number;
    }

    // --- Trading ---
    export interface Position {
      symbol: string;
      exchange: string;
      product: string;
      quantity: number;
      averagePrice: number;
      ltp: number;
      pnl: number;
      pnlPercent: number;
    }

    export interface Order {
      orderId: string;
      symbol: string;
      exchange: string;
      action: "BUY" | "SELL";
      quantity: number;
      price: number;
      orderType: string;
      status: string;
      product: string;
      strategy: string;
      timestamp: string;
    }

    export interface Trade {
      tradeId: string;
      orderId: string;
      symbol: string;
      exchange: string;
      action: "BUY" | "SELL";
      quantity: number;
      price: number;
      timestamp: string;
    }

    export interface Holding {
      symbol: string;
      exchange: string;
      quantity: number;
      averagePrice: number;
      ltp: number;
      pnl: number;
      pnlPercent: number;
    }

    export interface Funds {
      availableCash: number;
      usedMargin: number;
      totalBalance: number;
    }

    // --- Options ---
    export interface OptionChainStrike {
      strikePrice: number;
      ceSymbol: string;
      peSymbol: string;
      ceLtp: number;
      peLtp: number;
      ceOi: number;
      peOi: number;
      ceVolume: number;
      peVolume: number;
      ceIv: number;
      peIv: number;
      ceDelta?: number;
      ceGamma?: number;
      ceTheta?: number;
      ceVega?: number;
      peDelta?: number;
      peGamma?: number;
      peTheta?: number;
      peVega?: number;
    }

    export interface OptionChainData {
      symbol: string;
      expiry: string;
      spotPrice: number;
      strikes: OptionChainStrike[];
    }

    export interface Greeks {
      delta: number;
      gamma: number;
      theta: number;
      vega: number;
      iv: number;
    }

    // --- Order Placement ---
    export interface PlaceOrderParams {
      symbol: string;
      exchange: string;
      action: "BUY" | "SELL";
      quantity: number;
      orderType: "MARKET" | "LIMIT" | "SL" | "SL-M";
      product: "MIS" | "CNC" | "NRML";
      price?: number;
      triggerPrice?: number;
      strategy?: string;
    }

    export interface SmartOrderParams extends PlaceOrderParams {
      positionSize: number;
    }

    // --- WebSocket ---
    export interface WsTick {
      symbol: string;
      exchange: string;
      ltp: number;
      open?: number;
      high?: number;
      low?: number;
      close?: number;
      volume?: number;
      change?: number;
      pct?: number;
    }

    export type WsMode = "ltp" | "quote" | "depth";

    export interface WsInstrument {
      symbol: string;
      exchange: string;
    }

    export type WsAction =
      | "subscribe_ltp"
      | "subscribe_quote"
      | "subscribe_depth"
      | "unsubscribe_ltp"
      | "unsubscribe_quote"
      | "unsubscribe_depth";
    ```
  - **Expected:** Type file created with all OpenAlgo API shapes
  - **Verify:** `npx tsc --noEmit` (will fail because no TS files import it yet — that is OK)

- [ ] **1.6.2** Create shared types for Dockview widget system
  - **File:** `packages/terminal/src/types/widgets.ts`
  - **Content:**
    ```typescript
    import type { IDockviewPanelProps } from "dockview-react";

    export interface WidgetMeta {
      id: string;
      name: string;
      icon: string;
      category: "Trading" | "Analysis" | "Utility";
      description?: string;
    }

    export interface WidgetProps extends IDockviewPanelProps {
      // Additional FlintTrade-specific props can go here
    }

    export type WidgetId =
      | "dashboard"
      | "scalper"
      | "positions"
      | "orders"
      | "holdings"
      | "tradebook"
      | "orderpad"
      | "chart"
      | "optionchain"
      | "oichart"
      | "straddle"
      | "depth"
      | "greeks"
      | "watchlist";

    export type ToolId =
      | "settings"
      | "backtest-lab"
      | "trade-journal"
      | "strategy-builder"
      | "pnl-dashboard"
      | "market-intelligence"
      | "flow-builder";
    ```
  - **Expected:** Widget type definitions created

- [ ] **1.6.3** Create shared types for store shapes
  - **File:** `packages/terminal/src/types/stores.ts`
  - **Content:**
    ```typescript
    import type { DockviewApi } from "dockview-react";

    export type ConnectionStatus = "connected" | "disconnected" | "connecting" | "error";

    export interface ConnectionState {
      host: string;
      apiKey: string;
      wsUrl: string;
      status: ConnectionStatus;
      wsConnected: boolean;
      lastPing: number | null;
    }

    export interface LayoutPreset {
      id: string;
      name: string;
      description: string;
      panels: SerializedLayout;
    }

    export interface LayoutTab {
      id: string;
      name: string;
    }

    export interface LayoutState {
      tabs: LayoutTab[];
      activeTabId: string;
      dockviewApi: DockviewApi | null;
      presets: LayoutPreset[];
    }

    export interface TradingState {
      totalPnl: number;
      totalPnlPercent: number;
      positionCount: number;
      openOrderCount: number;
      usedMargin: number;
      availableMargin: number;
    }

    export interface SettingsState {
      persona: "trader" | "investor" | "beginner";
      theme: "dark";
      density: "compact" | "comfortable";
      defaultExchange: string;
      defaultProduct: string;
      defaultQty: number;
      riskLimits: {
        maxPositionLots: number;
        mtmStoploss: number;
        mtmTarget: number;
        maxOrdersPerMin: number;
      };
    }

    // Dockview serialization format placeholder
    export type SerializedLayout = Record<string, unknown>;
    ```
  - **Expected:** Store type definitions created
  - **Commit:** `feat(terminal): add TypeScript type definitions for API, widgets, and stores`

### 1.7 Verify React 19 + Dockview v5 compatibility

- [ ] **1.7.1** Create a minimal smoke test for Dockview with React 19
  - **File:** `packages/terminal/src/__tests__/dockview-smoke.test.tsx`
  - **Content:**
    ```typescript
    import { describe, it, expect } from "vitest";
    import { DockviewReact } from "dockview-react";

    describe("Dockview v5 + React 19", () => {
      it("DockviewReact component is importable", () => {
        expect(DockviewReact).toBeDefined();
        expect(typeof DockviewReact).toBe("function");
      });
    });
    ```
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npx vitest run src/__tests__/dockview-smoke.test.tsx
    ```
  - **Expected:** Test passes — DockviewReact is a valid component

- [ ] **1.7.2** Update vitest config for TypeScript support
  - **File:** `packages/terminal/vite.config.ts`
  - **Edit:** Add test configuration:
    ```typescript
    test: {
      globals: true,
      environment: "jsdom",
      setupFiles: [],
      include: ["src/**/*.test.{ts,tsx}"],
    },
    ```
  - **Expected:** `npx vitest run` discovers and runs `.test.ts` and `.test.tsx` files
  - **Commit:** `test(terminal): verify Dockview v5 + React 19 compatibility`

### 1.8 Update index.html for TypeScript entry point

- [ ] **1.8.1** Update `index.html` to reference `main.tsx`
  - **File:** `packages/terminal/index.html`
  - **Edit:** Change `<script type="module" src="/src/main.jsx"></script>` to `<script type="module" src="/src/main.tsx"></script>`
  - **Expected:** HTML references TypeScript entry point
  - **Note:** Do NOT rename `main.jsx` yet — that happens in Phase 3 when we rewrite App

---

## Phase 2: State Architecture (Days 4-6)

### 2.1 Create Zustand stores

- [ ] **2.1.1** Write test for connectionStore
  - **File:** `packages/terminal/src/stores/__tests__/connectionStore.test.ts`
  - **Content:**
    ```typescript
    import { describe, it, expect, beforeEach } from "vitest";
    import { useConnectionStore } from "../connectionStore";

    describe("connectionStore", () => {
      beforeEach(() => {
        useConnectionStore.setState(useConnectionStore.getInitialState());
      });

      it("initializes with disconnected status", () => {
        const state = useConnectionStore.getState();
        expect(state.status).toBe("disconnected");
        expect(state.wsConnected).toBe(false);
      });

      it("updates connection status", () => {
        useConnectionStore.getState().setStatus("connected");
        expect(useConnectionStore.getState().status).toBe("connected");
      });

      it("sets API configuration", () => {
        useConnectionStore.getState().setConfig({
          host: "http://localhost:5000",
          apiKey: "test-key",
        });
        const state = useConnectionStore.getState();
        expect(state.host).toBe("http://localhost:5000");
        expect(state.apiKey).toBe("test-key");
      });

      it("tracks WebSocket connection state", () => {
        useConnectionStore.getState().setWsConnected(true);
        expect(useConnectionStore.getState().wsConnected).toBe(true);
      });
    });
    ```
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npx vitest run src/stores/__tests__/connectionStore.test.ts
    ```
  - **Expected:** Test FAILS (store doesn't exist yet)

- [ ] **2.1.2** Implement connectionStore
  - **File:** `packages/terminal/src/stores/connectionStore.ts`
  - **Content:**
    ```typescript
    import { create } from "zustand";
    import { devtools } from "zustand/middleware";
    import type { ConnectionStatus } from "@/types/stores";

    interface ConnectionStore {
      host: string;
      apiKey: string;
      wsUrl: string;
      status: ConnectionStatus;
      wsConnected: boolean;
      lastPing: number | null;
      setStatus: (status: ConnectionStatus) => void;
      setWsConnected: (connected: boolean) => void;
      setConfig: (config: { host?: string; apiKey?: string; wsUrl?: string }) => void;
      setLastPing: (timestamp: number) => void;
    }

    const BASE = import.meta.env.DEV ? "" : (import.meta.env.VITE_OPENALGO_HOST || "http://127.0.0.1:5000");
    const API_KEY = import.meta.env.VITE_OPENALGO_API_KEY || "";
    const WS_URL = import.meta.env.DEV
      ? `ws://${window.location.host}/ws`
      : (import.meta.env.VITE_OPENALGO_WS || "ws://127.0.0.1:8765");

    export const useConnectionStore = create<ConnectionStore>()(
      devtools(
        (set) => ({
          host: BASE,
          apiKey: API_KEY,
          wsUrl: WS_URL,
          status: "disconnected",
          wsConnected: false,
          lastPing: null,
          setStatus: (status) => set({ status }, false, "setStatus"),
          setWsConnected: (wsConnected) => set({ wsConnected }, false, "setWsConnected"),
          setConfig: (config) => set((state) => ({ ...state, ...config }), false, "setConfig"),
          setLastPing: (lastPing) => set({ lastPing }, false, "setLastPing"),
        }),
        { name: "connection" }
      )
    );
    ```
  - **Command:** Re-run the test:
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npx vitest run src/stores/__tests__/connectionStore.test.ts
    ```
  - **Expected:** Test PASSES

- [ ] **2.1.3** Write test for tradingStore
  - **File:** `packages/terminal/src/stores/__tests__/tradingStore.test.ts`
  - **Content:**
    ```typescript
    import { describe, it, expect, beforeEach } from "vitest";
    import { useTradingStore } from "../tradingStore";

    describe("tradingStore", () => {
      beforeEach(() => {
        useTradingStore.setState(useTradingStore.getInitialState());
      });

      it("initializes with zero P&L", () => {
        const state = useTradingStore.getState();
        expect(state.totalPnl).toBe(0);
        expect(state.positionCount).toBe(0);
      });

      it("updates aggregated P&L from positions", () => {
        useTradingStore.getState().updateFromPositions([
          { pnl: 1500 },
          { pnl: -500 },
        ] as any[]);
        const state = useTradingStore.getState();
        expect(state.totalPnl).toBe(1000);
        expect(state.positionCount).toBe(2);
      });

      it("updates margin info from funds", () => {
        useTradingStore.getState().updateFromFunds({
          availableCash: 50000,
          usedMargin: 10000,
          totalBalance: 60000,
        });
        const state = useTradingStore.getState();
        expect(state.availableMargin).toBe(50000);
        expect(state.usedMargin).toBe(10000);
      });
    });
    ```
  - **Expected:** Test FAILS (store doesn't exist yet)

- [ ] **2.1.4** Implement tradingStore
  - **File:** `packages/terminal/src/stores/tradingStore.ts`
  - **Content:**
    ```typescript
    import { create } from "zustand";
    import { devtools } from "zustand/middleware";
    import type { Position, Funds } from "@/types/api";

    interface TradingStore {
      totalPnl: number;
      totalPnlPercent: number;
      positionCount: number;
      openOrderCount: number;
      usedMargin: number;
      availableMargin: number;
      updateFromPositions: (positions: Position[]) => void;
      updateFromFunds: (funds: Funds) => void;
      setOpenOrderCount: (count: number) => void;
    }

    export const useTradingStore = create<TradingStore>()(
      devtools(
        (set) => ({
          totalPnl: 0,
          totalPnlPercent: 0,
          positionCount: 0,
          openOrderCount: 0,
          usedMargin: 0,
          availableMargin: 0,
          updateFromPositions: (positions) => {
            const totalPnl = positions.reduce((sum, p) => sum + (p.pnl || 0), 0);
            set({
              totalPnl,
              positionCount: positions.length,
            }, false, "updateFromPositions");
          },
          updateFromFunds: (funds) => {
            set({
              usedMargin: funds.usedMargin || 0,
              availableMargin: funds.availableCash || 0,
            }, false, "updateFromFunds");
          },
          setOpenOrderCount: (count) => set({ openOrderCount: count }, false, "setOpenOrderCount"),
        }),
        { name: "trading" }
      )
    );
    ```
  - **Command:** Re-run the test:
    ```bash
    npx vitest run src/stores/__tests__/tradingStore.test.ts
    ```
  - **Expected:** Test PASSES

- [ ] **2.1.5** Write test for settingsStore
  - **File:** `packages/terminal/src/stores/__tests__/settingsStore.test.ts`
  - **Content:**
    ```typescript
    import { describe, it, expect, beforeEach } from "vitest";
    import { useSettingsStore } from "../settingsStore";

    describe("settingsStore", () => {
      beforeEach(() => {
        useSettingsStore.setState(useSettingsStore.getInitialState());
      });

      it("initializes with trader persona", () => {
        expect(useSettingsStore.getState().persona).toBe("trader");
      });

      it("initializes with compact density", () => {
        expect(useSettingsStore.getState().density).toBe("compact");
      });

      it("updates persona", () => {
        useSettingsStore.getState().setPersona("investor");
        expect(useSettingsStore.getState().persona).toBe("investor");
      });

      it("updates trading defaults", () => {
        useSettingsStore.getState().setTradingDefaults({
          defaultExchange: "BSE",
          defaultProduct: "CNC",
          defaultQty: 10,
        });
        const state = useSettingsStore.getState();
        expect(state.defaultExchange).toBe("BSE");
        expect(state.defaultProduct).toBe("CNC");
        expect(state.defaultQty).toBe(10);
      });

      it("updates risk limits", () => {
        useSettingsStore.getState().setRiskLimits({ mtmStoploss: 10000 });
        expect(useSettingsStore.getState().riskLimits.mtmStoploss).toBe(10000);
      });
    });
    ```
  - **Expected:** Test FAILS (store doesn't exist yet)

- [ ] **2.1.6** Implement settingsStore
  - **File:** `packages/terminal/src/stores/settingsStore.ts`
  - **Content:**
    ```typescript
    import { create } from "zustand";
    import { devtools, persist } from "zustand/middleware";

    interface RiskLimits {
      maxPositionLots: number;
      mtmStoploss: number;
      mtmTarget: number;
      maxOrdersPerMin: number;
    }

    interface SettingsStore {
      persona: "trader" | "investor" | "beginner";
      theme: "dark";
      density: "compact" | "comfortable";
      defaultExchange: string;
      defaultProduct: string;
      defaultQty: number;
      riskLimits: RiskLimits;
      setPersona: (persona: "trader" | "investor" | "beginner") => void;
      setDensity: (density: "compact" | "comfortable") => void;
      setTradingDefaults: (defaults: Partial<Pick<SettingsStore, "defaultExchange" | "defaultProduct" | "defaultQty">>) => void;
      setRiskLimits: (limits: Partial<RiskLimits>) => void;
    }

    export const useSettingsStore = create<SettingsStore>()(
      devtools(
        persist(
          (set) => ({
            persona: "trader",
            theme: "dark" as const,
            density: "compact",
            defaultExchange: "NFO",
            defaultProduct: "MIS",
            defaultQty: 1,
            riskLimits: {
              maxPositionLots: 10,
              mtmStoploss: 5000,
              mtmTarget: 10000,
              maxOrdersPerMin: 30,
            },
            setPersona: (persona) => set({ persona }, false, "setPersona"),
            setDensity: (density) => set({ density }, false, "setDensity"),
            setTradingDefaults: (defaults) =>
              set((state) => ({ ...state, ...defaults }), false, "setTradingDefaults"),
            setRiskLimits: (limits) =>
              set(
                (state) => ({
                  riskLimits: { ...state.riskLimits, ...limits },
                }),
                false,
                "setRiskLimits"
              ),
          }),
          { name: "flinttrade:settings" }
        ),
        { name: "settings" }
      )
    );
    ```
  - **Command:** Re-run the test:
    ```bash
    npx vitest run src/stores/__tests__/settingsStore.test.ts
    ```
  - **Expected:** Test PASSES

- [ ] **2.1.7** Write test for layoutStore (Zustand version)
  - **File:** `packages/terminal/src/stores/__tests__/layoutStore.test.ts`
  - **Content:**
    ```typescript
    import { describe, it, expect, beforeEach } from "vitest";
    import { useLayoutStore } from "../layoutStore";

    describe("layoutStore", () => {
      beforeEach(() => {
        useLayoutStore.setState(useLayoutStore.getInitialState());
      });

      it("initializes with one default tab", () => {
        const state = useLayoutStore.getState();
        expect(state.tabs.length).toBeGreaterThanOrEqual(1);
        expect(state.activeTabId).toBeTruthy();
      });

      it("adds a new tab", () => {
        const before = useLayoutStore.getState().tabs.length;
        useLayoutStore.getState().addTab("Test Layout");
        expect(useLayoutStore.getState().tabs.length).toBe(before + 1);
      });

      it("switches active tab", () => {
        useLayoutStore.getState().addTab("Second");
        const tabs = useLayoutStore.getState().tabs;
        const secondId = tabs[tabs.length - 1].id;
        useLayoutStore.getState().setActiveTab(secondId);
        expect(useLayoutStore.getState().activeTabId).toBe(secondId);
      });

      it("renames a tab", () => {
        const tabId = useLayoutStore.getState().tabs[0].id;
        useLayoutStore.getState().renameTab(tabId, "Renamed");
        const tab = useLayoutStore.getState().tabs.find((t) => t.id === tabId);
        expect(tab?.name).toBe("Renamed");
      });
    });
    ```
  - **Expected:** Test FAILS

- [ ] **2.1.8** Implement layoutStore (Zustand version)
  - **File:** `packages/terminal/src/stores/layoutStore.ts`
  - **Content:**
    ```typescript
    import { create } from "zustand";
    import { devtools, persist } from "zustand/middleware";
    import type { DockviewApi } from "dockview-react";

    interface LayoutTab {
      id: string;
      name: string;
      serializedLayout?: Record<string, unknown>;
    }

    interface LayoutStore {
      tabs: LayoutTab[];
      activeTabId: string;
      dockviewApi: DockviewApi | null;
      addTab: (name?: string) => void;
      removeTab: (id: string) => void;
      setActiveTab: (id: string) => void;
      renameTab: (id: string, name: string) => void;
      saveTabLayout: (id: string, layout: Record<string, unknown>) => void;
      getTabLayout: (id: string) => Record<string, unknown> | undefined;
      setDockviewApi: (api: DockviewApi | null) => void;
    }

    function generateId(): string {
      return `LAY-${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
    }

    const defaultTabId = generateId();

    export const useLayoutStore = create<LayoutStore>()(
      devtools(
        persist(
          (set, get) => ({
            tabs: [{ id: defaultTabId, name: "Workspace" }],
            activeTabId: defaultTabId,
            dockviewApi: null,
            addTab: (name) => {
              const id = generateId();
              const tabName = name || `Layout ${get().tabs.length + 1}`;
              set(
                (state) => ({
                  tabs: [...state.tabs, { id, name: tabName }],
                  activeTabId: id,
                }),
                false,
                "addTab"
              );
            },
            removeTab: (id) => {
              set(
                (state) => {
                  const remaining = state.tabs.filter((t) => t.id !== id);
                  if (remaining.length === 0) return state; // never remove last tab
                  const newActive =
                    state.activeTabId === id ? remaining[0].id : state.activeTabId;
                  return { tabs: remaining, activeTabId: newActive };
                },
                false,
                "removeTab"
              );
            },
            setActiveTab: (id) => set({ activeTabId: id }, false, "setActiveTab"),
            renameTab: (id, name) => {
              set(
                (state) => ({
                  tabs: state.tabs.map((t) => (t.id === id ? { ...t, name } : t)),
                }),
                false,
                "renameTab"
              );
            },
            saveTabLayout: (id, layout) => {
              set(
                (state) => ({
                  tabs: state.tabs.map((t) =>
                    t.id === id ? { ...t, serializedLayout: layout } : t
                  ),
                }),
                false,
                "saveTabLayout"
              );
            },
            getTabLayout: (id) => {
              return get().tabs.find((t) => t.id === id)?.serializedLayout;
            },
            setDockviewApi: (api) => set({ dockviewApi: api }, false, "setDockviewApi"),
          }),
          {
            name: "flinttrade:layouts",
            partialize: (state) => ({
              tabs: state.tabs,
              activeTabId: state.activeTabId,
            }),
          }
        ),
        { name: "layout" }
      )
    );
    ```
  - **Command:** Re-run all store tests:
    ```bash
    npx vitest run src/stores/
    ```
  - **Expected:** All 4 store test files PASS
  - **Commit:** `feat(terminal): Zustand stores — connection, trading, settings, layout`

### 2.2 Create Jotai atoms for real-time market data

- [ ] **2.2.1** Write test for market data atoms
  - **File:** `packages/terminal/src/atoms/__tests__/marketAtoms.test.ts`
  - **Content:**
    ```typescript
    import { describe, it, expect } from "vitest";
    import { createStore } from "jotai";
    import {
      tickAtomFamily,
      niftyAtom,
      sensexAtom,
      bankniftyAtom,
      vixAtom,
    } from "../marketAtoms";
    import type { WsTick } from "@/types/api";

    describe("marketAtoms", () => {
      it("tickAtomFamily creates unique atoms per instrument key", () => {
        const store = createStore();
        const niftyTick = tickAtomFamily("NSE_INDEX:NIFTY");
        const bnfTick = tickAtomFamily("NSE_INDEX:BANKNIFTY");
        expect(niftyTick).not.toBe(bnfTick);
      });

      it("tickAtomFamily returns same atom for same key", () => {
        const a1 = tickAtomFamily("NSE_INDEX:NIFTY");
        const a2 = tickAtomFamily("NSE_INDEX:NIFTY");
        expect(a1).toBe(a2);
      });

      it("index atoms derive from tickAtomFamily", () => {
        const store = createStore();
        const tick: WsTick = {
          symbol: "NIFTY",
          exchange: "NSE_INDEX",
          ltp: 23581,
          change: 100,
          pct: 0.74,
        };
        store.set(tickAtomFamily("NSE_INDEX:NIFTY"), tick);
        const val = store.get(niftyAtom);
        expect(val?.ltp).toBe(23581);
      });
    });
    ```
  - **Expected:** Test FAILS (atoms don't exist yet)

- [ ] **2.2.2** Implement market data atoms
  - **File:** `packages/terminal/src/atoms/marketAtoms.ts`
  - **Content:**
    ```typescript
    import { atom } from "jotai";
    import { atomFamily } from "jotai/utils";
    import type { WsTick } from "@/types/api";

    /**
     * Atom family for per-instrument tick data.
     * Key format: "{exchange}:{symbol}" e.g. "NSE_INDEX:NIFTY"
     * Each atom holds the latest WsTick or null.
     */
    export const tickAtomFamily = atomFamily(
      (_key: string) => atom<WsTick | null>(null)
    );

    // --- Derived index atoms (convenience) ---
    export const niftyAtom = tickAtomFamily("NSE_INDEX:NIFTY");
    export const sensexAtom = tickAtomFamily("BSE_INDEX:SENSEX");
    export const bankniftyAtom = tickAtomFamily("NSE_INDEX:BANKNIFTY");
    export const vixAtom = tickAtomFamily("NSE_INDEX:INDIAVIX");

    /**
     * Derived atom: total indices summary for TickerBar
     */
    export const indicesSummaryAtom = atom((get) => {
      return [
        { name: "NIFTY 50", data: get(niftyAtom) },
        { name: "SENSEX", data: get(sensexAtom) },
        { name: "BANK NIFTY", data: get(bankniftyAtom) },
        { name: "VIX", data: get(vixAtom) },
      ];
    });
    ```
  - **Command:** Re-run atom tests:
    ```bash
    npx vitest run src/atoms/
    ```
  - **Expected:** All tests PASS
  - **Commit:** `feat(terminal): Jotai atoms for per-instrument real-time market data`

### 2.3 Create TanStack Query hooks

- [ ] **2.3.1** Write test for usePositions hook
  - **File:** `packages/terminal/src/hooks/__tests__/usePositions.test.ts`
  - **Content:**
    ```typescript
    import { describe, it, expect, vi } from "vitest";
    import { renderHook, waitFor } from "@testing-library/react";
    import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
    import { createElement } from "react";
    import { usePositions } from "../usePositions";

    // Mock the API module
    vi.mock("@/services/api", () => ({
      getPositionbook: vi.fn().mockResolvedValue([
        { symbol: "NIFTY", pnl: 1500, quantity: 50 },
      ]),
    }));

    function createWrapper() {
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      return ({ children }: { children: React.ReactNode }) =>
        createElement(QueryClientProvider, { client }, children);
    }

    describe("usePositions", () => {
      it("fetches positions from API", async () => {
        const { result } = renderHook(() => usePositions(), {
          wrapper: createWrapper(),
        });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));
        expect(result.current.data).toHaveLength(1);
        expect(result.current.data?.[0].symbol).toBe("NIFTY");
      });
    });
    ```
  - **Note:** Install `@testing-library/react` if not present:
    ```bash
    npm install -D @testing-library/react @testing-library/jest-dom
    ```
  - **Expected:** Test FAILS (hook doesn't exist yet)

- [ ] **2.3.2** Migrate API service to TypeScript
  - **Rename:** `packages/terminal/src/services/api.js` -> `packages/terminal/src/services/api.ts`
  - **File:** `packages/terminal/src/services/api.ts`
  - **Edit:** Add types, fix 3 critical bugs:
    1. **Bug fix: `ping` uses POST but OpenAlgo API says GET** — change to `get("ping")`
    2. **Bug fix: `closePosition` doesn't pass strategy properly** — ensure `{ strategy }` is sent
    3. **Bug fix: `getOptionChain` doesn't pass expiry** — add `expiry` parameter
  - **Content outline:**
    ```typescript
    import type {
      Position, Order, Trade, Holding, Funds,
      Quote, MarketDepth, OHLCVBar, OptionChainData,
      PlaceOrderParams, SmartOrderParams, Greeks,
    } from "@/types/api";
    import { useConnectionStore } from "@/stores/connectionStore";

    function getBase(): string {
      return useConnectionStore.getState().host;
    }

    function getApiKey(): string {
      return useConnectionStore.getState().apiKey;
    }

    async function post<T>(endpoint: string, extra: Record<string, unknown> = {}): Promise<T> {
      const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apikey: getApiKey(), ...extra }),
      });
      if (!resp.ok) throw new Error(`API ${endpoint}: HTTP ${resp.status}`);
      const json = await resp.json();
      if (json.status === "error") throw new Error(json.message || `API ${endpoint} error`);
      return (json.data ?? json) as T;
    }

    async function get<T>(endpoint: string): Promise<T> {
      const resp = await fetch(`${getBase()}/api/v1/${endpoint}`);
      if (!resp.ok) throw new Error(`API ${endpoint}: HTTP ${resp.status}`);
      const json = await resp.json();
      if (json.status === "error") throw new Error(json.message || `API ${endpoint} error`);
      return (json.data ?? json) as T;
    }

    // --- Orders ---
    export const placeOrder = (params: PlaceOrderParams) => post<{ orderId: string }>("placeorder", params as any);
    export const placeSmartOrder = (params: SmartOrderParams) => post<{ orderId: string }>("placesmartorder", params as any);
    export const cancelOrder = (strategy: string, orderid: string) => post<void>("cancelorder", { strategy, orderid });
    export const cancelAllOrders = (strategy = "Flint") => post<void>("cancelallorder", { strategy });
    export const closePosition = (strategy = "Flint") => post<void>("closeposition", { strategy });
    export const modifyOrder = (params: Record<string, unknown>) => post<void>("modifyorder", params);
    export const orderStatus = (strategy: string, orderid: string) => post<Order>("orderstatus", { strategy, orderid });

    // --- Data ---
    export const getQuotes = (symbol: string, exchange = "NSE") => post<Quote>("quotes", { symbol, exchange });
    export const getMultiQuotes = (symbols: Array<{ symbol: string; exchange: string }>) => post<Quote[]>("multiquotes", { symbols });
    export const getDepth = (symbol: string, exchange = "NSE") => post<MarketDepth>("depth", { symbol, exchange });
    export const getHistory = (symbol: string, exchange: string, interval: string, start_date: string, end_date: string) =>
      post<OHLCVBar[]>("history", { symbol, exchange, interval, start_date, end_date });
    export const getOptionChain = (symbol: string, exchange = "NFO", expiry?: string) =>
      post<OptionChainData>("optionchain", { symbol, exchange, ...(expiry ? { expiry } : {}) });
    export const getOptionGreeks = (symbol: string, exchange = "NFO") => post<Greeks>("optiongreeks", { symbol, exchange });
    export const getExpiry = (symbol: string, exchange = "NFO") => post<{ expiry: string[] }>("expiry", { symbol, exchange });
    export const searchSymbol = (query: string) => post<Array<{ symbol: string; exchange: string }>>("search", { query });
    export const getIntervals = () => get<string[]>("intervals");

    // --- Account ---
    export const getFunds = () => post<Funds>("funds");
    export const getOrderbook = () => post<Order[]>("orderbook");
    export const getTradebook = () => post<Trade[]>("tradebook");
    export const getPositionbook = () => post<Position[]>("positionbook");
    export const getHoldings = () => post<Holding[]>("holdings");

    // --- Utility ---
    export const ping = () => get<{ status: string }>("ping");  // BUG FIX: was POST, should be GET
    export const analyzerStatus = () => get<{ enabled: boolean }>("analyzer/status");
    export const analyzerToggle = () => post<void>("analyzer/toggle");
    ```
  - **Expected:** API service fully typed, 3 bugs fixed

- [ ] **2.3.3** Implement TanStack Query hooks
  - **File:** `packages/terminal/src/hooks/usePositions.ts`
  - **Content:**
    ```typescript
    import { useQuery } from "@tanstack/react-query";
    import { getPositionbook } from "@/services/api";
    import { useTradingStore } from "@/stores/tradingStore";
    import type { Position } from "@/types/api";

    function isMarketHours(): boolean {
      const ist = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
      const mins = ist.getHours() * 60 + ist.getMinutes();
      const day = ist.getDay();
      if (day === 0 || day === 6) return false;
      return mins >= 555 && mins <= 930;
    }

    export function usePositions() {
      return useQuery<Position[]>({
        queryKey: ["positions"],
        queryFn: getPositionbook,
        refetchInterval: isMarketHours() ? 5_000 : 60_000,
        select: (data) => {
          // Side effect: update trading store with aggregated P&L
          useTradingStore.getState().updateFromPositions(data);
          return data;
        },
      });
    }
    ```
  - **Expected:** Hook created

- [ ] **2.3.4** Implement remaining TanStack Query hooks (batch)
  - **Files to create:**
    - `packages/terminal/src/hooks/useOrders.ts` — `queryKey: ["orders"]`, refetch every 10s
    - `packages/terminal/src/hooks/useHoldings.ts` — `queryKey: ["holdings"]`, refetch every 60s, `retry: false` (broker may not support)
    - `packages/terminal/src/hooks/useFunds.ts` — `queryKey: ["funds"]`, refetch every 30s
    - `packages/terminal/src/hooks/useOptionChain.ts` — `queryKey: ["optionchain", symbol, exchange, expiry]`, manual refetch
    - `packages/terminal/src/hooks/useTradebook.ts` — `queryKey: ["tradebook"]`, refetch every 30s
  - **Pattern for each:**
    ```typescript
    import { useQuery } from "@tanstack/react-query";
    import { getOrderbook } from "@/services/api";
    import type { Order } from "@/types/api";

    export function useOrders() {
      return useQuery<Order[]>({
        queryKey: ["orders"],
        queryFn: getOrderbook,
        refetchInterval: 10_000,
      });
    }
    ```
  - **Expected:** All 6 hooks created
  - **Command:**
    ```bash
    npx vitest run src/hooks/
    ```
  - **Commit:** `feat(terminal): TanStack Query hooks — positions, orders, holdings, funds, optionchain, tradebook`

### 2.4 Migrate WebSocket service to TypeScript

- [ ] **2.4.1** Write test for WebSocket service
  - **File:** `packages/terminal/src/services/__tests__/websocket.test.ts`
  - **Content:**
    ```typescript
    import { describe, it, expect, vi, beforeEach } from "vitest";
    import { WebSocketService } from "../websocket";

    // Mock WebSocket
    class MockWebSocket {
      static OPEN = 1;
      readyState = MockWebSocket.OPEN;
      onopen: (() => void) | null = null;
      onclose: (() => void) | null = null;
      onmessage: ((e: { data: string }) => void) | null = null;
      onerror: (() => void) | null = null;
      send = vi.fn();
      close = vi.fn();
    }

    vi.stubGlobal("WebSocket", MockWebSocket);

    describe("WebSocketService", () => {
      let ws: WebSocketService;

      beforeEach(() => {
        ws = new WebSocketService("ws://localhost:8765");
      });

      it("tracks subscription state per mode", () => {
        ws.subscribe([{ symbol: "NIFTY", exchange: "NSE_INDEX" }], "ltp");
        expect(ws.getSubscriptions("ltp")).toHaveLength(1);
      });

      it("does not duplicate subscriptions", () => {
        const inst = [{ symbol: "NIFTY", exchange: "NSE_INDEX" }];
        ws.subscribe(inst, "ltp");
        ws.subscribe(inst, "ltp");
        expect(ws.getSubscriptions("ltp")).toHaveLength(1);
      });

      it("removes subscriptions on unsubscribe", () => {
        const inst = [{ symbol: "NIFTY", exchange: "NSE_INDEX" }];
        ws.subscribe(inst, "ltp");
        ws.unsubscribe(inst, "ltp");
        expect(ws.getSubscriptions("ltp")).toHaveLength(0);
      });
    });
    ```
  - **Expected:** Test FAILS

- [ ] **2.4.2** Rewrite WebSocket service in TypeScript with ping/pong heartbeat
  - **File:** `packages/terminal/src/services/websocket.ts` (rename from `.js`)
  - **Key changes from v1:**
    1. Full TypeScript types
    2. Ping/pong heartbeat every 30s (OpenAlgo WS drops without it)
    3. Callback-based instead of DOM CustomEvents
    4. Jotai store integration for tick dispatch
  - **Content outline:**
    ```typescript
    import type { WsTick, WsMode, WsInstrument, WsAction } from "@/types/api";

    type TickCallback = (tick: WsTick) => void;
    type StatusCallback = (connected: boolean) => void;

    export class WebSocketService {
      private ws: WebSocket | null = null;
      private reconnectDelay = 1000;
      private readonly maxDelay = 30000;
      private readonly heartbeatInterval = 30000;
      private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
      private subscriptions: Record<WsMode, WsInstrument[]> = {
        ltp: [], quote: [], depth: [],
      };
      private connected = false;
      private shouldConnect = false;
      private tickCallbacks = new Set<TickCallback>();
      private statusCallbacks = new Set<StatusCallback>();

      constructor(private url: string) {}

      get isConnected(): boolean { return this.connected; }

      onTick(cb: TickCallback): () => void {
        this.tickCallbacks.add(cb);
        return () => this.tickCallbacks.delete(cb);
      }

      onStatus(cb: StatusCallback): () => void {
        this.statusCallbacks.add(cb);
        return () => this.statusCallbacks.delete(cb);
      }

      connect(): void { /* ... auto-reconnect, heartbeat ... */ }
      disconnect(): void { /* ... cleanup ... */ }
      subscribe(instruments: WsInstrument[], mode: WsMode = "ltp"): void { /* ... */ }
      unsubscribe(instruments: WsInstrument[], mode: WsMode = "ltp"): void { /* ... */ }
      getSubscriptions(mode: WsMode): WsInstrument[] { return [...this.subscriptions[mode]]; }

      private startHeartbeat(): void {
        this.heartbeatTimer = setInterval(() => {
          if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ action: "ping" }));
          }
        }, this.heartbeatInterval);
      }

      private stopHeartbeat(): void {
        if (this.heartbeatTimer) {
          clearInterval(this.heartbeatTimer);
          this.heartbeatTimer = null;
        }
      }
    }

    // Singleton — created lazily, URL from connectionStore
    let instance: WebSocketService | null = null;

    export function getWsService(url?: string): WebSocketService {
      if (!instance && url) {
        instance = new WebSocketService(url);
      }
      return instance!;
    }

    export function resetWsService(): void {
      instance?.disconnect();
      instance = null;
    }
    ```
  - **Command:** Re-run WS tests:
    ```bash
    npx vitest run src/services/__tests__/websocket.test.ts
    ```
  - **Expected:** Tests PASS

- [ ] **2.4.3** Create WebSocket-to-Jotai bridge hook
  - **File:** `packages/terminal/src/hooks/useWsBridge.ts`
  - **Content:**
    ```typescript
    import { useEffect } from "react";
    import { useSetAtom } from "jotai";
    import { tickAtomFamily } from "@/atoms/marketAtoms";
    import { useConnectionStore } from "@/stores/connectionStore";
    import { getWsService } from "@/services/websocket";
    import type { WsTick, WsInstrument } from "@/types/api";

    const INDEX_INSTRUMENTS: WsInstrument[] = [
      { symbol: "NIFTY", exchange: "NSE_INDEX" },
      { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
      { symbol: "SENSEX", exchange: "BSE_INDEX" },
      { symbol: "INDIAVIX", exchange: "NSE_INDEX" },
    ];

    /**
     * Bridge hook: connects WebSocket and dispatches ticks to Jotai atoms.
     * Mount once in App.tsx.
     */
    export function useWsBridge(): void {
      const setWsConnected = useConnectionStore((s) => s.setWsConnected);

      useEffect(() => {
        const wsUrl = useConnectionStore.getState().wsUrl;
        const ws = getWsService(wsUrl);

        const unsubTick = ws.onTick((tick: WsTick) => {
          const key = `${tick.exchange}:${tick.symbol}`;
          // Directly set the Jotai atom for this instrument
          // Note: we use store.set() from outside React for this
          tickAtomFamily(key);
          // The actual atom update happens via a global store reference
        });

        const unsubStatus = ws.onStatus((connected: boolean) => {
          setWsConnected(connected);
        });

        ws.connect();
        ws.subscribe(INDEX_INSTRUMENTS, "ltp");

        return () => {
          unsubTick();
          unsubStatus();
          ws.disconnect();
        };
      }, [setWsConnected]);
    }
    ```
  - **Expected:** Bridge hook connects WS to Jotai atoms
  - **Commit:** `feat(terminal): WebSocket service with ping/pong heartbeat + Jotai bridge`

### 2.5 Migrate rateLimiter to TypeScript

- [ ] **2.5.1** Rename and type rateLimiter
  - **Rename:** `packages/terminal/src/services/rateLimiter.js` -> `packages/terminal/src/services/rateLimiter.ts`
  - **File:** `packages/terminal/src/services/rateLimiter.ts`
  - **Edit:** Add TypeScript types:
    ```typescript
    interface RateLimiterConfig {
      tokensPerSecond: number;
      bucketSize: number;
    }

    export class RateLimiter {
      private tokensPerSecond: number;
      private bucketSize: number;
      private tokens: number;
      private lastRefill: number;

      constructor({ tokensPerSecond, bucketSize }: RateLimiterConfig) {
        this.tokensPerSecond = tokensPerSecond;
        this.bucketSize = bucketSize;
        this.tokens = bucketSize;
        this.lastRefill = Date.now();
      }

      tryConsume(count = 1): boolean {
        this.refill();
        if (this.tokens >= count) {
          this.tokens -= count;
          return true;
        }
        return false;
      }

      private refill(): void {
        const now = Date.now();
        const elapsed = (now - this.lastRefill) / 1000;
        this.tokens = Math.min(this.bucketSize, this.tokens + elapsed * this.tokensPerSecond);
        this.lastRefill = now;
      }
    }

    export const orderLimiter = new RateLimiter({ tokensPerSecond: 10, bucketSize: 10 });
    export const smartOrderLimiter = new RateLimiter({ tokensPerSecond: 2, bucketSize: 2 });
    export const generalLimiter = new RateLimiter({ tokensPerSecond: 50, bucketSize: 50 });
    ```
  - **Rename test:** `src/services/__tests__/rateLimiter.test.js` -> `src/services/__tests__/rateLimiter.test.ts`
  - **Command:**
    ```bash
    npx vitest run src/services/__tests__/rateLimiter.test.ts
    ```
  - **Expected:** Existing tests still PASS with no changes needed

### 2.6 Delete DataBus and old connectors

- [ ] **2.6.1** Delete DataBus files
  - **Commands:**
    ```bash
    rm C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal/src/services/dataBus.js
    rm C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal/src/services/__tests__/dataBus.test.js
    rm C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal/src/hooks/useDataBus.js
    rm C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal/src/services/dataConnector.js
    ```
  - **Expected:** 4 files deleted — DataBus system completely removed
  - **Verify:** `grep -r "dataBus\|DataBus\|useDataBus\|dataConnector" packages/terminal/src/` should show only import references in files not yet migrated (those will be fixed in Phase 4)
  - **Commit:** `refactor(terminal): remove DataBus — replaced by Zustand + Jotai + TanStack Query`

### 2.7 Create QueryClient provider

- [ ] **2.7.1** Create QueryClient configuration
  - **File:** `packages/terminal/src/providers/QueryProvider.tsx`
  - **Content:**
    ```typescript
    import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
    import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
    import type { ReactNode } from "react";

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: 5_000,
          gcTime: 300_000,
          retry: 2,
          refetchOnWindowFocus: true,
        },
      },
    });

    interface Props {
      children: ReactNode;
    }

    export function QueryProvider({ children }: Props) {
      return (
        <QueryClientProvider client={queryClient}>
          {children}
          {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
        </QueryClientProvider>
      );
    }

    export { queryClient };
    ```
  - **Expected:** QueryClient configured with sensible defaults for a trading app
  - **Commit:** `feat(terminal): QueryClient provider with devtools`

---

## Phase 3: Shell + Layout Migration (Days 7-8)

### 3.1 Rewrite App.tsx with Dockview

- [ ] **3.1.1** Create `main.tsx` (rename from `main.jsx`)
  - **Rename:** `packages/terminal/src/main.jsx` -> `packages/terminal/src/main.tsx`
  - **File:** `packages/terminal/src/main.tsx`
  - **Content:**
    ```typescript
    import React from "react";
    import ReactDOM from "react-dom/client";
    import { Provider as JotaiProvider } from "jotai";
    import { QueryProvider } from "./providers/QueryProvider";
    import App from "./App";
    import "./index.css";

    ReactDOM.createRoot(document.getElementById("root")!).render(
      <React.StrictMode>
        <JotaiProvider>
          <QueryProvider>
            <App />
          </QueryProvider>
        </JotaiProvider>
      </React.StrictMode>
    );
    ```
  - **Expected:** Entry point wraps app with Jotai + TanStack Query providers

- [ ] **3.1.2** Rewrite `App.tsx` with Dockview (replace FlexLayout)
  - **Rename:** `packages/terminal/src/App.jsx` -> `packages/terminal/src/App.tsx`
  - **File:** `packages/terminal/src/App.tsx`
  - **Pre-check:** Use context7 MCP: `query-docs` for `dockview-react` — specifically `DockviewReact` component props, `onReady` callback, `addPanel`, `fromJSON/toJSON`
  - **Content outline:**
    ```typescript
    import { useState, useCallback, useEffect, lazy, Suspense } from "react";
    import { DockviewReact, DockviewReadyEvent } from "dockview-react";
    import "dockview-react/dist/styles/dockview.css";
    import { useLayoutStore } from "@/stores/layoutStore";
    import { useWsBridge } from "@/hooks/useWsBridge";
    import TopBar from "@/chrome/TopBar";
    import TickerBar from "@/chrome/TickerBar";
    import WidgetPicker from "@/chrome/WidgetPicker";
    import ToolsDropdown from "@/chrome/ToolsDropdown";
    import { widgetComponents } from "@/layout/widgetFactory";
    import useGlobalKeys from "@/hooks/useGlobalKeys";
    import type { ToolId } from "@/types/widgets";

    const tools: Record<ToolId, React.LazyExoticComponent<any>> = {
      settings: lazy(() => import("@/tools/Settings/SettingsTool")),
      "backtest-lab": lazy(() => import("@/tools/BacktestLab/BacktestLabTool")),
      "trade-journal": lazy(() => import("@/tools/TradeJournal/TradeJournalTool")),
      "strategy-builder": lazy(() => import("@/tools/StrategyBuilder/StrategyBuilderTool")),
      "pnl-dashboard": lazy(() => import("@/tools/PnLDashboard/PnLDashboardTool")),
      "market-intelligence": lazy(() => import("@/tools/MarketIntelligence/MarketIntelligenceTool")),
      "flow-builder": lazy(() => import("@/tools/FlowBuilder/FlowBuilderTool")),
    };

    export default function App() {
      const [widgetPickerOpen, setWidgetPickerOpen] = useState(false);
      const [toolsMenuOpen, setToolsMenuOpen] = useState(false);
      const [activeTool, setActiveTool] = useState<ToolId | null>(null);
      const setDockviewApi = useLayoutStore((s) => s.setDockviewApi);

      // Initialize WebSocket bridge
      useWsBridge();

      const onDockviewReady = useCallback((event: DockviewReadyEvent) => {
        setDockviewApi(event.api);
        // Load saved layout or apply default preset
        const activeTabId = useLayoutStore.getState().activeTabId;
        const savedLayout = useLayoutStore.getState().getTabLayout(activeTabId);
        if (savedLayout) {
          try {
            event.api.fromJSON(savedLayout as any);
          } catch {
            // Apply default preset on failure
            applyDefaultLayout(event.api);
          }
        } else {
          applyDefaultLayout(event.api);
        }
      }, [setDockviewApi]);

      useGlobalKeys({
        onEscape: useCallback(() => {
          if (activeTool) { setActiveTool(null); return; }
          if (widgetPickerOpen) { setWidgetPickerOpen(false); return; }
          if (toolsMenuOpen) { setToolsMenuOpen(false); return; }
        }, [activeTool, widgetPickerOpen, toolsMenuOpen]),
        onCommandPalette: useCallback(() => {}, []),
      });

      const ToolComponent = activeTool ? tools[activeTool] : null;

      return (
        <div className="h-screen flex flex-col bg-background text-foreground overflow-hidden select-none">
          <TopBar
            onWidgetPicker={() => setWidgetPickerOpen(true)}
            onToolsMenu={() => setToolsMenuOpen(!toolsMenuOpen)}
          />
          <TickerBar />
          <ToolsDropdown
            isOpen={toolsMenuOpen}
            onClose={() => setToolsMenuOpen(false)}
            onSelectTool={(id: ToolId) => setActiveTool(id)}
          />
          {activeTool && ToolComponent ? (
            <div className="flex-1 overflow-auto">
              <Suspense fallback={<div className="flex items-center justify-center h-full text-muted-foreground text-sm">Loading tool...</div>}>
                <ToolComponent onClose={() => setActiveTool(null)} />
              </Suspense>
            </div>
          ) : (
            <div className="flex-1 relative overflow-hidden">
              <DockviewReact
                className="dockview-theme-dark"
                onReady={onDockviewReady}
                components={widgetComponents}
              />
            </div>
          )}
          <WidgetPicker
            isOpen={widgetPickerOpen}
            onClose={() => setWidgetPickerOpen(false)}
          />
        </div>
      );
    }

    function applyDefaultLayout(api: any): void {
      api.addPanel({ id: "dashboard", component: "dashboard", title: "Dashboard" });
    }
    ```
  - **Expected:** App renders with Dockview instead of FlexLayout

- [ ] **3.1.3** Add Dockview dark theme CSS
  - **File:** `packages/terminal/src/index.css`
  - **Edit:** Add Dockview dark theme overrides after shadcn/ui variables:
    ```css
    /* Dockview dark theme overrides */
    .dockview-theme-dark {
      --dv-background-color: #0a0a0f;
      --dv-paneview-header-border-color: #1e1e2e;
      --dv-tabs-and-actions-container-background-color: #12121a;
      --dv-activegroup-visiblepanel-tab-background-color: #0a0a0f;
      --dv-activegroup-hiddenpanel-tab-background-color: #12121a;
      --dv-inactivegroup-visiblepanel-tab-background-color: #0a0a0f;
      --dv-inactivegroup-hiddenpanel-tab-background-color: #12121a;
      --dv-tab-divider-color: #1e1e2e;
      --dv-activegroup-visiblepanel-tab-color: #e4e4e7;
      --dv-activegroup-hiddenpanel-tab-color: #71717a;
      --dv-separator-border: #16161f;
      --dv-drag-over-background-color: rgba(59, 130, 246, 0.15);
      --dv-drag-over-border-color: rgba(59, 130, 246, 0.4);
      font-family: 'Inter', system-ui, sans-serif;
      font-size: 11px;
    }
    ```
  - **Expected:** Dockview panels match FlintTrade's dark theme
  - **Commit:** `feat(terminal): replace FlexLayout with Dockview v5 shell`

### 3.2 Rewrite chrome components in TSX + shadcn/ui

- [ ] **3.2.1** Rewrite TopBar.tsx with shadcn/ui
  - **Rename:** `packages/terminal/src/chrome/TopBar.jsx` -> `packages/terminal/src/chrome/TopBar.tsx`
  - **File:** `packages/terminal/src/chrome/TopBar.tsx`
  - **Components to use:** `Button` (shadcn), `Tabs`/`TabsList`/`TabsTrigger` (shadcn), `Badge` (shadcn), `Tooltip` (shadcn)
  - **Key changes:**
    - Props: typed with TypeScript interface
    - Layout tabs: read from `useLayoutStore` instead of props
    - P&L display: read from `useTradingStore`
    - Connection dot: read from `useConnectionStore`
    - IST clock: keep inline
    - All raw `<button>` elements -> `<Button>` from shadcn
  - **Expected:** TopBar renders identically with shadcn/ui components and Zustand data

- [ ] **3.2.2** Rewrite TickerBar.tsx with Jotai atoms
  - **Rename:** `packages/terminal/src/chrome/TickerBar.jsx` -> `packages/terminal/src/chrome/TickerBar.tsx`
  - **File:** `packages/terminal/src/chrome/TickerBar.tsx`
  - **Key changes:**
    - Replace `useDataBus("quote:NIFTY:NSE_INDEX")` with `useAtomValue(niftyAtom)` from Jotai
    - Use `indicesSummaryAtom` derived atom for all 4 indices
    - Type all props
  - **Expected:** TickerBar shows live index data from Jotai atoms

- [ ] **3.2.3** Rewrite WidgetPicker.tsx with shadcn/ui
  - **Rename:** `packages/terminal/src/chrome/WidgetPicker.jsx` -> `packages/terminal/src/chrome/WidgetPicker.tsx`
  - **File:** `packages/terminal/src/chrome/WidgetPicker.tsx`
  - **Components to use:** `Dialog`, `DialogContent`, `DialogHeader`, `DialogTitle` (shadcn), `Button` (shadcn), `Badge` (shadcn)
  - **Key changes:**
    - Read `dockviewApi` from `useLayoutStore` to add panels
    - Replace `onAddWidget` callback with direct Dockview API call:
      ```typescript
      const api = useLayoutStore.getState().dockviewApi;
      api?.addPanel({ id: widgetId, component: widgetId, title: widgetName });
      ```
    - Add GreeksWidget to the catalog (was missing — bug fix)
  - **Expected:** Widget picker opens as shadcn Dialog, adds Dockview panels

- [ ] **3.2.4** Rewrite ToolsDropdown.tsx with shadcn/ui
  - **Rename:** `packages/terminal/src/chrome/ToolsDropdown.jsx` -> `packages/terminal/src/chrome/ToolsDropdown.tsx`
  - **File:** `packages/terminal/src/chrome/ToolsDropdown.tsx`
  - **Components to use:** `DropdownMenu`, `DropdownMenuContent`, `DropdownMenuItem`, `DropdownMenuTrigger` (shadcn)
  - **Key changes:**
    - Typed props interface
    - shadcn DropdownMenu replaces absolute-positioned div
    - Show all 7 tools with icons and "Notify me" badge for unbuilt ones
  - **Expected:** Tools dropdown renders as shadcn DropdownMenu
  - **Commit:** `feat(terminal): chrome components in TSX + shadcn/ui — TopBar, TickerBar, WidgetPicker, ToolsDropdown`

### 3.3 Rewrite widgetFactory for Dockview

- [ ] **3.3.1** Rewrite widgetFactory.tsx for Dockview component registry
  - **Rename:** `packages/terminal/src/layout/widgetFactory.jsx` -> `packages/terminal/src/layout/widgetFactory.tsx`
  - **File:** `packages/terminal/src/layout/widgetFactory.tsx`
  - **Pre-check:** Use context7 MCP: `query-docs` for `dockview-react` — how components are registered via `components` prop
  - **Key changes:**
    - Instead of a factory function, Dockview uses a `components` record:
      ```typescript
      import { lazy, Suspense, Component } from "react";
      import type { IDockviewPanelProps } from "dockview-react";
      import type { WidgetMeta } from "@/types/widgets";

      // Lazy-load all widgets
      const DashboardWidget = lazy(() => import("@/widgets/trading/Dashboard/DashboardWidget"));
      const ScalperWidget = lazy(() => import("@/widgets/trading/Scalper/ScalperWidget"));
      // ... all 14 widgets ...

      // Error boundary
      class WidgetErrorBoundary extends Component<
        { name: string; children: React.ReactNode },
        { hasError: boolean }
      > {
        state = { hasError: false };
        static getDerivedStateFromError() { return { hasError: true }; }
        componentDidCatch(error: Error, info: React.ErrorInfo) {
          console.error(`Widget "${this.props.name}" crashed:`, error, info);
        }
        render() {
          if (this.state.hasError) return <WidgetError name={this.props.name} />;
          return this.props.children;
        }
      }

      function wrapWidget(name: string, Widget: React.LazyExoticComponent<any>) {
        return (props: IDockviewPanelProps) => (
          <Suspense fallback={<WidgetFallback />}>
            <WidgetErrorBoundary name={name}>
              <Widget {...props} />
            </WidgetErrorBoundary>
          </Suspense>
        );
      }

      export const widgetComponents: Record<string, React.FC<IDockviewPanelProps>> = {
        dashboard: wrapWidget("dashboard", DashboardWidget),
        scalper: wrapWidget("scalper", ScalperWidget),
        positions: wrapWidget("positions", PositionsWidget),
        orders: wrapWidget("orders", OrdersWidget),
        holdings: wrapWidget("holdings", HoldingsWidget),
        tradebook: wrapWidget("tradebook", TradeBookWidget),
        orderpad: wrapWidget("orderpad", OrderPadWidget),
        chart: wrapWidget("chart", ChartWidget),
        optionchain: wrapWidget("optionchain", OptionChainWidget),
        oichart: wrapWidget("oichart", OIChartWidget),
        straddle: wrapWidget("straddle", StraddleWidget),
        depth: wrapWidget("depth", DepthWidget),
        greeks: wrapWidget("greeks", GreeksWidget), // BUG FIX: was missing from factory
        watchlist: wrapWidget("watchlist", WatchlistWidget),
      };

      export const widgetCatalog: WidgetMeta[] = [
        { id: "dashboard", name: "Dashboard", icon: "LayoutDashboard", category: "Trading" },
        // ... all 14 entries, including greeks which was missing ...
        { id: "greeks", name: "Greeks", icon: "Calculator", category: "Analysis" },
      ];
      ```
  - **Expected:** All 14 widgets registered in Dockview component map (including greeks)

### 3.4 Convert layout presets to Dockview format

- [ ] **3.4.1** Convert 7 layout presets from FlexLayout JSON to Dockview serialization
  - **Pre-check:** Use context7 MCP: `query-docs` for `dockview-react` — `DockviewApi.fromJSON()` format, panel serialization schema
  - **Files to update:**
    - `packages/terminal/src/layout/presets/minimal.json`
    - `packages/terminal/src/layout/presets/scalper-zone.json`
    - `packages/terminal/src/layout/presets/blank.json`
    - `packages/terminal/src/layout/presets/analysis-desk.json`
    - `packages/terminal/src/layout/presets/volatility-trading.json`
    - `packages/terminal/src/layout/presets/market-watch.json`
    - `packages/terminal/src/layout/presets/risk-monitor.json`
  - **Dockview JSON format (example for minimal):**
    ```json
    {
      "grid": {
        "root": {
          "type": "branch",
          "data": [
            {
              "type": "leaf",
              "data": {
                "views": ["dashboard"],
                "activeView": "dashboard",
                "id": "group-1"
              },
              "size": 1
            }
          ],
          "size": 1
        },
        "width": 1920,
        "height": 1080,
        "orientation": "HORIZONTAL"
      },
      "panels": {
        "dashboard": {
          "id": "dashboard",
          "contentComponent": "dashboard",
          "title": "Dashboard"
        }
      },
      "activeGroup": "group-1"
    }
    ```
  - **Expected:** All 7 presets use Dockview serialization format

- [ ] **3.4.2** Delete old LayoutManager.jsx
  - **Command:**
    ```bash
    rm C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal/src/layout/LayoutManager.jsx
    ```
  - **Expected:** Old FlexLayout manager removed (replaced by DockviewReact in App.tsx)

- [ ] **3.4.3** Delete old layoutStore.js
  - **Command:**
    ```bash
    rm C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal/src/layout/layoutStore.js
    ```
  - **Expected:** Old localStorage layout store removed (replaced by Zustand layoutStore)

- [ ] **3.4.4** Verify shell renders
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm run dev
    ```
  - **Verify with Playwright:** Take screenshot, confirm:
    - TopBar with layout tabs, P&L, connection dot, IST clock
    - TickerBar with 4 indices
    - Dockview canvas with at least one panel
    - No console errors
  - **Commit:** `feat(terminal): Dockview layout with 7 presets, widget factory with all 14 widgets`

### 3.5 Migrate useGlobalKeys to TypeScript

- [ ] **3.5.1** Rename and type useGlobalKeys
  - **Rename:** `packages/terminal/src/hooks/useGlobalKeys.js` -> `packages/terminal/src/hooks/useGlobalKeys.ts`
  - **Edit:** Add TypeScript interfaces:
    ```typescript
    interface GlobalKeyHandlers {
      onEscape?: () => void;
      onCommandPalette?: () => void;
    }

    export default function useGlobalKeys({ onEscape, onCommandPalette }: GlobalKeyHandlers): void {
      // ... same logic, typed ...
    }
    ```
  - **Expected:** Hook compiles with `tsc --noEmit`
  - **Commit:** `refactor(terminal): migrate useGlobalKeys to TypeScript`

---

## Phase 4: Widget Migration (Days 9-12)

### Batch 1: Trading Widgets (Days 9-10)

Each widget follows the same migration pattern:
1. Rename `.jsx` to `.tsx`
2. Add TypeScript types for props and state
3. Replace `useDataBus()` with Zustand/TanStack Query/Jotai hooks
4. Replace raw HTML `<button>`, `<input>`, `<select>` with shadcn/ui components
5. Add `IDockviewPanelProps` as base props type
6. Verify renders in Dockview panel

- [ ] **4.1.1** Migrate DashboardWidget
  - **Rename:** `src/widgets/trading/Dashboard/DashboardWidget.jsx` -> `.tsx`
  - **Replace:** `useDataBus("positions")` -> `usePositions()` from TanStack Query
  - **Replace:** `useDataBus("funds")` -> `useFunds()` from TanStack Query
  - **Replace:** `useDataBus("quote:*")` -> `useAtomValue(tickAtomFamily(key))` from Jotai
  - **Components:** Raw stat cards -> shadcn `Card`, `Badge`
  - **Verify:** Widget renders in Dockview panel, shows live data

- [ ] **4.1.2** Migrate ScalperWidget
  - **Rename:** `src/widgets/trading/Scalper/ScalperWidget.jsx` -> `.tsx`
  - **Replace:** DataBus subscriptions -> Jotai atoms for real-time prices
  - **Replace:** Order buttons -> shadcn `Button` with variant="destructive" for SELL
  - **Components:** Price displays -> monospace font, shadcn `Badge` for P&L
  - **Verify:** 3-panel layout (CE/Spot/PE) renders, order buttons functional

- [ ] **4.1.3** Migrate PositionsWidget
  - **Rename:** `src/widgets/trading/Positions/PositionsWidget.jsx` -> `.tsx`
  - **Replace:** `useDataBus("positions")` -> `usePositions()` from TanStack Query
  - **Components:** Table -> TanStack Table + shadcn `Table` components
  - **Verify:** Position table renders with live P&L updates

- [ ] **4.1.4** Migrate OrdersWidget
  - **Rename:** `src/widgets/trading/Orders/OrdersWidget.jsx` -> `.tsx`
  - **Replace:** `useDataBus("orders")` -> `useOrders()` from TanStack Query
  - **Components:** Table -> TanStack Table + shadcn `Table`
  - **Verify:** Order book table renders, cancel button works

- [ ] **4.1.5** Migrate HoldingsWidget
  - **Rename:** `src/widgets/trading/Holdings/HoldingsWidget.jsx` -> `.tsx`
  - **Replace:** `useDataBus("holdings")` -> `useHoldings()` from TanStack Query
  - **Components:** Table -> TanStack Table + shadcn `Table`
  - **Note:** Preserve error suppression for brokers that don't support holdings endpoint
  - **Verify:** Holdings table renders (or shows "not supported" gracefully)

- [ ] **4.1.6** Migrate TradeBookWidget
  - **Rename:** `src/widgets/trading/TradeBook/TradeBookWidget.jsx` -> `.tsx`
  - **Replace:** `useDataBus("tradebook")` -> `useTradebook()` from TanStack Query
  - **Components:** Table -> TanStack Table + shadcn `Table`
  - **Verify:** Trade history table renders

- [ ] **4.1.7** Migrate OrderPadWidget
  - **Rename:** `src/widgets/trading/OrderPad/OrderPadWidget.jsx` -> `.tsx`
  - **Components:** All form inputs -> `react-hook-form` + `zod` + shadcn `Input`, `Select`, `Label`, `Button`
  - **Schema:** Create zod schema for order validation:
    ```typescript
    const orderSchema = z.object({
      symbol: z.string().min(1),
      exchange: z.enum(["NSE", "NFO", "BSE", "MCX"]),
      action: z.enum(["BUY", "SELL"]),
      quantity: z.number().positive().int(),
      orderType: z.enum(["MARKET", "LIMIT", "SL", "SL-M"]),
      product: z.enum(["MIS", "CNC", "NRML"]),
      price: z.number().optional(),
      triggerPrice: z.number().optional(),
    });
    ```
  - **Verify:** Order form validates, places orders via API
  - **Commit:** `feat(terminal): migrate 7 trading widgets to TSX + shadcn/ui + TanStack Query`

### Batch 2: Analysis Widgets (Days 10-11)

- [ ] **4.2.1** Migrate ChartWidget
  - **Rename:** `src/widgets/analysis/Chart/ChartWidget.jsx` -> `.tsx`
  - **Also rename:** `src/components/Chart.jsx` -> `src/components/Chart.tsx`
  - **Replace:** `useDataBus("history:*")` -> TanStack Query for history + Jotai for live ticks
  - **Keep:** Lightweight Charts v5 integration (already correct version)
  - **Components:** Interval selector -> shadcn `Select`, symbol search -> shadcn `Command`
  - **Verify:** Chart renders candles, updates with live ticks

- [ ] **4.2.2** Migrate OptionChainWidget with Glide Data Grid
  - **Rename:** `src/widgets/analysis/OptionChain/OptionChainWidget.jsx` -> `.tsx`
  - **Pre-check:** Use context7 MCP: `query-docs` for `@glideapps/glide-data-grid` — `DataEditor`, `GridColumn`, `GridCell` types, `getCellContent` callback
  - **Major change:** Replace HTML table with Glide Data Grid for 100K+ update/sec performance
  - **Replace:** `useDataBus("optionchain:*")` -> `useOptionChain(symbol, exchange, expiry)`
  - **Columns:** Strike, CE LTP, CE OI, CE Volume, CE IV, CE Delta | Strike Price | PE Delta, PE IV, PE Volume, PE OI, PE LTP
  - **Verify:** Option chain renders with Glide Data Grid, scrolls smoothly with many strikes

- [ ] **4.2.3** Migrate OIChartWidget
  - **Rename:** `src/widgets/analysis/OIChart/OIChartWidget.jsx` -> `.tsx`
  - **Replace:** `useDataBus("optionchain:*")` -> `useOptionChain()` from TanStack Query
  - **Components:** Use Lightweight Charts for horizontal bar chart, shadcn `Badge` for PCR
  - **Verify:** OI bars render, PCR updates

- [ ] **4.2.4** Migrate StraddleWidget
  - **Rename:** `src/widgets/analysis/Straddle/StraddleWidget.jsx` -> `.tsx`
  - **Replace:** DataBus -> Jotai atoms for live straddle prices
  - **Components:** Price cards -> shadcn `Card`, overlays -> shadcn `Badge`
  - **Verify:** ATM straddle price displays with live updates

- [ ] **4.2.5** Migrate DepthWidget
  - **Rename:** `src/widgets/analysis/Depth/DepthWidget.jsx` -> `.tsx`
  - **Replace:** DataBus -> Jotai atoms (depth mode subscription)
  - **Components:** Bid/ask table -> shadcn `Table`, depth bars -> CSS gradients
  - **Verify:** 5-level bid/ask displays

- [ ] **4.2.6** Migrate GreeksWidget + register in factory
  - **Rename:** `src/widgets/analysis/Greeks/GreeksWidget.jsx` -> `.tsx`
  - **Replace:** DataBus -> TanStack Query for option greeks
  - **Components:** Greek values -> shadcn `Card` with monospace numbers
  - **BUG FIX:** Register GreeksWidget in widgetFactory (was missing in v1)
  - **Verify:** Greeks display (Delta, Gamma, Theta, Vega) with live values
  - **Commit:** `feat(terminal): migrate 6 analysis widgets to TSX — Chart, OptionChain (Glide), OI, Straddle, Depth, Greeks`

### Batch 3: Utility + Remaining (Days 11-12)

- [ ] **4.3.1** Migrate WatchlistWidget
  - **Rename:** `src/widgets/utility/Watchlist/WatchlistWidget.jsx` -> `.tsx`
  - **Replace:** DataBus -> Jotai atoms for live quotes, TanStack Query for search
  - **Components:** Symbol list -> shadcn `Table`, search -> shadcn `Command`, add button -> shadcn `Button`
  - **Verify:** Watchlist shows live prices, search works

- [ ] **4.3.2** Migrate all 7 tool stubs to TSX
  - **Files to rename (all `.jsx` -> `.tsx`):**
    - `src/tools/Settings/SettingsTool.jsx` -> `.tsx`
    - `src/tools/BacktestLab/BacktestLabTool.jsx` -> `.tsx`
    - `src/tools/TradeJournal/TradeJournalTool.jsx` -> `.tsx`
    - `src/tools/StrategyBuilder/StrategyBuilderTool.jsx` -> `.tsx`
    - `src/tools/PnLDashboard/PnLDashboardTool.jsx` -> `.tsx`
    - `src/tools/MarketIntelligence/MarketIntelligenceTool.jsx` -> `.tsx`
    - `src/tools/FlowBuilder/FlowBuilderTool.jsx` -> `.tsx`
  - **For each:** Add props interface `{ onClose: () => void }`, type the component
  - **For Settings:** Wire to `useSettingsStore` instead of any direct state
  - **Expected:** All tools compile with TypeScript
  - **Commit:** `feat(terminal): migrate utility widgets + tool stubs to TSX`

### 4.4 Delete old useWebSocket.js and rename

- [ ] **4.4.1** Migrate useWebSocket hook to TypeScript
  - **Rename:** `src/hooks/useWebSocket.js` -> `src/hooks/useWebSocket.ts`
  - **Edit:** Replace DOM event-based approach with callback-based WebSocketService:
    ```typescript
    import { useEffect, useRef, useState } from "react";
    import { getWsService } from "@/services/websocket";
    import { useConnectionStore } from "@/stores/connectionStore";
    import type { WsTick, WsMode, WsInstrument } from "@/types/api";

    export function useWebSocket(instruments: WsInstrument[] = [], mode: WsMode = "ltp") {
      const [ticks, setTicks] = useState<Record<string, WsTick>>({});
      const connected = useConnectionStore((s) => s.wsConnected);
      const prevRef = useRef<WsInstrument[]>([]);

      useEffect(() => {
        const ws = getWsService();
        if (!ws) return;

        const unsub = ws.onTick((tick: WsTick) => {
          const key = `${tick.exchange}:${tick.symbol}`;
          setTicks((prev) => ({ ...prev, [key]: tick }));
        });

        return unsub;
      }, []);

      useEffect(() => {
        const ws = getWsService();
        if (!ws || instruments.length === 0) return;

        const toAdd = instruments.filter(
          (i) => !prevRef.current.some((p) => p.symbol === i.symbol && p.exchange === i.exchange)
        );
        const toRemove = prevRef.current.filter(
          (p) => !instruments.some((i) => i.symbol === p.symbol && i.exchange === p.exchange)
        );
        if (toRemove.length) ws.unsubscribe(toRemove, mode);
        if (toAdd.length) ws.subscribe(toAdd, mode);
        prevRef.current = instruments;

        return () => {
          if (prevRef.current.length) ws.unsubscribe(prevRef.current, mode);
          prevRef.current = [];
        };
      }, [JSON.stringify(instruments), mode]);

      return { ticks, connected };
    }
    ```
  - **Expected:** Hook compiles, uses new WebSocketService
  - **Commit:** `refactor(terminal): migrate useWebSocket hook to TypeScript`

### 4.5 Final JS cleanup

- [ ] **4.5.1** Verify no `.js` or `.jsx` files remain in `src/`
  - **Command:**
    ```bash
    find C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal/src -name "*.js" -o -name "*.jsx" | head -20
    ```
  - **Expected:** No files found — all source files are `.ts` or `.tsx`
  - **If any remain:** Rename and add minimal types to compile

- [ ] **4.5.2** Run full TypeScript check
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npx tsc --noEmit
    ```
  - **Expected:** Zero type errors
  - **If errors:** Fix each one — no `any` types allowed (use `unknown` and type narrow instead)
  - **Commit:** `chore(terminal): zero JS files remaining — full TypeScript migration complete`

---

## Phase 5: Verification + Documentation (Days 13-14)

### 5.1 Build verification

- [ ] **5.1.1** TypeScript strict mode check
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npx tsc --noEmit
    ```
  - **Expected:** `0 errors`

- [ ] **5.1.2** Vite production build
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npm run build
    ```
  - **Expected:** Build succeeds with 0 warnings, output in `dist/`

- [ ] **5.1.3** Vitest test suite
  - **Command:**
    ```bash
    cd C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal
    npx vitest run
    ```
  - **Expected:** All tests pass (stores + rateLimiter + dockview smoke + query hooks)

### 5.2 Visual verification with Playwright

- [ ] **5.2.1** Screenshot every widget in Dockview
  - **Pre-check:** Use Playwright MCP browser tools
  - **Steps:**
    1. `browser_navigate` to `http://localhost:5173`
    2. `browser_take_screenshot` — full page
    3. Open widget picker, add each of the 14 widgets one by one
    4. `browser_take_screenshot` after each widget is added
    5. Verify no visual regressions
  - **Expected:** All 14 widgets render in Dockview panels without errors

- [ ] **5.2.2** Verify Dockview panel operations
  - **Steps:**
    1. Drag a panel to create a split
    2. Close a panel
    3. Float a panel (popout)
    4. Switch layout tabs
  - **Expected:** All Dockview operations work correctly

### 5.3 Documentation cleanup (35 files)

#### Files to REWRITE (5)

- [ ] **5.3.1** Rewrite `PLAN.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/PLAN.md`
  - **Why:** Completely stale — references F-key modules, separate React apps, items already done
  - **New content:** v2 roadmap based on the approved design spec (Weeks 3-6 items)

- [ ] **5.3.2** Rewrite `README.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/README.md`
  - **Why:** References 662 tests, 3 React apps, TOTP, wrong architecture diagram
  - **New content:** Accurate architecture (single app, Dockview, TS), correct test count, no TOTP

- [ ] **5.3.3** Rewrite `packages/terminal/CLAUDE.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/packages/terminal/CLAUDE.md`
  - **Why:** References port 3001, F1-F9 modules, TradePulse v0.3, branch strategy — all wrong
  - **New content:** Accurate terminal architecture (Dockview, shadcn/ui, Zustand/Jotai/TanStack Query)

- [ ] **5.3.4** Rewrite `docs/ARCHITECTURE.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/ARCHITECTURE.md`
  - **Why:** subtree->submodule migration, single React app, Dockview, new state arch
  - **New content:** Accurate system diagram matching the v2 spec

- [ ] **5.3.5** Rewrite `docs/references/TOOLS_AND_DEPS.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/references/TOOLS_AND_DEPS.md`
  - **Why:** Missing all new deps (dockview, shadcn, zustand, jotai, tanstack, glide-data-grid)
  - **New content:** Complete dependency list with versions and justifications

#### Files to UPDATE (18)

- [ ] **5.3.6** Update `CLAUDE.md` (root)
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/CLAUDE.md`
  - **What:** Widget arch description, 11 packages not 13 (dashboard/backtest deleted), correct test count, 4 .env vars

- [ ] **5.3.7** Update `AGENTS.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/AGENTS.md`
  - **What:** Remove any F-key/TOTP references

- [ ] **5.3.8** Update `CHANGELOG.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/CHANGELOG.md`
  - **What:** Remove TOTP claims, add v2 migration entry

- [ ] **5.3.9** Update `CONTRIBUTING.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/CONTRIBUTING.md`
  - **What:** Test count update, canonical DEVLOG format, TypeScript requirement

- [ ] **5.3.10** Update `REPOS.md` (root)
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/REPOS.md`
  - **What:** Sync with `docs/references/REPOS.md`

- [ ] **5.3.11** Update `docs/OPERATIONS_GUIDE.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/OPERATIONS_GUIDE.md`
  - **What:** Check for stale references, update any commands

- [ ] **5.3.12** Update `docs/SEBI_COMPLIANCE.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/SEBI_COMPLIANCE.md`
  - **What:** Remove TOTP cron ref, add April 2026 STT rates (0.05% futures, 0.15% options)

- [ ] **5.3.13** Update `docs/references/REPOS.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/references/REPOS.md`
  - **What:** Sync with root REPOS.md

- [ ] **5.3.14** Update `docs/references/OPENALGO_API.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/references/OPENALGO_API.md`
  - **What:** Verify accuracy against current OpenAlgo v2.0.0.1 API

- [ ] **5.3.15** Update `docs/machine-setup/QUICKSTART.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/machine-setup/QUICKSTART.md`
  - **What:** Remove F1-F8 references, update for Dockview/TS, TypeScript build step

- [ ] **5.3.16** Update `docs/setup/linux.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/setup/linux.md`
  - **What:** Remove old module references

- [ ] **5.3.17** Update `docs/setup/macos.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/setup/macos.md`
  - **What:** Remove old module references

- [ ] **5.3.18** Update `docs/setup/windows.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/setup/windows.md`
  - **What:** Fix port 3000 reference -> 5173

- [ ] **5.3.19** Update `docs/setup/raspberry-pi.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/setup/raspberry-pi.md`
  - **What:** Remove old module references

- [ ] **5.3.20** Update `infra/cron/README.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/infra/cron/README.md`
  - **What:** Remove TOTP login_job reference

- [ ] **5.3.21** Update `flint.toml`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/flint.toml`
  - **What:** Remove TOTP from automation description

- [ ] **5.3.22** Update `.env.example`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/.env.example`
  - **What:** Verify 4 vars only, all blank (should already be done in 1.5.1)

- [ ] **5.3.23** Update `.github/ISSUE_TEMPLATE/*.md`
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/.github/ISSUE_TEMPLATE/*.md`
  - **What:** Ensure templates reference TypeScript, Dockview, current architecture

#### Files to CHECK (10 package READMEs)

- [ ] **5.3.24** Check and update package READMEs for TOTP/stale references
  - **Files:**
    - `packages/core/README.md` — check for TOTP references
    - `packages/engine/README.md` — check for stale module references
    - `packages/data/README.md` — check for accuracy
    - `packages/historical/README.md` — check for accuracy
    - `packages/screener/README.md` — check for accuracy
    - `packages/backtest-engine/README.md` — check for accuracy
    - `packages/ai/README.md` — check for accuracy
    - `packages/integration/README.md` — check for accuracy
    - `packages/automation/README.md` — check for TOTP reference (known)
    - `packages/ditto/README.md` — check for accuracy
  - **Command to find TOTP references:**
    ```bash
    grep -rl "TOTP\|totp\|auto.login\|auto_login" C:/Users/navan/Documents/GitHub/FlintTrade/packages/*/README.md
    ```
  - **Expected:** All TOTP references removed

#### Files to ARCHIVE (4)

- [ ] **5.3.25** Archive historical documents
  - **Commands:**
    ```bash
    mkdir -p C:/Users/navan/Documents/GitHub/FlintTrade/docs/references/historical
    mv C:/Users/navan/Documents/GitHub/FlintTrade/RESTRUCTURE.md C:/Users/navan/Documents/GitHub/FlintTrade/docs/references/historical/RESTRUCTURE_V1.md
    mv C:/Users/navan/Documents/GitHub/FlintTrade/docs/THE_PLAN.md C:/Users/navan/Documents/GitHub/FlintTrade/docs/references/historical/THE_PLAN_V1.md
    mv C:/Users/navan/Documents/GitHub/FlintTrade/docs/references/MASTER_BLUEPRINT.md C:/Users/navan/Documents/GitHub/FlintTrade/docs/references/historical/MASTER_BLUEPRINT_V1.md
    mv C:/Users/navan/Documents/GitHub/FlintTrade/docs/superpowers/plans/2026-03-18-phase1-flexlayout-foundation.md C:/Users/navan/Documents/GitHub/FlintTrade/docs/references/historical/2026-03-18-phase1-flexlayout-foundation.md
    ```
  - **Expected:** 4 files moved to `docs/references/historical/`

#### Files to DELETE (3)

- [ ] **5.3.26** Delete temporary planning files
  - **Commands:**
    ```bash
    rm C:/Users/navan/Documents/GitHub/FlintTrade/findings.md
    rm C:/Users/navan/Documents/GitHub/FlintTrade/task_plan.md
    rm C:/Users/navan/Documents/GitHub/FlintTrade/progress.md
    ```
  - **Expected:** 3 temp files removed

#### Files to MARK as absorbed (1)

- [ ] **5.3.27** Mark ENHANCEMENT_BLUEPRINT.md as absorbed
  - **File:** `C:/Users/navan/Documents/GitHub/FlintTrade/docs/references/ENHANCEMENT_BLUEPRINT.md`
  - **Edit:** Add header:
    ```markdown
    > **Status:** Absorbed into v2 spec (2026-03-19-flinttrade-v2-foundation-design.md).
    > Kept for reference — AlgoMirror patterns, Kotak Neo details.
    ```
  - **Expected:** Document marked as superseded
  - **Commit:** `docs: rewrite 5 docs, update 18, archive 4, delete 3, check 10 — doc cleanup complete`

### 5.4 Remove all TOTP references

- [ ] **5.4.1** Find and remove all TOTP references across codebase
  - **Command to find:**
    ```bash
    grep -rl "TOTP\|totp\|auto.login\|auto_login\|login_job" C:/Users/navan/Documents/GitHub/FlintTrade/ --include="*.md" --include="*.py" --include="*.ts" --include="*.tsx" --include="*.toml" --include="*.yml" --exclude-dir=infra --exclude-dir=node_modules --exclude-dir=.git
    ```
  - **Expected:** List of files with TOTP references
  - **Action:** Edit each file to remove TOTP-related lines/sections
  - **Verify:** Re-run grep, zero matches
  - **Commit:** `chore: remove all TOTP references — OpenAlgo handles broker auth`

### 5.5 CI/CD update for TypeScript

- [ ] **5.5.1** Update GitHub Actions workflow for TypeScript
  - **File:** Check `.github/workflows/` for existing CI config
  - **Edit:** Add `tsc --noEmit` step before build:
    ```yaml
    - name: Type check
      working-directory: packages/terminal
      run: npx tsc --noEmit

    - name: Build
      working-directory: packages/terminal
      run: npm run build

    - name: Test
      working-directory: packages/terminal
      run: npx vitest run
    ```
  - **Expected:** CI pipeline includes TypeScript checking
  - **Commit:** `ci: add tsc --noEmit step to CI pipeline`

### 5.6 Final verification checklist

- [ ] **5.6.1** TypeScript strict mode — zero errors
  - **Command:** `cd packages/terminal && npx tsc --noEmit`
  - **Expected:** `0 errors`

- [ ] **5.6.2** No `any` types in source code
  - **Command:** `grep -r ": any\|as any" packages/terminal/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".test."`
  - **Expected:** Zero matches (test files may use `as any` for mocking — that is acceptable)

- [ ] **5.6.3** Vite build passes with zero warnings
  - **Command:** `cd packages/terminal && npm run build`
  - **Expected:** Clean build output

- [ ] **5.6.4** All tests pass
  - **Command:** `cd packages/terminal && npx vitest run`
  - **Expected:** All tests pass

- [ ] **5.6.5** All 14 widgets render in Dockview
  - **Verify:** Each widget can be added via WidgetPicker and renders content

- [ ] **5.6.6** No `.js` or `.jsx` files in `src/`
  - **Command:** `find packages/terminal/src -name "*.js" -o -name "*.jsx"`
  - **Expected:** Zero results

- [ ] **5.6.7** No FlexLayout references in code
  - **Command:** `grep -r "flexlayout\|FlexLayout\|flex.layout" packages/terminal/src/`
  - **Expected:** Zero results

- [ ] **5.6.8** No DataBus references in code
  - **Command:** `grep -r "dataBus\|DataBus\|useDataBus\|dataConnector" packages/terminal/src/`
  - **Expected:** Zero results

- [ ] **5.6.9** No TOTP references anywhere in repo (excluding submodules)
  - **Command:** `grep -rl "TOTP\|totp" . --exclude-dir=infra --exclude-dir=node_modules --exclude-dir=.git`
  - **Expected:** Zero results (or only this plan file and the design spec mentioning removal)

- [ ] **5.6.10** shadcn/ui components used everywhere — no raw HTML controls
  - **Command:** `grep -r "<button\|<input\|<select" packages/terminal/src/ --include="*.tsx" | grep -v "components/ui/" | grep -v ".test."`
  - **Expected:** Zero matches (all raw HTML replaced with shadcn/ui)

- [ ] **5.6.11** Documentation contradictions resolved
  - **Verify:** Root CLAUDE.md mentions 11 packages (not 13), correct test count, TypeScript, Dockview

- [ ] **5.6.12** Final commit and tag
  - **Commit:** `feat(terminal): v2 Foundation Sprint complete — TypeScript, Dockview, Zustand/Jotai/TanStack, shadcn/ui`
  - **Note:** Do NOT tag yet — that happens after live testing in Weeks 3-6

---

## Summary of Deliverables

| Category | Count | Details |
|----------|-------|---------|
| Files converted to TS/TSX | 39 | All source files in `packages/terminal/src/` |
| Files deleted | 7 | DataBus (3), dataBus.test (1), FlexLayout LayoutManager (1), old layoutStore (1), old useDataBus (1) |
| Files created (new) | ~25 | Types (3), Stores (4+tests), Atoms (1+test), Hooks (6+tests), Providers (1), vite-env.d.ts, tsconfig files (2), shadcn components (~15) |
| Layout presets converted | 7 | FlexLayout JSON -> Dockview serialization |
| Stub packages deleted | 2 | `packages/dashboard/`, `packages/backtest/` |
| Bugs fixed | 3 | ping GET, closePosition strategy, optionchain expiry |
| Docs rewritten | 5 | PLAN.md, README.md, terminal/CLAUDE.md, ARCHITECTURE.md, TOOLS_AND_DEPS.md |
| Docs updated | 18 | See Phase 5.3 list |
| Docs archived | 4 | RESTRUCTURE, THE_PLAN, MASTER_BLUEPRINT, phase1 plan |
| Docs deleted | 3 | findings.md, task_plan.md, progress.md |
| Docs checked | 10 | All package READMEs |
| TOTP references removed | 9+ | All files across repo |

## Estimated Timeline

| Phase | Days | Tasks | Key Risk |
|-------|------|-------|----------|
| Phase 1: Foundation | 1-3 | 20 tasks | shadcn/ui + Tailwind v4 init issues |
| Phase 2: State | 4-6 | 18 tasks | TanStack Query polling intervals tuning |
| Phase 3: Shell | 7-8 | 12 tasks | Dockview serialization format learning curve |
| Phase 4: Widgets | 9-12 | 16 tasks | Glide Data Grid for OptionChain complexity |
| Phase 5: Verify | 13-14 | 30 tasks | Doc cleanup volume (35 files) |
| **Total** | **14** | **~96 tasks** | |

## Rules for Execution

1. **TDD:** Write test first, see it fail, implement, see it pass
2. **context7 MCP:** Look up library APIs before writing any integration code
3. **REPO_FEATURE_MAP.md:** Check before writing new code — absorb patterns from cloned repos
4. **Commit frequently:** After each numbered task group (roughly every 2-5 tasks)
5. **No `any` types:** Use `unknown` + type narrowing, never `any`
6. **shadcn/ui only:** No raw `<button>`, `<input>`, `<select>`, `<dialog>` in source code
7. **Dockview panels:** Every widget is a Dockview panel — no fixed layouts
8. **One data path:** Jotai for WS ticks, TanStack Query for REST, Zustand for derived/UI — never duplicate
9. **Playwright verification:** Screenshot after each major visual change
10. **Live OpenAlgo test:** After Phase 4, test with broker sandbox during market hours
