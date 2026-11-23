"""bl — Blender per Skript für Agenten: offene Szene im Hintergrund-Worker, messen, ansehen, versionieren.

Exit-Codes: 0 ok · 1 Befund · 2 Skript-/Aufruffehler · 3 Infrastruktur (Worker/Blender).
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
BLENDER_DIR = Path(os.environ.get("BL_BLENDER_DIR", "/mnt/caches/ComfyUI/_tools/blender-5.2.4-linux-x64"))
IDLE = float(os.environ.get("BL_IDLE", "900"))


class Fail(Exception):
    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


def out(*lines):
    for ln in lines:
        print(ln)


# --------------------------------------------------------------------------- Projekt/Version

def active(st=None, need=True):
    """(projektordner, versionsordner) der Sitzung. need=True: Fehler, wenn kein Projekt aktiv."""
    st = core.load_state() if st is None else st
    name = st.get("projekt")
    if not name:
        if need:
            raise Fail("kein Projekt aktiv: zuerst `bl projekt <name>`")
        return None, None
    pdir = core.root() / name
    vs = core.versions(pdir)
    vdir = pdir / st["version"] if st.get("version") and (pdir / st["version"]).is_dir() else (vs[-1] if vs else None)
    if vdir is None and need:
        raise Fail("Projekt {} hat keine Version: `bl version \"<Label>\"`".format(name))
    return pdir, vdir


def make_version(pdir, label):
    v = pdir / core.next_version_name(pdir, label)
    for s in core.SUBDIRS:
        (v / s).mkdir(parents=True, exist_ok=True)
    return v


def cmd_projekt(a):
    name = core.clean_label(a.name)
    pdir = core.root() / name
    new = not pdir.exists()
    if new:
        make_version(pdir, "start")
    st = core.load_state()
    if st.get("projekt") != name:
        st["version"] = None
    st["projekt"] = name
    core.save_state(st)
    _p, v = active(st)
    out("{} Projekt {} ({})  aktive Version {}".format("✓ neu:" if new else "✓", name, pdir, v.name))
    w = worker_info()
    if w:
        out("  Hinweis: Worker läuft noch mit {} — `bl close` vor dem Wechsel der Szene".format(w.get("blend") or "ungespeicherter Szene"))


def cmd_version(a):
    pdir, cur = active()
    v = make_version(pdir, a.label)
    st = core.load_state()
    st["version"] = v.name
    core.save_state(st)
    msg = "✓ Version {} (vorher {})".format(v.name, cur.name if cur else "-")
    if worker_info():
        r = call("result = bllib.save({!r})".format(str(v / "blend" / (pdir.name + ".blend"))))
        msg += "  Szene gespeichert → {}".format(rel(r["path"]))
    out(msg)


def cmd_ls(a):
    st = core.load_state()
    pdir, vdir = active(st, need=False)
    if a.all or pdir is None:
        r = core.root()
        ps = sorted(p for p in r.iterdir() if p.is_dir()) if r.is_dir() else []
        out("Projekte unter {} ({}):".format(r, len(ps)))
        out(*core.clip_lines(("  {}{}  {} Versionen".format("* " if pdir and p == pdir else "  ", p.name,
                                                               len(core.versions(p))) for p in ps), 40))
        return
    out("Projekt {} ({})".format(pdir.name, pdir))
    for v in core.versions(pdir):
        cnt = {s: len(list((v / s).glob("*"))) for s in ("blend", "vorschau", "skripte", "export")}
        out("  {} {}  blend {} · bilder {} · skripte {} · export {}".format(
            "*" if v == vdir else " ", v.name, cnt["blend"], cnt["vorschau"], cnt["skripte"], cnt["export"]))


def rel(p):
    try:
        return str(Path(p).relative_to(core.root()))
    except ValueError:
        return str(p)


# --------------------------------------------------------------------------- Worker

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


def start_worker(blend=None, quiet=False):
    sd = core.state_dir()
    port = _free_port()
    log = sd / "worker.log"
    cmd = [blender_exe(), "-b"] + ([str(blend)] if blend else []) + [
        "--factory-startup", "--python-exit-code", "1", "-P", str(REPO / "bl" / "blender" / "boot.py"), "--",
        "--port", str(port), "--idle", str(IDLE), "--repo", str(REPO)] + ([] if blend else ["--empty"])
    env = {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "DISPLAY", "PYTHONPATH", "PYTHONHOME")}
    t0 = time.time()
    with open(log, "w") as fh:
        p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                             start_new_session=True)
    deadline = t0 + float(os.environ.get("BL_START_TIMEOUT", "120"))
    while time.time() < deadline:
        if p.poll() is not None:
            tail = log.read_text(errors="replace").strip().splitlines()[-6:]
            raise Fail("Worker beendet beim Start (Exit {}):\n  ".format(p.returncode) + "\n  ".join(tail) + "\n  Log: " + str(log), 3)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        os.kill(p.pid, signal.SIGTERM)
        raise Fail("Worker nicht erreichbar nach Timeout, Log: {}".format(log), 3)
    w = {"pid": p.pid, "port": port, "blend": str(blend) if blend else None, "started": time.time(), "log": str(log)}
    (sd / "worker.json").write_text(json.dumps(w))
    if not quiet:
        out("✓ Worker pid {} port {} ({:.1f} s) Szene {}".format(p.pid, port, time.time() - t0, rel(blend) if blend else "leer"))
    return w


def ensure_worker():
    w = worker_info()
    if w:
        return w
    pdir, vdir = active(need=False)
    blend = core.newest_blend(pdir, vdir) if pdir else None
    w = start_worker(blend, quiet=True)
    out("(Worker gestartet: pid {} Szene {})".format(w["pid"], rel(blend) if blend else "leer"))
    return w


def send(port, code, timeout):
    """Code an die Bridge senden (Protokoll wie blmcp/tools_helpers/connection.py, GPL-3.0+)."""
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
        raise Fail("Zeitüberschreitung nach {:.0f} s (Worker rechnet evtl. noch; `--timeout` erhöhen oder `bl close`)".format(timeout), 3)
    except OSError as ex:
        raise Fail("Worker nicht erreichbar ({}); `bl open`".format(ex), 3)
    if not buf:
        raise Fail("leere Antwort vom Worker", 3)
    return json.loads(buf.partition(b"\0")[0].decode())


def call(code, timeout=600, prefer_file=None):
    """Führt Code im Worker aus, gibt result zurück. Fehler → Fail mit einer Zeile + Log."""
    w = ensure_worker()
    resp = send(w["port"], "import bllib\n" + code, timeout)
    if resp.get("status") != "ok":
        tb = resp.get("message", "")
        log = core.state_dir() / "last_error.txt"
        log.write_text(tb + ("\n--- stdout\n" + resp["stdout"] if resp.get("stdout") else ""))
        raise Fail("✗ {}\n  Traceback: {}".format(core.error_line(tb, prefer_file), log), 2)
    r = resp.get("result", {})
    if resp.get("stdout"):
        r["_stdout"] = resp["stdout"]
    return r


def cmd_open(a):
    w = worker_info()
    if w:
        out("Worker läuft schon: pid {} port {} Szene {} — `bl close` zuerst".format(w["pid"], w["port"], rel(w["blend"]) if w["blend"] else "leer"))
        return
    if a.leer:
        blend = None
    elif a.blend:
        blend = Path(a.blend).resolve()
        if not blend.is_file():
            raise Fail("Datei fehlt: {}".format(blend))
    else:
        pdir, vdir = active(need=False)
        blend = core.newest_blend(pdir, vdir) if pdir else None
    start_worker(blend)


def cmd_close(a):
    w = worker_info()
    if not w:
        out("kein Worker aktiv")
        return
    if a.save:
        cmd_save(argparse.Namespace(**{"as": None}))
    try:
        send(w["port"], "import bllib\nbllib._request_quit()\nresult = {}", 10)
    except Fail:
        pass
    for _ in range(50):
        if not _alive(w["pid"]):
            break
        time.sleep(0.1)
    else:
        os.kill(w["pid"], signal.SIGTERM)
    (core.state_dir() / "worker.json").unlink(missing_ok=True)
    out("✓ Worker beendet (pid {})".format(w["pid"]))


# --------------------------------------------------------------------------- run / info / look / save

def cmd_run(a):
    _pdir, vdir = active()
    sk = vdir / "skripte"
    sk.mkdir(parents=True, exist_ok=True)
    if a.e is not None:
        src, stem = a.e, a.name or "schritt"
    else:
        f = Path(a.script)
        if not f.is_file():
            raise Fail("Skript fehlt: {}".format(f))
        src, stem = f.read_text(encoding="utf-8"), a.name or f.stem
    j = core.next_numbered(sk, stem, ".py")
    j.write_text(src if src.endswith("\n") else src + "\n", encoding="utf-8")
    t0 = time.time()
    r = call("result = bllib.run_file({!r})".format(str(j)), timeout=a.timeout, prefer_file=str(j))
    out("✓ {} ({:.2f} s)".format(rel(j), time.time() - t0))
    if r.get("_stdout"):
        out(*core.clip_lines(("  | " + ln for ln in r["_stdout"].rstrip().splitlines()), a.lines))
    res = r.get("result") or {}
    if res:
        out("  result " + core.clip_text(json.dumps(res, ensure_ascii=False), 400))
    if a.report:
        reps = r.get("reports") or []
        out(*(["  " + ln for ln in core.clip_lines(reps, 20)] if reps else ["  (nichts markiert: report(obj) im Skript)"]))
    if a.look:
        do_look(names=r.get("reported") or None, views=["iso"], mode="solid", size=a.size, sheet=False)


def cmd_info(a):
    r = call("result = bllib.info({!r}, {})".format(a.obj, a.limit))
    if a.json:
        out(json.dumps(r, ensure_ascii=False))
    else:
        out(*r["lines"])


def compare_ref(arg, pdir, vdir):
    """Vergleichsstand: 'auto' = zuletzt gespeicherte .blend (aktive Version, sonst ältere), sonst Pfad."""
    if arg == "auto":
        ref = core.newest_blend(pdir, vdir)
        if ref is None:
            raise Fail("kein gespeicherter Stand zum Vergleichen: vor der Änderung `bl version \"<label>\"` oder `bl save`")
        return ref
    ref = Path(arg).resolve()
    if not ref.is_file():
        raise Fail("Vergleichsdatei fehlt: {}".format(ref))
    return ref


def do_look(names, views, mode, size, sheet, label="look", compare=None):
    pdir, vdir = active()
    vor = vdir / "vorschau"
    vor.mkdir(parents=True, exist_ok=True)
    stem = label if label != "look" else "_".join(["sheet"] if sheet else views) + ("_" + mode if mode != "solid" else "")
    ref = compare_ref(compare, pdir, vdir) if compare else None
    if ref:
        stem += "_vergleich" if label == "look" else ""
    path = core.next_numbered(vor, stem, ".png")
    panel = size // 2 if (sheet or ref) else size
    r = call("result = bllib.look({!r}, views={!r}, names={!r}, mode={!r}, panel={}, sheet={}, compare={!r})".format(
        str(path), list(views), names, mode, panel, sheet, str(ref) if ref else None))
    out("✓ Bild {}  {}×{} px (≈{} Token)  1 px = {} mm".format(
        r["path"], r["w"], r["h"], core.image_tokens(r["w"], r["h"]), "/".join(str(x) for x in r.get("mm_per_px", [])) or "-"))
    if ref:
        ch = r.get("changes") or []
        mx = max((c["pct"] for c in ch), default=0)
        out("  Vergleich mit {}: {}".format(rel(ref), ", ".join("{} {:.1f} %".format(c["view"], c["pct"]) for c in ch)))
        if mx < 1:
            out("  ⚠ kaum sichtbare Änderung (< 1 % der Objektfläche): wirkt die Änderung überhaupt? Nicht als sichtbare Verbesserung melden.")
    return r


def cmd_look(a):
    if a.sheet:
        views = ["iso", "front", "right", "top"]
    else:
        views = a.view or ["iso"]
    names = a.obj or None
    do_look(names, views, a.mode, a.size, a.sheet or len(views) > 1, label=a.out or "look", compare=a.compare)


def cmd_save(a):
    pdir, vdir = active()
    name = core.clean_label(getattr(a, "as") or pdir.name) + ".blend"
    r = call("result = bllib.save({!r})".format(str(vdir / "blend" / name)))
    w = worker_info()
    if w:
        w["blend"] = r["path"]
        (core.state_dir() / "worker.json").write_text(json.dumps(w))
    out("✓ gespeichert {} ({:.1f} MB)".format(rel(r["path"]), r["bytes"] / 1e6))


# --------------------------------------------------------------------------- doctor

def cmd_doctor(a):
    ok = True
    out("Host {}  Sitzung {}  Repo {} ({})".format(socket.gethostname(), core.session_key(), REPO, _git_rev()))
    exe = blender_exe()
    if os.path.exists(exe):
        v = subprocess.run([exe, "-b", "--factory-startup", "--version"], capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}).stdout.splitlines()
        out("Blender {}  ({})".format(v[0] if v else "?", exe))
    else:
        ok = False
        out("✗ Blender fehlt: {}".format(exe))
    try:
        g = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
                            "--format=csv,noheader"], capture_output=True, text=True, timeout=10).stdout.strip()
        out(*("GPU " + ln for ln in g.splitlines()))
    except (OSError, subprocess.TimeoutExpired):
        out("GPU: nvidia-smi nicht verfügbar")
    r = core.root()
    if r.is_dir():
        du = shutil.disk_usage(r)
        out("Ablage {}  frei {:.0f} GB von {:.0f} GB".format(r, du.free / 1e9, du.total / 1e9))
    else:
        ok = False
        out("✗ Ablage fehlt: {}".format(r))
    pil = list((REPO / ".deps").glob("PIL/__init__.py"))
    if not pil:
        ok = False
    out("PIL im Worker: {}".format("ok ({})".format(REPO / ".deps") if pil else "✗ fehlt → bash tools/install.sh"))
    pdir, vdir = active(need=False)
    out("Projekt {}  Version {}".format(pdir.name if pdir else "-", vdir.name if vdir else "-"))
    ws = []
    base = core.state_base()
    for sd in sorted(base.iterdir()) if base.is_dir() else []:
        w = worker_info(sd)
        if w:
            ws.append("  {} pid {} port {} Szene {} seit {:.0f} min".format(
                sd.name, w["pid"], w["port"], rel(w["blend"]) if w["blend"] else "leer", (time.time() - w["started"]) / 60))
    out("Worker: {}".format(len(ws)), *ws)
    sk = Path.home() / ".claude" / "skills"
    names = sorted(p.name for p in sk.iterdir() if p.name.startswith("blender")) if sk.is_dir() else []
    out("Skills (~/.claude/skills): {}".format(", ".join(names) or "-"))
    if not ok:
        raise Fail("doctor: Probleme gefunden", 3)


def _git_rev():
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return "?"


# --------------------------------------------------------------------------- main

def build_parser():
    ap = argparse.ArgumentParser(prog="bl", description="Blender per Skript (headless, ohne MCP). Exit: 0 ok, 1 Befund, 2 Fehler, 3 Infrastruktur.")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("projekt", help="Projekt wählen/anlegen (unter BL_ROOT)")
    p.add_argument("name")
    p.set_defaults(fn=cmd_projekt)
    p = sp.add_parser("version", help="neue Version vNNN_<label>; offene Szene wird hineingespeichert")
    p.add_argument("label")
    p.set_defaults(fn=cmd_version)
    p = sp.add_parser("ls", help="Versionen des Projekts (oder alle Projekte mit --all)")
    p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_ls)
    p = sp.add_parser("open", help="Worker starten (Standard: neueste .blend der aktiven Version)")
    p.add_argument("blend", nargs="?")
    p.add_argument("--leer", action="store_true", help="leere Szene statt neuester Datei")
    p.set_defaults(fn=cmd_open)
    p = sp.add_parser("close", help="Worker beenden")
    p.add_argument("--save", action="store_true", help="vorher speichern")
    p.set_defaults(fn=cmd_close)
    p = sp.add_parser("run", help="Skript in der offenen Szene ausführen (wird nach skripte/ protokolliert)")
    p.add_argument("script", nargs="?")
    p.add_argument("-e", metavar="CODE", help="Code direkt statt Datei")
    p.add_argument("--name", help="Name im Skript-Protokoll")
    p.add_argument("--report", action="store_true", help="Messwerte der mit report() markierten Objekte")
    p.add_argument("--look", action="store_true", help="danach iso-Bild der markierten (sonst aller) Objekte")
    p.add_argument("--size", type=int, default=768)
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--lines", type=int, default=15, help="max. Zeilen print-Ausgabe")
    p.set_defaults(fn=cmd_run)
    p = sp.add_parser("info", help="kompakte Szenenauskunft; --obj NAME für Details")
    p.add_argument("--obj")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_info)
    p = sp.add_parser("look", help="Bild rendern (Workbench, ortho, gerahmt) nach vorschau/")
    p.add_argument("--view", action="append", choices=sorted(["iso", "front", "back", "right", "left", "top", "bottom"]))
    p.add_argument("--sheet", action="store_true", help="iso/front/right/top in einem Bild")
    p.add_argument("--obj", action="append", help="nur diese Objekte (mehrfach)")
    p.add_argument("--mode", default="solid", choices=["solid", "wire", "cam"])
    p.add_argument("--size", type=int, default=768, help="Bildbreite in px")
    p.add_argument("--out", help="Name im Bild-Protokoll")
    p.add_argument("--compare", nargs="?", const="auto", metavar="BLEND",
                   help="vorher/jetzt nebeneinander mit gleicher Kamera; ohne Wert: zuletzt gespeicherter Stand")
    p.set_defaults(fn=cmd_look)
    p = sp.add_parser("save", help="Szene in blend/ der aktiven Version speichern")
    p.add_argument("--as", help="Dateiname (ohne .blend)")
    p.set_defaults(fn=cmd_save)
    p = sp.add_parser("doctor", help="Umgebung prüfen")
    p.set_defaults(fn=cmd_doctor)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "run" and (a.script is None) == (a.e is None):
        print("✗ bl run: genau eins von <skript.py> oder -e CODE", file=sys.stderr)
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
