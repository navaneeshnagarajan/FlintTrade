# FlintTrade Dependencies

All version numbers below come from `--version` probes or from parsing manifest files at commit `93bbaa0`. Python package versions reflect what is **installed on this machine right now** (Windows 11 / Python 3.14.3); they may differ from the minimums declared in each `pyproject.toml`.

## Runtime Dependencies

| Runtime | Version | Notes |
|---|---|---|
| Python | **3.14.3** | `pyproject.toml` declares `target-version = "py312"` → drift (see STATUS.md) |
| Node.js | 24.14.0 | |
| npm | 11.9.0 | |
| Rust (cargo) | 1.94.0 (85eff7c80 2026-01-15) | Required for `packages/tick-engine` and `packages/desktop/src-tauri` |
| make | **not installed** on this host | `make test` / `make status` etc. do not work |
| TA-Lib | **not installed** (Python side) | `import talib → ModuleNotFoundError`; declared as optional extra in `packages/indicators/pyproject.toml` |
| DuckDB (Python) | 1.4.4 | Used by `flint-core`, `flint-data`, `flint-engine`, `flint-historical` |

### Installed Python package versions (sample)

| Package | Installed | Minimum declared |
|---|---|---|
| httpx | 0.28.1 | >=0.27.0 |
| pydantic | 2.12.5 | >=2.0 |
| numpy | 2.4.2 | >=1.26.0 |
| flask | 3.1.3 | >=3.0 |
| websockets | 15.0.1 | >=13.0 |
| cryptography | 46.0.5 | >=46.0.0 |
| structlog | 25.5.0 | >=24.1.0 |
| duckdb | 1.4.4 | >=1.0.0 |

Flask emits a deprecation warning: `'__version__' attribute is deprecated and will be removed in Flask 3.2` — affects any code reading `flask.__version__`.

## Python packages — top by usage across the 13 `pyproject.toml` files

```
10x  flint-core            (internal package, workspace root)
10x  pydantic
 9x  flask
 8x  httpx
 7x  numpy
 5x  duckdb
 3x  flint-indicators      (internal)
 3x  websockets
 3x  cryptography
 2x  pandas
 2x  pyotp
 2x  numba
 1x  chromadb
 1x  sentence-transformers
 1x  lightgbm
 1x  catboost
 1x  joblib
 1x  feedparser
 1x  PyYAML
 1x  python-telegram-bot
 1x  apscheduler
 1x  scipy
```

## npm packages — from `packages/terminal/package.json` (33 deps + 21 dev) and `packages/desktop/package.json` (1 dep + 1 dev)

Runtime (terminal):

```
@fontsource-variable/inter           ^5.2.8
@fontsource-variable/jetbrains-mono  ^5.2.8
@glideapps/glide-data-grid           ^6.0.3
@hookform/resolvers                  ^5.2.2
@tanstack/react-query                ^5.91.0
@tanstack/react-table                ^8.21.3
@tremor/react                        ^3.18.7
@xyflow/react                        ^12.10.2
class-variance-authority             ^0.7.1
clsx                                 ^2.1.1
cmdk                                 ^1.1.1
date-fns                             ^4.1.0
dockview                             ^5.1.0
dockview-react                       ^5.1.0
framer-motion                        ^12.38.0
geist                                ^1.7.0
jotai                                ^2.18.1
lightweight-charts                   ^5.0.0
lightweight-charts-indicators        ^0.4.0
lucide-react                         ^0.577.0
plotly.js-dist-min                   ^3.4.0
qrcode.react                         ^4.2.0
radix-ui                             ^1.4.3
react                                ^19.0.0
react-dom                            ^19.0.0
react-hook-form                      ^7.71.2
react-plotly.js                      ^2.6.0
react-resizable-panels               ^4.7.6
react-router-dom                     ^7.13.1
recharts                             ^3.8.0
tailwind-merge                       ^3.5.0
zod                                  ^4.3.6
zustand                              ^5.0.12
```

Dev (terminal):

