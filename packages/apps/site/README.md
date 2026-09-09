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

## Hostinger / VPS Node hosting

This package is a Next.js app, not a static export. Shared PHP-only Hostinger
hosting cannot serve it. Use a VPS (or any generic Node host) that can run
`next start`.

Requirements:

- Node.js >= 22.22.2 (the monorepo engine floor)
- A clone of this repository (the site build reads generated docs and, on
  `prebuild`, the terminal demo under `packages/apps/terminal`)
- `pnpm` at the version pinned in the root `packageManager` field

Build and run from the repository root:

```bash
pnpm install
pnpm --filter @flinttrade/site build
pnpm --filter @flinttrade/site start
```

`next start` honours `PORT` when the host sets it.

### Environment

| Variable | Purpose |
| --- | --- |
| `FLINTTRADE_SITE_URL` | Public https origin for metadata, install one-liners, and the hosted MCP snippet. Also allow-lists that host on incoming requests. No trailing slash. |
| `NEXT_PUBLIC_SITE_URL` | Accepted alias for the same origin if `FLINTTRADE_SITE_URL` is unset. |
| `FLINTTRADE_SITE_ORIGINS` | Optional comma-separated extra https origins to trust on the request Host and on `/api/csp-report` `Origin` (for example apex and `www` during a cutover). Allow-list only — not the fallback origin. |
| `FLINTTRADE_SITE_SOURCE_SHA` | 40-character commit SHA for `/web-install.sh` and sibling redirect routes. Without it those routes answer 503. |
| `FLINTTRADE_SITE_ORIGIN` | Optional extra CSP-report `Origin`. Still accepted when `FLINTTRADE_SITE_URL` is set. Reports are also accepted from loopback, the canonical host, `VERCEL_URL`, and every origin on the configured allow-list. |

Set `FLINTTRADE_SITE_URL` to the custom domain on Hostinger. That host is then
trusted on the request, so MCP and install snippets use it. Add any extra
hostnames (`www`, a temporary Vercel alias) to `FLINTTRADE_SITE_ORIGINS`.
Without those variables, an unknown Host falls back to the current Vercel
production origin. Loopback request hosts are trusted during local `next dev`.

Vercel-only install/build scripts (`scripts/vercel-install.sh`,
`scripts/vercel-build.sh`, `vercel.json`) stay for the current Vercel deploy.
They are not required for `next build` / `next start`. `@vercel/speed-insights`
is a no-op unless the process is running on Vercel.

### Docs MCP

`/api/mcp` is a Node route. It will not work on static-only shared hosting.
Keep this app on a Node server if contributors should use the hosted MCP
endpoint.

## How this fits in

This package's role in the wider FlintTrade architecture is documented in
[docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md). For end-user features it powers, see
[docs/USER_GUIDE.md](../../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`contributing.md`](../../../contributing.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../../LICENSE) for the full text.
