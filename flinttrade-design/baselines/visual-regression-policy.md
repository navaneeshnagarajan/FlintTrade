# Visual Regression Baseline Policy

FlintTrade keeps two visual baseline classes:

1. **Forensic baseline**: `flinttrade-design/baselines/visual-regression/d2ae362`.
   This is the pre-restructure snapshot tied to `pre-restructure-baseline`.
   Do not overwrite its retained snapshots. The authorised retirement exception
   below records the historical snapshots removed from the repository.
2. **Current release baseline**: a new SHA-named directory generated from the
   current tree, for example `visual-regression/<current-short-sha>/`.
   Promote one only after an intentional design review.

Use `scripts/generate-visual-regression-baseline.sh <output-dir>` to capture the
full `312` PNG matrix. Validate every new current capture with:

```bash
./.venv/bin/python scripts/verify-visual-regression-capture.py <output-dir> --min-bytes 4096
```

Promotion rule:

- keep the retained `d2ae362` snapshots immutable;
- add a new SHA directory for accepted current visuals;
- update `MANIFEST.json` only when the promoted directory becomes part of the
  tracked release baseline;
- record representative screenshots reviewed, command output, and any accepted
  intentional differences in the release notes.

The old pre-restructure baseline is useful for forensic comparison, but large
pixel diffs against the current Flint design language are expected. Current
release comparisons should use the latest accepted current SHA directory.

## Authorised retirement exception (2026-10-05)

The maintainer's whole-repository provider retirement includes rendered assets.
The historical `site/root`, `site/docs` and `site/api-reference` route families
showed retired provider features. Their 36 PNG variants were removed, leaving
276 historical images. These removals are recorded in `MANIFEST.json` and in
`d2ae362/retained-snapshots.json`; the latter records the unchanged SHA-256 of
every retained image. This is a closed historical removal, not permission to
overwrite the remaining forensic snapshots.

`tests/test_baseline_artifacts.py` verifies the exact retained route matrix,
absence of the retired families and every retained digest. The signed baseline
tag and unrelated CSV, build, test-count and signer artefacts remain unchanged.
The current release capture matrix and validator still require all 312 images.
