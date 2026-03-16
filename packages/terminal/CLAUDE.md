# FlintTrade — terminal

> Trading UI — scalper, option chain, 50-level DOM, OI analysis, charts

## Dev server port: 3001

## Absorbs
- fastscalper-tauri → Rust scalper UI patterns, one-click execution
- OpenTerminal → Open-source Indian trading terminal patterns
- openalgo-pinets → PineTS indicators, TradingView Lightweight Charts v5
- fyers-websockets → 50-level DOM analyzer, order flow analytics, TBT data
- tradingview-yahoo-finance → TradingView chart integration patterns
- openalgo-chart (crypt0inf0) → Chart component patterns

## Rules
- React 19, Vite, Tailwind CSS, TradingView Lightweight Charts v5
- Recharts for non-financial charts, Lucide React for icons
- Branch: feature/terminal-{description}

## Multi-exchange support
- Must handle ALL 10 exchange codes: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX, NSE_INDEX, BSE_INDEX
- MCX has different trading hours (9:00 AM - 11:55 PM) — charts must handle this
- MCX lot sizes are different per commodity (e.g., GOLD=1kg, GOLDM=100g, CRUDEOIL=100 barrels)
- Currency options (CDS) have decimal strike prices (e.g., USDINR 85.50)
- UI must show exchange-appropriate information (equity P&L vs commodity P&L)

## Crypto support (Delta Exchange)
- Must display crypto perpetual funding rates
- 24/7 charts — no market open/close markers
- Crypto lot sizes: fractional BTC/ETH (e.g., 0.001 BTC)
- Show liquidation price for leveraged positions (up to 100x)
- INR settlement display (not USD/USDT)

## Keyboard shortcuts (from TradePulse v0.3 architecture)
| Key | Action |
|---|---|
| F1 | Dashboard |
| F2 | Scalper |
| F3 | Option Chain |
| F4 | Futures OI |
| F5 | Strategy |
| F6 | Backtest |
| F7 | Portfolio |
| F8 | Journal |
| F9 | Settings |
| ↑ / ↓ | Buy / Sell |
| B / S | Quick buy / Quick sell |
| X | Exit all positions |
| C | Cancel all orders |
| 1-9 | Strike offset selection |
| Space | Toggle SL trail |
| Ctrl+K | Command palette |
| Tab | Switch panels |
| Enter | Confirm order |
| Esc | Cancel/close |

## UI reference
TradePulse v0.3 was a working 9-module React prototype. Use it as the design blueprint.
Modules: Dashboard, Scalper (3 synced TradingView charts), Option Chain, Futures OI Quadrant, Strategy Manager, Backtest, Portfolio, Journal, Settings.
