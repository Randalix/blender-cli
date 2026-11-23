# bl_docs (vendort)

Quelle: offizieller Blender-MCP, `https://projects.blender.org/lab/blender_mcp.git`, Commit `dbbf836`
(main, 2026-09-29), Verzeichnis `mcp/blmcp/tools_helpers/`. Lizenz GPL-3.0-or-later (`LICENSE`).

Übernommen: `rst_doc_search.py` (Volltextsuche, TF-IDF über Absätze) und `rst_parse_docs.py` (RST-Absätze mit docutils).
Zwei Änderungen, je mit `# bl:` markiert:
- `rst_doc_search.py`: relativer Import statt `blmcp.tools_helpers` (das Paket `blmcp` zieht FastMCP und yaml mit).
- `rst_parse_docs.py`: `data_dir()` zeigt auf `$BL_DOCS_DIR` bzw. `<repo>/.docs` statt auf `blmcp/data`.

Daten (`api/`, `manual/`, ≈ 30 MB RST) liegen nicht im Repo: `tools/install.sh` kopiert sie aus dem Checkout
desselben Commits nach `.docs/`. Abhängigkeit: `docutils` (nach `.deps/`).
Update: Dateien und Daten aus einem neuen Checkout übernehmen, Commit hier und in `tools/install.sh` eintragen, `tests/selftest.sh` laufen lassen.
