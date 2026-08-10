# Hostinger Local Non-Production Staging Preparation (Public-Site Only)

**Status:** PREPARATION / NON-PRODUCTION / STAGING-PREP ONLY
**Scope:** Repository-local artifacts and local verification for a Hostinger-compatible public-site path.
**Strict forbids (per card):** No Hostinger login, API tokens, credentials, DNS, subdomain, upload, deploy, account, payment, broker, trading, terminal, or production mutation of any kind. No live Hostinger actions. This document and generated artifacts are for local review only.

**Base commit:** `e039d38685ef569f856f73edd2185aae39e275f8` (preview-docs-page-pilot-20260809 tip)
**Worktree:** `wt/hostinger-local-staging-prep-e039`
**Linux cross-link (comments only):** t_b86141db

## 1. Hostinger-Compatible Public-Site Build/Deploy Manifest

### Exact Local Build Commands (from repo root, frozen lock)
All commands use the pinned pnpm version from the lock/workspace:

```bash
# 1. Frozen install (repo root)
npx --yes pnpm@10.34.5 install --frozen-lockfile

# 2. Site package gates (recommended: one command per line)
npx --yes pnpm@10.34.5 --filter @flinttrade/site test
npx --yes pnpm@10.34.5 --filter @flinttrade/site typecheck
npx --yes pnpm@10.34.5 --filter @flinttrade/site build
```

### Site Package Scripts (from packages/apps/site/package.json)
- `pretest` / `prebuild` / `pretypecheck`: `npm run generate:content` (runs content + fumadocs-mdx generation)
- `test`: `vitest run`
- `typecheck`: `tsc --noEmit`
- `build`: `next build --webpack`
- Additional: `generate:content`, `generate:demo`, `mcp:stdio`

**Note on pnpm vs npm:** Monorepo root uses pnpm workspace; `--filter` works via pnpm even if inner package.json lists npm scripts. Use the npx-pinned form above for reproducibility.

### Expected Build Outputs / Artifact Layout (Public Site Only)
After successful `pnpm --filter @flinttrade/site build` (from root or site dir):

