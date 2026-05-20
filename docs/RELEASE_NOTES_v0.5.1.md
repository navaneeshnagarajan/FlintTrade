# FlintTrade v0.5.1 - Security hardening and CI stability

## Summary

FlintTrade v0.5.1 is a patch release on top of `v0.5.0` focused on
security hardening, route-contract correctness, CI stability, and release
metadata reconciliation. It does not introduce breaking API changes.

## Release Type

- SemVer: patch stable release
- Date: 2026-05-20 IST
- Base: `v0.5.0` (`2741cad`, 2026-04-19)
- Tag: `v0.5.1`
- Target: `514dcd4`
- Diff: 65 commits

## Highlights

- Closed 4 Codex stop-gate findings: advanced-order mode safety,
  helper auth-header propagation, JWT-revocation lifecycle, and auth
  rate-limit auto-discovery.
- Added sandbox subprocess isolation so hostile strategy code cannot outlive
  its wall-clock timeout.
- Fixed frontend/backend route drift across `ivsmile`, payoff, earnings,
  pnl symbols, strategy lifecycle, and global-indices stubs.
- Fixed CI stability: widget-test OOMs, Python-test hangs, ruff failures,
  and warning cleanup.
- Added 8 demo-flagged backend stub routes so affected widgets render
  intentionally instead of 404-ing.
- Bumped release metadata consistently to `0.5.1` across manifests, docs,
  and lockfiles.

## Security

- Advanced order routes now require live-mode JWT unlock.
- PIN unlock now swaps the live JWT into the frontend auth store.
- Practice downgrade revokes the previous live JWT server-side.
- `ftApi.helpers` now attaches `X-API-Key` and `Authorization` headers
  consistently.
- Auth rate-limit registration is auto-discovered instead of hardcoded.
- Sandbox execution now runs untrusted strategy code in a killable child
  process.

## API And Route Fixes

- `iv_smile` frontend calls now match backend `/ivsmile`.
- Payoff and earnings blueprints now mount under `/api/v1`.
- `pnl/symbols` accepts both `GET` and `POST`.
- Uploaded strategy lifecycle calls no longer include the stale
  `/uploaded/` segment.
- Duplicate security and strategy routes were removed or renamed to prevent
  Flask route shadowing.

## CI And Dependencies

- `actions/setup-python` and `actions/setup-node` were bumped to their next
  major versions.
- Pytest uses `--timeout-method=thread` in CI.
- Vitest switched from thread pooling to fork pooling for widget tests.
- Radix umbrella imports were unwound in shadcn primitives to reduce the
  test module graph.
- Dependabot-driven `postcss` and Rust lockfile updates were consolidated.

## Verification

- CI green on `ea64af5`.
- Python CI: 8,989 passed, 147 skipped.
- Ruff: 0 errors.
- CI warnings: 0.
- Dependabot: 0 open actionable alerts after the release sweep.
- Sandbox tests: 51/51 pass.
- Mode-guard tests: 17/17 pass.
- Helper auth-header tests: 14/14 pass.

Final post-CI commits reconcile package manifests, root `VERSION`,
`CLAUDE.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, Cargo lockfile metadata,
and npm lockfile metadata. The release tag therefore points at the fully
reconciled `0.5.1` artifact rather than the earlier pre-sweep release commit.

## Upgrade Notes

- Safe upgrade from `v0.5.0`.
- Existing public backend API shapes remain compatible.
- Trusted internal BacktestLab callers can still opt into the legacy
  in-thread sandbox path with `SandboxExecutor(use_subprocess=False)`, but
  untrusted/user-uploaded strategy code should use the default subprocess
  executor.

## Known Carry Into v0.5.2-dev

- Windows sandbox Job Object enforcement.
- Trusted-mode spawn bypass for reviewed BacktestLab inner loops.
- Real implementations for the 8 demo-flagged stub endpoints.
- Upstream wait for the transitive `glib` alert.

## Commit Range

```text
v0.5.0 (2741cad) .. v0.5.1 (514dcd4)
```

Notable commits:

- `8851607` - mode-safety stack for advanced order routes.
- `00c06e7` - JWT lifecycle, route drift, and duplicate route cleanup.
- `b6fb501` - auth rate-limit auto-discovery and fail-closed mode downgrade.
- `270c2f8` - sandbox subprocess isolation and Radix import cleanup.
- `55ef6fb` - package version sweep from `0.5.0` to `0.5.1`.
- `47a3f22` - lockfile self-version metadata sync.
- `514dcd4` - final release metadata reconciliation.
