# Hostinger public-site local build/deploy manifest

**Status:** STAGING-PREP / NON-PRODUCTION / PREPARATION ONLY
**Scope:** Repository-local build commands, version pins, and artifact layout for a Hostinger-compatible **public-site** path (`@flinttrade/site` only).
**Not in scope:** Hostinger login, API tokens, credentials, DNS, subdomains, uploads, live deploys, account/payment actions, broker/trading/terminal mutation, or any production cutover.

This file is a local review artifact for PLAN.md reversible-sequence item 3:

> public-plane-only Hostinger staging prerequisites/configuration, with no production domain, DNS, account/payment, secret, broker or trading mutation;

Any Hostinger account, credential, secret, or deployment action still requires **separate explicit authorisation** before execution (PLAN.md gate note). This manifest does **not** authorise or perform those steps.

**Related prep doc:** `docs/setup/hostinger-local-staging-prep.md` (env/health/rollback matrix).
**Worktree HEAD at authoring:** `141766eb33b066fa78f28425a39ff8f4f741ab88`
**Requested base:** `e039d38685ef569f856f73edd2185aae39e275f8`

All versions and commands below are taken from repo lock/workspace/package files. No invented runtime pins.

---

## 1. Pinned runtimes (exact, repo-sourced)

| Pin | Exact value | Source |
|---|---|---|
| package manager | `pnpm@10.34.5` (integrity suffix on `packageManager` field) | root `package.json` → `packageManager` |
| packageManager full field | `pnpm@10.34.5+sha512.a4ee05f2f73658255bd6a89859c065a45c28a57daefae2c893a168ee2b73168c37b91e83e57ea67654ad03f03031746430e8bce38e362e042605fb8abc80192e` | root `package.json` |
| Node engines | `>=22.22.0` | root `package.json` → `engines.node` |
| lockfile format | `lockfileVersion: '9.0'` | `pnpm-lock.yaml` header |
| pnpm self-manage | `managePackageManagerVersions: false` | `pnpm-workspace.yaml` |
| pnpm strict pin | `packageManagerStrictVersion: true` | `pnpm-workspace.yaml` |
| pnpm floor (comment) | `>= 10.26.0` for `allowBuilds` to be enforced | `pnpm-workspace.yaml` comment |
| Site package name | `@flinttrade/site` | `packages/apps/site/package.json` → `name` |
| Site package version | `0.0.1` (private) | `packages/apps/site/package.json` |
| Next (resolved in lock) | `16.2.12` | `pnpm-lock.yaml` (`next@16.2.12` for site graph) |
| Next (package range) | `^16.2.12` | `packages/apps/site/package.json` |
| React / React DOM (package range) | `^19.2.8` | `packages/apps/site/package.json` |

**Not present in repo root (do not invent):** `.nvmrc`, `.node-version`, `.tool-versions`, Volta pins.

**Practical install form** (strips the `+sha512…` integrity suffix the same way `packages/apps/site/scripts/vercel-pnpm.sh` does for `npx --package`):

```bash
npx --yes pnpm@10.34.5 install --frozen-lockfile
```

Workspace packages (from `pnpm-workspace.yaml` / root `workspaces`):

- `packages/core/design-system`
- `packages/apps/terminal`
- `packages/apps/site`
- `packages/apps/desktop`

Site depends on `@flinttrade/design-system` via `file:../../core/design-system`, so the workspace install is the supported path (see `packages/apps/site/README.md`).

---

## 2. Exact local build commands (`@flinttrade/site`)

Run from the **monorepo root**. One command per line (no `&&` chaining — Windows PowerShell 5.1 compatibility, per AGENTS.md / site README).

### 2.1 Recommended reproducible form (npx-pinned pnpm)

```bash
npx --yes pnpm@10.34.5 install --frozen-lockfile
npx --yes pnpm@10.34.5 --filter @flinttrade/site test
npx --yes pnpm@10.34.5 --filter @flinttrade/site typecheck
npx --yes pnpm@10.34.5 --filter @flinttrade/site build
```

### 2.2 Documented filter form (when root already has the pinned pnpm on PATH)

From `packages/apps/site/README.md`:

```bash
pnpm --filter @flinttrade/site typecheck
pnpm --filter @flinttrade/site test
pnpm --filter @flinttrade/site build
```

Prefer the §2.1 `npx --yes pnpm@10.34.5 …` form for Hostinger staging-prep reproducibility: root `packageManagerStrictVersion: true` rejects a mismatched pnpm, and workspace `managePackageManagerVersions: false` means pnpm will not auto-fetch its pin.

### 2.3 What `build` actually runs

