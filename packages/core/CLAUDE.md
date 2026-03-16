# FlintTrade — core

> Framework, CLI, OpenAlgo API client, config, models, logger, exceptions

## Absorbs
- openalgo-python-library → SDK patterns, 80+ technical indicators
- All OpenAlgo SDKs (Node, Java, Go, Rust, .NET) → API pattern reference

## Depends on: none (foundation package)

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Write tests in tests/test_core.py
- Log work in root DEVLOG.md
- Branch: feature/core-{description}

## Configuration architecture
- `.env` → infrastructure only (OpenAlgo host, port, API key)
- `~/.flinttrade/workspace.json` → user preferences (paths, modules, UI, LLM, Telegram)
- `Workspace` class resolves paths cross-platform (Linux/macOS/Windows)
- `FlintTradeConfig` combines Settings (from .env) + Workspace (from workspace.json)
- Packages read config through FlintTradeConfig, never os.environ for paths

## Sandbox/Analyzer mode
- OpenAlgo has built-in Analyzer mode (sandbox): /api/v1/analyzer/toggle and /api/v1/analyzer/status
- FlintTrade must support toggling between live and sandbox mode
- OpenAlgo Analyzer mode provides virtual capital for paper trading
- All orders in sandbox mode go through OpenAlgo's analyzer, not real broker
- UI must show clear visual indicator (colored theme) when in sandbox mode
