"""bl — Blender by script for agents: open scene in a background worker, measure, look, version.

Exit codes: 0 ok · 1 finding · 2 script/usage error · 3 infrastructure (worker/Blender).
"""
import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

REPO = Path(os.environ.get("BL_REPO") or Path(__file__).resolve().parent.parent)
BLENDER_DIR = Path(os.environ.get("BL_BLENDER_DIR") or (os.path.dirname(shutil.which("blender") or "") or "."))
IDLE = float(os.environ.get("BL_IDLE", "900"))


class Fail(Exception):
    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


def out(*lines):
    for ln in lines:
        print(ln)


# --------------------------------------------------------------------------- project/version

def active(st=None, need=True):
    """(project dir, version dir) of the session. need=True: error if no project is active."""
    st = core.load_state() if st is None else st
    name = st.get("project") or st.get("projekt")  # "projekt": state written by older versions
    if not name:
        if need:
            raise Fail("no active project: run `bl project <name>` first")
        return None, None
    pdir = core.root() / name
    vs = core.versions(pdir)
    vdir = pdir / st["version"] if st.get("version") and (pdir / st["version"]).is_dir() else (vs[-1] if vs else None)
    if vdir is None and need:
        raise Fail("project {} has no version: `bl version \"<label>\"`".format(name))
    return pdir, vdir


def make_version(pdir, label):
    v = pdir / core.next_version_name(pdir, label)
    for s in core.SUBDIRS:
        (v / s).mkdir(parents=True, exist_ok=True)
    return v


def cmd_project(a):
    name = core.clean_label(a.name)
    pdir = core.root() / name
    new = not pdir.exists()
    if new:
        make_version(pdir, "start")
    st = core.load_state()
    if (st.get("project") or st.get("projekt")) != name:
        st["version"] = None
    st.pop("projekt", None)
    st["project"] = name
    core.save_state(st)
    _p, v = active(st)
    out("{} project {} ({})  active version {}".format("✓ new:" if new else "✓", name, pdir, v.name))
    w = worker_info()
    if w:
        out("  note: worker is still running with {} — `bl close` before switching scenes".format(w.get("blend") or "an unsaved scene"))


def cmd_version(a):
    pdir, cur = active()
    v = make_version(pdir, a.label)
    st = core.load_state()
    st["version"] = v.name
    core.save_state(st)
    msg = "✓ version {} (previous {})".format(v.name, cur.name if cur else "-")
    if worker_info():  # start state as its own file: `bl save` does not overwrite it, `--compare` finds it
        r = call("result = bllib.save({!r})".format(str(v / "blend" / (pdir.name + "_start.blend"))))
        msg += "  scene saved → {}".format(rel(r["path"]))
    out(msg)


def cmd_ls(a):
    st = core.load_state()
    pdir, vdir = active(st, need=False)
    if a.all or pdir is None:
        r = core.root()
        ps = sorted(p for p in r.iterdir() if p.is_dir()) if r.is_dir() else []
        out("projects under {} ({}):".format(r, len(ps)))
        out(*core.clip_lines(("  {}{}  {} versions".format("* " if pdir and p == pdir else "  ", p.name,
                                                               len(core.versions(p))) for p in ps), 40))
        return
    out("project {} ({})".format(pdir.name, pdir))
    for v in core.versions(pdir):
        cnt = {s: len(list((v / s).glob("*"))) for s in ("blend", "preview", "scripts", "export")}
        out("  {} {}  blend {} · images {} · scripts {} · export {}".format(
            "*" if v == vdir else " ", v.name, cnt["blend"], cnt["preview"], cnt["scripts"], cnt["export"]))


def rel(p):
    try:
        return str(Path(p).relative_to(core.root()))
    except ValueError:
        return str(p)


# --------------------------------------------------------------------------- worker

def _alive(pid):
    try:
        os.kill(pid, 0)
        cmd = Path("/proc/{}/cmdline".format(pid)).read_bytes()
        return b"boot.py" in cmd
    except (OSError, ValueError):
        return False


def worker_info(sd=None):
    f = (sd or core.state_dir()) / "worker.json"
    try:
        w = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    return w if _alive(w.get("pid", -1)) else None


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def blender_exe():
    return str(BLENDER_DIR / "blender")


