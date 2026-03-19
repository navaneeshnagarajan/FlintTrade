# FlintTrade — terminal

> Trading UI — widget-composable workspace with Dockview v5
> Port: 5173 | Branch: main (pre-release, no PRs)

## Quick Commands

```bash
npm install                                    # install deps
npm run dev                                    # dev server at localhost:5173
npm run build                                  # tsc --noEmit + vite build
npm run typecheck                              # tsc --noEmit only
npx vitest run                                 # all tests
npx vitest run src/path/to/file.test.ts        # single test file
npx vitest run -t "test name"                  # single test by name
```

## Architecture
- Single React app serving 3 personas via routes: /terminal, /invest, /learn, /setup
- Dockview v5 for widget-composable layout (floating, popout, tabs, serializable)
- 21 widgets (all TSX) + 7 full-page tools (all functional)
- Path alias: `@` → `src/`

## State Architecture
| Layer | Library | What |
|-------|---------|------|
| Real-time ticks | Jotai atoms | Per-instrument LTP/quote/depth via WebSocket |
| REST cache | TanStack Query v5 | Positions, orders, holdings, funds, option chain |
| App state | Zustand v5 | Connection, layout, settings, trading aggregates |
| Forms | react-hook-form + zod | Order entry, settings forms |

Boundary rule: data enters through ONE path only, never duplicated across stores.

## Vite Proxy (dev mode)
- `/api` → OpenAlgo REST (port 5000)
- `/ws` → OpenAlgo WebSocket (port 8765)
- `api.ts` uses empty base in dev (relative paths hit proxy), full host in production

## Key Files
- `src/chrome/widgetFactory.tsx` — widget registry (all 21 widgets + 7 tools)
- `src/services/api.ts` — OpenAlgo REST client with rate limiting
- `src/services/websocket.ts` — WebSocket client (authenticate → subscribe → parse nested data)
- `src/stores/connectionStore.ts` — host/apiKey/wsUrl (reads env vars on init)

## Multi-exchange support
- 10 exchange codes: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX, NSE_INDEX, BSE_INDEX
- MCX different hours (9:00-23:55), lot sizes per commodity
- CDS decimal strikes (USDINR 85.50)
- Crypto (Delta Exchange): 24/7, fractional lots, INR settlement

## Theme (locked)
- Background: #0a0a0f, Cards: #12121a, Borders: #1e1e2e
- Inter for UI, JetBrains Mono for numbers
- shadcn/ui dark theme with CSS variables
- Dockview dark theme overrides

## Rules
- TypeScript strict — no `any` types
- shadcn/ui components — no raw HTML controls
- Every widget is a Dockview panel registered in widgetFactory.tsx
- Absorb from repos before writing new code
- No mock/placeholder/fake data
- Test with Playwright after UI changes
