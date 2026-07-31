#!/bin/sh
# Vercel's installCommand for the site.
#
# Runs from packages/apps/site (the project's configured root directory) and
# installs the whole workspace from the repo root, so the site resolves against
# the same frozen lockfile everything else does.
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$here/../../../.." && pwd)

cd "$repo_root"

# The site's pnpmfile has to be visible at the workspace root for the install to
# pick it up; Vercel checks out the whole repo but runs with the site as its root.
if [ ! -f .pnpmfile.cjs ]; then
	cp packages/apps/site/pnpmfile.cjs .pnpmfile.cjs
fi

exec "$here/vercel-pnpm.sh" install --frozen-lockfile --reporter=append-only