def _autosave_hint(sd, implicit):
    """Idle backup of the last worker: abort on a silent start (bl run/save/…) so work does not continue on the
    old state; on bl open report it and move it aside with a timestamp."""
    f = sd / "autosave.blend"
    if not f.is_file():
        return
    if implicit:
        raise Fail("✗ The last worker ended while idle with unsaved changes, backed up to {}.\n"
                   "  Continue with it: `bl open {}` · load the old state and move the backup aside: `bl open`".format(f, f))
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(f.stat().st_mtime))
    dst, i = sd / "autosave_{}.blend".format(stamp), 1
    while dst.exists():
        i += 1
        dst = sd / "autosave_{}_{}.blend".format(stamp, i)
    f.rename(dst)
    out("⚠ The last worker ended while idle with unsaved changes; backup: {}  (`bl open {}`)".format(dst, dst))


def start_worker(blend=None, quiet=False, implicit=False):
    sd = core.state_dir()
    if not os.path.exists(blender_exe()):
        raise Fail("✗ Blender not found at {}: set BL_BLENDER_DIR or put 'blender' on PATH".format(blender_exe()), 3)
    if blend is not None and Path(blend).resolve() == (sd / "autosave.blend").resolve():
        # bl open <autosave>: move it aside first, then open the moved file
        _autosave_hint(sd, False)
        blend = sorted(sd.glob("autosave_*.blend"), key=lambda p: p.stat().st_mtime)[-1]
    else:
        _autosave_hint(sd, implicit)
    port = _free_port()
    log = sd / "worker.log"
    cmd = [blender_exe(), "-b"] + ([str(blend)] if blend else []) + [
        "--factory-startup", "--python-exit-code", "1", "-P", str(REPO / "bl" / "blender" / "boot.py"), "--",
        "--port", str(port), "--idle", str(IDLE), "--repo", str(REPO), "--autosave", str(sd / "autosave.blend")] + ([] if blend else ["--empty"])
    env = {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "DISPLAY", "PYTHONPATH", "PYTHONHOME")}
    t0 = time.time()
    with open(log, "w") as fh:
        p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                             start_new_session=True)
    deadline = t0 + float(os.environ.get("BL_START_TIMEOUT", "120"))
    while time.time() < deadline:
        if p.poll() is not None:
            tail = log.read_text(errors="replace").strip().splitlines()[-6:]
            raise Fail("worker exited during start (exit {}):\n  ".format(p.returncode) + "\n  ".join(tail) + "\n  log: " + str(log), 3)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        os.kill(p.pid, signal.SIGTERM)
        raise Fail("worker not reachable after timeout, log: {}".format(log), 3)
    w = {"pid": p.pid, "port": port, "blend": str(blend) if blend else None, "started": time.time(), "log": str(log)}
    (sd / "worker.json").write_text(json.dumps(w))
    if not quiet:
        out("✓ worker pid {} port {} ({:.1f} s) scene {}".format(p.pid, port, time.time() - t0, rel(blend) if blend else "empty"))
    return w


def ensure_worker():
    w = worker_info()
    if w:
        return w
    pdir, vdir = active(need=False)
    blend = core.newest_blend(pdir, vdir) if pdir else None
    w = start_worker(blend, quiet=True, implicit=True)
    out("(worker started: pid {} scene {})".format(w["pid"], rel(blend) if blend else "empty"))
    return w


def send(port, code, timeout):
    """Send code to the bridge (protocol as in blmcp/tools_helpers/connection.py, GPL-3.0+)."""
    req = (json.dumps({"type": "execute", "code": code, "strict_json": True}) + "\0").encode()
    buf = bytearray()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.sendall(req)
            while b"\0" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf.extend(chunk)
    except socket.timeout:
        raise Fail("timeout after {:.0f} s (the worker may still be computing; raise `--timeout` or `bl close`)".format(timeout), 3)
    except OSError as ex:
        raise Fail("worker not reachable ({}); `bl open`".format(ex), 3)
    if not buf:
        raise Fail("empty response from worker", 3)
    return json.loads(buf.partition(b"\0")[0].decode())


