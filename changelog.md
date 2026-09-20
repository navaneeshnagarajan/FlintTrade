# Changelog

All notable changes to FlintTrade will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/).
Versioning: [Semantic Versioning](https://semver.org/).

<!--
Release history was reset to a clean v0.0.1 baseline on 2026-07-23. The earlier
v0.1.0…v0.6.0-beta.13 tags and releases (the retired Tauri/PyInstaller line, plus
the updater-beta channel manifest) were deleted so the project could restart with
honest, pre-release-marked 0.0.x semantic versioning while it is still pre-usable.

No history was lost: every commit and its detailed message remains in git.
release-please regenerates the sections below from Conventional Commits, so the
changelog rebuilds itself from the first release cut after this baseline.
-->

## [Unreleased]

### Added

- **Service connections and in-process `BrokerReadPort`.** The backend now
  ships a rights-aware service-provider catalogue, static LLM/data profiles,
  and an inert persisted service-connection control plane. Listing or saving a
  connection does not resolve, probe, authenticate to, or start that provider.
  Exact broker reads in this change are the in-process `BrokerReadPort`
  contract (quotes, depth, history, balances, books, and related methods) —
  not a restored terminal Brokers screen or a new public HTTP read family.

- **Shared symbol bus from Watchlist (FT-TRADE-011).**
  Selecting a symbol in `/trade` Watchlist retargets
  Chart, Option Chain, and Scalper to that symbol —
  no retype. Keyboard retarget is optional later.
  Explore retarget is allowed and keeps Sample labels.
  An empty watchlist never silently retargets.

- **Option Chain OI profile + PCR strip (FT-TRADE-012).**
  The Option Chain strip shows OI profile + PCR for
  the selected expiry/symbol. Explore keeps a Sample
  badge and never invents live OI. An empty expiry
  is an honest empty, not zeros-as-data.

### Changed

- **Desk chrome: one TopBar + one ticker + flex shell (FT-UX-002).**
  Dual TopBar index slots are replaced by one dedicated
  scrolling TickerStrip under TopBar. TopBar keeps Mode,
  status, and overflow — not a second quote rail. Three
  Settings/Tools entries collapse into one Tools overflow
  menu plus at most one primary Settings entry. App chrome
  is a flex column: TopBar → TickerStrip → route body.
  Trade ships first; the same shell then rolls to Invest,
  Automate, Learn, and Ditto. Not a silent widen of
  FT-UX-001 Compact-only-on-Trade, and not a big-bang
  rewrite.

- **Mode vocabulary and Trade desk density (FT-UX-001).**
  Explore / Practice / Live chips mean execution mode only.
  Explore Order Pad uses Sample Buy / Sample Sell; Practice
  keeps Practice Buy / Sell; Live uses Place BUY/SELL Order.
  TopBar session chips (Continuous · CAS · Matching ·
  Post-close · Closed) stay session status (FT-CORE-001).
  Comfortable is the new-install default. Compact Trade at
  ~1280 and wider keeps chart, order pad, and positions
  primary, with ticker, tool ribbon, and watchlist /
  indices collapsed behind one desk-tools toggle. Selecting Compact on Trade at ~1280 and wider always
  starts with that disclosure collapsed.
  At most one primary banner (Explore sample > Practice sample >
  Live risk > feed disconnected). External-action gates stay fail-closed
  in Explore. Phone product and the marketing site are unchanged.

- **OpenAlgo-style password-first Explore; TOTP only before Live (FT-SETUP-002).**
  Setup and daily login are password-only for Explore and Practice.
  Authenticator enrolment is optional (“Set up later”) on day one.
  Confirming a live authenticator code enables TOTP for later logins.
  Live unlock still requires that enrolment plus the PIN. The mid-step
  Reset / Start-over wipe from #184 is unchanged.

- **Native broker HTTP freeze (accepted product decision).** Merging this work
  onto `main` leaves native broker UX down until Task 9D and Task 7C.2. That
  is accepted. Broker-account mutations — `/v1` account and auth writes, native
  connect / login / set-primary / delete, OAuth start and callback, and the
  other guarded account-authority routes — return a stable `503` with
  `{error: broker_account_cutover_unavailable}` until Task 9D migrates the
  handlers and removes `guard_broker_account_http` atomically. Native HTTP
  account and market-data reads return `409` with zero provider calls until
  the Task 7C.2 / 8B read-port cutover. The terminal still calls those routes,
  so Setup → Brokers and Settings → Brokers will show the freeze rather than a
  working native session. Service connections remain inert only. OpenAlgo
  bridge setup and gated live writes (`SafetySystem` L1–L5 → `gate_order` /
  `gate_broker_write` → `BrokerRouter`) stay unchanged.

### Fixed

- **Connected badge matches LLM install state (FT-AI-004).**
  `/ai` Chat (AI Hub) follows the real LLM status from
  Settings → AI / `#llm`, including Managed Ollama
  install state — not a green **Connected** while
  Settings shows **Not installed**. Managed Ollama
  **Not installed** shows **Not installed** (warning
  badge, not green) with a primary **Open Settings → AI**
  CTA to `/settings#llm`. Unconfigured stays
  **Not configured**. Composer input and Send stay
  disabled until the runtime is installed and
  configured — the same bar as FT-AI-002. A provider
  string of ollama is not Connected while the managed
  runtime is absent. A configured-but-broken probe still
  shows **Error** / **Disconnected** with Retry.
  Signals **Live** / **Polling** stay separate from
  Chat LLM readiness.

- **Authed `/home` skips password Welcome Back (FT-HOME-003).**
  `/home` is the canonical Home / Welcome dashboard.
  A signed-in operator who opens it (address bar,
  refresh, or same-tab bookmark) sees the same Home
  as SPA nav (sidebar, Alt+H, TopBar) — not the
  password Welcome Back gate. That gate stays on
  `/welcome` for unauthenticated visitors only.

- **Leverage tab content or honest empty (FT-SET-004).**
  `/settings#leverage` shows real leverage content when
  the broker snapshot is available. When leverage cannot
  be shown — unsupported broker, missing snapshot, or
  load failure — the pane shows the honest empty
  `Leverage settings unavailable.` plus **Retry**.
  Selecting the Leverage tab never leaves a highlighted
  tab over a blank content pane.

- **Kill All fail-closed when risk runtime unavailable (FT-DITTO-003).**
  Whenever the Ditto risk runtime is unavailable —
  including Explore `/ditto` Risk — **Kill All
  Positions** stays muted and disabled. Helper:
  `Risk runtime unavailable — Kill All disabled.`
  The control is never the armed red emergency CTA
  in that state. The backend rejects a Kill All if
  the UI slips. Live and Practice with a live
  runtime and managed accounts still keep the
  armed control (empty-account disarm is
  FT-DITTO-001).

- **Log refs no longer create a missing workspace.**
  A cold `log_ref` salt cache no longer calls
  `workspace_dir()` in a way that mkdir's the default
  workspace. Isolated callers (explicit-path TOTP
  stores) stay off the default pair.

- **Explore Schedules Pause gated for sample jobs (FT-AUTO-004).**
  Explore `/automate` → Schedules seeded jobs rely on
  the global Explore sample banner for disclosure —
  no extra Sample chip once Pause is gated. Seeded
  Explore jobs show status Sample/Demo (or muted),
  not a production-looking Active badge. Pause on
  those jobs is disabled, with title helper `Sample
  schedule — control unavailable in Explore`.
  Practice/Live jobs keep Pause/Resume. The backend
  rejects Explore pause/resume with `mode_blocked`.

- **Explore Stock Baskets disable demo Edit/Delete (FT-INVEST-002).**
  Explore `/invest#basket` seeded cards (NIFTY IT,
  Banking, and any other sample set) rely on the
  global Explore sample banner for disclosure — no
  card-level Sample chip. Bare ₹ / P&L under that
  banner is acceptable once actions cannot look live.
  Edit and Delete on seeded Explore baskets are
  disabled, with title helper `Sample basket —
  editing unavailable in Explore`. User-created
  Practice/Live baskets keep full Edit/Delete.
  Empty Explore is an honest empty or a clearly
  labelled sample set.

- **Feed-freshness honesty (FT-CORE-002).**
  Explore: the global
  `EXPLORE MODE — All data shown is sample only`
  banner plus per-widget Sample chips and age
  when known is enough. Per-symbol ticker Sample
  chips are optional. The Market Clock freshness
  chip appears only when that widget is mounted.
  Practice / Live: TopBar or the ticker must show
  Live · Delayed · Sample (and muted Stale /
  Unknown plus age when known). There is no
  Explore banner to lean on — silent-stale is a
  fail. Feed provenance stays separate from
  Explore / Practice / Live mode (Mode honesty).

- **Resource Hub User Guide first-open honesty (FT-LEARN-003).**
  Explore `/learn` → Resource Hub → User Guide shows
  `Loading document…` while the local backend/doc
  settles — never a red backend error on a cold race.
  A timeout or race is a muted soft fail:
  `Document isn’t ready yet.` plus a primary **Retry**
  (one automatic retry is allowed). Hard fail copy
  `Couldn’t load this document from the local backend.`
  plus **Retry** appears only after retry is exhausted.
  Order Safety Notes already loading in the same
  session does not mark User Guide permanently broken.

- **Holdings badge matches the visible table (FT-TRADE-010).**
  Practice/Explore `/invest` → Holdings with no broker
  shows `N holdings` for the rows currently in the table
  plus a muted Sample chip — never `0 holdings` over a
  10-row sample table. Dashboard and "N stocks" use the
  same N. Practice waits until the holdings query has
  settled empty before the sample fallback, so a cold
  load does not flash the wrong N. Dashboard
  `Net Worth (Equity + Cash)` uses the same shared demo
  book as Holdings. A broker read failure shows muted
  `Failed to load holdings` plus `Refresh` — never
  `0 holdings`, `No holdings`, or a sample table under
  a failed load. A connected broker with no positions
  shows `0 holdings` and an honest empty state (no
  sample table under a zero badge). Connected positions
  use the live count only, with no Sample chip.

- **Explore Execution Logs mode honesty (FT-AUTO-003).**
  Explore `/automate` → Execution Logs shows the muted
  empty state `No execution logs in Explore (sample-only).
  Switch to Practice or Live to see real run history.`
  and never the outage line on a healthy sample session.
  Practice/Live with a 200 OK and 0 rows use
  `No execution logs for this date.` — not an outage.
  The red `Failed to load logs. Backend may be offline.`
  copy (with Retry) is reserved for a real load failure.
  Loading shows a spinner / `Loading logs…` and never
  flashes the outage line.

- **SEBI CAS session clock / TopBar phases (FT-CORE-001).**
  TopBar market-status chips are Continuous · CAS ·
  Matching · Post-close · Closed (one active).
  Tooltip/title is the window, e.g.
  `CAS · 15:15–15:35 (as of Aug 2026)`. When
  equity F&O still runs after cash continuous ends, a
  secondary `F&O open · till 15:40` chip appears.
  Market Clock follows Continuous (~09:15–15:15)
  → CAS 15:15–15:35 → Matching → Post-close
  15:50–16:00. Non-CAS cash still continuous to
  15:30. Cash is never green "open" after 15:15;
  CAS is not Closed. Flat "Market open until
  15:30" and "VWAP last 30 min" closing-price
  copy are gone. The September 2026 consultation
  stays out of the UI.

- **Position Mirror Start fail-closed gate (FT-DITTO-002).**
  Explore `/ditto` → Position Mirror Start stays
  muted and disabled when unavailable — never
  the primary green armed CTA. Explore is
  always disarmed (sample-only). Helper:
  `Mirroring blocked in Explore (sample-only).
  Switch to Practice or Live with broker
  accounts connected.` Practice stays disarmed
  — the backend is Live-only. Helper:
  `Mirroring requires Live with broker accounts
  connected.` Live enables Start only with a
  source selected, at least one target, and
  broker accounts ready. Missing source/targets:
  `Select a source account and at least one
  target to start mirroring.` A successfully
  empty account list: `Connect a source and at
  least one target account to start mirroring.`
  Pending and failed account fetches stay muted
  with `Loading accounts...` / `Could not load
  accounts.` and never look like an empty
  connect state. The backend rejects Explore,
  Practice, or incomplete starts
  (`mode_blocked` or equivalent).

- **Explore Scalper fail-closed order path (FT-TRADE-009).**
  Explore `/trade` → Scalper is disarmed —
  Buy CE / Sell / 1-CLICK never open Confirm
  Order and never place. Buy/Sell stay disabled.
  Helper: `Orders blocked in Explore
  (sample-only). Switch to Practice or Live with
  a broker connected to trade.` 1-CLICK stays
  OFF / disabled; title `One-click unavailable
  in Explore`. Sample quote preview is allowed;
  Confirm BUY / Confirm SELL chrome is not.
  Practice and Live use Confirm only when the
  mode allows it and a gateway is configured.
  The backend rejects Explore orders with
  `code: mode_blocked` if the UI slips.

- **OI Chart shares Option Chain expiries (FT-TRADE-007).**
  Explore `/trade` Analysis layout → maximize OI Chart
  now shares Option Chain expiries for the
  symbol/exchange. A non-empty list shows the
  expiry control; charts and statistics cover
  only the selected expiry (the chain’s
  selection when both widgets are open;
  otherwise the nearest listed). Explore sample
  expiries stay listed and are badged Sample.
  No expiries or no OI is an honest empty —
  `No expiries for this symbol` or `No OI for
  this expiry` — with no bars and no PCR/max-pain
  stats, never “No expiries” over fake charts.

- **Watchlist LTP / % change use ticker sample quotes (FT-TRADE-008).**
  Explore `/trade` → Watchlist with Sparkline + LTP +
  % change checked now paints those column headers
  and cells. LTP and % change read the same sample
  quote source as the ticker tape (Jotai tick atoms
  from the Explore demo feed) for NIFTY, BANKNIFTY,
  SBIN, RELIANCE, HDFCBANK, and any other symbol on
  that feed. A Sample data badge discloses this.
  Missing quotes show `—` (or a brief `…` while the
  first fetch is in flight), never silent blank
  chrome. Unchecking a column hides it; checking it
  again shows the sample value or the honest empty.

- **Options Builder Net Debit and Max Loss share a position ₹ basis (FT-LAB-005).**
  Explore `/lab` Options Builder now shows Net
  Debit/Credit, Max Loss, and Max Profit on a
  shared position ₹ basis. Net Debit/Credit is
  the signed premium × lots × lot size. Max
  Loss and Max Profit are expiry-payoff results
  (intrinsic at the strikes, strike width, or
  unlimited) scaled to that same position basis
  — not premium × lots × lot size on every card.
  For a long call, Max Loss equals the Net Debit
  (the premium paid for the position). A muted
  sublabel `₹X per lot · N lots · lot size L`
  sits under those figures and is never the only
  number. Header and Legs chips use the same
  position basis as Payoff. When lots differ and
  a single per-lot breakdown cannot be formed,
  the primary figure is tagged `position` —
  never two unlabelled ₹ on mixed bases.
  Blank premiums still show `—` (FT-LAB-003).

- **Backtest headline P&L vs trade-log (FT-LAB-004).**
  Explore `/lab` backtest results now show labelled
  dual metrics. **Total Return (%)** is initial
  capital → final equity (including a forced last-bar
  close), with subtitle `Initial capital → final
  equity`. Live `total_return` percentage points are
  not passed through `fmtPct` a second time.
  **Net trade P&L (₹)** sums Trade Log `net_pnl`
  when present; if `net_pnl` is missing the card is
  labelled **Trade log P&L** with `Gross — net P&L
  not in result` rather than calling a gross sum net.
  When that sum matches the equity change, a quiet
  `Reconciles with trade log` note appears; when
  they diverge (fees, open marks, partial fills)
  both numbers stay visible with
  `Trade log sum ≠ equity change — fees / open
  marks`. Monthly P&L stays trade-based so the
  chart matches the log.

- **Learn Glossary Lot Size freshness (FT-LEARN-002).**
  Explore `/learn` → Glossary → Lot Size now teaches the
  Jan 2026 NSE-cycle index lots — NIFTY 65, BANKNIFTY 30,
  FINNIFTY 60, MIDCPNIFTY 120 — with an explicit “as of”
  date and a Verify on NSE link to circular NSE/FAOP/70616
  (3 Oct 2025). Stale `NIFTY=25` / `BANKNIFTY=15` copy is
  gone. Learn market facts that exchanges revise must ship
  dated, not as forever hardcodes. Independent of #213
  (FT-UX-001).

- **Performance follows the Review date range (FT-TRADE-006).**
  Trade Review **Performance** uses the same date range as
  Log and the other Review tabs. Changing Review dates
  updates Performance. A visible **Review range** | **YTD**
  control keeps YTD as an explicit choice; the active chip
  always shows the effective window (for example
  `YTD · 01 Jan–11 Sep 2026`). Opening Performance no longer
  auto-jumps to YTD. An empty range or no fills is an honest
  empty for that window, not a quiet YTD fallback. Metrics
  cover the labelled window up to the journal's 1,000-fill
  analytics page; a larger window is disclosed rather than
  silently sliced.

- **Heatmap Group by Exchange shows labelled group bands (FT-TRADE-005).**
  Explore `/trade` Positions → Heat → Group by Exchange (and
  Group by Sector) now draws a labelled band per group: a
  name chip (`NSE`, `NFO`, …) plus an optional exposure
  sublabel, with a stronger gutter than the leaf-tile
  borders. A single group still carries its label. Positions
  with no exchange metadata show `No exchange groups in these
  positions` instead of an undifferentiated treemap. Flat
  stays leaf-only, with no group chrome.

- **Explore Mutual Fund NAVs no longer claim a daily AMFI feed (FT-INVEST-001).**
  Explore `/invest#mutual-funds` now labels the fixture
  `Sample NAVs · as of 10-Sep-2026` and drops “Updated daily
  after market close.” The sample date was refreshed once so
  the as-of is not months stale; it does not auto-update.
  Practice and Live keep the daily-update sentence when the
  live AMFI feed is in use.

- **Options Builder Explore Long Call no longer looks zero-risk (FT-LAB-003).**
  Explore `/lab` Options Builder now treats a blank premium as
  unknown: Payoff summary cards show `—` and
  `Enter premium to model payoff` instead of modelling ₹0.
  The Long Call template seeds the Explore sample-chain ATM CE
  LTP, labelled `Sample premium — edit to model`, so Max Loss
  and breakeven follow FT-LAB-001 maths on a non-zero cost.
  Typing an explicit ₹0 still uses that maths and warns
  `Premium is ₹0 — payoff treats cost as free`.

- **Security PIN requires exactly six digits (FT-SET-003).**
  Explore `/settings#security` keeps New and Confirm as digits-only
  fields with `maxLength` 6. Set/Change PIN stays disabled until the
  account password is present, both fields are exactly six digits,
  and they match. Blurring a field with 1–5 digits shows
  `PIN must be exactly 6 digits`; blurring Confirm when both are
  filled and different shows `PINs do not match`. A five-digit value
  no longer looks valid. `POST /v1/auth/pin/set` still rejects
  anything that is not `^\d{6}$`.

- **Progressive TopBar collapse at ~390px (FT-MOBILE-002).**
  The terminal chrome no longer clips workspace, status, or ticker
  behind a horizontal TopBar scroll at about 390px. Logo mark, Mode
  (Explore / Practice / Live), and compact session/status stay
  visible and tappable. The ticker strip hides first (default off
  under ~480px). Workspace, account, Tools, search, fullscreen, and
  clock move into a More overflow menu with hit targets of at least
  44px. Workspace and ticker stay reachable via More; no control is
  clipped and unreachable.

- **Suggest recommendations refresh when mood changes (FT-AI-003).**
  Explore `/ai` Suggest treats market mood as a filter, not a draft.
  Changing mood (chip or **Next mood**) immediately replaces the
  recommendation list and the selected mood chip from one mood
  state. A previously focused strategy card is cleared, so a prior
  mood's card (for example Iron Condor after leaving Sideways)
  cannot remain. An empty mood + risk match shows an honest empty
  state with **Try another mood**.

- **Honest unconfigured LLM state on `/ai` (FT-AI-002).**
  `/ai` Chat probes `advisor/status` (including Explore /
  `demo-user`) and aligns the badge and composer with Settings
  `#llm` hydration — not a stale local store, and not an
  env-default `configured: true` while Settings looks empty.
  Unconfigured shows a warning **Not configured** badge, empty
  **LLM not configured**, a primary **Open Settings → AI** CTA to
  `/settings#llm`, and an outline **Retry**. When a leftover
  transcript hides that empty state, the header still offers
  **Retry** and **Open Settings → AI**. Returning to Chat after
  saving Settings → AI re-checks readiness. The composer input and
  Send stay disabled, so there is no send-then-`no reply` path. A
  configured but broken probe shows **Error** / **Disconnected**
  with Retry — never a green Connected. Signals **Live** /
  **Polling** stay separate from Chat LLM readiness. Do not add a
  fake Connected sample advisor in Explore; any later demo replies
  must be labelled **Sample replies**.

- **Telegram Send Test stays enabled in Explore (FT-AUTO-002).**
  Explore `/automate#settings` Telegram Alerts now disables Send Test
  and keeps the prefilled message as a preview-only sample. Helper:
  Telegram tests are blocked in Explore (sample-only). Switch to
  Practice or Live with Telegram configured to send a real test.
  Practice and Live enable Send Test only when Telegram is configured;
  otherwise the control stays disarmed with "Configure Telegram first".
  The backend rejects Explore-mode test sends with `mode_blocked`.

- **Practice Trading has no OpenAlgo Gateway setup CTA (FT-LEARN-001).**
  Explore `/learn` Practice Trading now links to Settings → Broker
  Gateway (`/settings#api`) so operators can configure OpenAlgo.
  On ~390px the Learn section tabs stack above the page instead of
  a 224px side column, and Practice copy, lists, sandbox rows and
  the Gateway button wrap. The CTA does not send operators to
  native Brokers.

- **P&L columns unusable at ~390px (FT-MOBILE-001).**
  Explore `/trade` Positions and Invest Holdings switch to stacked
  cards below 480px, so each row shows symbol, quantity, LTP, P&L
  and P&L% on one screen. The wide nowrap table no longer clips
  those figures off-screen behind a tiny scrollbar.

- **Invest deep-link hash tabs ignored on load (FT-ROUTE-001).**
  Opening `/invest#holdings` (and the other Invest tab hashes)
  now selects the matching tab on load. A direct `#holdings`
  URL no longer falls back to Dashboard.

- **Duplicate Watchlist widgets from Add widget picker (FT-HOME-002).**
  Explore `/home` Add widget no longer adds a second Watchlist when
  one is already on the dashboard. Already-present widget types are
  disabled or hidden in the picker; choosing Watchlist focuses the
  existing card instead of duplicating it.

- **Broker Gateway and Ditto default URLs diverge (FT-SET-002).**
  Explore `/settings#api` Broker Gateway and Explore `/ditto` Add
  Account now share the OpenAlgo default `http://127.0.0.1:5000`.
  Add Account prefills the saved Gateway host and REST port
  without retaining the bridge API key, so the two forms no
  longer silently default to ports 5000 and 5001.

- **Home greeting uses local evening at noon IST (FT-HOME-001).**
  Explore `/home` greets from the Asia/Kolkata clock, so ~12:01 IST
  is Good afternoon (or Good morning before noon), not Good evening
  from a non-IST browser clock.

- **Market status closed during NSE regular hours (FT-TRADE-004).**
  Explore `/trade` header treats OpenAlgo/Explore session timings
  as IST clock hours (09:15–15:30 on weekdays), not epoch
  milliseconds. Mid-session no longer shows a false
  “Market closed”. After hours and weekends stay closed.

- **Chart stays stale when timeframe selector changes (FT-TRADE-003).**
  Explore `/trade` timeframe buttons now refresh the chart
  series and visible range to match the selected interval.
  Switching 5m → 1D no longer leaves candles and intraday
  timestamps on the prior range, or a brief blank that stays
  stale.

- **Empty Monitors has no Strategy Builder/Lab CTA (FT-AUTO-001).**
  Explore `/automate` Monitors empty state now includes an
  "Open Strategy Builder" link to `/lab`. Operators no longer
  have to find Strategy Lab independently from copy-only text.

- **Settings `#llm` load failure with no recovery (FT-SET-001).**
  Explore `/settings#llm` no longer treats a demo or unconfigured
  session as a broken load. It shows an empty LLM state with Retry
  and guidance that Explore cannot persist LLM secrets. Live still
  fail-closes on a real load error to protect a saved configuration,
  and now offers Retry.

- **Kill All Positions armed on empty Explore Ditto dashboard (FT-DITTO-001).**
  Explore `/ditto` Risk Dashboard with ₹0 totals and no accounts
  listed now disables Kill All Positions and shows an empty
  state. The control is no longer a bright red armed emergency
  CTA on an empty dashboard. Live and Practice with managed
  accounts still keep the armed control.

- **Practice orders in Explore without a live broker (FT-TRADE-002).**
  Explore `/trade` Order Pad Practice Buy opens the Practice review and
  records a sample fill — no live broker is required. Live still
  uses the gated `placeOrder` path and still requires a broker
  connection. Native broker freeze is excluded.

- **Daily Sign In 2FA field while authenticator is deferred (FT-SETUP-002).**
  Login Sign In probes `/auth/status` every time it is shown and hides
  2FA unless `totp_enabled` is explicitly true. A stale Welcome
  `totpRequired={true}` after Sign Out can no longer keep the field.
  Enrolment still requires TOTP; Live still needs enrolment plus PIN.

- **Duplicate zero placeholders on backtest metrics (FT-LAB-002).**
  Explore `/lab` backtest headline metrics (Sharpe ratio, max
  drawdown, win rate, profit factor) now show a single formatted
  value. The leftover count-up `0.00` / `0.00%` beside the real
  figure is gone.

- **Explore Ctrl+K symbol search false unavailable error (FT-CMD-001).**
  Explore `search` now uses the same sample-instrument catalogue as
  Explore quotes and history. Ctrl+K → Symbols → NIFTY returns
  sample hits (NIFTY, BANKNIFTY, FINNIFTY) instead of a false
  connection error. Live and Practice still use native / OpenAlgo
  search.

- **Zero-premium long-call payoff (unbounded max profit + breakeven) (FT-LAB-001).**
  Options Builder Payoff now summarises expiry P&L from strike kinks
  and the right-hand slope, not the ±15% chart sample. A zero-premium
  long call shows Unlimited max profit, max loss equal to the premium
  (₹0), and breakeven at the strike. Paid-premium long calls and
  other unbounded legs (short calls, straddles) use the same rule.

- **Trade Review date filter and mangled timestamps in Explore (FT-TRADE-001).**
  Explore `/trade` Trade Review now clips the Log to the committed IST
  date range (the same predicate as the sample-journal badge) and
  renders fill timestamps as `D Mon YYYY HH:MM:SS` with a literal
  space, so `13 Apr 26` can no longer glue onto `14:55:42`. Live and
  Practice still use the journal/tradebook path; only the shared IST
  format and range helpers changed there.

- **Explore /ai chat produces no assistant reply (FT-AI-001).**
  `/ai` and the floating tutor now share one advisor chat path:
  a short status probe (including Explore/sample-data), SSE
  streaming, then the non-streaming fallback. A missing LLM, an
  unreachable backend, an empty completion, or an SSE error
  becomes a visible assistant error instead of a blank bubble.
  Empty assistant placeholders are no longer persisted, so a
  reload cannot restore the silent blank. The 45-second stream
  budget is first-token only: once a token arrives, a longer
  healthy completion is not aborted mid-reply. Native broker
  freeze is excluded. MF Optimizer and AI suggestions + deploy
  are unchanged.

- **Explore/Practice blocked until mandatory TOTP (FT-SETUP-001).**
  Setup Step 2/7 now has an obvious **Explore first — continue without
  2FA** path so sample-data Explore/Practice is reachable without
  finishing authenticator setup. The hatch marks the durable demo
  session (same as **Try with sample data**) so `/home` survives
  refresh and a `/welcome` remount instead of bouncing to the
  password+TOTP wall. Sign-in still requires TOTP. Daily login still
  requires password + TOTP, and Live still requires the PIN, as
  designed. **Start over** wipes the unfinished account via the
  account-create setup JWT so a lost QR seed is recoverable without the
  TOTP secret. Daily-login session tokens cannot wipe the account. A
  hard refresh of `/home` after Explore first restores the sample-data
  session even when `flinttrade:mode` was never persisted; unfinished
  setup progress stays so Start over / Delete account remain reachable.

- **Strategy Lab stays empty after AI Deploy (FT-DEMO-002).**
  Deploying a suggestion from `/demo-app/ai` (for example “Trend EMA
  Crossover”) opens `/demo-app/lab?strategy=TrendEMACrossover`. Strategy
  Lab now hydrates the Backtest selector from `?strategy=`, keeps a
  linked registry key in the catalogue when the loaded list does not
  include it, and enables Run Backtest once a strategy is selected.
  Sample demo backtests are unchanged; a Lab opened without the query
  is unchanged.

- **Invest dashboard holdings count vs listed sample stocks (FT-DEMO-001).**
  On `/demo-app/invest` the sample dashboard header now uses the Explore
  demo holdings book (`getDemoHoldings`) as its count source, so the
  badge matches the listed sample stocks and the Holdings tab. Live and
  Practice still read the live book — an empty funded account stays at
  0.

- **Remaining homepage nav overflow at ~390px (FT-SITE-003).** After
  #180, the primary nav wrapped without clipping Contribute, but at
  about 390px four chips still packed onto the first row and left
  “Explore demo” cramped against Docs/API. Below 480px the marketing
  nav now uses two-across chips with slightly smaller type and tighter
  padding, so every primary label stays on one line with slack. The
  900px wrap from #180 is unchanged.

- **Docs page summary duplicated as first body paragraph (FT-SITE-002).**
  On `/docs*` routes the page summary no longer appears twice. The
  generator still lifts the first body paragraph into frontmatter for
  SEO, but marks `hideDescription` when that extract matches the opening
  body paragraph. The docs page skips `DocsDescription` unless the page
  opts in with a distinct subtitle (fail-closed if the flag is missing).

- **Primary nav overflow clips Contribute (FT-SITE-001).** The marketing
  header no longer uses a shrinking `overflow-x: auto` row below 900px.
  Primary links wrap without shrinking, so Contribute and the other
  destinations stay fully visible on phones around 390px.

- **Dependabot qs and fflate (medium).** `qs` 6.15.2 (via `http-server` →
  `union`) is overridden to 6.16.0, clearing GHSA-4mjr / GHSA-px8p. `fflate`
  0.6.10 (via `three-stdlib`) is overridden to 0.6.11, clearing GHSA-x5fp.
  No new allowlist entries.

- **Node audit blockers on main.** Newly disclosed HIGH/CRITICAL advisories
  against the existing lock (next Windows/AVIF RCE, maplibre-gl XSS,
  `@xmldom/xmldom` name-injection/ReDoS, sharp libheif, js-yaml merge-key
  DoS, and four fast-uri host-confusion/SSRF issues) are cleared by real
  version bumps: next 16.3.4, and overrides for fast-uri 4.1.4, js-yaml
  4.3.2, sharp 0.35.4, maplibre-gl 6.8.0 and `@xmldom/xmldom` 0.8.15. No
  new allowlist entries.

- **Production systemd install.** `infra/scripts/setup-production.sh` hardcodes
  `/opt/flinttrade` (the prefix `flinttrade.service` already uses), refuses
  `FLINTTRADE_DIR`, symlink targets and non-git trees, and requires Python
  >= 3.12 before creating `$INSTALL_DIR/.venv`. The unit exports
  `FLINTTRADE_WORKSPACE_DIR=/opt/flinttrade/.flinttrade` so Workspace writes
  stay inside `ReadWritePaths`, `FLINTTRADE_BACKEND_PORT`, and starts
  `python -m flinttrade_core.app` with every workspace package on
  `PYTHONPATH`. First-time setup (and later deploys) build
  `packages/apps/terminal/dist` with the pinned pnpm and run
  `python -m flinttrade_core.cli init --provision-master-password` as
  `www-data`, so the non-interactive backend can start and serve the UI.
  Checkout-mode normalisation skips `.flinttrade` and `data` so hardened
  `0600` secrets stay owner-only. Code and `.venv` stay root-owned; only
  runtime workspace/data/log paths are `www-data`. `infra/scripts/deploy.sh`
  updates that tree with `sudo git` and does not take ownership.



- **Workspace path unification.** Nineteen modules resolved their own storage as
  the literal `~/.flinttrade` instead of asking `flinttrade_core.workspace`. On
  Linux that happens to be the workspace, so it never failed in CI; on macOS
  (`~/Library/Application Support/flinttrade`) and Windows (`%APPDATA%\flinttrade`)
  every one of them wrote to a second, invisible directory that the rest of the
  app did not read and the uninstaller could not find. Affected state included
  the TOTP secret store and its install key, the trade journal and its
  screenshots, saved presets, keyboard shortcuts, quantity-freeze limits, the
  pending-order approval queue, the watchlist, expiry and FII/DII stores, and the
  operator's own FlowBuilder flows, trained signal models and strategy files.

  Every module now resolves its path inside a function body at call time, so
  `FLINTTRADE_WORKSPACE_DIR` and `FLINTTRADE_HOME` are honoured on every
  construction rather than frozen at import. On a default install each artefact
  is **copied** into the platform workspace once, under a cross-process lock; the
  pre-workspace original is left untouched, so the upgrade is reversible. Where a
  workspace copy already exists it wins and no merge is attempted — an
  approval-queue merge could dispatch the same order twice. The TOTP store and
  its install key move as one unit, verified by a decrypt round-trip before the
  legacy pair is trusted, and the trade journal moves with its screenshot
  directory or not at all. Migration probes are skipped entirely when a workspace
  environment override is in force.

- Both uninstallers now enumerate every pre-workspace dropping written directly
  at `~/.flinttrade/<name>` — flows, models, strategies, journal screenshots,
  presets, the TOTP pair and the remaining stores — as named `--purge`/`-Purge`
  candidates. They were deleted before, but only as part of the managed root, so
  the confirmation list never mentioned the operator's own strategy code.

- `FlowBuilder` and the trade journal no longer fall back to a home-directory
  path when `flinttrade_core` cannot be imported. A broken install now fails
  loudly and the affected routes degrade to 503, instead of silently opening an
  empty shadow store.

### Changed

- Vulnerable ChromaDB persistence is replaced by FlintTrade's local
  SQLite/NumPy vector store. Existing vector directories are deliberately not
  auto-migrated because Chroma's on-disk index and embedding space are not
  compatible with the replacement. If `chroma.sqlite3` is present, FlintTrade
  refuses to create `flinttrade_vectors.sqlite` beside it: the database and
  vector-segment files are left untouched, RAG stays disabled, and agent
  learning uses its logged in-process fallback. To recover existing lessons or
  custom documents, export them with the previous release. To intentionally
  start empty, move the complete legacy directory aside as a backup before
  restarting; do not delete individual segment files. Each collection now
  persists one embedding dimension and refuses mixed-width writes after the
  first vector, inner-product distance stays unnormalised, and shutdown joins
  the optional background RAG indexer before closing the store.

- The traffic and latency observability logs (`traffic_log.duckdb`,
  `latency_log.duckdb`) are not migrated: they are disposable, and both were
  already workspace-routed in production. On macOS and Windows their history
  restarts from empty.

### Security

- **Clear-text secret logging in service-connection tests.** CodeQL
  `py/clear-text-logging-sensitive-data` alerts
  [#420](https://github.com/navaneeshnagarajan/FlintTrade/security/code-scanning/420)
  and
  [#421](https://github.com/navaneeshnagarajan/FlintTrade/security/code-scanning/421)
  flagged `packages/core/core/tests/test_service_connections.py` for passing a
  `secret_version` object to `logger.debug`. The redaction contract still
  asserts that binding identity and supplied credential material never appear
  in `str`/`repr`, public DTOs, exception text, or captured logs; the logger
  now receives only the masked `ServiceSecretVersion(<redacted>)` fixture.

## [0.0.1] — 2026-07-23

Clean-slate baseline. Pre-1.0, pre-usable, and marked as a pre-release: anything
may change without notice until the project reaches a stable 1.0.0.
