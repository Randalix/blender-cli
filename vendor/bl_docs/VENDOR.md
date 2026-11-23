# bl_docs (vendored)

Source: official Blender MCP, `https://projects.blender.org/lab/blender_mcp.git`, commit `dbbf836`
(main, 2026-09-29), directory `mcp/blmcp/tools_helpers/`. License GPL-3.0-or-later (`LICENSE`).

Taken: `rst_doc_search.py` (full-text search, TF-IDF over paragraphs) and `rst_parse_docs.py` (RST paragraphs via docutils).
Two changes, each marked with `# bl:`:
- `rst_doc_search.py`: relative import instead of `blmcp.tools_helpers` (the `blmcp` package pulls in FastMCP and yaml).
- `rst_parse_docs.py`: `data_dir()` points to `$BL_DOCS_DIR` or `<repo>/.docs` instead of `blmcp/data`.

Data (`api/`, `manual/`, ≈ 30 MB RST) is not in the repo: `tools/install.sh` copies it from a checkout of the
same commit into `.docs/` (set `BL_DOCS_SRC`). Dependency: `docutils` (into `.deps/`).
Update: take files and data from a new checkout, record the commit here and in `tools/install.sh`, run `tests/selftest.sh`.