def call(code, timeout=600, prefer_file=None):
    """Run code in the worker, return result. Errors → Fail with one line + log."""
    w = ensure_worker()
    resp = send(w["port"], "import bllib\n" + code, timeout)
    if resp.get("status") != "ok":
        tb = resp.get("message", "")
        log = core.state_dir() / "last_error.txt"
        log.write_text(tb + ("\n--- stdout\n" + resp["stdout"] if resp.get("stdout") else ""))
        raise Fail("✗ {}\n  traceback: {}".format(core.error_line(tb, prefer_file), log), 2)
    r = resp.get("result", {})
    if resp.get("stdout"):
        r["_stdout"] = resp["stdout"]
    return r


def worker_changed(w):
    """True/False: unsaved script runs in the worker; None: unknown (still computing, old bllib, error)."""
    try:
        resp = send(w["port"], "import bllib\nresult = {'changed': bllib.changed()}", 10)
    except Fail:
        return None
    if resp.get("status") != "ok":
        return None
    v = (resp.get("result") or {}).get("changed")
    return v if isinstance(v, bool) else None


def cmd_open(a):
    # check the target first: a typo must not end the running worker
    if a.empty:
        blend = None
    elif a.blend:
        blend = Path(a.blend).resolve()
        if not blend.is_file():
            raise Fail("file missing: {}".format(blend))
    else:
        pdir, vdir = active(need=False)
        blend = core.newest_blend(pdir, vdir) if pdir else None
    w = worker_info()
    if w:
        changed = worker_changed(w)
        if changed is not False and not a.discard:
            why = "has unsaved changes" if changed else "does not answer clearly (still computing or old bllib), state unknown"
            raise Fail("✗ open scene {} (worker pid {}, scene {}): `bl save` first, or `bl open … --discard`".format(
                why, w["pid"], rel(w["blend"]) if w["blend"] else "empty"))
        cmd_close(argparse.Namespace(save=False, discard=True))
    start_worker(blend)


def cmd_close(a):
    w = worker_info()
    if not w:
        out("no active worker")
        return
    if a.save:
        cmd_save(argparse.Namespace(**{"as": None}))
    elif not getattr(a, "discard", False):
        changed = worker_changed(w)
        if changed is not False:
            raise Fail("✗ {} (worker pid {}): `bl close --save`, `bl save`, or `bl close --discard`".format(
                "unsaved changes" if changed else "state unknown (still computing or old bllib)", w["pid"]))
    try:
        send(w["port"], "import bllib\nbllib._request_quit()\nresult = {}", 10)
    except Fail:
        pass
    pending = core.state_dir() / "autosave.blend.pending"
    t_end = time.time() + 5
    while _alive(w["pid"]):
        if pending.exists():  # worker is writing its idle backup right now: do not kill it
            t_end = max(t_end, time.time() + 1)
            if time.time() - pending.stat().st_mtime > 600:
                break
        elif time.time() > t_end:
            break
        time.sleep(0.1)
    if _alive(w["pid"]):
        os.kill(w["pid"], signal.SIGTERM)
    (core.state_dir() / "worker.json").unlink(missing_ok=True)
    out("✓ worker stopped (pid {})".format(w["pid"]))


# --------------------------------------------------------------------------- run / info / look / save

