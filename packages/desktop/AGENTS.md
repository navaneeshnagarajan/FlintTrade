# FlintTrade — desktop

> Tauri-v2 native shell wrapping the React terminal. Read `packages/desktop/CLAUDE.md` first.

## Absorbs
- fastscalper-tauri → Tauri window/entitlement patterns (reference only)

## Depends on: terminal (must be built first; this package consumes `terminal/dist/`)

## Rules
- Read root CLAUDE.md for project-wide rules.
- This package contains NO application UI code — all UI changes belong in `packages/terminal/`.
- `src-tauri/tauri.conf.json` is platform configuration, not application logic.
- Bundle identifiers (`com.flinttrade.*`) must stay stable across releases to avoid orphaned installs on update.
- Update root CHANGELOG.md for any release-affecting change.
- Branch: main (pre-release, all commits to main).
