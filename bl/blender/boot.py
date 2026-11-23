"""bl worker: runs in `blender -b [file] --factory-startup -P boot.py -- --port N ...`.

Starts the vendored bridge (vendor/bl_bridge) and serves requests blocking until `bl close`
(bllib._request_quit) or the idle timeout. Blender then exits because the script ends.
With --gui (`bl gui`, Blender with a window) a bpy.app.timers callback polls the bridge instead, as the official
add-on does, so the interface stays usable; no idle timeout, `bl close` quits Blender.
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
ap.add_argument("--gui", action="store_true", help="Blender runs with a window: poll from a timer, do not block")
args = ap.parse_args(argv)

sys.path[:0] = [os.path.join(args.repo, "vendor"), os.path.join(args.repo, "bl", "blender"), os.path.join(args.repo, ".deps")]

import bpy  # noqa: E402

if args.empty and args.gui:
    bpy.ops.wm.read_homefile(use_empty=True)  # empty scene that is not marked as changed (GUI counts is_dirty)
elif args.empty:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for d in list(coll):
            if d.users == 0:
                coll.remove(d)

import bllib  # noqa: E402
from bl_bridge import mcp_to_blender_server as srv  # noqa: E402

srv.start("127.0.0.1", args.port)
if args.gui:
    import traceback

    bllib._gui = True
    bpy.context.preferences.view.smooth_view = 0  # bl shot --frame: no animation before the screenshot
    srv.timer_internal_vars_calc()

    def _quit_now():
        srv.stop()
        print("BL_EXIT (close)", flush=True)
        bpy.ops.wm.quit_blender()
        return None

    def _tick():
        try:
            did = srv.poll()
        except Exception:  # noqa: BLE001  the timer must survive, as in the official add-on
            print("bl: error in the bridge timer:\n" + traceback.format_exc(), flush=True)
            did = True
        if bllib._quit:  # the reply to `bl close` is written in this poll; quit on the next tick
            if not srv.poll():
                bpy.app.timers.register(_quit_now, first_interval=0.1)
                return None
            return 0.05
        if not srv.is_running():
            return None
        if did:
            srv.timer_idle_reset()
        return srv.timer_idle_interval()

    bpy.app.timers.register(_tick, first_interval=0.01, persistent=True)
    print("BL_READY port={} pid={} blend={} gui".format(args.port, os.getpid(), bpy.data.filepath or "-"), flush=True)
if not args.gui:
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
