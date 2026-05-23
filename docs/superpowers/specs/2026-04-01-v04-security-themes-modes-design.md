# FlintTrade v0.4.0 — Security, Themes, Modes Design Spec

> **Date:** 2026-04-01
> **Author:** Navaneesh + Claude Code
> **Status:** Approved
> **Scope:** Login/security system, theme overhaul, three execution modes, welcome flow changes

---

## 1. Login & Security System

### 1.1 One-Time Setup (First Launch)

Single-user platform deployable anywhere (NAS, cloud, personal machine). One account per instance.

**Setup steps (merge of new security + existing /setup wizard):**

| Step | Content | Source |
|------|---------|--------|
| 1. Account Security | Username, email, strong password (zxcvbn), 6-digit PIN, 2FA TOTP (QR for Authenticator apps) | NEW |
| 2. Persona | Trader / Investor / Beginner selection | FROM /setup |
| 3. Broker Connection | Connect OpenAlgo + individual brokers | FROM /setup |
| 4. Trading Defaults | Exchange, product type, order type | FROM /setup |
| 5. Risk Limits | Max daily loss, position size limits | FROM /setup |
| 6. Mode Selection | Demo / Sandbox / Live | NEW |

**Credential storage:**
- Password: argon2id hash
- PIN: PBKDF2 hash (separate from password)
- TOTP secret: AES-256 encrypted (keyed from master password)
- All stored in `~/.flinttrade/auth.db` (SQLite, encrypted at rest)
- Recovery: 8 one-time backup codes generated during setup, downloadable as text file

**Email configuration:**
- SMTP settings entered during setup or later in Settings
- Used for: password reset after 5 failed attempts, security alerts

### 1.2 Daily Login Flow

**Session expiry:** Every day at 08:00 IST, all sessions expire. This enforces daily re-authentication aligned with SEBI's broker login requirement.

**Returning user flow:**
```
/welcome (auto-redirect to login)
  → Step 1: Password + TOTP code
            OR PIN (if session was recently active, <30 min idle)
  → Step 2: Mode selection (Demo / Sandbox / Live)
  → Step 3: Broker Dashboard
            - All connected brokers listed with status (red = disconnected)
            - Click each to authenticate (TOTP/OAuth/OTP per broker)
            - OpenAlgo users: "Managed by OpenAlgo" badge — skipped
            - "Skip for now" — enters app with brokers disconnected
  → Enter app at last-used route
```

### 1.3 PIN Quick-Unlock

- After full login, if user is idle >5 min but <30 min: PIN unlock screen (no full password + 2FA)
- After 30 min idle: falls back to full login (password + TOTP)
- PIN also required for: switching to LIVE mode mid-session

### 1.4 Security Hardening

- **Session:** JWT in memory (not localStorage), httpOnly cookie for Flask backend
- **Login rate limit:** 5 failed attempts → account locked → password reset via email
- **IP binding:** Optional (configurable in Settings → Security) — session bound to originating IP
- **No secrets in localStorage:** All auth tokens in memory only
- **CSRF:** All state-changing requests require auth header (no body-based API key)
- **Audit trail:** All login/logout/mode-change events logged to audit.db

### 1.5 Route Protection

- Every route except `/welcome` requires a valid session
- Direct URL access (e.g. typing `/trade` in browser) redirects to login if no session
- API endpoints continue to use X-API-Key header (unchanged)

---

## 2. Theme System Overhaul

### 2.1 Built-In Themes (3)

| Theme | Dark Accent | Light Accent | Character |
|-------|------------|-------------|-----------|
| **Graphite** (default) | Emerald green `#22c55e` | Emerald green `#16a34a` | Neutral, professional |
| **Midnight** | Sky blue `#38bdf8` | Blue `#2563eb` | Deep, focused |
| **Ember** | Amber `#f59e0b` | Orange `#ea580c` | Warm, energetic |

Each theme defines a complete palette for BOTH dark and light modes:
- 4 surface levels (base, card, elevated, floating)
- 4 text levels (primary, secondary, muted, disabled)
- 2 border levels (default, subtle)
- Accent colour (primary interactive colour)
- Trading semantics (profit, loss, warning — consistent green/red/amber across all themes)
- 5 chart data colours
- Particle style + background

### 2.2 Three Modes

- **Dark:** Theme's dark palette applied
- **Light:** Theme's light palette applied
- **System:** Follows OS `prefers-color-scheme` media query, auto-switches in real time

Persisted in themeStore: `{ activeThemeId, mode: "dark" | "light" | "system" }`

