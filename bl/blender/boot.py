"""bl-Worker: läuft in `blender -b [datei] --factory-startup -P boot.py -- --port N ...`.

Startet die vendorte Bridge (vendor/bl_bridge) und bedient Anfragen blockierend, bis `bl close`
(bllib._request_quit) oder Leerlauf-Timeout. Danach beendet sich Blender, weil das Skript endet.
"""
import argparse
import os
import sys
import time

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser(prog="bl-worker")
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--idle", type=float, default=900.0)
ap.add_argument("--repo", required=True)
ap.add_argument("--empty", action="store_true", help="Default-Szene leeren (kein Würfel/Licht/Kamera)")
args = ap.parse_args(argv)

sys.path[:0] = [os.path.join(args.repo, "vendor"), os.path.join(args.repo, "bl", "blender")]

import bpy  # noqa: E402

if args.empty:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for d in list(coll):
            if d.users == 0:
                coll.remove(d)

import bllib  # noqa: E402
from bl_bridge import mcp_to_blender_server as srv  # noqa: E402

srv.start("127.0.0.1", args.port)
print("BL_READY port={} pid={} blend={}".format(args.port, os.getpid(), bpy.data.filepath or "-"), flush=True)
last = time.time()
reason = "close"
try:
    while srv.is_running() and not bllib._quit:
        if srv.poll_blocking(1.0):
            last = time.time()
        elif time.time() - last > args.idle:
            reason = "idle {:.0f}s".format(args.idle)
            break
finally:
    srv.stop()
print("BL_EXIT ({})".format(reason), flush=True)
