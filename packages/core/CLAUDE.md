# FlintTrade — core

> Framework, CLI, OpenAlgo API client, config, models, logger, exceptions, app server, admin, security, monitoring

## Key Modules
- `app.py` — Flask app server (90+ routes, main entry point)
- `openalgo_client.py` — OpenAlgo REST client (45+ endpoints)
- `config.py` / `workspace.py` — Configuration and workspace management
- `models.py` / `exceptions.py` — Data models and exception hierarchy
- `cli.py` — CLI entry point
- `admin_routes.py` — Admin panel API routes
- `security.py` / `security_routes.py` — Security middleware and API routes
- `monitoring.py` / `monitoring_routes.py` — Health monitoring and API routes

## Absorbs
- openalgo-python-library → SDK patterns, 80+ technical indicators
- All OpenAlgo SDKs (Node, Java, Go, Rust, .NET) → API pattern reference

## Depends on: none (foundation package)

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Tests are in the `tests/` directory. Add new test files as needed.
- Update root CHANGELOG.md
- Branch: main (pre-release, all commits to main)

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
