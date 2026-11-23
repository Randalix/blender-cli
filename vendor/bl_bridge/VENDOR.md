# bl_bridge (vendort)

Quelle: offizieller Blender-MCP, `https://projects.blender.org/lab/blender_mcp.git`, Commit `dbbf836`
(main, 2026-09-29, "Include GPL3+ license"), Verzeichnis `addon/blender_mcp_addon/`. Lizenz GPL-3.0-or-later (`LICENSE`).

Übernommen, **unverändert**: `mcp_to_blender_server.py` (TCP-Server, `\0`-terminiertes JSON, `execute`),
`capture_output.py`, `weak_sandbox.py`, `deferred_tool.py`, `execute_blocking.py`.
Eigen: `__init__.py` (leer, statt der Add-on-Registrierung des Originals).

Nicht übernommen: Add-on-UI/Registrierung, MCP-Server (`mcp/blmcp`), Tool-Code, Doku-Daten.
Update: Dateien aus einem neuen Checkout kopieren, Commit hier eintragen, `tests/selftest.sh` laufen lassen.