### 2.3 Transparency/Glass Toggle

- Settings → Appearance: "Glass effects" toggle
- **On:** `backdrop-blur` on cards, floating panels, overlays, sidebar
- **Off:** Solid opaque surfaces (better performance on low-end hardware)
- Default: On

### 2.4 Custom Theme Builder

- Base: pick Graphite/Midnight/Ember as starting point
- Override any colour with a colour picker
- Live preview as you edit (temporarily applies CSS vars)
- WCAG AA contrast validation: warns if accent vs surface fails 4.5:1
- Export as JSON, import from JSON
- Saved to `~/.flinttrade/themes/<name>.json`
- Custom themes appear alongside built-in themes in the picker

### 2.5 Cleanup (confirmed by user)

- **Remove:** 5 legacy CSS theme files (light.css, midnight.css, obsidian.css, ocean-blue.css, terminal-green.css)
- **Remove:** 5 dead theme icons from /welcome top-left
- **Remove:** `V1_THEME_MAP` backward compatibility mapping
- **Remove:** Old CinematicTheme v3 presets (Graphite, Midnight, Arctic Frost, Monochrome, Solarized Dark, Light) — replaced by 3 new polished v4 themes
- **Single source of truth:** CinematicTheme v4 — 3 built-in themes (Graphite, Midnight, Ember) + custom builder
- **Migration:** Existing users auto-mapped to Graphite (default)
- **Other files:** No deletions/modifications without explicit user approval

---

## 3. Three Execution Modes

### 3.1 Mode Definitions

| Mode | Data Source | Order Execution | Broker Required |
|------|-----------|----------------|----------------|
| **Demo** | Mock data engine (simulated prices) | None — read only | No |
| **Sandbox** | Live market data from broker | Paper trades (local DuckDB) | Yes |
| **Live** | Live market data from broker | Real orders via OpenAlgo → broker | Yes |

### 3.2 Mode Selection

- **At login:** "How would you like to trade today?" → Demo / Sandbox / Live
- **TopBar pill:** Grey `DEMO` / Amber `SANDBOX` / Green `LIVE`
- **Mid-session switching:**
  - Any → Demo: confirmation dialog, no PIN
  - Any → Sandbox: confirmation dialog, no PIN
  - Any → Live: confirmation dialog + PIN re-entry required
  - Downgrading (Live → Sandbox/Demo): no PIN needed

### 3.3 Demo Mode

**Entry choice (first time only):**
> "How would you like to explore FlintTrade?"
> - **Free Explore** — Jump in with simulated data, explore at your own pace
> - **Guided Tour** — Step-by-step walkthrough of every feature

**Mock data engine:**
- Generates realistic Indian market prices: NIFTY ~24,000, BANKNIFTY ~51,000, RELIANCE ~2,800, etc.
- Random walk ticks updating every 1 second
- Simulated positions (5 open), orders (8 today), holdings (10 stocks)
- Option chain with computed Greeks
- Portfolio with sample mutual funds and SIPs
- All 30 widgets functional with mock data
- All routes accessible

**Guided tour:**
- Overlay-based walkthrough using SpotlightTour component (already exists)
- Covers: /trade workspace, /invest portfolio, /learn courses, /lab backtesting, /automate flows, /ai advisor
- User can exit tour at any time → switches to free explore

**Visual indicator:**
- Persistent grey banner: "DEMO MODE — Simulated data, no real trades"
- Grey `DEMO` pill in TopBar

### 3.4 Sandbox Mode

**Paper trading engine:**
- Virtual capital: configurable (default ₹10,00,000)
- Capital adjustment: increase/decrease anytime via Settings or TopBar dropdown
- Orders validated against virtual capital and risk limits
- P&L tracked in DuckDB `sandbox_trades` table (separate from real trades)
- Real-time P&L using live prices from broker WebSocket

**Data management:**
- **Reset:** Clear all sandbox trades, positions, orders → fresh start with configured capital
- **Backup export:** Export sandbox data as JSON (trades, positions, equity curve, settings)
- **Import/restore:** Import previously exported JSON to restore sandbox state
- All accessible from Settings → Sandbox or TopBar dropdown

**Visual indicator:**
- Amber banner: "SANDBOX — Paper trading with virtual capital"
- Amber `SANDBOX` pill in TopBar

### 3.5 Live Mode

- Full real trading through OpenAlgo → broker → exchange
- Requires at least one broker connected
- PIN confirmation on mode entry
- Green `LIVE` pill in TopBar
- No banner (clean trading UI — mode is communicated via pill only)

