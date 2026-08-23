# Fleet leftover inventory — 2026-08-23

Inventory of every leftover remote head after PR #132 (`feat(repo): converge completed non-release work`) and the later #139 / #140 / Dependabot wave. Compared against `origin/main` at `67abb7b2`. Live heads from `git ls-remote --heads origin` on 2026-08-23; merge-base of the archive fleet is `dec2393c` (`fix(web): serve installed frontend assets cross-platform`, #119).

This pass does **not** squash-merge archive snapshots. PR #132 already excluded Graphite, Three.js, Hostinger, Phase 4 proof stubs, unfinished-job governance, and lock-drift snapshots. Release-please PR #60 is untouched.

## Decision key

| Verdict | Meaning |
|---|---|
| **Already on main** | Unique product work landed via #132 or later |
| **Superseded** | Later main work covers the same surface |
| **Ported** | Unique unfinished work finished on this converge branch |
| **Skipped** | Archive-only, rejected product direction, stub, or governance snapshot |

## Live leftover heads

| Remote branch | Tip | Verdict | Why |
|---|---|---|---|
| `archive-sanitized/fleet-20260810/linux/feature/phase4-practice-proof` | `759db85a` | **Skipped** | v1 harness hardcodes PASS evidence (`assert True` legacy guard, fabricated counts). Not a proof. |
| `archive-sanitized/fleet-20260810/linux/feature/phase4-practice-proof-v2` | `afb7dc8f` | **Skipped** (partial salvage below) | Widest Phase 4 file set, but Claim B / full-day / verifier are stubs; `BrokerRouter` constructor is stale vs current main. |
| `archive-wip/fleet-20260810/linux/feature/phase4-practice-proof-v3-real` | `c776602f` | **Ported** | Real Flask → `orders_bp` → isolated `SandboxEngine` + frozen-clock 10/11 burst. Forged Live-header case inverted to 403 (current `_mode_header_mismatch_response`). Stub schema / run scripts not ported. |
| `archive-sanitized/fleet-20260810/linux/fix/hostinger-staging-8d31a9a8` | `6cfd742c` | **Skipped** | Operator-specific Hostinger VPS staging runbooks. Not generic public-site product work. Excluded by #132. |
| `archive-sanitized/fleet-20260810/linux/review/windows-hostinger-8d31a9a8` | `6bf8bcae` | **Skipped** | Same Hostinger bundle minus `hostinger-public-docs.test.ts`. |
| `archive-sanitized/fleet-20260810/windows/wt/hostinger-local-staging-prep-e039` | `e22f935a` | **Skipped** | Windows sanitised snapshot of the same Hostinger prep. |
| `archive/fleet-20260810/linux/feature/site-threejs-enrichment-pilot` | `4066e1ea` | **Skipped** | Default-off Three.js “Spark Path” pilot. Main already has canvas `hero-cinematic.tsx`. New product direction; excluded by #132. |
| `archive-sanitized/fleet-20260810/linux/integration/site-3d-staging-20260809` | `db11df2f` | **Skipped** | Three.js pilot plus Hostinger docs plus Graphite bundle. |
| `archive-sanitized/fleet-20260810/linux/integration/terminal-accepted-core-20260809` | `3e3eed1d` | **Already on main** | Terminal Slices 1–3, provenance, E2E foundation, persona routes. Main is ahead (account-read authority, #140 CI). |
| `archive/fleet-20260810/linux/integration/unfinished-jobs-20260809` | `6ea819d3` | **Skipped** | Tip commit is a Phase 2 Remaining wording tweak; ancestry also rewrites `AGENTS.md` / agent PLAN template toward excluded Hostinger / Spark Path / Grok-Hermes pipeline. #132 kept current governance. Nightly-CI clause is satisfied by #140. |
| `archive-wip/fleet-20260810/mac/wt/flinttrade-workspace-correction-ddc64756-v1` | `8cae72b4` | **Already on main** | `ddc64756` landed in #132 and was extended (quarantine, remint, creation transactions). Merging the tip would regress TopBar / E2E. |
| `archive-wip/fleet-20260810/windows/wt/workspace-hybrid-clone-failclosed-c5e1` | `ce268270` | **Skipped** | Classifier + clone SOT absorbed by #132. Only remaining delta is mixed-family `familyCount > 1` rejection; #132 chose early dockview return. Porting that would be a new behaviour change. |
| `archive-wip/fleet-20260810/mac/wt/graphite-continuity-a1-1b49ed1c` | `909838de` | **Skipped** | Site truth CTA already on main. Unique remainder is Graphite A1 motion / four-band IA. Excluded by #132. Do not revive `DemoChoice`. |
| `archive/fleet-20260810/linux/review/windows-graphite-a1-35145553` | `35145553` | **Skipped** | Fullest Graphite A1 tip; same exclusion. Blind merge would revert main MCP / docs.page work. |
| `archive/fleet-20260810/linux/review/windows-graphite-a1-a4bebe07` | `a4bebe07` | **Skipped** | Same as `35145553` with minor homepage-band / CSS deltas. |
| `archive/fleet-sync-manifest-20260810` | `dc4c1475` | **Superseded** | Point-in-time 2026-08-10 preservation manifest. This document replaces it for decision-making. |
| `release-please--branches--main--components--flinttrade-monorepo` | (PR #60) | **Untouched** | Release-please / chore(main): release 0.0.1. No tag, no changelog-as-release, no Phase 6. |
| `main` | `67abb7b2` | Baseline | Already includes #132, #139, #140, and recent Dependabot merges. |

## Themes checked against current main

| Theme | Outcome |
|---|---|
| Phase 4 Practice-proof | Ported the real-sandbox HTTP burst and inverted mode-header test. v1/v2 stub harnesses, evidence theatre, and wall-clock “full day” scripts skipped. Market-day Practice run remains the Phase 4 exit. |
| Hostinger / public-site continuation | Archive-only operator staging. Site truth CTA already on main via #132. |
| Site 3D / Three.js pilot | Rejected product direction; canvas cinematic remains on main. |
| Workspace fail-closed / hybrid-clone | Already on main via #132; mixed-family discriminator not ported. |
| Graphite continuity / Windows graphite A1 | Archive-only motion / IA. Truth CTA already on main. |
| Terminal accepted-core leftovers | Already on main; main is ahead. |
| Orders / positions / PnL provenance | Already on main via #132 and follow-ups. |
| Nightly CI leftovers | Superseded by #140. Archive `fix/nightly-*` refs are no longer on the remote. |

## Human-gated items (untouched)

Groww session approval, Kotak Neo live probe, funded live order smoke, W6 spec, B3 order-capable MCP, Apple signing / notarisation.

## What this converge ships

- `packages/core/core/tests/test_phase4_practice_http_proof.py` — real `SandboxEngine` Practice fills, 403 on Practice JWT + forged Live header, invalid JWT / routed-live negatives, frozen-clock 21-call burst (10 accepted / 11 rate-limited) with live-path sentinels unused.
- `PLAN.md` — Phase 2 Remaining notes #140; Phase 4 Done records the HTTP burst pin without claiming the market-day exit.
- This inventory.

No order-path bypass. No release. No lockfile churn.
