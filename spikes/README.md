# spikes

Wegwerf-Versuche, die eine Plan-Entscheidung belegen. Kein Produktionscode.

- `bridge_client_spike.py` (23.11.2026): Python-Client spricht ohne MCP-Protokoll mit der Add-on-Bridge des
  offiziellen Blender-MCP (Hintergrund-Worker `blender-gpu -b --online-mode --command blender_mcp --port 9890`,
  Extension aus `huffwork/blender-mcp-official/.blender_user`). Ergebnis: Worker bereit nach 0,61 s,
  `execute` 1–4 ms, Szene bleibt zwischen zwei Client-Prozessen offen. Aufruf:
  `BLENDER_MCP_PORT=9890 uv run --no-project --with 'mcp[cli]<2' --with pyyaml --with docutils python spikes/bridge_client_spike.py <official>/mcp`
  Wiki: Plans/Blender-Agent-Setup (bl) — Plan, Abschnitt 2a.
