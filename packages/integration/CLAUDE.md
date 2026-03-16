# FlintTrade — integration

> TradingView, ChartInk, webhooks, Chrome extension, Excel, Amibroker, visual flow builder

## Absorbs
- openalgo-flow → Visual strategy builder (N8N-style, React)
- openalgo-chrome → Chrome extension with floating LE/LX/SE/SX buttons
- OpenAlgo-Excel → C#/Excel-DNA add-in, WebSocket streaming in cells
- OpenAlgoPlugin → Amibroker data plugin

## Depends on: core, engine

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Write tests in tests/test_integration.py
- Log work in root DEVLOG.md
- Branch: feature/integration-{description}