From `packages/apps/site/package.json` scripts (verbatim):

| Lifecycle | Command |
|---|---|
| `prebuild` | `npm run generate:content && npm run generate:demo` |
| `build` | `next build --webpack` |
| `generate:content` | `node scripts/generate-content.mjs && fumadocs-mdx` |
| `generate:demo` | `node scripts/generate-demo.mjs` |
| `pretest` | `npm run generate:content` |
| `test` | `vitest run` |
| `pretypecheck` | `npm run generate:content` |
| `typecheck` | `tsc --noEmit` |
| `predev` | `npm run generate:content` |
| `dev` | `next dev --port 3000` |
| `mcp:stdio` | `node scripts/generate-content.mjs >/dev/null && tsx src/mcp/stdio.ts` |

So `pnpm --filter @flinttrade/site build` expands to:

1. Content generation (`scripts/generate-content.mjs` + `fumadocs-mdx`)
2. Demo app generation (`scripts/generate-demo.mjs`)
3. `next build --webpack`

### 2.4 Framework / build config facts (repo-sourced)

**`packages/apps/site/next.config.mjs`:**

- `reactStrictMode: true`
- `allowedDevOrigins: ['127.0.0.1']`
- `transpilePackages: ['@flinttrade/design-system']`
- `turbopack.root` = monorepo root
- Rewrites: `/demo-app` and `/demo-app/:path*` → `/demo-app/index.html`
- CSP headers scoped to `/demo-app/:path*`
- Wrapped with `createMDX()` from `fumadocs-mdx/next`
- **No** `output: 'export'`
- **No** `output: 'standalone'`

**`packages/apps/site/vercel.json`** (existing public deploy lane reference only — not a Hostinger config):

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "buildCommand": "sh scripts/vercel-build.sh",
  "installCommand": "sh scripts/vercel-install.sh",
  "framework": "nextjs"
}
```

Vercel helpers under `packages/apps/site/scripts/`:

- `vercel-pnpm.sh` — reads root `packageManager`, strips `+sha512…`, runs `npx --yes --package "$pin" -- pnpm "$@"`
- `vercel-install.sh` — from site dir, cd repo root, ensure root `.pnpmfile.cjs`, then pinned `install --frozen-lockfile --reporter=append-only`
- `vercel-build.sh` — pinned `pnpm run build` while remaining in `packages/apps/site`

These scripts are the template for “how the repo already freezes pnpm for a remote builder”; they are **not** Hostinger deploy scripts and are not executed by this prep.

---

## 3. Expected build output artifact layout

After a successful `pnpm --filter @flinttrade/site build`, artifacts live under `packages/apps/site/`.

### 3.1 Primary Next.js output: `.next/` (default `distDir`)

Observed layout on a successful local build in this worktree (illustrative structure; hashed build id changes per build):

```text
packages/apps/site/.next/
  BUILD_ID                          # single-line build id (e.g. 6appXXOeIizKkzNkZ151B)
  build-manifest.json
  app-path-routes-manifest.json
  prerender-manifest.json
  routes-manifest.json
  required-server-files.json        # Node hosting needs this + server tree
  required-server-files.js
  export-marker.json                # hasExportPathMap: false (static export not used)
  package.json
  server/
    app/                            # App Router server bundles
    chunks/
    pages/
    middleware.js
    *.manifest.json
  static/
    <BUILD_ID>/                     # build-id–scoped assets
    chunks/                         # hashed JS chunks
    css/
    media/
  cache/                            # local build cache (not a deploy payload)
  diagnostics/
  types/
```

`export-marker.json` in this tree reports:

```json
{
  "version": 1,
  "hasExportPathMap": false,
  "exportTrailingSlash": false,
  "isNextImageImported": false
}
```

There is **no** `packages/apps/site/out/` directory after build — static HTML export is not enabled.

### 3.2 Public static inputs (copied/served alongside the app)

```text
packages/apps/site/public/
  demo-app/                 # full-page terminal demo SPA (index.html + assets)
    index.html
    assets/
    fonts/
    favicon.svg
    logo.svg
  flinttrade/
    logo.svg
    screenshots/
  llms.txt
  llms-full.txt
