# FlintTrade v0.4.1 — Mode System Wiring & Safety Design Spec

> Superseded. Modes are Practice, Connected (read), and Live. Sample data is Example. The public web demo is Demo (example data). A fresh browser opens in Practice. Password sign-in on a finished Setup opens in Practice. The notes below are a retired design.


> **Date:** 2026-04-04
> **Author:** Navaneesh + Claude Code (7-agent synthesis)
> **Status:** Approved
> **Scope:** Unify mode system, server-side order safety, visual indicators, flow streamlining
> **Parent:** v0.4.0 spec (2026-04-01-v04-security-themes-modes-design.md)
> **Agents used:** Trader Persona, Investor Persona, Beginner Persona, Competitive Research, Codebase Audit, Security Engineer, UX Architect

---

## 1. Two Paths Architecture

### Path 1: Example (pre-auth)

- **Who:** Anyone curious — beginners, traders evaluating, investors comparing
- **Entry:** "Try with example data" on /welcome (elevated to equal weight with "Get Started")
- **Experience:** /explore with ALL features, mock data via MockDataEngine, guided tour option
- **No auth, no setup, no broker needed**
- **Persistent indicator:** Grey "EXAMPLE" pill in TopBar + 3px grey top border + banner "EXAMPLE — Sample data only"
- **Conversion CTA:** Persistent "Set up for real" link on example data

### Path 2: Live (post-auth)

- **Who:** Users who've set up an account
- **Entry:** "Get Started" on /welcome → Setup wizard → Login
- **Experience:** Full app with real broker data
- **Toggle:** Practice (paper) ↔ Live (real) in TopBar
- **Default on daily login:** Practice mode (safety-first)

---

## 2. Unified Mode System

### 2.1 Single Store

Replace the current dual-store system:

| Current | Issue |
|---------|-------|
| `modeStore`: demo/sandbox/live (sessionStorage) | Resets on browser close |
| `settingsStore.sandboxMode`: boolean (localStorage) | Disconnected from modeStore |

**New system:**

```typescript
type AppMode = "explore" | "practice" | "live";

interface ModeStore {
  mode: AppMode;
  setMode: (mode: AppMode) => void;
  requiresPinForMode: (target: AppMode) => boolean;
}
```

- **Persist in localStorage** (not sessionStorage) — mode survives browser close
- **Reset to "practice" on daily 8AM IST session expiry** — safety-first default
- The sample-data claim is only set via WelcomeRoute's "Try with example data" button (no auth)
- **Remove `settingsStore.sandboxMode`** — compute as `modeStore.mode === "practice"`

### 2.2 Mode Transitions

| From → To | Confirmation | PIN required | Notes |
|-----------|-------------|-------------|-------|
| example data → practice | Setup required first | No | Must create account + connect broker |
| example data → live | Setup required first | Yes | Must create account + connect broker |
| practice → live | Dialog + PIN | Yes | "Real money. Every order is real." |
| live → practice | Instant | No | Safety action — no friction |
| live → example data | Not available | — | Can't return to example data from a signed-in session |
| practice → example data | Not available | — | Can't return to example data from a signed-in session |

### 2.3 Language

| Internal value | UI label | User-facing description |
|---------------|----------|----------------------|
| `"explore"` | EXAMPLE | "Sample data only — no real money" |
| `"practice"` | PRACTICE | "Real prices, virtual money" |
| `"live"` | LIVE | "Real money — orders are executed" |

Never use "sandbox", "paper", or "demo" as a Mode. Modes are Practice, Connected (read), and Live. Sample data is Example.
Exception: safety disclaimer text may reference "simulated trading."

---

## 3. Server-Side Mode Enforcement (CRITICAL)

### 3.1 The Problem

Frontend calls OpenAlgo directly for orders (`api.ts → POST /api/v1/placeorder`). Neither `modeStore.mode` nor `settingsStore.sandboxMode` is checked. A user in "practice" mode can place real orders.

### 3.2 The Fix

All order placement routes through FlintTrade backend (port 5001):

```
Frontend (order widgets)
    │
    ▼
FlintTrade Backend (port 5001)
    │ checks session mode
    │
    ├── mode = "explore" ──→ REJECT 403
    ├── mode = "practice" ──→ Practice fill path (SQLite state.sqlite)
    └── mode = "live"    ──→ OpenAlgo (real broker)
```

### 3.3 Backend Changes

1. Add `mode` field to JWT payload (set during login/mode-switch)
2. Add `/v1/orders/place` endpoint on FlintTrade backend that:
   - Validates JWT + extracts mode
   - If explore → reject
   - If practice → route to Practice fill path
   - If live → forward to OpenAlgo
3. Frontend `api.ts` order functions call FlintTrade backend, not OpenAlgo directly

### 3.4 Frontend Changes

1. `api.ts` order functions (`placeOrder`, `placeSmartOrder`, `cancelOrder`, etc.) route to `/ft-api/v1/orders/*` instead of `/api/v1/*`
2. Add client-side guard as defense-in-depth (belt AND suspenders)
3. Block all order API calls when `mode === "explore"`

---

## 4. Visual Mode Indicators

### 4.1 Specification (Thinkorswim-inspired)

| Mode | TopBar Pill | App Top Border | Banner | Order Button Label |
|------|-----------|---------------|--------|-------------------|
| Example | Grey "EXAMPLE" | 3px grey `border-text-muted/40` | "EXAMPLE — Sample data only" | "Practice Order (no real money)" |
| Practice | Amber "PRACTICE" toggle | 3px amber `border-amber-500` | "PRACTICE — Virtual capital, real prices" | "Paper Order (virtual money)" |
| Live | Green "LIVE" toggle | 1px green `border-profit/60` | None (clean UI) | "Place Order (REAL — ₹X)" |

