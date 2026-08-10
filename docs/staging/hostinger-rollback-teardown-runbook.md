# Hostinger Local Staging Prep — Rollback and Future Teardown Runbook

**Status:** PREPARATION / NON-PRODUCTION / STAGING-PREP ONLY
**Audience:** Operators discarding the local Hostinger staging-prep line, or documenting a future authorised staging teardown.
**Related prep manifest:** `docs/setup/hostinger-local-staging-prep.md`
**Tone reference (structure and caution only):** `flinttrade-design/baselines/rollback-runbook-2026-05-24.md`

This tracked runbook is the public rollback and teardown artefact for the
Hostinger **local non-production staging preparation** line. It summarises safe
local discard of the prep worktree/branch and records a **documentation-only**
checklist for any future authorised remote staging slot. A fresh public clone
does not need `.local` files to understand rollback handling.

---

## Scope

| In scope | Out of scope |
| --- | --- |
| Discard local prep worktree and branch | Hostinger login, API, control panel, FTP, or CLI |
| Revert or drop unpushed prep commits on the prep branch only | Production domain, DNS, SSL, billing, account, or payment changes |
| Clean local site build outputs (`.next`, `out`) | Broker, trading, terminal, or order-path mutation |
| Document prospective future staging teardown | Operator data under `~/.flinttrade/` |
| Post-local-rollback verification on a surviving clone | Live deploy, upload, or secret rotation |

**Base commit for this prep line:** `e039d38685ef569f856f73edd2185aae39e275f8`
**Default prep branch name:** `wt/hostinger-local-staging-prep-e039`
**Default prep worktree path (this machine):**
`<prep-worktree>`

**Assumption (not a Hostinger product fact):** Paths and branch names above are
local operator conventions for this prep card. Other machines may use a
different worktree directory; substitute the live `git worktree list` path.

Rollback here is **not** the atomic v0.6.0-alpha restructure rollback. Do not
confuse this document with `flinttrade-design/baselines/rollback-runbook-2026-05-24.md`
except for tone (explicit scope, no shared-history rewrite, protect operator
data, post-verify).

---

## Strict forbids

Do **not** perform any of the following while following this runbook unless a
separate, explicit human authorisation names the action:

