#!/usr/bin/env bash
# Guard for a manual Release run (workflow_dispatch) that releases an already-tagged commit.
#
# Usage: check-tagged-release.sh <version>
#   e.g. check-tagged-release.sh 0.12.1
#
# Passes only when:
#   1. HEAD already carries at least one tag (pre-release or not; the kind is not checked).
#   2. The requested <version> tag does not exist locally or on origin.
# Run from a checkout with tags fetched (actions/checkout with fetch-depth: 0).
# Exits 1 with a ::error:: annotation when a check fails, so the Release job stops before tagging.
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "usage: $0 <version>" >&2
  exit 2
fi

VERSION="$1"

# Same shape as the SemVer check in release.yml, without a leading "v".
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  echo "::error::'${VERSION}' is not a SemVer version. Use e.g. 0.12.1 or 0.12.1-rc1 (no leading v)."
  exit 1
fi

HEAD_SHA=$(git rev-parse --short HEAD)
HEAD_TAGS=$(git tag --points-at HEAD)

if [ -z "$HEAD_TAGS" ]; then
  echo "::error::HEAD (${HEAD_SHA}) carries no tag. A manual release needs a commit that is already tagged."
  echo "::error::For a release that includes new commits, use a release/${VERSION} branch and PR instead."
  exit 1
fi

echo "HEAD ${HEAD_SHA} carries tag(s): $(echo "$HEAD_TAGS" | paste -sd ' ' -)"

if git rev-parse -q --verify "refs/tags/${VERSION}" >/dev/null; then
  echo "::error::tag '${VERSION}' already exists locally. Choose a version that has not been released."
  exit 1
fi

if ! REMOTE_REFS=$(git ls-remote --tags origin "refs/tags/${VERSION}"); then
  echo "::error::could not query origin for tags. Re-run the workflow later."
  exit 1
fi
if [ -n "$REMOTE_REFS" ]; then
  echo "::error::tag '${VERSION}' already exists on origin. Choose a version that has not been released."
  exit 1
fi

echo "OK: tag '${VERSION}' is free locally and on origin; HEAD is already tagged."
