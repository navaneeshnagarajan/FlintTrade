# FlintTrade v0.5.2-dev - SemVer release hygiene snapshot

## Summary

FlintTrade v0.5.2-dev is a prerelease snapshot that records the release
metadata cleanup after the stable v0.5.1 patch. It keeps v0.5.1 immutable,
advances the active development tree to the next patch prerelease, and aligns
the local changelog, manifests, tags, and GitHub release structure with
Semantic Versioning.

## Release Type

- SemVer: `0.5.2-dev`
- Git tag: `v0.5.2-dev`
- GitHub release state: prerelease, not latest
- Stability: development snapshot
- Base release: `v0.5.1`
- Latest stable: `v0.5.1`

## Highlights

- Standardised the release-note structure across GitHub releases using the
  same sections: Summary, Release Type, Highlights, Verification, Upgrade
  Notes, and Tag Details.
- Rebuilt annotated tags so their tagger chronology follows the project
  release timeline: alpha, beta, stable, patch, then this dev snapshot.
- Rebuilt GitHub releases in a clean SemVer sequence while keeping prereleases
  marked as prereleases and v0.5.1 marked as the latest stable release.
- Advanced the current tree to `0.5.2-dev` in root metadata, release-tracked
  Python packages, terminal package metadata, and desktop Tauri metadata.
- Documented release rules: manifests use bare SemVer, git tags use
  `v<semver>`, independent package tracks stay independent, and published
  releases are not retargeted after publication.

## Verification

- SemVer rules checked against https://semver.org/.
- Local tag chronology checked with `git for-each-ref refs/tags --sort=creatordate`.
- GitHub release order and prerelease/latest flags checked with
  `gh release list`.
- Release bodies checked for the standard section set.
- Version metadata checked across manifests with `git grep`.

## Upgrade Notes

- Production users should remain on `v0.5.1` until a stable `v0.5.2` release is
  cut.
- `0.5.2-dev` is valid SemVer prerelease syntax. Python packaging tools may
  normalise it internally as `0.5.2.dev0`; the source manifests keep the project
  SemVer spelling.
- The Chrome extension, tick-engine, and private desktop npm shell keep their
  independent package versions.

## Tag Details

- Tag type: annotated
- Target: the commit containing this prerelease metadata snapshot
- Previous stable tag: `v0.5.1`
