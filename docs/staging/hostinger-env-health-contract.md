# Public-site environment and health contract (Hostinger staging prep)

**Status:** PREPARATION / NON-PRODUCTION / STAGING-PREP ONLY
**Surface:** `@flinttrade/site` (docs / marketing / public website) only
**Audience:** Local staging-prep operators and machine-checkable readiness gates

This document is the **authoritative environment + health contract** for public-plane Hostinger staging **preparation**. It covers only the public site env surface and checks that run **on the local machine** after install / build / local serve.

## Hard scope boundaries

**In scope**

- Environment variables referenced by `packages/apps/site` (runtime, build scripts, Next routes).
- Local readiness checks after `pnpm` install, test, typecheck, build, and optional local serve.
- Explicit fail-closed rules that block any *future* remote staging step.

**Out of scope (do not document or require here)**

- Backend, broker, gateway, OpenAlgo, vault, order-path, kill-switch, or trading runtime env vars.
- Terminal product env (`VITE_*` and similar) except the note that demo generation **strips** `VITE_*` so deployment secrets are not baked into `public/demo-app`.
- Live Hostinger control panel, APIs, FTP/SFTP, DNS, SSL, account, payment, or deploy commands.
- Production domain claims, production secrets, or committed real `.env` values.

Companion prep overview (build commands, rollback tone): `docs/setup/hostinger-local-staging-prep.md`.

---

## 1. Environment surface (public site only)

### 1.1 Classification legend

| Class | Meaning |
|---|---|
| **Required** | Must be set and valid before the named readiness class is considered green. Missing or invalid → **fail-closed** for that class. |
| **Optional** | Safe to omit; code has a documented default or degrades without aborting the basic docs build. |
| **Platform-injected** | Set automatically by a host/runtime (e.g. Next sets `NODE_ENV`). Do not invent Hostinger mappings here. |
| **Forbidden for this prep** | Must not be introduced, committed, or required for public-site staging prep. |

### 1.2 Required environment variables

#### Class A — Basic docs/marketing build + static artifact readiness

| Variable | Required? | Notes |
|---|---|---|
| *(none)* | — | A successful frozen install + site `build` needs **no** operator-supplied env vars. Content generation resolves the monorepo root relative to `packages/apps/site` when `FLINTTRADE_REPO_ROOT` is unset. |

**Contract statement:** For Class A readiness, the required-env set is the empty set. Absence of any optional var below is **not** a fail-closed condition for Class A.

#### Class B — Install-script redirect routes (feature-gated readiness)

These routes (`/install.sh`, `/install.ps1`, `/web-install.sh`, `/web-install.ps1`, uninstall variants) pin bootstrap scripts to an immutable commit SHA via `siteSourceSha()` in `packages/apps/site/src/lib/install-script-routes.ts`.

| Variable | Required for Class B? | Valid form | Behaviour if missing/invalid |
|---|---|---|---|
| `FLINTTRADE_SITE_SOURCE_SHA` | **Yes** (preferred), **or** | Exactly 40 lowercase/uppercase hex chars (`^[0-9a-fA-F]{40}$`); trimmed then lowercased | Route returns **HTTP 503** plain text: install-script source unavailable |
| `VERCEL_GIT_COMMIT_SHA` | **Yes** as fallback only | Same 40-hex form | Used only if `FLINTTRADE_SITE_SOURCE_SHA` is unset/invalid |

**Contract statement:** Class B is green only when at least one of the two yields a valid 40-char hex SHA. Invalid length, empty string, or non-hex → treat as missing → fail-closed for Class B (and for any staging label that claims install-script redirects work).

Class A can still be green while Class B is red.

### 1.3 Optional environment variables

