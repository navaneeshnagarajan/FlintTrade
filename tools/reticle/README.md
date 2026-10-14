# Maintained Reticle correction carrier

This is an offline **test/setup carrier**, not a second application runtime or an upstream release. It reconstructs the accepted `reticle-3.6.0+r101.correction.1` package from public inputs, then runs the repository's current `shared-core-integrated.spec.ts` through the existing fixture registry, Vite registration and normal Flask factory.

Qualified package-map SHA-256:

```
43d63a9f647032663d6f190fcfa61afaa594792a16079a3008ec82b9fef18b5e
```

`qualification.json` distinguishes the historical R101/R83/R63 application proof from the still-required current-application run. A successful setup or toolkit control is **not** current-stack acceptance.

## Public inputs and reconstruction

1. `pristine-archives.json` lists every inherited public npm archive by URL, SRI and local filename. Obtain those bytes in a separate dependency-acquisition phase; no application execution is required. `reconstruct-pristine.py` accepts that archive directory or an explicit npm cache, verifies all archive digests, reconstructs the recorded public lock/bin links, and checks the complete file/link inventory. It does not require an `_npx` directory or copy a prior runtime.
2. `reconstruction.json` lists the nine public upgrade tarballs by exact filename, URL and SHA-256. Retain these separately under `RETICLE_ARCHIVES`.
3. Supply extracted TypeScript **6.0.3** (`https://registry.npmjs.org/typescript/-/typescript-6.0.3.tgz`), `@types/node` **26.6.4**, `@types/ws` **8.18.2**, and `@types/pngjs` **6.0.5**. Their registry tarball URLs use `https://registry.npmjs.org/@types/NAME/-/NAME-VERSION.tgz`; every extracted file/link is bound in `qualification.json`. The compiler archive SHA-256 is `33cd0ee1beaa8c9e9d15a9da836c62ddea4c34a42d7c2d349dbc80d94165d22a`.
4. `hydration.patch.json` is the retained R39/R42 reconstruction dependency. The reconstructed hydration map must equal `c6d431df947e6e92014ac52b3a9dd32dc539b74b41dde18feff716eb4b4e78c1` before building anything.
5. `reticle-3.6.0.patch` and `source/` carry the cumulative source changes against upstream commit `c08be484e72d578b0f226122b9bef90d412f99ad`. Build all seventeen affected production modules with strict declarations/maps; verify the entire final package map against the qualified digest above. **The source patch alone is not package closure.**

`setup.py` neither fetches dependencies nor installs into the application's node_modules. It refuses nonfresh output, wrong source/compiler/type inputs, changed reconstruction bytes and a changed final package. See `LICENSING.md`: server source/tests remain **FSL-1.1-ALv2**, not Apache-only.

## CI connection

The existing current-runtime browser job prepares a clean exact-head source tree,
installs the frozen application dependencies at their final paths and obtains the
lockfile-selected Chromium. Its separate acquisition command is:

```sh
python -B tools/reticle/acquire.py --output "$SOURCE/.ci-inputs/reticle"
```

This downloads only the declared primary npm archives and verifies their pinned
hashes. `build-archives.json` pins the documented compiler/type archives; every
extracted file still must match `qualification.json`. Acquisition never runs npm
lifecycle scripts, a compiler or the application. It is not a no-egress exception
for tests: reconstruction, compilation and acceptance use `tools/acceptance/isolated.py`.

CI runs reconstruction/setup into disposable output, ends that invocation, then
admits only that fresh output at `tools/reticle/runtime` for a second, read-only
invocation. The latter runs the unchanged terminal **full `e2e` aggregate** with
explicit current Python and writable Vite-cache paths. No lane, case, predicate,
skip policy, package digest or dependency policy is replaced. Failures propagate
through `terminal-e2e-infra-self-tests` to the existing required `python-tests`
summary. Floor lanes and their original commands remain independently required.

The Python invariant matrix additionally builds the current ticks crate with
hash-pinned Maturin, an explicit interpreter and a source-keyed fresh Cargo target.
It compares before/after source inputs, imports `tick_engine` from the selected
environment, matches the actual extension bytes to the fresh wheel, checks the
distribution/interpreter versions and makes a native functional call. Cargo-only
results and optional binding-test skips cannot satisfy that check. No installer or
release artifact is produced by these additions.

## Compiler compatibility

The primary npm registry reports **7.0.2** as latest stable. It is not a drop-in compiler API for this builder: executing its published root yields only `version` and `versionMajorMinor`; `lib/typescript.js` is absent, and actual calls to `transpileModule` and `createProgram` fail. Its `unstable/sync` and `unstable/async` exports are replacement APIs, not the required classic exports. Its CLI does execute successfully as 7.0.2; this carrier-specific API constraint does **not** constrain the application's compiler or claim TypeScript 7 cannot compile these sources through a different builder.

**6.0.3** is the newest published stable 6.x and retains the required programmatic API. The build replaces deprecated `baseUrl` with absolute `paths` targets to the same package-local check directory. All strict checks remain enabled; no `ignoreDeprecations` suppression is used. Native module-resolution comparisons cover all 38 affected `@/` imports, and negative compiler controls exercise nullability, unchecked indexing, exact optional properties, unused locals/parameters and implicit returns.

Fresh 6.0.3 compilation of the unchanged seventeen production modules and declaration/maps reproduced the complete **5,749-entry** package map above byte-for-byte. Thus its fingerprint is unchanged, not fabricated as a new upstream release. **5.9.3 is no longer a setup dependency**, including historical-byte reconstruction. Reticle-only controls and selected upstream regressions were rerun; the original six-case/seven-window current-application acceptance remains separately required.

