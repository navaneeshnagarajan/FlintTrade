# Public-site local rollback and teardown

## Scope

This procedure covers reversible cleanup of an isolated local checkout used for public-site preparation. It does not authorise remote publication, account access, credential use, domain changes, payment actions, production changes, broker access, or trading activity.

The operator supplies these shell variables before using the examples:

```bash
export REPO_ROOT="/absolute/path/to/canonical-repository"
export PREP_CHECKOUT="/absolute/path/to/isolated-checkout"
export PREP_REF="refs/heads/example-preparation-ref"
export ROLLBACK_BUNDLE="/safe/path/public-site-preparation.bundle"
export SITE_SERVICE_UNIT="flinttrade-site.service"
```

`REPO_ROOT` must be the absolute, canonical top-level path of an approved repository checkout that will survive this procedure. It must not name `PREP_CHECKOUT`. Resolve symlinks before setting either path. Replace the examples with operator-approved local values, and do not store credentials in these variables.

## Preconditions

Validate the paths and inspect the isolated checkout and service state separately:

```bash
test "${REPO_ROOT#/}" != "$REPO_ROOT"
test "${PREP_CHECKOUT#/}" != "$PREP_CHECKOUT"
test "$REPO_ROOT" != "$PREP_CHECKOUT"
test -d "$REPO_ROOT"
test -d "$PREP_CHECKOUT"
git -C "$REPO_ROOT" rev-parse --show-toplevel
git -C "$REPO_ROOT" worktree list --porcelain
git -C "$REPO_ROOT" -C "$PREP_CHECKOUT" status --short
git -C "$REPO_ROOT" -C "$PREP_CHECKOUT" diff
systemctl --user is-active "$SITE_SERVICE_UNIT"
```

Confirm that the top-level output exactly matches `REPO_ROOT` and that the worktree listing associates `PREP_CHECKOUT` with `PREP_REF` before continuing. Do not remove the isolated checkout while the site service is active. Stop the local service through its approved supervisor, then repeat the service-state command. Preserve any unrelated uncommitted change before continuing.

## Reversible preservation

Create and verify a portable Git bundle before cleanup:

```bash
git -C "$REPO_ROOT" bundle create "$ROLLBACK_BUNDLE" "$PREP_REF"
git -C "$REPO_ROOT" bundle verify "$ROLLBACK_BUNDLE"
```

Both commands must succeed. Keep the named ref until the retention period ends.

## Preferred cleanup

Use the repository-anchored non-force command. No directory change is required:

```bash
git -C "$REPO_ROOT" worktree remove "$PREP_CHECKOUT"
```

If removal refuses because the checkout is dirty or locked, stop. Review and preserve the remaining state instead of escalating automatically. Do not delete generated paths separately; successful worktree removal already removes checkout-local generated output.

## Restoration

Confirm the preserved ref still exists, then recreate the isolated checkout:

```bash
git -C "$REPO_ROOT" show-ref --verify "$PREP_REF"
git -C "$REPO_ROOT" worktree add "$PREP_CHECKOUT" "$PREP_REF"
```

If the preserved ref is unavailable, restore it from the verified bundle before recreating the checkout:

```bash
git -C "$REPO_ROOT" fetch "$ROLLBACK_BUNDLE" "$PREP_REF:$PREP_REF"
git -C "$REPO_ROOT" worktree add "$PREP_CHECKOUT" "$PREP_REF"
```

## Optional final ref cleanup

Delete the local ref only after the retention period, bundle verification, service shutdown, and confirmation that no surviving checkout uses it:

```bash
git -C "$REPO_ROOT" branch -d "${PREP_REF#refs/heads/}"
```

If safe deletion refuses, retain the ref and investigate. Do not make force deletion the default.

## Verification

```bash
git -C "$REPO_ROOT" worktree list
git -C "$REPO_ROOT" bundle verify "$ROLLBACK_BUNDLE"
systemctl --user is-active "$SITE_SERVICE_UNIT"
```

Expected results depend on whether cleanup or restoration was selected, but the bundle must remain verifiable and the service state must match the operator's intended state.
