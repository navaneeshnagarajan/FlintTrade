# MiroFish Persona Simulation Findings

> Date: 2026-03-31
> Method: 3 AI agents with distinct personas navigated FlintTrade via Playwright browser automation
> Version tested: v0.3.0 (commit 8f17d85)

## Personas Tested

| Persona | Profile | Routes Tested |
|---------|---------|---------------|
| Beginner | 22yo college student, Pune, ₹5K capital | /welcome, /learn, /invest, /ai, /settings, /trade, /explore |
| Day Trader | 35yo full-time F&O trader, Mumbai | /trade, /lab, /automate, /ai |
| HNI/Wealth Manager | 48yo advisor, Bangalore, ₹50Cr AUM | /invest (all 16 tabs), /settings, /admin |

## P0 Blockers (FIXED)

- **NoConnectionOverlay hijacked all routes** — auto-redirected away from /learn, /invest, /ai within 5-7s when OpenAlgo not running. Fixed: expanded SUPPRESSED_ROUTE_PREFIXES to all non-trading routes. (commit 8f17d85)

## P1 High Priority (NOT YET FIXED)

1. **LIVE mode is default** — beginners should start in paper/demo mode
2. **/explore route redirects** instead of showing demo content
3. **Welcome page has zero explanation** of what FlintTrade is
4. **Placeholder text visible in /trade** — "Full watchlist in next iteration", "Order pad coming in next iteration"
5. **Most tabs blank without OpenAlgo** — Holdings, Tax, Sector, ETF, Social all show loading spinners forever
6. **No multi-account/client management UI** — ditto package exists as Python backend but has no terminal UI
7. **Zero export capability** — no PDF, CSV, or print for any data view
8. **"Margin Used" label shows cost basis** — incorrect terminology

## P2 Medium Priority

1. Jargon everywhere: NAV feed, XIRR, Margin, Scalper, VIX — no tooltips
2. Invest tab count inconsistency (5 vs 16 tabs based on skill level — confusing)
3. No demo/sample data mode for most tabs when disconnected
4. No benchmark comparison for portfolio performance
5. No PDF tax statement export
6. No client-ready reporting templates
7. Error states are minimal (single line text, no illustrations)
8. No loading skeletons on most tabs

## P3 Low Priority

1. TanStack Query devtools button overlaps CTA on /welcome (dev only)
2. Theme inconsistency on /settings (dark content, light sidebar)
3. Console error spam when disconnected (should be silenced)

## What Works Well (from all 3 personas)

- SIP calculator is functional and accurate
- Tax tab implementation has correct Budget 2024 rates
- Overlap detection with sector concentration is unique
- Kill switch in 3 locations is good risk management
- Skill-level gating (beginner 5 tabs, advanced 12) is smart UX
- IPO tracker with historical data immediately useful
- Contextual education tips (30+) are helpful for beginners
- Hotkey customization system is professional-grade
- Overall design system is polished (typography, colors, accessibility)

## Recommendations for v0.4.0

1. Default new users to PAPER mode
2. Add demo/sample data fallback for all tabs when disconnected
3. Build multi-account UI (wire ditto package to terminal)
4. Add PDF/CSV export to Tax, Holdings, P&L reports
5. Add tooltips for all financial jargon
6. Fix welcome page — add tagline + value proposition
7. Remove placeholder text from /trade widgets
8. Add client reporting templates for wealth managers
