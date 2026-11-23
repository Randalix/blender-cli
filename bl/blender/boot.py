"""bl worker: runs in `blender -b [file] --factory-startup -P boot.py -- --port N ...`.

Starts the vendored bridge (vendor/bl_bridge) and serves requests blocking until `bl close`
(bllib._request_quit) or the idle timeout. Blender then exits because the script ends.
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
ap.add_argument("--empty", action="store_true", help="clear the default scene (no cube/light/camera)")
ap.add_argument("--autosave", help="on idle exit with unsaved script runs, back up to this file")
args = ap.parse_args(argv)

sys.path[:0] = [os.path.join(args.repo, "vendor"), os.path.join(args.repo, "bl", "blender"), os.path.join(args.repo, ".deps")]

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
if reason.startswith("idle") and args.autosave and bllib.changed():
    pending = args.autosave + ".pending"  # bl close waits while this file exists (no SIGTERM in the middle of saving)
    try:  # do not silently drop unsaved work; bl reports the file on the next start
        open(pending, "w").close()
        bpy.ops.wm.save_as_mainfile(filepath=args.autosave, copy=True, check_existing=False)
        print("BL_AUTOSAVE {}".format(args.autosave), flush=True)
    except Exception as ex:  # noqa: BLE001
        print("BL_AUTOSAVE failed: {}".format(ex), flush=True)
    finally:
        if os.path.exists(pending):
            os.remove(pending)
print("BL_EXIT ({})".format(reason), flush=True)
