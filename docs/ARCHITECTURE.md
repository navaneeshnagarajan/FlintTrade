# FlintTrade Architecture

```
┌─── FlintTrade (one repo) ────────────────────────────────┐
│                                                           │
│  terminal ─── dashboard ─── screener ─── ai              │
│      │             │            │          │              │
│               engine ◄──── backtest-engine                │
│                    │            │                         │
│               core ◄──── data ◄── historical             │
│                    │                                     │
│            automation ──── integration ── ditto           │
└────────────────────┼──────────────────────────────────────┘
                     │ REST API + WebSocket
              ┌──────┴───────┐
              │   OpenAlgo   │ infra/openalgo/ (git subtree)
              │  30+ brokers │
              └──────────────┘
```

## Safety Layers (engine)
1. Order validation (price ±5% LTP, qty limits)
2. Position limits (max 5 simultaneous, 60% margin)
3. Portfolio risk (net delta/vega limits)
4. Daily P&L limit (3% pause, 15% kill)
5. Kill switch (Telegram, UI, auto-trigger)
