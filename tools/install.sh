#!/usr/bin/env bash
# Set up bl (idempotent): Pillow + docutils into .deps/, documentation data into .docs/, symlink ~/bin/bl.
# Machine config (optional): ${XDG_CONFIG_HOME:-$HOME/.config}/bl/env with plain `export VAR=...` lines.
set -eu
cfg="${XDG_CONFIG_HOME:-$HOME/.config}/bl/env"
# shellcheck disable=SC1090
[ -f "$cfg" ] && . "$cfg"
here="$(cd "$(dirname "$0")/.." && pwd)"
if [ -n "${BL_BLENDER_DIR:-}" ]; then
  bdir="$BL_BLENDER_DIR"
elif command -v blender >/dev/null 2>&1; then
  bdir="$(dirname "$(readlink -f "$(command -v blender)")")"
else
  echo "✗ Blender not found: set BL_BLENDER_DIR (directory of the official Blender archive) or put 'blender' on PATH" >&2
  exit 3
fi
py="$(ls "$bdir"/*/python/bin/python3.* 2>/dev/null | head -1)"
[ -x "$py" ] || { echo "✗ Blender's bundled Python not found under $bdir" >&2; exit 3; }
env -u LD_LIBRARY_PATH -u PYTHONPATH "$py" -s -m pip install --quiet --disable-pip-version-check \
  --target "$here/.deps" --upgrade "pillow==12.3.0" "docutils==0.23"
# Documentation data for `bl docs`: RST from the official Blender MCP, same commit as vendor/bl_docs
docs_rev="dbbf836"
docs_src="${BL_DOCS_SRC:-}"
if [ -n "$docs_src" ] && [ -d "$docs_src/mcp/blmcp/data/api" ]; then
  rev="$(git -C "$docs_src" rev-parse --short=7 HEAD 2>/dev/null || echo ?)"
  [ "$rev" = "$docs_rev" ] || echo "⚠ docs source is at $rev instead of $docs_rev ($docs_src)"
  rm -rf "$here/.docs.tmp" && mkdir -p "$here/.docs.tmp"
  cp -a "$docs_src/mcp/blmcp/data/api" "$docs_src/mcp/blmcp/data/manual" "$here/.docs.tmp/"
  rm -rf "$here/.docs" && mv "$here/.docs.tmp" "$here/.docs"
  echo "✓ documentation data in $here/.docs (source $docs_src @ $rev)"
else
  echo "⚠ skipping documentation data for 'bl docs' (BL_DOCS_SRC ${docs_src:-not set}). To enable it:"
  echo "    git clone https://projects.blender.org/lab/blender_mcp.git && git -C blender_mcp checkout $docs_rev"
  echo "    BL_DOCS_SRC=\$PWD/blender_mcp bash tools/install.sh"
fi
mkdir -p "$HOME/bin"
ln -sfn "$here/bin/bl" "$HOME/bin/bl"
echo "✓ Pillow + docutils in $here/.deps, symlink $HOME/bin/bl -> $here/bin/bl"
