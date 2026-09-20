# Technology Stack and Dependencies

FlintTrade combines a React trading terminal, a Python backend, a Rust tick
engine, an Electron desktop shell, and a Next.js documentation site. This guide
explains what the main dependencies do and where to find their versions.

## Where versions come from

The version families below describe the architecture. The linked manifests and
lockfiles record the exact dependency requirements and resolved versions for
the same source revision; they are the authoritative inventory. A requirement
such as `^19.2.8` or `>=3.0` is a permitted range, not the exact installed version.

| Version question | Source of truth |
|---|---|
| Which FlintTrade release is this? | [VERSION](../VERSION); this is separate from dependency versions. |
| Which Python and Node versions are supported? | [flint.toml](../flint.toml), `[requirements]`: supported minimums and development targets are separate. See [Compatibility](COMPATIBILITY.md). |
| Which JavaScript packages does each app require? | The [terminal](../packages/apps/terminal/package.json), [desktop](../packages/apps/desktop/package.json), [site](../packages/apps/site/package.json), and [design-system](../packages/core/design-system/package.json) manifests. |
| Which JavaScript versions are resolved? | [pnpm-lock.yaml](../pnpm-lock.yaml), including each workspace importer; shared overrides live in [pnpm-workspace.yaml](../pnpm-workspace.yaml). |
| Which Python versions are resolved? | [uv.lock](../uv.lock). [requirements.lock](../requirements.lock) is its frozen export for the pip installation path. Each package's `pyproject.toml` declares its direct requirements. |
| Which Rust versions are resolved? | [Cargo.toml](../packages/core/ticks/Cargo.toml) and [Cargo.lock](../packages/core/ticks/Cargo.lock). |
| Which package manager is used? | The root [package.json](../package.json) `packageManager` field pins pnpm. Installer tool downloads have separate verified pins in the [bootstrap manifest](../packages/apps/desktop/resources/bootstrap/tool-manifest.json). |

The terminal's **Settings → About** shows selected frontend dependency requirements and
links to this guide. They are declared version ranges from that build; the lockfile records exact
resolved versions. They do not
report the running backend's Python packages or the installed Electron shell.
For a reproducible dependency inventory, inspect the lockfiles at the commit
used to build that installation. The public docs follow the site's source
revision and may be newer than an installed app.

## Trading terminal and shared UI

| Dependency | What FlintTrade uses it for |
|---|---|
| React 19 and React DOM | Rendering the terminal routes, widgets, forms, and shared design-system components. |
| TypeScript and Vite 8 | Static checking, development server, and production terminal bundling. TypeScript is a build tool; the site can use a different compiler version from the terminal. |
| Tailwind CSS 4, Radix UI, shadcn/ui patterns | Styling, design tokens, and accessible interactive primitives. shadcn components are owned source files, not a single runtime package with one version. |
| FlexLayout 0.11 and FINOS FDC3 2 | Dockable panels and saved workspaces; in-process symbol linking and widget intents. |
| Lightweight Charts 5 | Price charts through FlintTrade's shared chart runtime and theme. [TradingView attribution](REFERENCES.md) is also visible in About. |
| FINOS Perspective 3, Glide Data Grid 6, TanStack Table 9 | Portfolio pivot analytics, canvas grids, and headless sortable/filterable tables respectively. |
| Zustand 5, Jotai 2, TanStack Query 5 | UI/derived state, streaming quote atoms, and cached REST responses respectively. See the [state boundaries](ARCHITECTURE.md#state-architecture). |
| React Router 8, React Hook Form 7, Zod 4 | Route loading, form state, and runtime validation. |
| Three.js, React Three Fiber, Drei, Plotly | Specialist 3D and analytical visualisations. Shared standard charts use FlintTrade's design-system primitives. |
| Lucide React, Framer Motion, date-fns | Icons, interface motion, and date formatting/calculations. |

Direct requirements are in the [terminal manifest](../packages/apps/terminal/package.json)
and [shared design-system manifest](../packages/core/design-system/package.json).

## Python backend, data, and integrations

| Dependency | What FlintTrade uses it for |
|---|---|
| Python, Flask, Waitress | Backend services, HTTP routes, and the local WSGI server. Flask extensions provide CORS handling and request limits. |
| Pydantic, httpx, websockets | Validated data models, outbound HTTP clients, and streaming WebSocket connections. |
| SQLite, DuckDB, PyArrow | Transactional local state, analytical queries, and columnar/Parquet data respectively. SQLite is provided by Python's standard library. |
| NumPy, pandas, SciPy | Indicator arrays, historical-data processing, numerical statistics, and backtest analytics. |
| structlog and Sentry SDK | Structured service logs and configured error reporting. |
| argon2-cffi, cryptography, PyJWT, pyotp | Password hashing, encrypted credential storage, signed authentication tokens, and time-based one-time passwords. |
| DhanHQ, Upstox, Kotak Neo, Groww SDKs | Native broker integration adapters. An SDK upgrade does not establish live-order readiness; broker capabilities and order-safety gates remain separate. |
| LightGBM, CatBoost, joblib | Model training, inference, and model persistence for analysis/signals. The AI package's optional `ml` extra adds scikit-learn and Optuna support. |
| pypdf | PDF ingestion for the optional AI `rag` extra. The vector store uses local SQLite/NumPy; local model execution uses the managed Ollama service. |

Start with the [core manifest](../packages/core/core/pyproject.toml),
[gateway manifest](../packages/integrations/gateway/pyproject.toml), and
[AI manifest](../packages/services/ai/pyproject.toml). The
[package map](DEVELOPER_GUIDE.md#1-repository-layout) identifies the remaining
services. Optional extras are distinct from the default runtime installation.

## Desktop, website, and native processing

| Surface | Dependencies and purpose | Direct requirements |
|---|---|---|
| Desktop | Electron provides the sandboxed native window, tray, and local source lifecycle. Electron Builder creates installers; archive and signature libraries support verified bootstrap/update handling. | [Desktop package](../packages/apps/desktop/package.json) |
| Website | Next.js 16 and React 19 serve the public site. Fumadocs renders repository docs; MCP libraries expose the read-only documentation/contribution interface. | [Site package](../packages/apps/site/package.json) |
| Tick engine | Rust with PyO3 exposes the native engine to Python. Rayon provides parallel processing; thiserror defines Rust errors. | [Tick engine crate](../packages/core/ticks/Cargo.toml) |

The desktop shell and the managed source checkout update separately. Updating
JavaScript or Python source dependencies does not update an already installed
Electron shell. See [Desktop App](DESKTOP.md).

## Development dependencies and maintenance

Vitest and Testing Library test TypeScript/React behaviour; Playwright exercises
browser workflows. pytest and its plugins test Python; Ruff checks Python style
and correctness; ESLint checks frontend code. These tools support development
and CI rather than broker connectivity or strategy execution.

[Dependabot configuration](../.github/dependabot.yml) covers JavaScript, Python,
Rust, and GitHub Actions. Review a proposed bump against the owning package and
its actual call sites, keep the manifests and lockfiles consistent, and run the
relevant checks described in [CI](CI.md). A major upgrade can require code or
configuration changes even when the lockfile resolves successfully.

When a dependency changes, update this guide if its role or version family has
changed, and regenerate the dependency notice:

```bash
python scripts/generate-notice.py
```

[notice](../notice) contains project attribution; [notice.generated](../notice.generated)
records lockfile fingerprints. Dependency licences remain with their respective
authors. Historical release notes describe the versions shipped at that time.
