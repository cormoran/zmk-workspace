#!/usr/bin/env bash
# Install the Renode portable (self-contained) Linux tarball. No system mono/dotnet
# required — the portable bundle ships its own runtime.
#
# Usage: install_renode.sh [version]
# Installs to $RENODE_HOME (default: $HOME/.renode/<version>) and prints the
# path to the `renode` launcher on the last line.
set -euo pipefail

VERSION="${1:-1.16.1}"
RENODE_ROOT="${RENODE_ROOT:-$HOME/.renode}"
DEST="$RENODE_ROOT/$VERSION"
LAUNCHER="$DEST/renode"

if [ -x "$LAUNCHER" ]; then
  echo "renode $VERSION already installed" >&2
  echo "$LAUNCHER"
  exit 0
fi

mkdir -p "$RENODE_ROOT"
# Prefer the self-contained "portable" build (bundles mono). Fall back to the
# dotnet portable build if the mono one is unavailable for the version.
TARBALL="renode-${VERSION}.linux-portable.tar.gz"
URL="https://github.com/renode/renode/releases/download/v${VERSION}/${TARBALL}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "downloading $URL" >&2
if ! curl -fSL "$URL" -o "$TMP/$TARBALL"; then
  TARBALL="renode-${VERSION}.linux-portable-dotnet.tar.gz"
  URL="https://github.com/renode/renode/releases/download/v${VERSION}/${TARBALL}"
  echo "falling back to $URL" >&2
  curl -fSL "$URL" -o "$TMP/$TARBALL"
fi

mkdir -p "$DEST"
tar -xzf "$TMP/$TARBALL" -C "$DEST" --strip-components=1

if [ ! -x "$LAUNCHER" ]; then
  # Some bundles name the launcher differently; find it.
  LAUNCHER="$(find "$DEST" -maxdepth 2 -name 'renode' -type f | head -1)"
fi
[ -x "$LAUNCHER" ] || { echo "ERROR: renode launcher not found under $DEST" >&2; exit 1; }

echo "installed renode $VERSION -> $LAUNCHER" >&2
echo "$LAUNCHER"
