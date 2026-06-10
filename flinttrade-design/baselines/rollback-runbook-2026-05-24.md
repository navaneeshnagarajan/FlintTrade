# FlintTrade Restructure Rollback Runbook

This tracked runbook is the public rollback artefact for the
`pre-restructure-baseline` manifest. It summarises the safe restore procedure
from the local baselines spec so a fresh public clone does not need `.local`
files to understand rollback handling.

## Scope

Rollback is for the atomic v0.6.0-alpha restructure commit only. It restores
repository code, package paths, generated public docs, and deployment config.
It must not alter operator data under `~/.flinttrade/`.

## Git Revert

### Rollback Rehearsal

Before creating a rollback commit, run the safe rollback rehearsal:

```bash
python scripts/rehearse-baseline-rollback.py --output-dir /private/tmp/flinttrade-rollback-rehearsal <restructure-commit-sha>
```

The rehearsal uses `git merge-tree` to model the revert against the current
tree and writes a report under the output directory without changing the
worktree, index, branch, or operator data. If the JSON summary reports
`conflict_indicators` above `0`, the conflict indicators are blocking evidence:
do not declare the rollback clean. Resolve the
rollback in a dedicated branch or temporary worktree, record the conflict
classes, then re-run the rehearsal and the verification gates before publishing
the revert commit.

### Revert Commit

Use `git revert <restructure-commit-sha>` on public history only after the
rollback rehearsal is clean or after the controlled resolution branch has been
verified. Do not use `git reset --hard` for shared/public history because it
rewrites collaborators' clones.

After the revert commit is produced:

```bash
git status --short
make full-check
```

If a targeted check is needed before the broader gate, run:

```bash
python -m pytest tests/test_project_structure.py tests/test_restructure_goals.py -v --import-mode=importlib
```

## Vercel Rollback

If the public website deploy fails after the revert, use Vercel rollback to
promote the last known-good deployment while the repository fix is pushed.
The expected rollback window is short; cached docs are acceptable during that
window as long as the promoted deployment is from the same public repo.

## LICENSE File

This section covers the root `LICENSE` rollback path.

The public repo keeps `LICENSE` as a regular text file whose contents match
`licenses/agpl-3.0.txt`. This is intentionally not a symlink: macOS, Linux,
and Windows clones should materialise the licence without relying on symlink
support or path-target limits. If rollback changes the licence entry, restore
both files from the same commit and verify the contents still match. Do not
invent a different licence file.

## Operator Data

`~/.flinttrade/` is outside the repository and is never part of the rollback.
The rollback must not delete, overwrite, or migrate:

- `workspace.json`
- `auth.db`
- `credentials.db`
- `auth_state.duckdb`
- audit archives
- journal files
- broker contract caches

Workspace migrations must remain restartable and must preserve manual edits.
If a migration fails, restore from the same-directory backup created by the
workspace migration runner.

## Broker Credentials

Broker credentials remain in `~/.flinttrade/credentials.db` and are protected
by the configured master password/envelope. A rollback does not rotate broker
tokens or force re-authentication. If a separate broker session refresh was
performed during the failed deployment window, document the affected broker in
the revert commit message so the operator can re-authenticate deliberately.

## Post-Rollback Verification

Run these checks before declaring the rollback complete:

```bash
python -m pytest tests/test_project_structure.py tests/test_restructure_goals.py -v --import-mode=importlib
python -m pytest packages/core/core/tests/test_workspace_migrations.py -v --import-mode=importlib
cd packages/apps/site && npm run build
cd packages/apps/terminal && npm run build
```

Then verify:

- root public docs still use lowercase tracked names;
- package paths match the reverted tree;
- `LICENSE` resolves correctly;
- `~/.flinttrade/` contents were not touched;
- Vercel serves the intended deployment;
- the rollback commit message names any known residual user action.