def cmd_run(a):
    _pdir, vdir = active()
    sk = vdir / "scripts"
    sk.mkdir(parents=True, exist_ok=True)
    try:
        args = core.parse_set(a.set)
    except ValueError as ex:
        raise Fail("✗ " + str(ex))
    if a.name and len(a.scripts) > 1:
        out("  note: --name applies to a single script only; the chain uses the file names")
    if a.e is not None:
        jobs = [(a.e, a.name or "step")]
    else:
        jobs = []
        for sc in a.scripts:
            f = Path(sc)
            if not f.is_file():
                raise Fail("script missing: {}".format(f))
            jobs.append((f.read_text(encoding="utf-8"), a.name if (a.name and len(a.scripts) == 1) else f.stem))
    reported = []
    for i, (src, stem) in enumerate(jobs):
        j, new = core.journal_file(sk, stem, src, args)
        t0 = time.time()
        try:
            r = call("import json\nresult = bllib.run_file({!r}, json.loads({!r}))".format(str(j), json.dumps(args)),
                     timeout=a.timeout, prefer_file=str(j))
        except Fail as ex:
            core.journal_count(j, ok=False)
            if len(jobs) > 1:
                ex.args = (str(ex) + "\n  chain aborted at script {}/{}; not run: {}".format(
                    i + 1, len(jobs), ", ".join(st for _s, st in jobs[i + 1:]) or "-"),)
            raise
        res = r.get("result") or {}
        runs = core.journal_count(j, ok=True, result=res)
        out("✓ {}{} ({:.2f} s)".format(rel(j), "" if new else " (unchanged, run {})".format(runs), time.time() - t0))
        if r.get("_stdout"):
            out(*core.clip_lines(("  | " + ln for ln in r["_stdout"].rstrip().splitlines()), a.lines))
        if res:
            full = json.dumps(res, ensure_ascii=False)
            if a.json or len(full) <= 400:
                out("  result " + full)
            else:
                out("  result " + core.clip_text(full, 400), "  (full result: --json, or {})".format(
                    rel(j.with_name(j.stem + ".run.json"))))
        if a.report:
            reps = r.get("reports") or []
            out(*(["  " + ln for ln in core.clip_lines(reps, 20)] if reps else ["  (nothing marked: report(obj) in the script)"]))
        reported += [n for n in r.get("reported") or [] if n not in reported]
    if a.look:
        do_look(names=reported or None, views=["iso"], mode="solid", size=a.size, sheet=False)


def cmd_info(a):
    r = call("result = bllib.info({!r}, {})".format(a.obj, a.limit))
    if a.json:
        out(json.dumps(r, ensure_ascii=False))
    else:
        out(*r["lines"])


def compare_ref(arg, pdir, vdir):
    """Reference state: 'auto'/'start' = start state of the version, 'last' = last `bl save`, else a path."""
    if arg in ("auto", "start", "last"):
        start = vdir / "blend" / (pdir.name + "_start.blend")
        last = vdir / "blend" / (pdir.name + ".blend")
        if arg == "last":  # intermediate state last saved with `bl save`
            ref = last if last.is_file() else (start if start.is_file() else core.newest_blend(pdir, vdir))
        else:  # start state of the version (from `bl version`); `bl save` does not overwrite it
            ref = start if start.is_file() else core.newest_blend(pdir, vdir)
        if ref is None:
            raise Fail("no saved state to compare with: `bl version \"<label>\"` or `bl save` before the change")
        return ref
    ref = Path(arg).resolve()
    if not ref.is_file():
        raise Fail("comparison file missing: {}".format(ref))
    return ref


def do_look(names, views, mode, size, sheet, label="look", compare=None, focus=None, radius=None, section=None,
            engine=None, samples=None):
    pdir, vdir = active()
    prev = vdir / "preview"
    prev.mkdir(parents=True, exist_ok=True)
    stem = label if label != "look" else "_".join(["sheet"] if sheet else views) + ("_" + mode if mode != "solid" else "")
    ref = compare_ref(compare, pdir, vdir) if compare else None
    if focus and label == "look":
        stem += "_closeup"
    if section and label == "look":
        stem = "section-" + section.replace("=", "").replace(".", "_") + ("_" + mode if mode != "solid" else "")
    if ref:
        stem += "_compare" if label == "look" else ""
    path = core.next_numbered(prev, stem, ".png")
    panel = size // 2 if (sheet or ref) else size
    r = call("result = bllib.look({!r}, views={!r}, names={!r}, mode={!r}, panel={}, sheet={}, compare={!r}, focus={!r}, radius_mm={!r}, "
             "section={!r}, engine={!r}, samples={!r})".format(
                 str(path), list(views), names, mode, panel, sheet, str(ref) if ref else None, focus, radius, section, engine, samples))
    out("✓ image {}  {}×{} px (≈{} tokens)  1 px = {} mm".format(
        r["path"], r["w"], r["h"], core.image_tokens(r["w"], r["h"]), "/".join(str(x) for x in r.get("mm_per_px", [])) or "-"))
    if r.get("engine"):
        out("  engine {}".format(r["engine"]))
    if r.get("section_shift_mm"):
        out("  section plane moved {:.3g} mm off a vertex row (exactly on it the cut faces get lost)".format(r["section_shift_mm"]))
    for w in r.get("warnings") or []:
        out("  " + w)
    if r.get("exposure"):
        out("  " + r["exposure_line"])
    if r.get("empty"):
        out("  ⚠ EMPTY: nothing visible in {}. Closeup missed? --focus x,y,z is in mm.".format("/".join(r["empty"])))
    if r.get("ground"):
        out("  ground not framed/shown: {} (select it with --obj)".format(", ".join(r["ground"])))
    if ref:
        ch = r.get("changes") or []
        mx = max((c["pct"] for c in ch), default=0)
        out("  compared with {}: {}".format(rel(ref), ", ".join("{} {:.1f} %".format(c["view"], c["pct"]) for c in ch)))
        if mx < 1:
            out("  ⚠ barely visible change (< 1 % of the object area): does the change have any effect? Do not report it as a visible improvement.")
    return r


