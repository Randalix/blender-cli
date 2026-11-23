# bl_bridge (vendored)

Source: official Blender MCP, `https://projects.blender.org/lab/blender_mcp.git`, commit `dbbf836`
(main, 2026-09-29, "Include GPL3+ license"), directory `addon/blender_mcp_addon/`. License GPL-3.0-or-later (`LICENSE`).

Taken **unchanged**: `mcp_to_blender_server.py` (TCP server, `\0`-terminated JSON, `execute`),
`capture_output.py`, `weak_sandbox.py`, `deferred_tool.py`, `execute_blocking.py`.
Own: `__init__.py` (empty, instead of the original add-on registration).

Not taken: add-on UI/registration, MCP server (`mcp/blmcp`), tool code, documentation data.
Update: copy the files from a new checkout, record the commit here, run `tests/selftest.sh`.
