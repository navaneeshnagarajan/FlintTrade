# FlintTrade Onboarding + Navigation Architecture — Phase 1B Design Spec

**Date:** 2026-03-21
**Scope:** Welcome screen, setup wizard enhancement, global navigation, workspace management, daily welcome, interactive tour
**Depends on:** Phase 1A (design tokens — complete)

---

## Problem

FlintTrade has no onboarding flow, no global navigation between routes, no way to switch personas after setup, and no daily welcome. Users land directly on `/terminal` with no context. The three personas (Learn/Invest/Trade) are isolated islands — switching requires typing URLs.

## Goal

Create a cohesive first-time and returning-user experience that showcases FlintTrade's 6 unique pillars (Learn · Invest · Trade · Backtest · Automate · AI), provides smart daily context, and allows fluid workspace management.

---

## 1. Route Architecture (Updated)

### Current routes
```
/ → redirect to /terminal
/setup → SetupRoute
/terminal → TerminalRoute
/invest → InvestRoute
/learn → LearnRoute
```

### New routes
```
/ → Smart redirect (first-time → /welcome, returning → last route)
/welcome → WelcomeRoute (cinematic, first-time only)
/explore → ExploreRoute (try-before-setup, sample data)
/setup → SetupRoute (enhanced wizard)
/terminal → TerminalRoute (with global nav)
/invest → InvestRoute (with global nav)
/learn → LearnRoute (with global nav)
```

### Smart redirect logic (in main.tsx)

Uses Zustand's persisted store envelope (not raw localStorage):
```typescript
function getInitialRoute(): string {
  const raw = localStorage.getItem("flinttrade:settings");
  if (!raw) return "/welcome";
  try {
    const envelope = JSON.parse(raw);
    const persona = envelope?.state?.persona;
    if (!persona) return "/welcome";
    if (persona === "investor") return "/invest";
    if (persona === "beginner") return "/learn";
    return "/terminal";
  } catch { return "/welcome"; }
}
```

### Route layout split

Two layout groups in the router:
- **Flow routes** (`/welcome`, `/explore`, `/setup`): Full-page, no TopBar, no TickerBar
- **App routes** (`/terminal`, `/invest`, `/learn`): Shared `AppLayout` with TopBar (route tabs + workspace tabs) + TickerBar

```
<BrowserRouter>
  <Route path="/" element={<RootLayout />}>
    <!-- Flow routes: full-page, no chrome -->
    <Route path="welcome" element={<WelcomeRoute />} />
    <Route path="explore" element={<ExploreRoute />} />
    <Route path="setup" element={<SetupRoute />} />

    <!-- App routes: shared chrome (TopBar + TickerBar) -->
    <Route element={<AppLayout />}>
      <Route path="terminal" element={<TerminalRoute />} />
      <Route path="invest" element={<InvestRoute />} />
      <Route path="learn" element={<LearnRoute />} />
    </Route>
  </Route>
</BrowserRouter>
```

New file: `src/routes/AppLayout.tsx` — renders TopBar + TickerBar + `<Outlet />`. This extracts TopBar from TerminalRoute so all app routes share it.

**WebSocket bridge:** `useWsBridge()` stays in `RootLayout` but no-ops when `connectionStore.apiKey` is empty (already handles this — the `if (!wsUrl) return;` guard on line 27 of useWsBridge.ts).

---

## 2. Cinematic Welcome Screen (`/welcome`)

**Shows:** First-time only (no settings in localStorage).

### Sequence (pure CSS @keyframes + React state transitions — NO Framer Motion)

