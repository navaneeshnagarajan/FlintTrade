# FlintTrade patch note

This directory vendors `plist` 1.9.0 temporarily for the desktop Tauri build.
The only runtime change from the published crate is bumping `quick-xml` from
`0.39.2` to `0.41.0` so `cargo audit` clears `RUSTSEC-2026-0194`.
Upstream test fixtures are included so the vendored crate can still be tested
locally after the dependency bump.

Remove this patch once `plist` publishes a compatible release that depends on
`quick-xml >=0.41.0`.
