#!/bin/sh
# Vercel's buildCommand for the site.
#
# `pnpm run` trips the same strict-version gate as `pnpm install`, so this has to
# go through the pinned pnpm too — fixing only the install command moves the
# failure one step later rather than removing it.
#
# Deliberately does not change directory: Vercel runs this from
# packages/apps/site, which is where the build script lives.
set -eu

exec "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/vercel-pnpm.sh" run build
