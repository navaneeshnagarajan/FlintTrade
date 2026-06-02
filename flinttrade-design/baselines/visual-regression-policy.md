# Visual Regression Baseline Policy

FlintTrade keeps two visual baseline classes:

1. **Forensic baseline**: `flinttrade-design/baselines/visual-regression/d2ae362`.
   This is the pre-restructure snapshot tied to `pre-restructure-baseline`.
   Do not overwrite it.
2. **Current release baseline**: a new SHA-named directory generated from the
   current tree, for example `visual-regression/<current-short-sha>/`.
   Promote one only after an intentional design review.

Use `scripts/generate-visual-regression-baseline.sh <output-dir>` to capture the
full `312` PNG matrix. Validate any capture with:

```bash
./.venv/bin/python scripts/verify-visual-regression-capture.py <output-dir> --min-bytes 4096
```

Promotion rule:

- keep `d2ae362` immutable;
- add a new SHA directory for accepted current visuals;
- update `MANIFEST.json` only when the promoted directory becomes part of the
  tracked release baseline;
- record representative screenshots reviewed, command output, and any accepted
  intentional differences in the release notes.

The old pre-restructure baseline is useful for forensic comparison, but large
pixel diffs against the current Flint design language are expected. Current
release comparisons should use the latest accepted current SHA directory.
