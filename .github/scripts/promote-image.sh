#!/usr/bin/env bash
# Promote an already-tested multi-arch image to one or more destination references by
# copying the manifest list and all platform images with their digests preserved.
#
# Usage: promote-image.sh <source-ref> <dest-ref>...
#   e.g. promote-image.sh localhost:5000/margot:candidate ghcr.io/org/margot:1.2.3 ghcr.io/org/margot:latest
#
# TLS verification is disabled only for localhost / 127.0.0.1 registries.
# Credentials come from the docker config written by docker/login-action
# (skopeo falls back to ~/.docker/config.json).
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <source-ref> <dest-ref>..." >&2
  exit 2
fi

SRC="$1"
shift

if ! command -v skopeo >/dev/null 2>&1; then
  echo "skopeo not found, installing"
  sudo apt-get update
  sudo apt-get install -y skopeo
fi

# Print the registry host (without port) of an image reference.
ref_host() {
  local first="${1%%/*}"
  if [ "$first" = "$1" ] || { [[ "$first" != *.* ]] && [[ "$first" != *:* ]] && [ "$first" != "localhost" ]; }; then
    echo "docker.io"
  else
    echo "${first%%:*}"
  fi
}

is_local() {
  case "$(ref_host "$1")" in
    localhost | 127.0.0.1) return 0 ;;
    *) return 1 ;;
  esac
}

# Digest of the top-level manifest (the index), i.e. sha256 of its raw bytes.
index_digest() {
  local ref="$1"
  shift
  local sum
  sum=$(skopeo inspect --raw "$@" "docker://${ref}" | sha256sum)
  echo "sha256:${sum%% *}"
}

src_tls=()
if is_local "$SRC"; then src_tls=(--tls-verify=false); fi

SRC_DIGEST=$(index_digest "$SRC" "${src_tls[@]}")
echo "Source ${SRC} index digest: ${SRC_DIGEST}"

for DEST in "$@"; do
  copy_args=(--all --preserve-digests)
  dest_tls=()
  if is_local "$SRC"; then copy_args+=(--src-tls-verify=false); fi
  if is_local "$DEST"; then
    copy_args+=(--dest-tls-verify=false)
    dest_tls=(--tls-verify=false)
  fi

  echo "Promoting ${SRC} -> ${DEST}"
  skopeo copy "${copy_args[@]}" "docker://${SRC}" "docker://${DEST}"

  DEST_DIGEST=$(index_digest "$DEST" "${dest_tls[@]}")
  if [ "$DEST_DIGEST" != "$SRC_DIGEST" ]; then
    echo "::error::digest mismatch for ${DEST}: expected ${SRC_DIGEST}, got ${DEST_DIGEST}"
    exit 1
  fi
  echo "OK ${DEST} -> ${DEST_DIGEST}"
done