- Hostinger account login, API tokens, credentials, or payment actions
- DNS, subdomain, SSL, or production domain changes
- Upload, deploy, rsync, scp, or FTP of build artifacts to any remote host
- Broker, trading, terminal, or order-path mutation
- `git reset --hard` or force-push on shared/public history
- Deletion or migration of `~/.flinttrade/` (or Windows `%USERPROFILE%\.flinttrade\`)

**Local rollback always takes precedence** over any future remote teardown.

---

## 1. Local-only rollback

Use this section when the prep line must be discarded before any remote
Hostinger work is authorised. All steps are repository-local.

### 1.1 Preconditions

Run from any healthy clone of the monorepo (the main checkout is preferred so
the prep worktree is not the shell's cwd when it is removed).

```bash
git rev-parse --show-toplevel
git worktree list
git branch --list "wt/hostinger-local-staging-prep-e039"
git status --short
```

Confirm:

1. The prep worktree path appears in `git worktree list`.
2. You are **not** inside that worktree as the only remaining checkout you need.
3. The prep branch has **not** been merged to `main` (or any shared integration
   branch) unless a separate revert plan exists.
4. No unrelated dirty work sits only in the prep worktree that you still need.

**Assumption (local operator fact, not Hostinger):** If the prep branch was
never pushed, branch delete is sufficient history cleanup. If it was pushed to
a personal remote, remote branch delete is a separate optional step and still
must not rewrite `main`.

### 1.2 Preferred path — discard worktree and branch

Leave the prep worktree first (cd to the primary clone):

```bash
cd <repo>
```

Remove the prep worktree. Prefer non-force when the tree is clean; use
`--force` only if the worktree is dirty or locked and you accept losing
uncommitted prep files:

```bash
git worktree remove "<prep-worktree>"
```

If Git refuses because the tree is dirty or locked:

```bash
git worktree remove "<prep-worktree>" --force
```

Delete the local prep branch (safe only if unmerged work is intentionally
abandoned):

```bash
git branch -D wt/hostinger-local-staging-prep-e039
```

Deleting the local branch discards **unpushed** prep commits on that branch
only (including tracked prep artefacts under `docs/staging/` and the setup
manifest if they exist solely on this line). That is intentional discard, not a
`main` rewrite.

Do **not** run `git checkout` / `git switch` onto `main` or onto base commit
`e039d386…` as a side effect of cleanup unless you already intended to change
branches in that clone. Do **not** detach HEAD on the primary clone. Do **not**
mutate `main` history.

### 1.3 Alternate path — keep the worktree, drop prep commits only

Use only when the worktree directory must remain but the prep commits must go.

If the prep commits are **not** on shared history and HEAD is still the prep
tip with a clear base:

```bash
git status --short
git merge-base --is-ancestor e039d38685ef569f856f73edd2185aae39e275f8 HEAD
git log --oneline e039d38685ef569f856f73edd2185aae39e275f8..HEAD
```

Then reset the prep branch to the base **only on this private prep branch**:

```bash
git switch wt/hostinger-local-staging-prep-e039
git reset --hard e039d38685ef569f856f73edd2185aae39e275f8
```

**Warning:** `git reset --hard` is allowed here solely because the target is the
private prep branch tip, not shared `main`. Never hard-reset published history.

If prep commits **were** published on a shared branch, do not hard-reset.
Instead create inverse commits with `git revert` (newest first) after a clean
rehearsal, matching the caution in the restructure rollback runbook:

```bash
python scripts/rehearse-baseline-rollback.py --output-dir /tmp/flinttrade-hostinger-prep-revert-rehearsal <prep-commit-sha>
```

**Assumption (tooling availability):** `scripts/rehearse-baseline-rollback.py`
exists for the restructure baseline path. For simple unpushed prep commits,
branch discard (section 1.2) is preferred over rehearsal+revert.

### 1.4 Clean local build outputs

Public-site prep proofs leave Next.js build output under
`packages/apps/site/` only. From the surviving checkout (or from the prep
worktree before removal if you are only scrubbing artifacts):

```bash
rm -rf packages/apps/site/.next
rm -rf packages/apps/site/out
```

Optional caches that rebuild on the next site gate (remove only if you
intentionally want a cold content gen or a clean TypeScript incremental
state):

```bash
rm -rf packages/apps/site/.source
rm -f packages/apps/site/tsconfig.tsbuildinfo
```

**Repo fact:** current `@flinttrade/site` build is `next build --webpack` and
does **not** enable `output: 'export'`, so `out/` is normally absent unless a
future config change adds static export. Removing `out/` remains safe and
idempotent.

Do **not** delete root `node_modules` or `packages/apps/site/node_modules` as
part of this runbook unless you are also planning a full reinstall; dependency
trees are shared monorepo state, not Hostinger-specific staging artifacts.

Do **not** delete terminal/desktop build outputs (`packages/apps/terminal/dist`,
desktop packagers, Python `.venv`) for this public-site prep line.

**Windows note:** The same paths work under Git Bash. PowerShell equivalents:

```powershell
Remove-Item -Recurse -Force packages\apps\site\.next -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force packages\apps\site\out -ErrorAction SilentlyContinue
Remove-Item -Force packages\apps\site\tsconfig.tsbuildinfo -ErrorAction SilentlyContinue
```

Use one command per line. Do not chain with `&&` in contributor docs
(PowerShell 5.1).

### 1.5 Optional — remove untracked prep-only files

If the worktree is kept and untracked staging-prep files remain:

```bash
git status --short
```

Remove named paths explicitly. Do **not** use `git clean -fdx` as a default: it
can wipe local `.env`, evidence bundles, and tool caches unrelated to Hostinger
prep.

### 1.6 Post-local-rollback verification

From the primary clone after worktree/branch discard:

```bash
git worktree list
git branch --list "wt/hostinger-local-staging-prep-e039"
git status --short
git rev-parse HEAD
```

Expect:

- Prep worktree path absent from `git worktree list`
- Prep branch absent (if section 1.2 completed)
- Working tree clean for unrelated work you still need
- `~/.flinttrade/` (operator data) untouched — spot-check that the directory
  still exists if it did before rollback; this runbook never deletes it
- No Hostinger credentials or `.env` files were created by this prep line; none
  need rotation for a pure local discard

Optional sanity if you still need the public site on another branch:

```bash
npx --yes pnpm@10.34.5 --filter @flinttrade/site test
npx --yes pnpm@10.34.5 --filter @flinttrade/site typecheck
npx --yes pnpm@10.34.5 --filter @flinttrade/site build
```

One command per line. Pins match root `packageManager` / prep manifest.

---

## 2. Future staging teardown checklist (documentation only)

**DO NOT EXECUTE.** This section is prospective documentation for a future
environment that does not exist in this prep line. No commands below are live
runbook steps. No API calls, CLI invocations, or control-panel automations are
authorised by this document.

Any real remote teardown requires **separate explicit human authorisation**
naming the account, host, and change window. Until then, treat every item as a
planning checklist only.

### 2.1 Explicit assumptions (not Hostinger product facts)

Label each assumption before any future operator acts on it:

| ID | Assumption | Status |
| --- | --- | --- |
| A1 | A future non-production Hostinger (or other) hosting slot may exist under a staging-only hostname or path | **Assumption** — not provisioned by this prep |
| A2 | Example names such as `staging.flinttrade.example` are placeholders, not real DNS | **Assumption / placeholder** |
| A3 | Future upload may use Hostinger file manager, FTP/SFTP, or Node hosting — none selected here | **Assumption** |
| A4 | Future staging-only tokens or env vars might be issued later; this prep creates none | **Repo fact:** prep creates no secrets; **Assumption:** future tokens may exist |
| A5 | Billing, SSL, and DNS behaviour are host-specific and unknown until an authorised account is used | **Assumption** — not measured |
| A6 | Production public site today remains on the existing Vercel-oriented public path unless maintainers decide otherwise | **Repo/docs context** — not a Hostinger cutover plan |

### 2.2 Checklist (manual, after separate authorisation only)

When (and only when) a human authorises teardown of a real staging slot, an
operator would walk this list manually. Items are prose on purpose so they are
not copy-pasteable as automation.

1. **Confirm authorisation** — written approval naming account, hostname/path,
   and that the slot is non-production.
2. **Inventory remote slot** — record hostname, hosting type (static vs Node),
   deploy path, and any staging labels (`STAGING-PREP` / `NON-PRODUCTION`).
3. **Drain or disable public access** — remove temporary access links or auth
   gates if any were added after authorisation (none exist in this prep).
4. **Remove uploaded artifacts** — delete staging build files from the host
   file tree or Node app instance **only** for the staging slot.
5. **Release hostname / path** — detach staging subdomain or hosting path from
   the slot; do not touch production DNS.
6. **Revoke staging-only secrets** — rotate or delete tokens and env vars that
   were issued solely for that slot (none issued by this prep).
7. **Billing / SSL residual check** — confirm no unwanted renewal, certificate,
   or invoice line remains for the staging slot (host-specific; see A5).
8. **Update internal docs** — mark the staging slot decommissioned in manifests
   and runbooks; keep this local rollback section valid for future prep lines.
9. **Local confirmation** — primary clone has no dependency on the remote slot;
   local rollback (section 1) already applied if the prep branch was discarded.
10. **Record outcome** — short note of what was removed, who authorised it, and
    residual operator actions (if any).

### 2.3 What this section deliberately omits

- No `curl`, `ssh`, `scp`, `rsync`, Hostinger CLI, or API examples
- No account IDs, tokens, invoice numbers, or server IPs
- No production cutover or traffic-shift language
- No steps that mutate brokers, trading state, or `~/.flinttrade/`

If a future authorised runbook needs executable remote steps, write a **new**
document under an explicit authorisation header. Do not “upgrade” this section
in place without human review.

---

## 3. Operator data and credentials

Aligned with the restructure rollback runbook’s protection rules:

- `~/.flinttrade/` (and Windows `%USERPROFILE%\.flinttrade\`) is **outside**
  this rollback. Never delete, overwrite, or migrate it as part of Hostinger
  prep discard.
- Broker credentials databases and auth state are untouched.
- This prep line does not create Hostinger API tokens. There is nothing to
  revoke for a pure local rollback.
- Root `.env` / `.env.local` files, if present on a developer machine, are not
  owned by this prep; do not delete them via this runbook.

---

## 4. Relationship to other documents

| Document | Role |
| --- | --- |
| `docs/setup/hostinger-local-staging-prep.md` | Prep overview; short rollback summary must defer here |
| `docs/staging/hostinger-local-build-manifest.md` | Exact site build pins and artifact layout |
| `docs/staging/hostinger-env-health-contract.md` | Public-site env/health contract (local) |
| `docs/staging/hostinger-local-test-proof.md` | Local test/build proof record |
| `flinttrade-design/baselines/rollback-runbook-2026-05-24.md` | Tone and caution reference for restructure rollback only — **not** Hostinger cutover |
| `PLAN.md` item 3 (reversible sequence) | Gate: public-plane-only Hostinger staging prerequisites/configuration with no production domain, DNS, account/payment, secret, broker or trading mutation |
| This file | Authoritative local discard + future teardown documentation |

When the prep manifest’s short rollback section and this runbook disagree,
**prefer this runbook** for discard/teardown detail and keep the manifest
pointing here. Do **not** treat the restructure runbook’s Vercel section as
Hostinger guidance.

---

## 5. Local validation record (this prep worktree)

Validation performed **without** destroying the live prep worktree used by the
Hostinger staging-prep kanban line. Destructive git steps were rehearsed on a
throwaway worktree/branch, then removed. Artifact cleanup was exercised against
fake `.next` / `out` trees inside that throwaway only.

**Initial rehearsal timestamp:** 2026-08-09T19:10:48+05:30
**Re-validation timestamp:** 2026-08-09T19:38:00+05:30
**Live prep HEAD during re-validation:** `8d31a9a80a3c39df757a157da06e058f175082a1`
**Throwaway branch (deleted):** `tmp/hostinger-rollback-rehearsal-52728` (first pass)
**Throwaway path (removed):** `<prep-worktree-rollback-rehearsal-tmp>`
**Primary clone path confirmed:** `<repo>`

| Check | Result |
| --- | --- |
| Prep worktree registered on `wt/hostinger-local-staging-prep-e039` | Pass |
| Base `e039d386…` is ancestor of prep HEAD | Pass |
| Primary clone present and is a separate worktree from prep | Pass |
| Throwaway: fake `.next`/`out` → `rm -rf` clean (section 1.4) | Pass (first pass) |
| Throwaway: `git worktree remove` then `git branch -D` (section 1.2) | Pass (first pass) |
| Live prep worktree still registered after rehearsal/re-validation | Pass |
| Section 1 covers worktree discard, branch delete, commit drop, build clean | Pass |
| Section 2 has no fenced shell and no `curl`/`ssh`/`scp`/`rsync` command lines | Pass |
| Section 2 carries `DO NOT EXECUTE` + assumption table (A1–A6) | Pass |
| No Vercel production cutover steps presented as Hostinger guidance | Pass |
| Operator data path not a delete target | Pass (authoring review) |
| No remote Hostinger/account/DNS actions executed by this task | Pass |

Update this table if a full discard of the real prep line is later executed.

---

## 6. End state after a full local rollback

- Prep worktree directory gone
- Prep branch deleted locally
- Site build outputs removed from any surviving checkout you cleaned
- Primary clone history for `main` unchanged
- No remote Hostinger (or other host) changes
- No operator-data changes
- Future teardown checklist remains documentation only until separately authorised

**End of runbook.** All remote teardown content is non-executable documentation.