```
@playwright/test                     ^1.59.1
@sentry/react                        ^8.55.1
@tailwindcss/vite                    ^4.2.1
@tanstack/react-query-devtools       ^5.91.3
@testing-library/dom                 ^10.4.1
@testing-library/jest-dom            ^6.9.1
@testing-library/react               ^16.3.2
@testing-library/user-event          ^14.6.1
@types/node                          ^25.5.0
@types/react                         ^19.2.14
@types/react-dom                     ^19.2.3
@types/react-plotly.js               ^2.6.4
@vitejs/plugin-react                 ^4.0.0
jsdom                                ^29.0.0
marked                               ^17.0.5
react-responsive-carousel            ^3.2.23
rollup-plugin-visualizer             ^7.0.1
tailwindcss                          ^4.0.0
typescript                           ^5.9.3
vite                                 ^6.0.0
vitest                               ^3.0.0
```

Desktop (Tauri wrapper):

```
@tauri-apps/api                      (runtime)
@tauri-apps/cli                      (dev)
```

## Rust dependencies

### `packages/tick-engine/Cargo.toml`

```
pyo3 = { version = "0.24", features = ["abi3-py312"] }
rayon = "1.10"
thiserror = "2.0"
```

Features: `extension-module` (default) → builds a Python extension via `maturin`. Also exposes `rlib` for Cargo tests on Windows.

### `packages/desktop/src-tauri/Cargo.toml`

```
tauri            = { version = "2" }
tauri-build      = { version = "2" }
tauri-plugin-shell = "2"
keyring          = "3"
axum             = "0.7"
tower-http       = { version = "0.5", features = ["cors", "trace"] }
tokio            = { version = "1", features = ["full"] }
reqwest          = { version = "0.12", features = ["json", "rustls-tls"], default-features = false }
serde            = { version = "1.0", features = ["derive"] }
chrono           = { version = "0.4", features = ["serde"] }
chrono-tz        = "0.10"
thiserror        = "1.0"
```

## Git submodules

All three are present in `infra/` and updated through Wave 5.

| Submodule | Path | Ref (git describe) |
|---|---|---|
| OpenAlgo | `infra/openalgo/` | `openalgo-stability-fix-21-g0f1ee545` |
| OpenClaw | `infra/openclaw/` | `v2026.4.19-beta.2-6-g8c4ecf42df` |
| AlgoMirror | `infra/algomirror/` | `algomirror-postgres-10-gfa063e2` |

## External Services

| Service | Detail |
|---|---|
| Broker | **UNKNOWN — needs manual verification.** No broker is declared in repo-tracked files. CLAUDE.md implies "Dhan/other" and OpenAlgo holds the credentials in `infra/openalgo/.env` (not committed). |
| LLM | **UNKNOWN — needs manual verification.** `~/.flinttrade/workspace.json` is absent on this host, so no provider is configured in the workspace. CLAUDE.md references LM Studio + Qwen 3.5 9B Q4_K_M, but that is an environmental observation rather than a committed value. |
| Database (workspace) | `~/.flinttrade/` contains: `activity.db`, `auth.db`, `credentials.db`, `error_log.duckdb`, `latency_log.duckdb`, `security.db`, `traffic_log.duckdb`, plus `contracts/`, `data/`, `sandbox/`, `archive/`, and `jwt_secret`. |
| DuckDB files | `error_log.duckdb`, `latency_log.duckdb`, `traffic_log.duckdb` (DuckDB 1.4.4) + `security.db` (also DuckDB, held open by PID 26840 at report time — caused pytest to fail). |
| SQLite files | `activity.db`, `auth.db`, `credentials.db` (extensions suggest SQLite but content was not verified for this report). |
| OpenAlgo | Reachable at `http://127.0.0.1:5000` per CLAUDE.md; **not running** on this host at report time (`curl -m 2` got no response). |

## `.env.example` (committed)

4 required variables, everything else commented:

```
OPENALGO_HOST=
OPENALGO_PORT=
OPENALGO_API_KEY=
OPENALGO_WS_PORT=

# FLINTTRADE_PORT=5100
# MASTER_PASSWORD=
# CORS_ORIGINS=http://127.0.0.1:5173
```
