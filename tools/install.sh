#!/usr/bin/env bash
# Einrichtung von bl auf Hufflepuff (idempotent): Pillow fuer den Worker nach .deps/, Symlink ~/bin/bl.
set -eu
here="$(cd "$(dirname "$0")/.." && pwd)"
bdir="${BL_BLENDER_DIR:-/mnt/caches/ComfyUI/_tools/blender-5.2.4-linux-x64}"
py="$(ls "$bdir"/*/python/bin/python3.* | head -1)"
env -u LD_LIBRARY_PATH -u PYTHONPATH "$py" -s -m pip install --quiet --disable-pip-version-check \
  --target "$here/.deps" --upgrade "pillow==12.3.0"
mkdir -p "$HOME/bin"
ln -sfn "$here/bin/bl" "$HOME/bin/bl"
echo "✓ Pillow in $here/.deps, Symlink $HOME/bin/bl -> $here/bin/bl"