| Variable | Where used | Default if unset | Effect |
|---|---|---|---|
| `FLINTTRADE_REPO_ROOT` | `scripts/generate-content.mjs` | Monorepo root three levels above `packages/apps/site` | Override repo root for content/docs generation (e.g. unusual checkout layouts). |
| `VERCEL_GIT_COMMIT_SHA` | `generate-content.mjs` (ref metadata); also Class B fallback | Content path falls through to `VERCEL_GIT_COMMIT_REF` then `'main'` | Labels generated content with a commit; not required for build success. |
| `VERCEL_GIT_COMMIT_REF` | `generate-content.mjs` | `'main'` | Branch/ref label for generated content when SHA unset. |
| `npm_package_version` | `generate-content.mjs` VERSION fallback | `'0.0.0-dev'` | Package manager may inject; build does not require operator to set it. |
| `FLINTTRADE_SKIP_DEMO` | `scripts/generate-demo.mjs` | unset (demo builds) | Set to `1` to skip terminal demo bundle into `public/demo-app`. Build continues; `/demo-app` routes will 404 until demo is generated. |
| `FLINTTRADE_SITE_ORIGIN` | `src/app/api/csp-report/route.ts` | `http://127.0.0.1:3000` | Expected browser `Origin` for CSP report POSTs. Mismatch → **403** on that API only. |
| `FLINTTRADE_GLITCHTIP_URL` | `src/proxy.ts` (`buildCsp`) | unset (`null`) | When set, added to CSP `connect-src`. When unset, CSP omits it. Does **not** abort request handling. |
| `NODE_ENV` | `src/proxy.ts` (CSP `script-src`) | Set by Next (`development` / `production`) | In development, CSP allows `'unsafe-eval'`. Operator should not force production values during local dev. |
| `NEXT_PUBLIC_*` | *(none hard-coded in current public surface)* | — | Reserved for future public client config. **None required** for current staging prep. Do not invent analytics keys for this contract. |

### 1.4 Platform / tooling pins (not secrets; still contractual)

These are **workspace pins**, not app secrets. Staging prep must honour them; they are checked as process/tool readiness, not as dotenv entries.

| Pin | Source | Contract |
|---|---|---|
| Node.js | root `package.json` `engines.node` | `>=22.22.0` |
| pnpm | root `package.json` `packageManager` | `pnpm@10.34.5` (exact; use `npx --yes pnpm@10.34.5 …`) |
| Lockfile | `pnpm-lock.yaml` | `lockfileVersion: '9.0'`; install with `--frozen-lockfile` |

### 1.5 Explicitly out of surface (forbidden requirements)

Do **not** list, require, or invent any of the following for this public-site contract:

- Broker API keys, OpenAlgo URLs/tokens, order-gateway credentials
- `~/.flinttrade/` paths, credentials.db, vault secrets
- Hostinger API tokens, FTP passwords, panel cookies, DNS provider keys
- Production domain, TLS private keys, payment or account identifiers
- Terminal-only `VITE_*` deployment DSNs (demo build actively strips `VITE_*` from the child env)

Root `.env.example` may mention GlitchTip **infra** keys for other stacks; those are **not** `@flinttrade/site` public-site requirements. The site optional var is `FLINTTRADE_GLITCHTIP_URL` only (CSP connect-src allowlist), not `GLITCHTIP_SECRET_KEY` / DB passwords.

### 1.6 Secrets handling

- Never commit a real `.env` with live values.
- This prep **creates no new secret files**.
- Optional vars above are either public origins/URLs, non-secret SHAs, or local path overrides — not broker credentials.
- If an operator adds a future secret for the public site, it must gain an explicit row here and a fail-closed rule before any staging label may claim support.

---

## 2. Local health and readiness checks

All checks are **local-only**. No Hostinger API, control panel, remote HTTP to production/staging hosts, or DNS queries against a planned public name.

### 2.1 Prerequisite tool checks

Run from the worktree / repo root. One command per line (PowerShell-safe).

```bash
node -v
npx --yes pnpm@10.34.5 -v
```

| Check ID | Pass condition | Fail-closed? |
|---|---|---|
| `H-NODE` | `node -v` reports a version satisfying `>=22.22.0` | **Yes** — do not run install/build |
| `H-PNPM` | `pnpm@10.34.5` resolves via the pinned npx form | **Yes** — do not run install/build |

### 2.2 Dependency install