---

## 4. Welcome Screen Changes

### 4.1 Removals
- **Remove:** "Skip →" button (top-right)
- **Remove:** 5 legacy theme icons (top-left)
- **Remove:** /setup as a standalone route
- **Remove:** /explore as a standalone route (replaced by Demo mode)

### 4.2 New Flow

**First-time user:**
```
/welcome (cinematic intro)
  → "Get Started" button
  → 6-step setup wizard (Section 1.1)
  → Enter app in chosen mode
```

**Returning user:**
```
/welcome (brief cinematic, auto-redirect after 1s)
  → Login screen (password + TOTP or PIN)
  → Mode selection
  → Broker dashboard
  → Enter app at last-used route
```

### 4.3 No Bypass

- No skip, no direct URL access without session
- Every app entry goes through authentication
- Bookmarking `/trade` redirects to `/welcome` → login → `/trade`

---

## 5. Files Affected (Estimated)

### New Files
- `packages/core/core/src/auth.py` — auth service (argon2, JWT, TOTP, PIN)
- `packages/core/core/src/auth_routes.py` — login/logout/setup/reset endpoints
- `packages/core/core/src/auth_middleware.py` — session validation middleware
- `packages/core/core/src/email_service.py` — SMTP password reset
- `packages/apps/terminal/src/routes/LoginRoute.tsx` — daily login screen
- `packages/apps/terminal/src/routes/SetupAccountRoute.tsx` — one-time account setup
- `packages/apps/terminal/src/routes/BrokerDashboardRoute.tsx` — daily broker reconnect
- `packages/apps/terminal/src/routes/ModeSelectRoute.tsx` — mode picker
- `packages/apps/terminal/src/services/mockDataEngine.ts` — demo mode data generator
- `packages/apps/terminal/src/stores/authStore.ts` — session state
- `packages/apps/terminal/src/stores/modeStore.ts` — Demo/Sandbox/Live state
- `packages/apps/terminal/src/hooks/useAuthGuard.ts` — route protection hook
- `packages/apps/terminal/src/components/sandbox/SandboxControls.tsx` — capital/reset/export

### Modified Files
- `packages/apps/terminal/src/main.tsx` — route restructuring, auth guards
- `packages/apps/terminal/src/routes/WelcomeRoute.tsx` — remove skip + theme icons, new flow
- `packages/apps/terminal/src/stores/themeStore.ts` — v4 theme system
- `packages/apps/terminal/src/lib/cinematicThemes.ts` — 3 themes, v4 schema
- `packages/apps/terminal/src/components/theme/ThemePicker.tsx` — updated for v4
- `packages/apps/terminal/src/index.css` — remove legacy token overrides
- `packages/apps/terminal/src/chrome/TopBar.tsx` — mode pill, auth status
- `packages/core/core/src/app.py` — register auth blueprint, session middleware

### Files Requiring Confirmation Before Delete/Modify
All existing files are preserved unless explicitly confirmed by the user:
- `packages/apps/terminal/src/themes/*.css` — migrate to v4 format, don't delete originals until confirmed
- `packages/apps/terminal/src/routes/SetupRoute.tsx` — reuse components in new setup flow, keep file until confirmed
- `packages/apps/terminal/src/routes/ExploreRoute.tsx` — keep alongside Demo mode until confirmed
- Any other existing file — ask before deleting or making breaking changes

---

## 6. Out of Scope (Deferred)

- Route reorganisation (separate project)
- Multi-user support (single user only for now)
- OAuth/social login (not needed for single user)
- Biometric auth (OS-dependent, future consideration)
- Cloud sync of themes/settings (local only for now)

---

## 7. Dependencies

- `argon2-cffi` — password hashing (Python)
- `PyJWT` — JSON Web Tokens (Python)
- `pyotp` — TOTP generation/verification (Python)
- `qrcode` — QR code generation for 2FA setup (Python)
- `zxcvbn-ts` — password strength meter (npm, already common in React apps)

---

## 8. Success Criteria

1. First-time user can set up account with 2FA in <3 minutes
2. Daily login (password + TOTP + broker connect) completes in <60 seconds
3. All 3 modes work: Demo (no broker), Sandbox (live data, paper trades), Live (real trades)
4. Theme switching (dark/light/system) works across ALL components with zero colour clashes
5. Custom theme builder produces valid themes with WCAG AA compliance
6. No route accessible without valid session
7. Session expires at 08:00 IST every day without exception
8. PIN unlock works for quick re-entry and LIVE mode switching