The public SDK package names are `@reticlehq/react` and `@reticlehq/vite-plugin`; both, and `@reticlehq/server`, were independently verified at 3.6.0. There is no assumed `@reticlehq/sdk` dependency.

## Execution contract

Run every command below **inside the already-qualified isolation launcher**: fresh hidden HOME, no egress, ordinary UID, zero capabilities, owned loopback. These programs do not create or weaken that boundary. `/run/test` is its output/runtime namespace, not a historical input dependency. Python optimisation is refused.

After setting explicit absolute input paths within that boundary:

```sh
python tools/reticle/reconstruct-pristine.py \
  --archive-dir "$RETICLE_PRISTINE_ARCHIVES" \
  --output /run/test/pristine-node-modules

python tools/reticle/setup.py \
  --pristine /run/test/pristine-node-modules \
  --archives "$RETICLE_ARCHIVES" \
  --typescript "$RETICLE_TYPESCRIPT" \
  --node "$RETICLE_NODE_TYPES" \
  --ws "$RETICLE_WS_TYPES" \
  --pngjs "$RETICLE_PNGJS_TYPES" \
  --output /run/test/reticle/package
```

End that build invocation. Copy only its newly generated `reticle/` directory to
`tools/reticle/runtime` in the prepared source-only input tree, **outside** the
execution boundary. Start a new invocation: the source, qualified package and
consumers are now all read-only inputs. Do not use a writable source overlay.

```sh
python tools/reticle/run.py controls
python tools/reticle/run.py collect
python tools/reticle/run.py infra
python tools/reticle/run.py original --python "$QUALIFIED_CURRENT_PYTHON"
```

The last command requires an explicitly parent-qualified **Python 3.14.8 dependency environment**. Its editable sources must resolve to the current application; the fixture records real module origins and refuses old application sources. There is no 3.14.7 fallback, no automatic selection of an earlier application snapshot, and no provider/broker credential access.

The controller sets up the existing shared-core fixture's normal-factory core, real API relay, read-only discovery observer and MCP client. It selects only the existing original six cases, one worker, zero retries, with no filters or caller-provided Playwright flags. The seven original windows and all count/body/geometry guards remain required. Runtime modules are selected only by the dedicated `vite.reticle.config.ts`; `src/reticle-dev.ts` retains the production stores/QueryClient registration. Other browser configurations are unchanged.

## Capture invariants

- Snapshot immediately after the original live export, before supplemental wire export or receipt materialisation.
- Preserve the entire initial packet and post-endpoint tail. Materialise only the snapshot's exact final sequence; never extend the observation window.
- Native evaluation receives the original capture scope. Registry-object/incarnation/document/epoch drift is rejected before and after the awaited evaluation.
- Public wire pages use the exact `withoutUrlRaw` projection; private raw custody remains untouched.
- Zod validates without coercion/defaults or replacing the raw objects.
- Require original and fresh `verified: "yes"` **and** `pass: true`, plus capture accounting and lifecycle checks.

`controls` includes real Chromium/WebSocket lifecycle and endpoint tests. Raw-boundary tests consume the fresh endpoint test's packet, not a private archived application fixture. Toolkit controls run outside application project registration, as the original isolated controls did; current-app collection/execution uses explicit maintained config paths.

## Acceptance and evidence

Keep `/run/test/artifacts` private. The runner checks six JUnit cases (including both failure and error nodes), seven accepted packets and owned-port teardown. Final parent acceptance must still reconcile exact bodies/relay/core ledgers, geometry, scope/native transcripts and current source/runtime fingerprints. No setup receipt, source patch, toolkit green, or test collection replaces that readback. R99-S4 optional paging refactoring remains deferred.

### CI publication boundary

Actions artifacts are readable by repository readers, not private custody. The
maintained CI lane uploads exactly `public-evidence/maintained-summary.json`,
produced by `scripts/ci_artifact_projection.py`. Its allowlist is schema version,
validated commit SHA, numeric process exit (or null), boolean isolation status
(or null), fixed lane completion flags, fixed report IDs and validated numeric
outcome counts, projection validity, fixed issue codes and
`acceptance_verified: false`. Missing or inconsistent reports have null counts;
real failures and errors are retained, never rewritten to zero. This projection
does not replace any existing acceptance validator or raw evidence join.

No raw labels, test titles, command lines, URLs, tokens, request/response bodies,
wire fields, traces, screenshots, paths or exception text enter the projection.
The original raw files and launcher logs remain untouched in runner-local state;
launcher output is also redirected there rather than echoed to Actions logs.
Hosted runner-local custody expires when the runner is destroyed. This workflow
configures no durable private store and does not claim otherwise; durable raw
retention requires a separately authorised private custodian, never an expanded
public upload glob.

### Native acceptance preparation is not execution evidence

The existing Python invariant matrix prepares an exact-head source-only tree,
installs frozen dependencies at its final path and builds/installs the locked
wheel there. Only then does the unchanged `tools/acceptance/isolated.py` launch
`scripts/ci_runtime.py native`, with the source, environment, wheel and input
receipt read-only. Native acceptance reuses the existing guard and requires
EROFS, selected environment identity, current inputs, installed-wheel byte and
version correspondence, an actual extension loader and the functional call.
Inert build/extension dispatch controls do not prove a real ABI. Positive native
acceptance remains a hosted job obligation, not a local build claim.
