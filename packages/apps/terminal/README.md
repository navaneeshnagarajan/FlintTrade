# Terminal

> Single-page terminal — FlexLayout workspace with home widgets, tools, routes, and workspace presets.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source self-hosted trading software monorepo built with Python, React, TypeScript, and Rust.

**Language:** TypeScript + React 19

## Public surface

- `src/main.tsx — entry point and route registration`
- `src/routes/HomeRoute.tsx — dashboard and home widget orchestration`
- `src/layout/workspacePresets.ts — named workspace presets`
- `src/services/api.ts — REST + WebSocket client`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
pnpm install
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

## Tests

```bash
pnpm --filter @flinttrade/terminal test:base
pnpm --filter @flinttrade/terminal build
```

Run one command per line. They work unchanged in bash, zsh and Windows
PowerShell — do not join them with `&&`, which Windows PowerShell 5.1 does not
support.

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md](../../../docs/DEVELOPER_GUIDE.md).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in
[docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md). For end-user features it powers, see
[docs/USER_GUIDE.md](../../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`contributing.md`](../../../contributing.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../../LICENSE) for the full text.