```

Generated/compiled content used by the build (not the final host root, but required at build time):

- `packages/apps/site/.source/` — fumadocs-mdx compiled sources (`server.ts`, `browser.ts`, `dynamic.ts`, `source.config.mjs`)
- `packages/apps/site/content/docs/` — docs corpus input to fumadocs
- `packages/apps/site/src/generated/` — generator outputs consumed by the app

### 3.3 Hostinger-compatible staging shape (prep notes only)

These are **staging-prep compatibility notes**, not live Hostinger product claims and not an instruction to deploy.

| Hosting mode | Compatible with current repo config? | Artifact expectation |
|---|---|---|
| **Node.js app hosting** (run Next in Node) | **Yes — matches current config** | Keep `packages/apps/site` install graph + `.next/` server+static output; start with the package’s Next runtime (`next start` after build). Requires Node satisfying `engines.node` `>=22.22.0`. |
| **Pure static file hosting** (`out/` HTML export) | **No — not enabled** | Would need `output: 'export'` in `next.config.mjs`, which this prep **does not** add. No `out/` is produced today. |
| **Static-only upload of `.next/static` alone** | **Insufficient** | `.next/static` is only client assets; App Router HTML/RSC still needs the Node server side (or a true static export, which is off). |

**Label any future authorised staging slot** (when separately approved) as `STAGING-PREP` / `NON-PRODUCTION`. Do not attach production domains, production DNS, or production traffic assumptions to these artifacts.

**Minimal local post-build checks (local only):**

```bash
# From packages/apps/site after a green build
test -f .next/BUILD_ID
test -d .next/static
test -d .next/server
test -f public/llms.txt
```

Optional local Node serve check (still local; not a Hostinger action):

```bash
npx --yes pnpm@10.34.5 --filter @flinttrade/site exec next start --port 3000
```

Then verify with a local client against `http://127.0.0.1:3000` only.

### 3.4 What is intentionally excluded from the deploy payload

Do **not** treat these as Hostinger upload roots:

- `node_modules/` (reinstall on the Node host from the frozen lock, or use the host’s Node install flow — not defined here)
- `.next/cache/`
- Source trees outside the public-site path when only serving the site
- Any `.env` with real secrets (none required for basic public-site build per `docs/setup/hostinger-local-staging-prep.md`)
- Terminal, desktop, gateway, broker, or trading packages

---

## 4. Env contract (public-site build — summary)

Full contract: `docs/setup/hostinger-local-staging-prep.md` §2.

- **Required env vars for basic build + local serve:** none (repo-sourced claim in the prep doc).
- Vars that appear in site code/scripts (optional / platform / local defaults — not Hostinger secrets):

| Variable | Role (repo reference) |
|---|---|
| `NODE_ENV` | `src/proxy.ts` |
| `FLINTTRADE_GLITCHTIP_URL` | `src/proxy.ts` |
| `FLINTTRADE_SITE_ORIGIN` | `src/app/api/csp-report/route.ts` (default `http://127.0.0.1:3000`) |
| `FLINTTRADE_REPO_ROOT` | `scripts/generate-content.mjs` |
| `VERCEL_GIT_COMMIT_SHA` / `VERCEL_GIT_COMMIT_REF` | `scripts/generate-content.mjs` (Vercel platform; fallback ref `'main'`) |
| `FLINTTRADE_SKIP_DEMO=1` | `scripts/generate-demo.mjs` |
| `npm_package_version` | fallback in `scripts/generate-content.mjs` |

Root `.env.example` has **no** Hostinger- or `NEXT_PUBLIC_*`-specific site keys in this worktree.

---

## 5. Explicit non-production rules

1. This manifest is **STAGING-PREP / NON-PRODUCTION** only.
2. No production domain names, DNS records, SSL cutovers, or live Hostinger actions are authorised by this document.
3. No Hostinger credentials, API tokens, or account/payment steps are included or implied.
4. No broker, trading, terminal, or order-path mutation is part of this public-site path.
5. PLAN.md item 3 gate still applies: separate explicit authorisation before any Hostinger account/credential/deploy action.
6. Immediate rollback for this prep is local worktree/branch discard — see `docs/setup/hostinger-local-staging-prep.md` §3 and tone reference `flinttrade-design/baselines/rollback-runbook-2026-05-24.md` (local discard precedence).

---

## 6. Source index (traceability)

| Fact area | Files |
|---|---|
| pnpm + Node pins | `package.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml` |
| Site scripts / deps | `packages/apps/site/package.json` |
| Filter commands | `packages/apps/site/README.md` |
| Next config | `packages/apps/site/next.config.mjs` |
| Existing remote build lane (Vercel reference) | `packages/apps/site/vercel.json`, `packages/apps/site/scripts/vercel-*.sh` |
| Env / health / rollback prep | `docs/setup/hostinger-local-staging-prep.md` |
| Gate text | `PLAN.md` (reversible-sequence item 3) |

---

**End of manifest.** Local review artifact only. No production references; no invented runtime versions.