def cmd_light(a):
    r = call("result = bllib.light_studio({!r}, {!r}, {!r}, {!r})".format(a.obj or None, a.strength, a.keep_others, a.keep_world))
    out("✓ studio light for objects around ({}) mm, diagonal {} mm{}".format(
        ", ".join("{:g}".format(x) for x in r["center_mm"]), r["diag_mm"],
        ", aimed from camera " + r["camera"] if r["camera"] else ", no scene camera: fixed iso direction"))
    out(*("  " + ln for ln in r["lights"]))
    if r["off"]:
        out("  other lights off for rendering (hide_render): {}  (--keep-others keeps them)".format(", ".join(r["off"])))
    if r["world"]:
        out("  world {}: gray, strength 0.15{}".format(r["world"], "; yours ({}) stays in the file, --keep-world uses it".format(
            r["kept_world"]) if r.get("kept_world") else ""))
    out("  view transform {} · next: bl look --mode cam (prints exposure numbers)".format(r["view_transform"]))


def cmd_look(a):
    if a.sheet:
        views = ["iso", "front", "right", "top"]
    else:
        views = a.view or ["iso"]
    names = a.obj or None
    if a.section:
        try:
            core.parse_section(a.section)
        except ValueError as ex:
            raise Fail("✗ " + str(ex))
        if a.sheet or a.view or a.mode == "cam":
            raise Fail("✗ --section picks the view direction itself (perpendicular to the cut): no --sheet/--view/--mode cam")
    if (a.engine or a.samples) and a.mode != "cam":
        raise Fail("✗ --engine/--samples only with --mode cam")
    do_look(names, views, a.mode, a.size, (a.sheet or len(views) > 1) and not a.section, label=a.out or "look",
            compare=a.compare, focus=a.focus, radius=a.radius, section=a.section, engine=a.engine, samples=a.samples)


def cmd_save(a):
    pdir, vdir = active()
    name = core.clean_label(getattr(a, "as") or pdir.name) + ".blend"
    r = call("result = bllib.save({!r})".format(str(vdir / "blend" / name)))
    w = worker_info()
    if w:
        w["blend"] = r["path"]
        (core.state_dir() / "worker.json").write_text(json.dumps(w))
    out("✓ saved {} ({:.1f} MB)".format(rel(r["path"]), r["bytes"] / 1e6))


def _positive(typ):
    def f(v):
        x = typ(v)
        if x <= 0:
            raise argparse.ArgumentTypeError("must be > 0, not {}".format(v))
        return x
    return f