### 4.2 TopBar Component

Merge `SandboxToggle` + `ModePill` into a single `ModeIndicator` component:

- On example data: grey pill showing "EXAMPLE" (not clickable — changing Mode requires setup)
- In **practice/live** modes: Toggle button with AlertDialog confirmation
  - Practice → Live: PIN required
  - Live → Practice: Instant (no dialog)

### 4.3 AppLayout Changes

Replace the 0.5px amber border with:
- Example: `<div className="h-[3px] bg-text-muted/40" />`
- Practice: `<div className="h-[3px] bg-amber-500" />`
- Live: `<div className="h-px bg-profit/60" />`

---

## 5. Flow Streamlining

### 5.1 Returning User Login (Current vs Proposed)

**Current (5 screens, ~20s):**
```
Cinematic (1.5s) → Greeting (3s) → Password+TOTP → ModeSelect → BrokerDash → /trade
```

**Proposed (1-2 screens, ~5s):**
```
/welcome → PIN (if idle <30min) → /trade (last mode + workspace)
/welcome → Password+TOTP (daily) → /trade (defaults to practice)
```

Changes:
- Remove `ModeSelectRoute` from returning-user login flow
- Remove `BrokerDashboardRoute` from login flow (move to Settings)
- Mode persists in localStorage — no need to re-select daily
- GreetingScreen: add click-to-dismiss (not forced 3s wait)
- On daily login, reset mode to "practice" (safety-first)

### 5.2 Setup Completion Fix

**Current:** `useAuthStore.getState().setLoggedOut(); navigate("/welcome");`
**Proposed:** `useAuthStore.getState().setLoggedIn(username, email, token); navigate("/trade");`

User completes setup → logged in → lands in /trade. Never logged out after setup.

### 5.3 Persona-Adaptive Setup

| Persona | Steps shown | Deferred to Settings |
|---------|------------|---------------------|
| Beginner/Learner | Account (name+password), Persona | 2FA, PIN, Broker, Trading defaults, Risk limits |
| Investor | Account, Persona, Broker (with skip) | 2FA, Trading defaults, Risk limits |
| Trader | Account, Persona, Broker, Trading defaults | 2FA deferred to first Live switch |

---

## 6. Wire Orphaned Components

| Component | Destination | Integration |
|-----------|------------|-------------|
| `MockDataEngine` (332 lines) | Example-data provider | Start on the sample-data entry, feed to widgets via Jotai atoms |
| `DemoChoice` (161 lines) | First sample-data entry | Show "Free example data" vs "Guided Tour" before example data starts |
| `SandboxControls` (417 lines) | Settings → Practice section | New settings section for capital adjustment, reset, export/import |
| `ModeSelectRoute` (218 lines) | Setup wizard step 6 only | Remove from login flow, keep in setup |

---

## 7. Files Affected

### New Files
- `packages/core/core/src/order_routes.py` — Order proxy with mode enforcement
- `packages/apps/terminal/src/chrome/ModeIndicator.tsx` — Unified mode pill/toggle
- `packages/apps/terminal/src/hooks/useModeData.ts` — Mode-aware data hook
- `packages/apps/terminal/src/tools/Settings/PracticeSection.tsx` — Settings section for SandboxControls

### Modified Files
- `packages/apps/terminal/src/stores/modeStore.ts` — Rename values, localStorage persist
- `packages/apps/terminal/src/stores/settingsStore.ts` — Remove sandboxMode
- `packages/apps/terminal/src/services/api.ts` — Route orders through backend
- `packages/apps/terminal/src/chrome/TopBar.tsx` — Replace SandboxToggle with ModeIndicator
- `packages/apps/terminal/src/routes/AppLayout.tsx` — Mode-aware border + banner
- `packages/apps/terminal/src/routes/WelcomeRoute.tsx` — Remove mode/broker from login flow
- `packages/apps/terminal/src/routes/SetupAccountRoute.tsx` — Fix completion, persona-adaptive
- `packages/apps/terminal/src/routes/ExploreRoute.tsx` — Wire MockDataEngine + DemoChoice
- `packages/core/core/src/app.py` — Register order proxy blueprint
- `packages/core/core/src/auth_routes.py` — Add mode to JWT payload
- `packages/apps/terminal/src/routes/SettingsRoute.tsx` — Add Practice section
- `packages/apps/terminal/src/tools/Settings/settingsConfig.ts` — Add "practice" section

### Delete/Archive
- `packages/apps/terminal/src/chrome/SandboxToggle.tsx` — Replaced by ModeIndicator
- `packages/apps/terminal/src/chrome/ModePill.tsx` — Merged into ModeIndicator

---

## 8. Order Safety

- Paper trading through OpenAlgo (broker gateway) is broker-integrated, not third-party — permissible
- Add disclaimer in practice mode: "Virtual trading results are simulated and do not represent actual trading outcomes"
- Broker order-tagging requirements remain live-mode only; practice mode is clearly marked "SIMULATED"

---

## 9. Success Criteria

1. No orders reach OpenAlgo when the session is example data or Practice (server-enforced)
2. Mode is visible at all times — TopBar pill + coloured border + order button label
3. Returning user reaches /trade in <5 seconds (PIN or password+TOTP, no intermediate screens)
4. Setup completion logs user IN (never back to /welcome)
5. All 4 orphaned components (MockDataEngine, DemoChoice, SandboxControls, ModeSelectRoute) are wired
6. "Sandbox"/"Paper"/"Demo" removed from all user-facing UI text
7. TypeScript builds clean, all vitest tests pass, all pytest tests pass