- `.next/` (standard Next.js build directory containing:
  - `static/` - hashed JS/CSS chunks, images, fonts
  - `server/` - server-side bundles (for Node hosting)
  - `app/` or page assets
  - `BUILD_ID`, `static/chunks/`, etc.
- `public/` assets copied (flinttrade images, etc.)
- Generated content from `scripts/generate-content.mjs` and Fumadocs MDX (docs corpus, llms.txt, MCP capabilities)

**Hostinger Compatibility Notes (staging-prep assumptions only):**
- Hostinger Web Hosting or Cloud Hosting can serve static Next.js exports or Node.js apps.
- For pure static: Next.js static export (`output: 'export'` in next.config) would produce `out/` with index.html + assets — **not enabled in current config**; this prep does not modify next.config or enable export.
- Recommended for Hostinger static hosting trial: build locally, then manually upload `.next/static/` + root HTML/JS if adapting, or use Hostinger's Node hosting option for full Next.js.
- **Explicitly non-production:** These artifacts are staging-prep only. No production domain, no SSL/DNS config, no live traffic assumptions. Mark all deploys (future) with `STAGING-PREP` or `NON-PRODUCTION` labels.
- Pin Node/pnpm from repo lock: Node ^ (from package engines if present; current env v26+ compatible per local test), pnpm 10.34.5.
- No invented runtime versions.

**Machine-Checkable Manifest Guard (example for future TDD):**
A simple presence check could verify `docs/setup/hostinger-local-staging-prep.md` exists and contains the exact build commands above (see test section below).

## 2. Environment and Health Contract (Public-Site Only)

### Required vs Optional Env Vars (Public/Docs/Marketing Site)
Public-site staging prep uses **minimal or zero** environment variables for core functionality (docs + Fumadocs + MCP read-only):

- **Required (fail-closed if missing for full features):**
  - None strictly required for basic build + static serve. The site is largely static-generated content.
- **Optional / Recommended for staging:**
  - `NEXT_PUBLIC_*` prefixed vars if any marketing/analytics (none hard-coded in current public surface per audit).
  - Vercel-specific (for reference only): `VERCEL_*` envs are Vercel platform; for Hostinger ignore or map equivalents if using their Node hosting.
  - Any MCP or content generation envs: none documented in site for public path.

**Fail-closed rule:** If a required env for a future staging health check is missing or invalid → do not proceed to any deploy step. Health check must pass locally first.

### Local Health / Readiness Expectations (Post-Build)
After `pnpm --filter @flinttrade/site build`:

1. **Build success:** Exit code 0, no TS errors, no content generation failures.
2. **Local serve test (optional but recommended for prep):**
   - Use `npx --yes serve@latest out` (if static export added later) or `npx next start` (requires Node hosting).
   - Or simply verify build artifacts exist and `ls .next/static | wc -l > 0`.
3. **Health indicators (local only):**
   - `curl -I http://localhost:3000` (after `next start`) returns 200 for index.
   - No console errors on load (manual browser check).
   - MCP stdio or HTTP endpoints respond if enabled (read-only public catalogue only).
   - Generated `llms.txt` or docs index present in build output.

**No Hostinger API health checks** — purely local after build.

**Secrets note:** Never commit real `.env` with keys. Use `.env.example` only. This prep creates no new secret files.

## 3. Rollback / Teardown Runbook

### Local-Only Rollback (Immediate, Safe)
To discard this prep branch/worktree and revert to base:

```bash
# From repo root (or worktree parent)
git worktree remove "C:/Users/USER/Desktop/Trading/FlintTrade-wt-hostinger-local-staging-prep-e039" --force
git branch -D wt/hostinger-local-staging-prep-e039
git checkout e039d38685ef569f856f73edd2185aae39e275f8  # or main if needed, but do not mutate main

# Clean build outputs if present
rm -rf packages/apps/site/.next packages/apps/site/out 2>/dev/null || true

# Verify clean
git status --short
git rev-parse HEAD
```

**Rehearsal note:** Similar to existing `flinttrade-design/baselines/rollback-runbook-2026-05-24.md` rehearsal pattern (use `git merge-tree` if complex revert needed). This prep has no restructure commit; simple branch discard suffices.

**Do not use `git reset --hard`** on shared history.

### Future-Staging Teardown Checklist (Documentation Only — Do Not Execute)
This section is **purely prospective documentation** for a future authorised staging environment. It is not actionable here.

**Assumptions (explicitly labeled — not Hostinger facts):**
- Hypothetical future Hostinger account / subdomain (e.g. `staging.flinttrade.example` or Hostinger-hosted path) would require separate explicit authorisation.
- Teardown would cover:
  1. Delete / archive the staging subdomain or hosting path in Hostinger control panel (manual UI action only after auth).
  2. Remove any uploaded build artifacts from Hostinger file manager / FTP (if used).
  3. Revoke any future-issued staging-only tokens or env vars (never created in this prep).
  4. Update any internal docs or manifests to mark the staging slot as decommissioned.
  5. Verify no residual DNS / SSL / billing impact (Hostinger-specific steps).
  6. Confirm local repo remains on production branch with no staging artifacts left.

**Tone alignment:** Mirrors the structure and caution of `flinttrade-design/baselines/rollback-runbook-2026-05-24.md` (git revert, operator data protection, post-verify) but **replaces all Vercel references with generic "future staging host" language** and explicitly labels assumptions. No production cutover language is copied verbatim.

**Local rollback always takes precedence** over any future remote teardown.

## 4. Local Tests + Build Proof (Verification Matrix — Run for Real)

**Order:** deps → site gates → safety belt → git truth. Quote exact output.

**Commands (executed in worktree root):**

```bash
# Deps
npx --yes pnpm@10.34.5 install --frozen-lockfile

# Site gates (pnpm filter)
npx --yes pnpm@10.34.5 --filter @flinttrade/site test
npx --yes pnpm@10.34.5 --filter @flinttrade/site typecheck
npx --yes pnpm@10.34.5 --filter @flinttrade/site build

# Safety belt (repo root; clear any Hermes PYTHONPATH leak)
env -u PYTHONPATH -u VIRTUAL_ENV -u PYTHONHOME PATH="packages/integrations/gateway/.venv/Scripts:${PATH}" python -m pytest -q packages/integrations/gateway/tests/test_no_legacy_order_path.py --import-mode=importlib

# Git truth (post any commits)
git rev-parse HEAD
git merge-base --is-ancestor e039d38685ef569f856f73edd2185aae39e275f8 HEAD
git status --short
git diff --check e039d38685ef569f856f73edd2185aae39e275f8..HEAD
git diff --name-only e039d38685ef569f856f73edd2185aae39e275f8..HEAD
```

**TDD / Mechanical Guards:**
- New files (this manifest, future guards) should include a simple source guard test (e.g. in `packages/apps/site/__tests__/` or root) that asserts presence of the staging-prep.md and absence of forbidden production markers (e.g. no "production domain" claims, no real Hostinger tokens).
- RED→GREEN: First commit a failing guard test asserting the manifest section exists, then implement the doc to make it pass.
- Conventional Commits only; explicit `git add <specific paths>`.

**Current verification status (to be updated on run):** [See evidence comment / bundle for actual run output]

## 5. TDD / Process Notes

- Tests-first for any machine-checkable prep (manifest presence, no-secrets pattern scanner, forbidden string guard).
- All new artifacts explicitly marked **STAGING-PREP / NON-PRODUCTION**.
- No scope creep: only public-site path.
- Final tree clean before tip-named bundle.

## References
- PLAN.md item 3 (public-plane-only Hostinger staging)
- packages/apps/site/package.json, README.md, vercel.json, next.config.mjs
- flinttrade-design/baselines/rollback-runbook-2026-05-24.md (tone alignment only)
- AGENTS.md, site scripts

**End of preparation manifest.** All content is local-only review artifact.