```bash
npx --yes pnpm@10.34.5 install --frozen-lockfile
```

| Check ID | Pass condition | Fail-closed? |
|---|---|---|
| `H-INSTALL` | Exit code **0** | **Yes** |

### 2.3 Package gates (post-install)

```bash
npx --yes pnpm@10.34.5 --filter @flinttrade/site test
npx --yes pnpm@10.34.5 --filter @flinttrade/site typecheck
npx --yes pnpm@10.34.5 --filter @flinttrade/site build
```

| Check ID | Pass condition | Fail-closed? |
|---|---|---|
| `H-TEST` | Exit code **0** (pretest `generate:content` + vitest) | **Yes** for any staging-prep “gates green” claim |
| `H-TYPECHECK` | Exit code **0** (`tsc --noEmit` after pretypecheck) | **Yes** |
| `H-BUILD` | Exit code **0** (`prebuild` content+demo + `next build --webpack`) | **Yes** |

Notes:

- Prefer full package scripts so `pre*` hooks run. Bare `vitest` / bare `tsc` without hooks is **not** a substitute for these check IDs.
- `FLINTTRADE_SKIP_DEMO=1` may be used for **docs-only** local iteration; it does **not** satisfy full public-site Class A artifact readiness if `/demo-app` is part of the claimed surface. Default staging-prep posture: leave unset so `generate-demo` runs during `build`.

### 2.4 Build artifact presence (no serve required)

After `H-BUILD`, from `packages/apps/site`:

| Check ID | Pass condition | Fail-closed? |
|---|---|---|
| `H-ARTIFACT-NEXT` | `.next/BUILD_ID` exists and is non-empty | **Yes** for Class A |
| `H-ARTIFACT-STATIC` | `.next/static` exists and contains at least one file | **Yes** for Class A |
| `H-ARTIFACT-PUBLIC` | `public/llms.txt` exists (generated/public docs surface) | **Yes** for Class A docs surface |
| `H-ARTIFACT-DEMO` | `public/demo-app/index.html` exists | **Yes** if demo surface is claimed; **N/A** if operator explicitly scoped docs-only with `FLINTTRADE_SKIP_DEMO=1` **and** does not claim `/demo-app` |

Example local probes (illustrative; adapt for Windows `Test-Path` if needed):

```bash
test -s packages/apps/site/.next/BUILD_ID
test -d packages/apps/site/.next/static
test -f packages/apps/site/public/llms.txt
test -f packages/apps/site/public/demo-app/index.html
```

### 2.5 Local serve readiness (optional but recommended)

Serve is **local loopback only**. Do not point these checks at any remote Hostinger URL.

From `packages/apps/site` after a successful build:

```bash
npx --yes pnpm@10.34.5 --filter @flinttrade/site exec next start --port 3000
```

In a second shell:

```bash
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/docs
```

| Check ID | Pass condition | Fail-closed? |
|---|---|---|
| `H-SERVE-HOME` | HTTP status **200** from `http://127.0.0.1:3000/` | **Yes** if a “local serve proven” label is claimed; otherwise recommended |
| `H-SERVE-DOCS` | HTTP status **200** from a docs entry path (e.g. `/docs` or `/docs/…` as present in the build) | Same as above |

CSP report endpoint (optional negative/positive checks; local only):

| Check ID | Pass condition |
|---|---|
| `H-CSP-ORIGIN-DEFAULT` | With default `FLINTTRADE_SITE_ORIGIN`, same-origin local posts are not rejected solely for origin mismatch when `Origin` is `http://127.0.0.1:3000` |
| `H-CSP-ORIGIN-MISMATCH` | A deliberately wrong `Origin` header receives **403** `origin-mismatch` (proves fail-closed on that API) |

### 2.6 Class B install-script readiness (local only)

With the site serving locally **and** a valid Class B SHA in the environment used to start the process:

```bash
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/web-install.sh
```

