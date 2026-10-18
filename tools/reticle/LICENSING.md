# Reticle correction carrier — licence boundaries

The cumulative `reticle-3.6.0.patch` and `source/` preserve upstream package licensing:

- `source/server/**`, including server tests and documentation: **FSL-1.1-ALv2**, as stated in `licenses/server/LICENSE`. This is not an Apache-only patch/package.
- `source/core/**`, `source/adapters/realm/browser/**`, and the inherited engine hydration correction: **Apache-2.0**, with complete package licences in `licenses/`.
- `licenses/LICENSE` is upstream's root licensing index, not a replacement for package licences.
- `tests/*.mjs` are the maintained Reticle qualification controls; treat the server-derived controls as **FSL-1.1-ALv2**. The application fixture and new orchestration remain subject to the FlintTrade repository licence; they do not relicense Reticle.
- The upstream Apache attribution texts are retained beside the licences: `licenses/core/NOTICE`, `licenses/engine/NOTICE` and `licenses/adapters/realm/browser/NOTICE`. Their bytes match the corresponding pinned archive entries in `reconstruction.json`.
- Runtime reconstruction retains the licences shipped in all pinned npm archives.

This carrier does not claim upstream approval, DCO sign-off, release/publication rights or final application qualification. Integrators must preserve the package-specific notices. Private wire captures, browser packets, qualification logs and operator evidence are not source inputs and must not be committed or uploaded.
