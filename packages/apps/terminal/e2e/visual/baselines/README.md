# Visual baselines

Screenshot baselines for `e2e/visual-a11y.spec.ts` live in this directory.
They are produced by one runner only: the `visual-a11y.yml` workflow on
`ubuntu-latest`, which is the same hosted image as the terminal Playwright
job. Do not commit baselines generated on a laptop or another image. Font
rasterisation and subpixel coverage will not match, and every later run
will report a false diff.

## Regenerate

1. Push the branch that should receive the files.
2. In GitHub Actions, run **Visual and accessibility** with
   **Regenerate screenshot baselines** turned on, against that branch.
3. The job runs Playwright with snapshot updates, commits
   `*-chromium-linux.png` files and the axe snapshot when they changed,
   and pushes to the same branch. It also uploads the images as an artifact
   named `visual-baselines`.

The job stays green while `VISUAL_AXE_GATE` is `"0"`. Changing that value
to `"1"` is the gate. Leave it advisory until several pull requests have
reported no unexpected diffs.

Axe snapshots (`known-axe-violations.json`) record rule ids and targets,
not pixels. A review run can refresh them with `UPDATE_AXE_SNAPSHOT=1`.
Pixel baselines still come only from the workflow above.

Reticle does not judge these pictures. It reads network, app state, and
the console. Contrast, spacing, and clipping are what this directory is for.