| Check ID | Pass condition | Fail-closed? |
|---|---|---|
| `H-INSTALL-SCRIPT-PINNED` | Status **302** (redirect) when SHA valid | **Yes** for Class B |
| `H-INSTALL-SCRIPT-UNPINNED` | Status **503** when both SHA env vars missing/invalid | **Yes** as a negative proof of fail-closed behaviour |

Do **not** follow redirects to GitHub as a Hostinger health signal; Class B only asserts the **local** route decision.

### 2.7 Explicitly excluded “health” ideas

The following are **not** part of this contract and must not be used as staging-prep gates:

- Hostinger uptime, panel login, or hosting API status
- DNS resolution of any production or future staging hostname
- TLS certificate checks against a public name
- Broker connectivity, order path, or gateway pytest (those belong to other packages; order-path safety may run as a **separate** monorepo belt, not as a public-site env health check)
- Hitting `https://flinttrade.vercel.app` or any third-party marketing URL as a readiness oracle

---

## 3. Fail-closed rules (unambiguous)

A rule is **fail-closed** when the only legal action on failure is to **stop** and refuse any further staging-prep promotion language (including any future remote step). There is no “warn and continue” path for these rules.

### 3.1 Global rules

| ID | Condition | Required action |
|---|---|---|
| `FC-ENV-UNKNOWN` | A process or doc requires an env var **not** listed in §1 for public-site behaviour | **Stop.** Do not invent the var in silent config. Extend this contract first, or drop the requirement. |
| `FC-SECRET-COMMIT` | Real secrets or Hostinger credentials appear in the worktree staged for commit | **Stop.** Remove secrets; never commit. |
| `FC-REMOTE-TOUCH` | Any step would login, call Hostinger APIs, change DNS, upload, or deploy | **Stop.** Out of scope for this prep contract. |
| `FC-SCOPE-BLEED` | A check or required env pulls in broker/backend/terminal product secrets | **Stop.** Wrong surface. |

### 3.2 Tooling and gate rules

| ID | Condition | Required action |
|---|---|---|
| `FC-NODE` | `H-NODE` fails | Do not install or build. |
| `FC-PNPM` | `H-PNPM` fails | Do not install or build. |
| `FC-INSTALL` | `H-INSTALL` non-zero | Do not claim deps ready; do not build. |
| `FC-TEST` | `H-TEST` non-zero | Do not claim gates green. |
| `FC-TYPECHECK` | `H-TYPECHECK` non-zero | Do not claim gates green. |
| `FC-BUILD` | `H-BUILD` non-zero | Do not claim artifacts ready; do not serve-as-proof. |
| `FC-ARTIFACT` | Any required `H-ARTIFACT-*` for the claimed class fails | Do not claim Class A (or demo) readiness. |

### 3.3 Environment class rules

| ID | Condition | Required action |
|---|---|---|
| `FC-CLASS-A-EMPTY-REQUIRED` | (Reserved) If a future change adds a **Required** row under Class A and it is missing/invalid | Do not run or accept Class A readiness until set. **Today Class A required set is empty** — this rule arms automatically when the table gains a required row. |
| `FC-CLASS-B-SHA` | Class B is claimed (install-script redirects part of staging label) and neither `FLINTTRADE_SITE_SOURCE_SHA` nor `VERCEL_GIT_COMMIT_SHA` is a valid 40-hex SHA | **Fail Class B.** Do not advertise install-script routes as working. Local routes must 503. |
| `FC-CLASS-B-PARTIAL` | Class A green but Class B red | Allowed only if communications **explicitly** exclude install-script redirects from the staging-prep claim. Silent partial success is forbidden. |
| `FC-ORIGIN-MISMATCH-AS-HEALTH` | Operator “fixes” CSP 403 by disabling origin checks or shipping with wrong `FLINTTRADE_SITE_ORIGIN` without documenting the serve URL | **Stop.** Align `FLINTTRADE_SITE_ORIGIN` with the actual local origin or accept 403 on mismatched posts; do not weaken the check ad hoc without a contract change. |

### 3.4 Local serve rules

