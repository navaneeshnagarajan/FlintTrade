# Packaging configuration regressions

`../packaging-configuration.test.ts` is discovered by the existing Electron Vitest configuration. It validates the installed builder schema, compares the configured hashes to the retained published Electron checksum list, and executes the real AppImage target and Linux desktop serializer. Its inert packager fixture supplies a desktop name; it does not qualify application registration, packaging or runtime sandbox operation.

## Pinned acquisition contract

The installed `app-builder-lib` 26.17.0 accepts `ElectronGetOptions`. Configure `electronDownload` with **`force: false` and `checksums`**, with **no `mirrorOptions` property**:

- `force: false` explicitly retains cache reads. In 26.17.0, `checksums` also selects the modern options branch in `buildElectronArtifactConfig`; removing `force` no longer drops validation. Keep the configured `force: false` unchanged.
- `ElectronFramework.createDownloadOpts` passes these fields through when `mirrorOptions` is absent. Adding even an empty `mirrorOptions` selects a different branch that drops the checksums.
- `@electron/get` 3.1.0 validates a cache hit. Without explicit hashes, it bypasses the checksum-file cache and attempts a fresh request. Pinning hashes prevents that request; it does not disable validation.

`electron-v44.9.3-SHASUMS256.txt` is the exact published release list from:

`https://github.com/electron/electron/releases/download/v44.9.3/SHASUMS256.txt`

Its SHA-256 is `700028090148758e3c2b9c53bd0403499c9867168302fa14fa28ace1bfdae303`. It was retained from the already-acquired, reviewed input set, not synthesized from the local ZIP. This unsigned checksum list is not a detached publisher signature. When upgrading Electron, refresh the original published list and configured target hashes together, then rerun both test classes below.

## Explicit real-archive regression

`probe-packaging.cjs` is a portable fixture consumer, not an installer or an isolation launcher. Run it **only inside the existing approved no-egress isolation**, with a disposable HOME/cache, read-only source/dependencies and a read-only, previously acquired published Linux x64 ZIP. Do not run it against an operator cache. It makes independent writable cache copies, never alters the source archive, and does not execute Electron. It uses the unchanged installed downloader; no mirror/downloader injection or dependency edits are involved.

Within that boundary, run the pinned Node executable as follows:

```text
node electron/fixtures/probe-packaging.cjs <absolute-desktop-dir> <absolute-published-electron-zip> <fresh-output-dir> <case>
```

Cases and required observations:

| Case | Expected child exit | Required observation |
|---|---:|---|
| `original` | 1 | Original missing checksums attempts fresh acquisition and is refused by no-egress isolation. |
| `api` | 0 | `downloadElectronArtifactZip` returns the real cached ZIP with the published digest, without a download attempt. |
| `framework` | 0 | `createElectronFrameworkSupport(...).prepareApplicationStageDirectory(...)` uses the canonical options construction, acquisition and extraction path; Linux Electron is present, default app and version files are cleaned. |
| `corrupt` | 1 | A one-byte-corrupted independent cached ZIP produces the real library's `ChecksumMismatchError`; fallback acquisition is refused. |
| `mismatch` | 1 | An intentionally wrong expected hash produces `ChecksumMismatchError`; fallback acquisition is refused. |
| `missing-entry` | 1 | Missing filename produces `NoChecksumFoundError`; fallback acquisition is refused. |
| `without-force` | 0 | Checksums alone now selects the modern options branch: the real cached ZIP is returned with the published digest. Independently corrupting that cache without force must still emit `ChecksumMismatchError` and refuse fallback acquisition. |
| `mirror-options` | 1 | Adding empty mirror options loses hashes through the actual framework consumer. |
| `launcher` | 0 | Real target/helper output is saved as `original.desktop` and `corrected.desktop`: `Exec=AppRun --no-sandbox %U` versus `Exec=AppRun %U`. |

Each case writes `result.json`; preserve stdout and stderr too. The installed API catches cache-validation failures and attempts a re-download, so the final negative error is **ENOTFOUND**, not the checksum error. The checksum error must also be present in the library's real debug diagnostics. A nonzero exit without that evidence is not the corruption oracle. Never enable egress to make negative controls finish differently.

The `launcher` case uses exact package metadata and retains any existing desktop-name warning rather than silently adding registration fields. Empty `appImage.executableArgs` removes only the inherited sandbox-disabling argument. It does not change FUSE2, AppImage toolsets, fuses, runtime policy, or the canonical packaging commands.

These tests are not a built/extracted AppImage, installer qualification, Chromium sandbox acceptance, native Windows/macOS/arm64 evidence, or a substitute for the repository's full desktop build/package gates.
