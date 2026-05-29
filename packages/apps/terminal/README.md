# Terminal

> Single-page terminal — Dockview workspace with 82 widgets, 7 tools, 13 workspace presets, and 12 public routes.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source modular trading platform for Indian F&O, commodities, and crypto.

**Language:** TypeScript + React 19

## Public surface

- `src/main.tsx — entry point and route registration`
- `src/layout/widgetFactory.tsx — widget registry (83 entries)`
- `src/layout/workspacePresets.ts — 13 named presets`
- `src/services/api.ts — REST + WebSocket client`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
pnpm install
cd packages/apps/terminal
npm run typecheck
```

If you only want to use the package in isolation, `package.json` lists its dependencies, but the supported path is the root pnpm workspace.

## Tests

```bash
cd packages/apps/terminal
npm run test:base
npm run build
```

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md](../../../docs/DEVELOPER_GUIDE.md).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in [docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md). For end-user features it powers, see [docs/USER_GUIDE.md](../../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`contributing.md`](../../../contributing.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../../LICENSE) for the full text.