def cmd_qa(a):
    _pdir, vdir = active()
    qdir = Path(os.environ.get("BL_QA_DIR", str(Path.home() / "repos/blender-skills/skills/blender-asset-qa/scripts")))
    if not (qdir / "qa_check.py").is_file():
        raise Fail("✗ qa_check.py missing under {} (repo EL4CTEO/blender-skills, or set BL_QA_DIR)".format(qdir), 3)
    r = call("result = bllib.qa({!r}, {!r}, {!r}, {!r}, {!r}, qa_dir={!r})".format(
        a.obj or None, a.profile, a.budget, a.eps, a.tol, str(qdir)), timeout=a.timeout)
    mdir = vdir / "measurements"
    mdir.mkdir(parents=True, exist_ok=True)
    f = core.next_numbered(mdir, "qa-" + a.profile, ".json")
    f.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    head = "{} qa {} · profile {}{} · tris {}{} · {} errors, {} warnings".format(
        "✓" if r["pass"] else "✗", "passed" if r["pass"] else "failed", r["profile"],
        " · each object separately" if r.get("per_object") else " · as one asset", r["tris"],
        " / budget {}".format(r["budget"]) if r.get("budget") else "", len(r["errors"]), len(r["warnings"]))
    lines = [head]
    lines += ["  ERROR   " + e for e in core.clip_lines(r["errors"], a.lines)]
    lines += ["  warning " + w for w in core.clip_lines(r["warnings"], a.lines)]
    for n, o in list(r["objects"].items())[:20]:
        lines.append("  {}  tris {}  parts {}  {} mm".format(n, o["tris"], o.get("islands", "-"),
                                                          "×".join("{:g}".format(x) for x in o["dims_mm"])))
    if r.get("ground"):
        lines.append("  ground plane skipped: {} (check it with --obj)".format(", ".join(r["ground"])))
    lines.append("  report {}".format(rel(f)))
    if not r["pass"]:
        raise Fail("\n".join(lines), 1)
    out(*lines)


# --------------------------------------------------------------------------- docs / doctor

def cmd_docs(a):
    import docs
    if not docs.available():
        raise Fail("✗ documentation data missing under {} → bash tools/install.sh (with BL_DOCS_SRC)".format(docs.docs_dir()), 3)
    q = " ".join(a.terms).strip()
    width = 220
    if not a.manual and a.hit is None and len(a.terms) == 1:
        r = docs.lookup(q)
        if r:
            f, lines = r
            import textwrap
            out("{}  ({})".format(q, f.name))
            wrapped = [w for ln in lines for w in (textwrap.wrap(docs.clean(ln), width, subsequent_indent="    ",
                                                                 break_on_hyphens=False) or [""])]
            out(*core.clip_lines(wrapped, a.lines))  # wrap instead of truncating: signatures stay complete
            return
    scope = "manual" if a.manual else "api"
    r = docs.search(q, scope, a.n, a.hit)
    hits = r.get("hits") or []
    if not hits:
        raise Fail("✗ nothing found in {} for {!r} (all words must occur; fewer/other terms{})".format(
            scope, q, "" if a.manual else ", or --manual"), 1)
    per = a.lines if a.hit is not None else max(3, a.lines // len(hits))
    for h in hits:
        i = h["index"] if a.hit is None else a.hit
        out("[{}] {}{}".format(i, h["path"], " · " + h["breadcrumb"] if h.get("breadcrumb") else ""))
        body = [ln for ln in h["text"].splitlines() if ln.strip()]
        out(*("    " + ln for ln in core.clip_lines((core.clip_text(docs.clean(x), width) for x in body), per)))
    if a.hit is None:
        out("more on hit i: bl docs {}{} --hit i{}".format(q if " " not in q else repr(q), " --manual" if a.manual else "",
                                                       "  (truncated, more hits: -n)" if r.get("truncated") else ""))


def cmd_doctor(a):
    ok = True
    out("host {}  session {}  repo {} ({})".format(socket.gethostname(), core.session_key(), REPO, _git_rev()))
    exe = blender_exe()
    if os.path.exists(exe):
        v = subprocess.run([exe, "-b", "--factory-startup", "--version"], capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}).stdout.splitlines()
        out("Blender {}  ({})".format(v[0] if v else "?", exe))
    else:
        ok = False
        out("✗ Blender missing: {} (set BL_BLENDER_DIR or put 'blender' on PATH)".format(exe))
    try:
        g = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
                            "--format=csv,noheader"], capture_output=True, text=True, timeout=10).stdout.strip()
        out(*("GPU " + ln for ln in g.splitlines()))
    except (OSError, subprocess.TimeoutExpired):
        out("GPU: nvidia-smi not available")
    r = core.root()
    if r.is_dir():
        du = shutil.disk_usage(r)
        out("storage {}  free {:.0f} GB of {:.0f} GB".format(r, du.free / 1e9, du.total / 1e9))
    else:
        ok = False
        out("✗ storage missing: {} (create it or set BL_ROOT)".format(r))
    pil = list((REPO / ".deps").glob("PIL/__init__.py"))
    if not pil:
        ok = False
    out("PIL in worker: {}".format("ok ({})".format(REPO / ".deps") if pil else "✗ missing → bash tools/install.sh"))
    try:
        import docs
        dv = docs.available()
    except Exception:  # noqa: BLE001
        dv = {}
    if not dv:
        ok = False
    out("docs (bl docs): {}".format("ok (api {api}, manual {manual} files)".format(**{"api": 0, "manual": 0, **dv}) if dv
                                    else "✗ missing → bash tools/install.sh (with BL_DOCS_SRC)"))
    pdir, vdir = active(need=False)
    out("project {}  version {}".format(pdir.name if pdir else "-", vdir.name if vdir else "-"))
    ws = []
    base = core.state_base()
    for sd in sorted(base.iterdir()) if base.is_dir() else []:
        w = worker_info(sd)
        if w:
            ws.append("  {} pid {} port {} scene {} for {:.0f} min".format(
                sd.name, w["pid"], w["port"], rel(w["blend"]) if w["blend"] else "empty", (time.time() - w["started"]) / 60))
    out("workers: {}".format(len(ws)), *ws)
    sk = Path.home() / ".claude" / "skills"
    names = sorted(p.name for p in sk.iterdir() if p.name.startswith("blender")) if sk.is_dir() else []
    out("skills (~/.claude/skills): {}".format(", ".join(names) or "-"))
    if not ok:
        raise Fail("doctor: problems found", 3)


