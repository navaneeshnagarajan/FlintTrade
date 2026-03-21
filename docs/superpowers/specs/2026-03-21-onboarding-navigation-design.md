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
/terminal → TerminalRoute (with global nav in TopBar)
/invest → InvestRoute (with global nav in TopBar)
/learn → LearnRoute (with global nav in TopBar)
```

### Smart redirect logic (in main.tsx)
```typescript
function getInitialRoute(): string {
  const settings = localStorage.getItem("flinttrade:settings");
  if (!settings) return "/welcome"; // First time
  const { persona } = JSON.parse(settings);
  return personaRoute(persona); // Returning user → last route
}
```

---

## 2. Cinematic Welcome Screen (`/welcome`)

**Shows:** First-time only (no settings in localStorage).

### Sequence (CSS @keyframes + Framer Motion)

1. **Dark void** (0-1s) — Pure black screen
2. **Spark ignition** (1-2s) — Small green spark (#22c55e) appears center, grows with glow
3. **Logo formation** (2-3.5s) — Spark becomes the FlintTrade "F" icon, wordmark types out letter by letter
4. **Tagline** (3.5-4.5s) — "Learn · Invest · Trade" fades in below, spaced with dots
5. **6 Pillars reveal** (4.5-8s) — Cards slide up from bottom, staggered 200ms each:

| Pillar | Icon | Headline | Subtext |
|--------|------|----------|---------|
| Learn | 📚 | Learn | Market basics to advanced strategies — built into the terminal |
| Invest | 💰 | Invest | Mutual funds, SIPs, portfolio tracking, net worth |
| Trade | 📊 | Trade | F&O scalping, options analysis, real-time execution |
| Backtest | ⚡ | Backtest | Rust-powered tick-level backtesting — no broker has this |
| Automate | 🔄 | Automate | 54-node flow builder, cron scheduler, Telegram kill switch |
| AI | 🤖 | AI | Local LLM advisor, RAG analysis, sentiment signals |

6. **CTA** (8-10s) — Two buttons fade in:
   - **"Explore First"** → `/explore` (try before setup)
   - **"Set Up Workspace"** → `/setup`

7. **Skip** — Click anywhere or press Enter/Space/Escape at any point to skip to CTA

### Technical
- New file: `src/routes/WelcomeRoute.tsx`
- CSS @keyframes for spark/fade/slide animations
- No external animation library (pure CSS + React state transitions)
- `will-change: transform, opacity` for GPU acceleration
- Responsive: scales down on smaller viewports via clamp()

---

## 3. Explore Mode (`/explore`)

**Purpose:** Let users try the terminal without setting up a broker. Ubuntu "try before install" concept.

### What they see
- Full terminal workspace (Dockview) with a sample layout
- TopBar with route tabs (Learn / Invest / Trade) — all navigable
- TickerBar showing **delayed/snapshot data** (last market close prices, hardcoded or fetched from free API)
- Dashboard with sample index values
- Chart with historical data (from OpenAlgo history API, no auth needed for some endpoints, or bundled sample data)
- Option chain in "demo" mode (static snapshot)
- A persistent banner at top: "Exploring with sample data. [Set up your workspace →] to connect your broker and go live."

### What they CAN'T do
- Place orders (buttons disabled with tooltip "Connect broker first")
- See live ticks (WebSocket not connected)
- Access real positions/orders/holdings

### Technical
- New file: `src/routes/ExploreRoute.tsx`
- Reuses TerminalRoute's Dockview workspace but with a `demo: true` flag in connectionStore
- Sample data: bundle a JSON snapshot of NIFTY 5-min candles + option chain for demo
- Banner component: `src/components/explore/ExploreBanner.tsx`

---

## 4. Setup Wizard Enhancement

### Keep existing
- Quick (2 steps) / Guided (5 steps) / Advanced (7 steps) modes
- Connection step (OpenAlgo host + API key)
- Experience level picker

### Add: Persona × Interest Matrix

Replace the single "Persona" picker with a two-axis selection:

**Axis 1: Experience Level** (already exists)
- Beginner
- Intermediate
- Pro
- Custom

**Axis 2: Interests** (NEW — multi-select)
- [ ] Learning & Education
- [ ] Investing (MF, SIP, Portfolio)
- [ ] Trading (F&O, Intraday)
- [ ] Backtesting & Strategy
- [ ] Automation & Algo Trading
- [ ] AI & Analysis

**Matrix → Layout Preset mapping:**

| Experience | Primary Interest | Default Route | Layout Preset |
|-----------|-----------------|---------------|---------------|
| Beginner | Learning | /learn | Learn-first: Basics + Glossary |
| Beginner | Investing | /invest | Invest-lite: Portfolio + SIP Calculator |
| Beginner | Trading | /learn | Learn-then-trade: Basics + Paper Trading |
| Intermediate | Trading | /terminal | Trader: Chart + Option Chain + Positions |
| Intermediate | Investing | /invest | Investor: Portfolio + Holdings + Net Worth |
| Intermediate | All | /terminal | Full: Chart + Dashboard + Option Chain |
| Pro | Trading | /terminal | Scalper Zone: Scalper + Chart + Option Chain + Depth |
| Pro | Trading + Investing | /terminal | Power User: Scalper + Portfolio + Positions |
| Pro | All | /terminal | Everything: Dense 4-panel with all key widgets |
| Custom | User picks | User picks | Empty canvas or user-selected template |

### Add: Layout Preview

After selecting experience + interests, show a **preview card** of what their workspace will look like (small screenshot/mockup of the layout preset). User can accept or choose "Customize" to start from blank.

### Technical
- Modify: `src/routes/SetupRoute.tsx`
- Add interest multi-select step (new wizard step between Persona and Connection)
- Add layout preview component
- Predefined layouts stored in `src/layouts/presets.ts` as serialized Dockview JSON

---

## 5. Global Navigation in TopBar

### Design (approved: Option B — TopBar Integration)

Add route tabs to the LEFT side of TopBar, before workspace tabs:

```
[F logo] [Learn] [Invest] [Trade] | [Workspace 1] [Workspace 2] [+] ... [TOOLS] [WIDGETS] [● dhan] [23:30 IST]
```

**Route tab order: Learn · Invest · Trade** (deliberate — learning first philosophy)

### Behavior
- Clicking a route tab navigates to that route via react-router
- Active route tab has accent highlight (`bg-accent/15 text-accent border-b-2 border-accent`)
- Workspace tabs only show on `/terminal` route (Dockview is terminal-only)
- On `/invest` and `/learn`, the workspace tab area shows the current section name
- Route tabs are always visible on ALL routes (terminal, invest, learn)
- NOT visible on /welcome, /explore, /setup (those are full-page flows)

### Technical
- Modify: `src/chrome/TopBar.tsx`
- Add `useLocation()` from react-router to detect active route
- Add `useNavigate()` for route switching
- Route tabs component: `RouteTabBar` (inline in TopBar or separate)

---

## 6. Daily Welcome (Smart Welcome Card)

### Shows: Every app open (not just first time)

**NOT a full-page block.** A slide-in card in the top-right corner that auto-dismisses after 8 seconds. User can dismiss immediately by clicking X.

### Content (context-aware by time of day):

**Pre-market (before 9:15 IST):**
- "Good morning, {name}" (name from settings or "Trader")
- Global indices overnight (if available)
- "Market opens in {X} minutes"
- Quick-launch: Last workspace

**Market hours (9:15-15:30):**
- Minimal — just restore workspace, no greeting card
- Exception: if open positions exist, show "You have {N} open positions" alert

**Post-market (15:30-20:00):**
- "Markets closed"
- Today's P&L summary (if traded)
- "Review in Trade Journal?" link

**Evening/Weekend:**
- "Good evening"
- Suggestions: "Try backtesting a strategy" / "Explore learning modules"

**Recovery mode (crash/unexpected close with open positions):**
- RED alert card: "⚠️ You have {N} open positions"
- Shows positions summary
- "Go to Terminal" button (prominent)
- Does NOT auto-dismiss

### Technical
- New component: `src/components/welcome/DailyWelcome.tsx`
- Reads from settingsStore (persona, name) and positionStore
- Time-of-day logic with IST timezone
- Rendered in RootLayout.tsx (appears on all routes)
- localStorage flag: `flinttrade:lastOpen` timestamp to detect long absence

---

## 7. Workspace Management

### Current state
- `layoutStore` has multi-tab support (tabs array, activeTabId)
- Tabs are Dockview layouts serialized to JSON
- Create/delete tabs exists but UI is minimal (just + and X buttons)

### Enhancement

**Workspace menu** (dropdown from the + button or workspace tab right-click):
- **New from Template** — Shows preset grid (Scalper Zone, Options Desk, Market Watch, etc.)
- **New Blank** — Empty Dockview canvas
- **Clone Current** — Duplicate current workspace
- **Rename** — Inline edit on tab name
- **Delete** — Confirm dialog, can't delete last workspace

**Template presets** (from the persona × interest matrix + extras):
- Start Fresh (empty)
- Scalper Zone (Scalper + Chart + Depth)
- Options Desk (Option Chain + Chart + Greeks + Straddle)
- Market Watch (Dashboard + News + Market Intelligence)
- Investor View (Portfolio + Holdings + Net Worth)
- Learning Path (integrated learn content)
- Backtest Lab (Chart + Backtest Lab + Strategy Builder)
- Automation Hub (Flow Builder + Settings + Positions)

### Technical
- Modify: `src/stores/layoutStore.ts` (add template presets)
- New: `src/layouts/presets.ts` (serialized Dockview layout JSON for each preset)
- Modify: TopBar workspace area to add dropdown menu

---

## 8. Interactive Tour

### When: After first setup completion, before entering workspace

### Style: Interactive sandbox (Option C from brainstorming)

The workspace loads with the user's selected layout preset. Pulsing green dots appear on 6 key areas:

1. **Route tabs** (Learn/Invest/Trade) — "Switch between modes here"
2. **Workspace tabs** — "Create and manage multiple workspaces"
3. **WIDGETS button** — "Add any widget to your workspace"
4. **TOOLS button** — "Access full-page tools like Backtest Lab and Strategy Builder"
5. **TickerBar** — "Live market prices update here during trading hours"
6. **A widget** (the first panel) — "Drag edges to resize, right-click header for options"

User clicks each dot to see a tooltip. After clicking all 6 (or clicking "Skip Tour"), dots disappear and the workspace is fully theirs.

### Technical
- New component: `src/components/tour/InteractiveTour.tsx`
- Stores tour completion in localStorage: `flinttrade:tourComplete`
- Pulsing dots use CSS @keyframes animation
- Tooltip content is static (hardcoded strings)
- Tour state managed by a simple React state array of completed steps

---

## 9. Files Created/Modified

### New files
| File | Purpose |
|------|---------|
| `src/routes/WelcomeRoute.tsx` | Cinematic welcome (6 pillars, CSS animations) |
| `src/routes/ExploreRoute.tsx` | Try-before-setup with sample data |
| `src/components/explore/ExploreBanner.tsx` | "Exploring with sample data" banner |
| `src/components/welcome/DailyWelcome.tsx` | Context-aware daily greeting card |
| `src/components/tour/InteractiveTour.tsx` | Pulsing dot walkthrough |
| `src/layouts/presets.ts` | 8 predefined Dockview layout JSON presets |
| `src/data/sample-snapshot.json` | Bundled sample market data for explore mode |

### Modified files
| File | Change |
|------|--------|
| `src/main.tsx` | Add /welcome, /explore routes, smart redirect |
| `src/routes/SetupRoute.tsx` | Add interest multi-select, layout preview, matrix logic |
| `src/chrome/TopBar.tsx` | Add route tabs (Learn/Invest/Trade), workspace dropdown |
| `src/stores/settingsStore.ts` | Add interests[], lastOpenTimestamp |
| `src/stores/layoutStore.ts` | Add template preset methods |
| `src/routes/RootLayout.tsx` | Render DailyWelcome overlay |

---

## 10. Implementation Priority

| Priority | Component | Effort |
|----------|-----------|--------|
| 1 | Global Navigation (TopBar route tabs) | Small — unblocks everything |
| 2 | Setup Wizard Enhancement (interest matrix + presets) | Medium |
| 3 | Layout Presets | Medium (Dockview serialization) |
| 4 | Cinematic Welcome Screen | Medium (CSS animations) |
| 5 | Explore Mode | Medium (sample data + demo flag) |
| 6 | Daily Welcome Card | Small |
| 7 | Interactive Tour | Small |
| 8 | Workspace Management Menu | Small |

---

## 11. Success Criteria

- First-time user sees cinematic welcome → can explore without setup → setup with interest matrix → lands on personalized workspace → interactive tour
- Returning user gets context-aware daily card → auto-restores last workspace
- Route tabs (Learn/Invest/Trade) visible and functional on all main routes
- 8 layout presets load correctly for each persona × interest combination
- All routes accessible from any other route via TopBar
- Tour completes and never shows again
- Zero hardcoded hex colors — uses Phase 1A design tokens throughout
- tsc clean, vitest pass, build clean