| ID | Condition | Required action |
|---|---|---|
| `FC-SERVE-CLAIM` | A handoff claims “local serve proven” but `H-SERVE-HOME` (and claimed docs path) did not return 200 on loopback | **Reject the claim.** Re-run serve checks or drop the claim. |
| `FC-SERVE-REMOTE` | Serve or curl targets a non-loopback / Hostinger / production host for “readiness” | **Invalid check.** Does not satisfy this contract. |

### 3.5 Decision table (summary)

| Claimed readiness label | Minimum green checks | Must also satisfy |
|---|---|---|
| **Class A — build artifacts** | `H-NODE`, `H-PNPM`, `H-INSTALL`, `H-TEST`, `H-TYPECHECK`, `H-BUILD`, `H-ARTIFACT-NEXT`, `H-ARTIFACT-STATIC`, `H-ARTIFACT-PUBLIC` | No required env missing (empty set today) |
| **Class A + demo** | Class A + `H-ARTIFACT-DEMO` | `FLINTTRADE_SKIP_DEMO` not `1` during build |
| **Class A + local serve** | Class A (+ demo if claimed) + `H-SERVE-HOME` (+ docs path if claimed) | Loopback only |
| **Class B — install scripts** | Class A + valid Class B SHA env at process start + `H-INSTALL-SCRIPT-PINNED` | `FC-CLASS-B-SHA` |

**Any red cell in the chosen row → fail-closed for that label.**

---

## 4. Operator quick reference

### Minimal Class A path (no optional env)

```bash
npx --yes pnpm@10.34.5 install --frozen-lockfile
npx --yes pnpm@10.34.5 --filter @flinttrade/site test
npx --yes pnpm@10.34.5 --filter @flinttrade/site typecheck
npx --yes pnpm@10.34.5 --filter @flinttrade/site build
```

Then verify `.next/BUILD_ID`, `.next/static`, and `public/llms.txt`.

### Optional local serve

```bash
npx --yes pnpm@10.34.5 --filter @flinttrade/site exec next start --port 3000
```

Default CSP origin assumption: `http://127.0.0.1:3000` (override with `FLINTTRADE_SITE_ORIGIN` only if you intentionally bind a different origin).

### Optional Class B pin (local process env only)

```bash
# Example shape only — use a real 40-char commit SHA from the worktree when testing Class B.
# FLINTTRADE_SITE_SOURCE_SHA=<40-hex-sha>
```

Unset both SHA vars to confirm `H-INSTALL-SCRIPT-UNPINNED` (503).

---

## 5. Source map (repo facts this contract rests on)

| Fact | Location |
|---|---|
| Site package scripts | `packages/apps/site/package.json` |
| CSP + `FLINTTRADE_GLITCHTIP_URL` / `NODE_ENV` | `packages/apps/site/src/proxy.ts` |
| `FLINTTRADE_SITE_ORIGIN` default + origin fail-closed | `packages/apps/site/src/app/api/csp-report/route.ts` |
| `FLINTTRADE_REPO_ROOT`, `VERCEL_GIT_*`, version fallback | `packages/apps/site/scripts/generate-content.mjs` |
| `FLINTTRADE_SKIP_DEMO`, `VITE_*` strip | `packages/apps/site/scripts/generate-demo.mjs` |
| Install-script SHA pin + 503 | `packages/apps/site/src/lib/install-script-routes.ts` |
| Node / pnpm pins | root `package.json` (`engines.node`, `packageManager`) |
| Prep overview | `docs/setup/hostinger-local-staging-prep.md` |
| PLAN item 3 posture | root `PLAN.md` (public-plane-only Hostinger staging prerequisites; no production domain/DNS/secret/broker mutation) |

---

## 6. Change control

- Any new **required** public-site env var must update §1.2 and add a `FC-*` row in §3 before merge.
- Any new local health check must get a stable `H-*` id in §2 and appear in the §3.5 decision table.
- Deploy, DNS, and Hostinger panel steps must **never** be added to this file; they belong in a separately authorised runbook outside staging-prep.

**End of contract.** Local-only. Public-site surface only. Fail-closed on red gates.
