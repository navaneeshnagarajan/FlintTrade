# @flinttrade/site

> Next.js + Fumadocs public website, generated documentation, contribution pages, llms files, and read-only docs MCP.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source self-hosted trading software monorepo built with Python, React, TypeScript, and Rust.

**Language:** TypeScript + React 19

## Public surface

- `src/app/page.tsx — public landing page`
- `scripts/generate-content.mjs — docs/package/release content generator`
- `src/lib/mcp/capabilities.ts — docs MCP tools and prompts`

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
pnpm --filter @flinttrade/site typecheck
pnpm --filter @flinttrade/site test
pnpm --filter @flinttrade/site build
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
