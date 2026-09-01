# Changelog

All notable changes to FlintTrade will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/).
Versioning: [Semantic Versioning](https://semver.org/).

<!--
Release history was reset to a clean v0.0.1 baseline on 2026-07-23. The earlier
v0.1.0…v0.6.0-beta.13 tags and releases (the retired Tauri/PyInstaller line, plus
the updater-beta channel manifest) were deleted so the project could restart with
honest, pre-release-marked 0.0.x semantic versioning while it is still pre-usable.

No history was lost: every commit and its detailed message remains in git.
release-please regenerates the sections below from Conventional Commits, so the
changelog rebuilds itself from the first release cut after this baseline.
-->

## [Unreleased]

### Fixed

- **Workspace path unification.** Nineteen modules resolved their own storage as
  the literal `~/.flinttrade` instead of asking `flinttrade_core.workspace`. On
  Linux that happens to be the workspace, so it never failed in CI; on macOS
  (`~/Library/Application Support/flinttrade`) and Windows (`%APPDATA%\flinttrade`)
  every one of them wrote to a second, invisible directory that the rest of the
  app did not read and the uninstaller could not find. Affected state included
  the TOTP secret store and its install key, the trade journal and its
  screenshots, saved presets, keyboard shortcuts, quantity-freeze limits, the
  pending-order approval queue, the watchlist, expiry and FII/DII stores, and the
  operator's own FlowBuilder flows, trained signal models and strategy files.

  Every module now resolves its path inside a function body at call time, so
  `FLINTTRADE_WORKSPACE_DIR` and `FLINTTRADE_HOME` are honoured on every
  construction rather than frozen at import. On a default install each artefact
  is **copied** into the platform workspace once, under a cross-process lock; the
  pre-workspace original is left untouched, so the upgrade is reversible. Where a
  workspace copy already exists it wins and no merge is attempted — an
  approval-queue merge could dispatch the same order twice. The TOTP store and
  its install key move as one unit, verified by a decrypt round-trip before the
  legacy pair is trusted, and the trade journal moves with its screenshot
  directory or not at all. Migration probes are skipped entirely when a workspace
  environment override is in force.

- Both uninstallers now enumerate every pre-workspace dropping written directly
  at `~/.flinttrade/<name>` — flows, models, strategies, journal screenshots,
  presets, the TOTP pair and the remaining stores — as named `--purge`/`-Purge`
  candidates. They were deleted before, but only as part of the managed root, so
  the confirmation list never mentioned the operator's own strategy code.

- `FlowBuilder` and the trade journal no longer fall back to a home-directory
  path when `flinttrade_core` cannot be imported. A broken install now fails
  loudly and the affected routes degrade to 503, instead of silently opening an
  empty shadow store.

### Changed

- Vulnerable ChromaDB persistence is replaced by FlintTrade's local
  SQLite/NumPy vector store. Existing vector directories are deliberately not
  auto-migrated because Chroma's on-disk index and embedding space are not
  compatible with the replacement. If `chroma.sqlite3` is present, FlintTrade
  refuses to create `flinttrade_vectors.sqlite` beside it: the database and
  vector-segment files are left untouched, RAG stays disabled, and agent
  learning uses its logged in-process fallback. To recover existing lessons or
  custom documents, export them with the previous release. To intentionally
  start empty, move the complete legacy directory aside as a backup before
  restarting; do not delete individual segment files.

- The traffic and latency observability logs (`traffic_log.duckdb`,
  `latency_log.duckdb`) are not migrated: they are disposable, and both were
  already workspace-routed in production. On macOS and Windows their history
  restarts from empty.

## [0.0.1] — 2026-07-23

Clean-slate baseline. Pre-1.0, pre-usable, and marked as a pre-release: anything
may change without notice until the project reaches a stable 1.0.0.
