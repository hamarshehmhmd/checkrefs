#!/bin/sh
# Turn examples/tinyhttp into a small git repo with two releases (v1.3.0, v1.4.0) at $1 (default /tmp/tinyhttp).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-/tmp/tinyhttp}"
rm -rf "$DEST"
cp -R "$HERE/tinyhttp" "$DEST"
cd "$DEST"
export GIT_AUTHOR_NAME=sam GIT_AUTHOR_EMAIL=sam@example.com GIT_COMMITTER_NAME=sam GIT_COMMITTER_EMAIL=sam@example.com
git init -q -b main
git add -A
GIT_AUTHOR_DATE=2024-01-10T12:00:00 GIT_COMMITTER_DATE=2024-01-10T12:00:00 git commit -qm "tinyhttp 1.3.0"
git tag v1.3.0
echo "# 1.4.0: faster header parsing" >> README.md
GIT_AUTHOR_DATE=2024-06-10T12:00:00 GIT_COMMITTER_DATE=2024-06-10T12:00:00 git commit -qam "tinyhttp 1.4.0"
git tag v1.4.0
echo "$DEST"
