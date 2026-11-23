#!/usr/bin/env bash
# Einrichtung von bl auf Hufflepuff (idempotent): Pillow + docutils nach .deps/, Doku-Daten nach .docs/, Symlink ~/bin/bl.
set -eu
here="$(cd "$(dirname "$0")/.." && pwd)"
bdir="${BL_BLENDER_DIR:-/mnt/caches/ComfyUI/_tools/blender-5.2.4-linux-x64}"
py="$(ls "$bdir"/*/python/bin/python3.* | head -1)"
env -u LD_LIBRARY_PATH -u PYTHONPATH "$py" -s -m pip install --quiet --disable-pip-version-check \
  --target "$here/.deps" --upgrade "pillow==12.3.0" "docutils==0.23"
# Doku-Daten fuer `bl docs`: RST aus dem offiziellen Blender-MCP, gleicher Commit wie vendor/bl_docs
docs_src="${BL_DOCS_SRC:-/mnt/caches/neon_build/huffwork/blender-mcp-official/official}"
docs_rev="dbbf836"
if [ -d "$docs_src/mcp/blmcp/data/api" ]; then
  rev="$(git -C "$docs_src" rev-parse --short=7 HEAD 2>/dev/null || echo ?)"
  [ "$rev" = "$docs_rev" ] || echo "⚠ Doku-Quelle auf $rev statt $docs_rev ($docs_src)"
  rm -rf "$here/.docs.tmp" && mkdir -p "$here/.docs.tmp"
  cp -a "$docs_src/mcp/blmcp/data/api" "$docs_src/mcp/blmcp/data/manual" "$here/.docs.tmp/"
  rm -rf "$here/.docs" && mv "$here/.docs.tmp" "$here/.docs"
  echo "✓ Doku-Daten in $here/.docs (Quelle $docs_src @ $rev)"
else
  echo "⚠ Doku-Quelle fehlt: $docs_src (git clone https://projects.blender.org/lab/blender_mcp.git; git checkout $docs_rev; BL_DOCS_SRC=…)"
fi
mkdir -p "$HOME/bin"
ln -sfn "$here/bin/bl" "$HOME/bin/bl"
echo "✓ Pillow + docutils in $here/.deps, Symlink $HOME/bin/bl -> $here/bin/bl"