1. **Dark void** (0-1s) — Pure black screen
2. **Spark ignition** (1-2s) — Small green spark (#22c55e) appears center, grows with glow
3. **Logo formation** (2-3s) — Spark becomes the FlintTrade "F" icon, wordmark types out
4. **Tagline** (3-3.5s) — "Learn · Invest · Trade" fades in below
5. **6 Pillars reveal** (3.5-6s) — Cards slide up from bottom, staggered 200ms each:

| Pillar | Lucide Icon | Headline | Subtext |
|--------|-------------|----------|---------|
| Learn | `BookOpen` | Learn | Market basics to advanced strategies — built into the terminal |
| Invest | `PiggyBank` | Invest | Mutual funds, SIPs, portfolio tracking, net worth |
| Trade | `CandlestickChart` | Trade | F&O scalping, options analysis, real-time execution |
| Backtest | `Zap` | Backtest | Rust-powered tick-level backtesting — no broker has this |
| Automate | `Workflow` | Automate | 54-node flow builder, cron scheduler, Telegram kill switch |
| AI | `Bot` | AI | Local LLM advisor, RAG analysis, sentiment signals |

6. **CTA** (6-7s) — Two buttons fade in:
   - **"Explore First"** → `/explore`
   - **"Set Up Workspace"** → `/setup`
   - **"Skip"** label visible from the start (top-right corner)

7. **Skip** — Click "Skip" text, press Enter/Space/Escape, or click anywhere to jump to CTA instantly

### Technical
- New file: `src/routes/WelcomeRoute.tsx`
- Pure CSS @keyframes — no animation libraries (Framer Motion NOT used)
- `will-change: transform, opacity` for GPU acceleration
- Lucide icons (already installed), not emoji
- Responsive via clamp()
- Total duration shortened to ~7s (not 10s)

---

## 3. Explore Mode (`/explore`)

**Purpose:** Try the terminal without setting up a broker. Ubuntu "try before install" concept.

### What they see
- Full terminal workspace (Dockview) with a sample layout
- TopBar with route tabs (Learn / Invest / Trade) — navigable
- TickerBar showing **bundled snapshot data** from `src/data/sample-snapshot.json`
- Dashboard with sample index values from snapshot
- Chart with bundled historical candle data (NIFTY 5-min, ~500 bars)
- Option chain with static snapshot data
- Persistent banner: "Exploring with sample data. [Set up your workspace →] to connect your broker."

### What they CAN'T do
- Place orders (buttons disabled, tooltip: "Connect broker first")
- See live ticks (WebSocket not connected)
- Access real positions/orders/holdings

### Technical
- New file: `src/routes/ExploreRoute.tsx`
- New file: `src/data/sample-snapshot.json` (bundled market snapshot — ALL explore data comes from this file, no API calls)
- Add `demo` field to `ConnectionStore` interface:
```typescript
interface ConnectionStore {
  // existing fields...
  demo: boolean;
  setDemo: (v: boolean) => void;
}
```
- When `demo === true`:
  - `useWsBridge` skips WebSocket connection (already handled by empty apiKey guard)
  - API hooks (`usePositions`, `useOrders`, etc.) return empty arrays without fetching
  - Chart/OptionChain hooks read from sample-snapshot.json instead of API
  - Order mutation buttons are disabled
- Banner: `src/components/explore/ExploreBanner.tsx`

---

## 4. Setup Wizard Enhancement

### Keep existing
- Quick (2 steps) / Guided (5 steps) / Advanced (7 steps) modes
- Connection step, experience level picker

### Add: Persona × Interest Matrix

Replace single "Persona" picker with two-axis selection:

**Axis 1: Experience Level** (already exists)
- Beginner / Intermediate / Pro / Custom

**Axis 2: Interests** (NEW — multi-select checkboxes)
- [ ] Learning & Education
- [ ] Investing (MF, SIP, Portfolio)
- [ ] Trading (F&O, Intraday)
- [ ] Backtesting & Strategy
- [ ] Automation & Algo Trading
- [ ] AI & Analysis

**Matrix → Layout Preset mapping:**

| Experience | Primary Interest | Default Route | Layout Preset |
|-----------|-----------------|---------------|---------------|
| Beginner | Learning | /learn | learn-first |
| Beginner | Investing | /invest | invest-lite |
| Beginner | Trading | /learn | learn-then-trade |
| Intermediate | Trading | /terminal | trader |
| Intermediate | Investing | /invest | investor |
| Intermediate | All | /terminal | full |
| Pro | Trading | /terminal | scalper-zone |
| Pro | Trading + Investing | /terminal | power-user |
| Pro | All | /terminal | everything |
| Custom | User picks | User picks | blank or user-selected |

### Add: Layout Preview
After selecting experience + interests, show preview card of the workspace layout. User accepts or clicks "Customize" for blank canvas.

### Technical
- Modify: `src/routes/SetupRoute.tsx`
- Add interest step (new wizard step)
- Presets stored in `src/layout/presets/` (extends existing preset JSON files, NOT a new `src/layouts/` directory)

---

## 5. Global Navigation in TopBar

### Design (approved: TopBar Integration)

```
[F logo] [Learn] [Invest] [Trade] | [Workspace 1] [Workspace 2] [+] ... [TOOLS] [WIDGETS] [● dhan] [23:30 IST]
```

**Route tab order: Learn · Invest · Trade**

### Behavior
- Clicking route tab navigates via react-router
- Active tab: `bg-accent/15 text-accent border-b-2 border-accent`
- Workspace tabs only on `/terminal`
- On `/invest` and `/learn`, workspace area shows section name
- Route tabs on ALL app routes, NOT on flow routes (/welcome, /explore, /setup)

### Technical
- TopBar extracted from TerminalRoute into `AppLayout.tsx` (shared by all app routes)
- TopBar receives `currentRoute` from `useLocation()` and `navigate` from `useNavigate()`
- Terminal-specific controls (TOOLS, WIDGETS) conditionally shown only on `/terminal`
- TOOLS and WIDGETS also available on other routes via a simplified menu

---

## 6. Daily Welcome (Smart Welcome Card)

**NOT a full-page block.** Slide-in card, top-right, auto-dismiss 8s.

### Content (context-aware):

| Time | Content |
|------|---------|
| Pre-market (<9:15) | "Good morning" + market opens countdown |
| Market hours (9:15-15:30) | No card (don't block trading). Exception: position alert |
| Post-market (15:30-20:00) | "Markets closed" + P&L summary |
| Evening/Weekend | Suggestions (backtest, learn) |
| Recovery (crash with positions) | RED alert, does NOT auto-dismiss |

### Crash detection
Set `flinttrade:sessionActive = "true"` on mount via `useEffect`. Clear on `beforeunload` event. If `sessionActive` is still `"true"` on next mount AND `tradingStore.positionCount > 0`, show recovery card.

### Data sources
- Name: `settingsStore.name` (new field, defaults to "Trader")
- Position count: `useTradingStore.getState().positionCount` (existing)
- P&L: `useTradingStore.getState().totalPnl` (existing)

### Technical
- New: `src/components/welcome/DailyWelcome.tsx`
- Rendered in `AppLayout.tsx` (not RootLayout — only shows on app routes)
- localStorage: `flinttrade:lastOpen`, `flinttrade:sessionActive`

---

## 7. settingsStore Additions

Add these fields to `settingsStore.ts` with Zustand persist migration:

```typescript
// New fields
name: string;                    // User's display name, default "Trader"
interests: string[];             // Selected interests from setup
experience: "beginner" | "intermediate" | "pro" | "custom";
lastOpenTimestamp: number;       // Last app open time (ms since epoch)

// Zustand persist migration
version: 2, // bump from current version
migrate: (state, version) => {
  if (version < 2) {
    return { ...state, name: "Trader", interests: [], experience: "intermediate", lastOpenTimestamp: 0 };
  }
  return state;
}
```

---

## 8. Layout Presets

Extend the existing `src/layout/presets/` directory (which already has 7 JSON files) with new preset files:

| Preset File | Widgets |
|------------|---------|
| `learn-first.json` | NEW — Learn basics + glossary panels |
| `invest-lite.json` | NEW — Portfolio + SIP Calculator |
| `learn-then-trade.json` | NEW — Paper trading + basics |
| `trader.json` | EXISTS as `minimal.json` — rename/extend |
| `investor.json` | NEW — Holdings + Net Worth + Funds |
| `full.json` | NEW — Chart + Dashboard + Option Chain |
| `power-user.json` | NEW — Scalper + Portfolio + Positions |
| `everything.json` | NEW — Dense 4-panel |

Each JSON file is a serialized Dockview layout (same format as existing presets).

---

## 9. Workspace Management Menu

**Dropdown from + button in TopBar:**
- New from Template → preset grid
- New Blank → empty Dockview
- Clone Current → duplicate
- Rename → inline edit
- Delete → confirm dialog (can't delete last)

Modify: TopBar workspace area, `layoutStore.ts`

---

## 10. Interactive Tour

After first setup, pulsing green dots on 6 areas:
1. Route tabs — "Switch between Learn, Invest, Trade"
2. Workspace tabs — "Create multiple workspaces"
3. WIDGETS — "Add panels to your workspace"
4. TOOLS — "Full-page tools: Backtest, Strategy Builder"
5. TickerBar — "Live market prices"
6. First widget — "Drag to resize, right-click for options"

Click dot → tooltip. Click all 6 or "Skip Tour" → done. Stored in `flinttrade:tourComplete`.

New: `src/components/tour/InteractiveTour.tsx`

---

## 11. Files Summary

### New files (9)
| File | Purpose |
|------|---------|
| `src/routes/WelcomeRoute.tsx` | Cinematic welcome |
| `src/routes/ExploreRoute.tsx` | Try-before-setup |
| `src/routes/AppLayout.tsx` | Shared chrome for app routes |
| `src/components/explore/ExploreBanner.tsx` | Demo banner |
| `src/components/welcome/DailyWelcome.tsx` | Daily greeting |
| `src/components/tour/InteractiveTour.tsx` | Pulsing dot tour |
| `src/data/sample-snapshot.json` | Bundled demo data |
| `src/layout/presets/*.json` (6 new) | Layout presets |

### Modified files (6)
| File | Change |
|------|--------|
| `src/main.tsx` | New routes, smart redirect, route layout split |
| `src/routes/SetupRoute.tsx` | Interest matrix, layout preview |
| `src/chrome/TopBar.tsx` | Route tabs, workspace menu |
| `src/stores/settingsStore.ts` | name, interests, experience, migration |
| `src/stores/connectionStore.ts` | Add demo flag |
| `src/stores/layoutStore.ts` | Preset loading methods |

---

## 12. Implementation Priority

| # | Component | Effort | Depends on |
|---|-----------|--------|------------|
| 1 | AppLayout + Global Nav | Small | Nothing |
| 2 | settingsStore additions | Small | Nothing |
| 3 | Layout Presets (JSON files) | Medium | Nothing |
| 4 | Setup Wizard (interest matrix) | Medium | #2, #3 |
| 5 | Cinematic Welcome | Medium | Nothing |
| 6 | Explore Mode | Medium | #1, #3 |
| 7 | Daily Welcome Card | Small | #2 |
| 8 | Interactive Tour | Small | #1 |
| 9 | Workspace Menu | Small | #3 |

**Parallelizable:** #1, #2, #3, #5 can all run in parallel. Then #4, #6, #7, #8, #9 after.

---

## 13. Success Criteria

- First-time: cinematic welcome → explore without setup → setup with interests → personalized workspace → tour
- Returning: context-aware daily card → auto-restore last workspace
- Route tabs (Learn/Invest/Trade) visible on all app routes
- 8+ layout presets load correctly
- All routes accessible from any other route
- Tour completes, never shows again
- Crash recovery detects open positions
- Zero hardcoded hex colors
- tsc clean, vitest pass, build clean
