#!/bin/sh
# Run the pnpm release this repo pins, rather than the one Vercel's image ships.
#
# Vercel's build image carries its own pnpm (10.28.0 when this was written) and
# does not honour the root package.json `packageManager` pin, because Corepack is
# not enabled there. pnpm will not fetch its own pin either: pnpm-workspace.yaml
# sets `managePackageManagerVersions: false` deliberately, and
# `packageManagerStrictVersion: true` turns the resulting mismatch into a hard
# error. The image's pnpm therefore refuses to run at all — which is the correct
# outcome, since the alternative is a lockfile resolved by a version it was never
# written for.
#
# `npx --package` installs the requested spec and puts *its* bin directory first
# on PATH, so the pinned pnpm shadows the image's. The pin keeps a single home in
# the root package.json; nothing here writes the version down a second time.
#
# The `+sha512...` suffix has to be stripped, because `pnpm@<version>+sha512...`
# is not a published registry version and npx cannot resolve it. That does mean
# this lane is version-exact but no longer integrity-pinned: Corepack was the only
# thing that ever verified that digest, and this repo is deliberately
# Corepack-free. npm's own registry integrity still applies.
#
# This lives in a script rather than inline in vercel.json because Vercel caps
# buildCommand and installCommand at 256 characters, and the derivation does not
# fit.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../../.." && pwd)

# Resolved from inside repo_root with a relative require, in a subshell so the
# caller's working directory is untouched — vercel-build.sh depends on staying in
# packages/apps/site. Interpolating an absolute path into the JS string instead
# would break on any path node cannot resolve verbatim, or one carrying a quote
# or a backslash.
pin=$(
	cd "$repo_root" &&
		node -p "const v=(require('./package.json').packageManager||'').split('+')[0];if(!v.startsWith('pnpm@'))throw new Error('root package.json must pin pnpm in its packageManager field');v"
)

exec npx --yes --package "$pin" -- pnpm "$@"