def _git_rev():
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return "?"


# --------------------------------------------------------------------------- main

def build_parser():
    ap = argparse.ArgumentParser(prog="bl", description="Blender by script (headless, no MCP). Exit: 0 ok, 1 finding, 2 error, 3 infrastructure.")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("project", help="select/create a project (under BL_ROOT)")
    p.add_argument("name")
    p.set_defaults(fn=cmd_project)
    p = sp.add_parser("version", help="new version vNNN_<label>; the open scene is saved into it")
    p.add_argument("label")
    p.set_defaults(fn=cmd_version)
    p = sp.add_parser("ls", help="versions of the project (or all projects with --all)")
    p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_ls)
    p = sp.add_parser("open", help="start the worker (default: newest .blend of the active version)")
    p.add_argument("blend", nargs="?")
    p.add_argument("--empty", action="store_true", help="empty scene instead of the newest file")
    p.add_argument("--discard", action="store_true", help="switch the running worker even with unsaved changes")
    p.set_defaults(fn=cmd_open)
    p = sp.add_parser("close", help="stop the worker")
    p.add_argument("--save", action="store_true", help="save first")
    p.add_argument("--discard", action="store_true", help="stop even with unsaved changes")
    p.set_defaults(fn=cmd_close)
    p = sp.add_parser("run", help="run script(s) in the open scene, one after another (journaled in scripts/)")
    p.add_argument("scripts", nargs="*", metavar="script.py")
    p.add_argument("--set", action="append", metavar="NAME=VALUE", help="script parameter as args[NAME] (value as JSON, else text)")
    p.add_argument("-e", metavar="CODE", help="code directly instead of a file")
    p.add_argument("--name", help="name in the script journal")
    p.add_argument("--report", action="store_true", help="measurements of the objects marked with report()")
    p.add_argument("--json", action="store_true", help="print the full result (it is always stored in the journal's .run.json)")
    p.add_argument("--look", action="store_true", help="afterwards an iso image of the marked (else all) objects")
    p.add_argument("--size", type=int, default=768)
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--lines", type=int, default=15, help="max. lines of print output")
    p.set_defaults(fn=cmd_run)
    p = sp.add_parser("info", help="compact scene summary; --obj NAME for details")
    p.add_argument("--obj")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_info)
    p = sp.add_parser("look", help="render an image (Workbench, ortho, framed) into preview/")
    p.add_argument("--view", action="append", choices=sorted(["iso", "front", "back", "right", "left", "top", "bottom"]))
    p.add_argument("--sheet", action="store_true", help="iso/front/right/top in one image")
    p.add_argument("--obj", action="append", help="only these objects (repeatable)")
    p.add_argument("--mode", default="solid", choices=["solid", "wire", "cam"])
    p.add_argument("--size", type=int, default=768, help="image width in px")
    p.add_argument("--out", help="name in the image journal")
    p.add_argument("--compare", nargs="?", const="auto", metavar="BLEND",
                   help="before/now side by side with the same camera; no value or 'start': start state of the version, "
                        "'last': state last saved with bl save, else a path")
    p.add_argument("--focus", metavar="OBJ|x,y,z", help="closeup around an object or a point x,y,z in mm")
    p.add_argument("--radius", type=float, metavar="MM", help="radius of the closeup in mm")
    p.add_argument("--section", metavar="x|y|z=MM", help="cut at the plane (mm), view perpendicular to it; cut faces red")
    p.add_argument("--engine", choices=["eevee", "cycles", "workbench"], help="--mode cam only: engine for this image")
    p.add_argument("--samples", type=int, help="--mode cam only: samples (EEVEE/Cycles) for this image")
    p.set_defaults(fn=cmd_look)
    p = sp.add_parser("light", help="lighting rig scaled to the objects (studio: key/fill/rim area lights)")
    p.add_argument("rig", choices=["studio"])
    p.add_argument("--obj", action="append", help="light these objects (default: visible geometry without ground)")
    p.add_argument("--strength", type=_positive(float), default=1.0, help="multiply all light powers (default 1)")
    p.add_argument("--keep-others", action="store_true", help="leave other lights on")
    p.add_argument("--keep-world", action="store_true", help="leave the world as it is")
    p.set_defaults(fn=cmd_light)

    p = sp.add_parser("qa", help="check with numbers (EL4CTEO asset-qa + broken faces + poly budget); exit 1 on errors")
    p.add_argument("--obj", action="append", help="these objects together as one asset (default: each visible mesh separately, without ground plane)")
    p.add_argument("--profile", default="game", choices=["game", "render", "print", "roblox"],
                   help="game: UV/scale/normals strict · render: lenient · print: watertight")
    p.add_argument("--budget", type=_positive(int), metavar="TRIS", help="poly budget (total tris)")
    p.add_argument("--eps", type=_positive(float), metavar="M", help="z-fighting distance in m (default 0.001)")
    p.add_argument("--tol", type=_positive(float), metavar="M", help="contact tolerance for floating parts in m (default 0.002)")
    p.add_argument("--lines", type=int, default=15)
    p.add_argument("--timeout", type=float, default=600)
    p.set_defaults(fn=cmd_qa)
    p = sp.add_parser("save", help="save the scene into blend/ of the active version")
    p.add_argument("--as", help="file name (without .blend)")
    p.set_defaults(fn=cmd_save)
    p = sp.add_parser("docs", help="Blender API/manual offline: exact name (bpy.types.Object.matrix_world, "
                                   "bmesh.ops.bevel) or search terms; no worker needed")
    p.add_argument("terms", nargs="+")
    p.add_argument("--manual", action="store_true", help="search the manual instead of the API")
    p.add_argument("-n", type=int, default=5, help="number of search hits (default 5)")
    p.add_argument("--hit", type=int, metavar="I", help="search hit I with more context")
    p.add_argument("--lines", type=int, default=30, help="print at most this many lines (default 30)")
    p.set_defaults(fn=cmd_docs)
    p = sp.add_parser("doctor", help="check the environment")
    p.set_defaults(fn=cmd_doctor)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "run" and bool(a.scripts) == (a.e is not None):
        print("✗ bl run: <script.py …> or -e CODE (not both)", file=sys.stderr)
        return 2
    try:
        a.fn(a)
    except Fail as ex:
        print(str(ex), file=sys.stderr)
        return ex.code
    except ValueError as ex:
        if "BL_ROOT" not in str(ex):
            raise
        print("✗ " + str(ex), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
