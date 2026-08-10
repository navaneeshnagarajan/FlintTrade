# Hostinger Local Staging Prep — Verification Record (Generic / Evergreen)

**Status:** PREPARATION / NON-PRODUCTION / STAGING-PREP ONLY
**Scope:** Concise public record of the verification matrix for the Hostinger local non-prod staging prep line. Detailed raw logs, machine captures, and evidence are kept in gitignored evidence directory only.

## Verification Matrix (executed for real in prep worktree; quoted exits/counts)

All commands run from repo root / worktree root with pinned toolchain.

```bash
# 1. Frozen install (repo root)
npx --yes pnpm@10.34.5 install --frozen-lockfile   # exit 0

# 2. Site package gates
npx --yes pnpm@10.34.5 --filter @flinttrade/site test          # 124/124 passed, exit 0
npx --yes pnpm@10.34.5 --filter @flinttrade/site typecheck     # clean tsc, exit 0
npx --yes pnpm@10.34.5 --filter @flinttrade/site build         # 60/60 pages, exit 0 (portable launcher)

# 3. Safety belt (prefer worktree .venv; clear any PYTHONPATH/VIRTUAL_ENV leak)
env -u PYTHONPATH -u VIRTUAL_ENV -u PYTHONHOME ... python -m pytest ...   # 53/53 passed, exit 0

# 4. Git truth (post commits)
git rev-parse HEAD
git merge-base --is-ancestor e039d38685ef569f856f73edd2185aae39e275f8 HEAD   # ancestor OK
git status --short   # clean
git diff --check e039d38685ef569f856f73edd2185aae39e275f8..HEAD   # clean
git diff --name-only ...   # tracked changes only
```

## Reproducibility Contract
- Exact Node/pnpm pins preserved (Node >=22.22.0, pnpm@10.34.5).
- Safety commands use active repo/worktree .venv generically and remain cross-platform.
- No stale "Worktree HEAD at authoring", no internal run IDs/timestamps/PIDs in this public record.
- All machine/user-specific details removed.
- Use generic placeholders (`<repo>`, `<prep-worktree>`, `<venv>`) in instructional text.

## Notes
- Portable Vite launcher TDD guard preserved (build-script.test.ts + generate-demo.mjs).
- Source contract (no-private-references + hosting truth) enforced via site tests.
- This replaces the previous long raw private log. Full verbatim captures remain in gitignored evidence directory only.

**End of concise generic verification record.** All content is local-only review artifact.