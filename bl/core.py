"""bl — reine Hilfsfunktionen ohne Blender: Sitzung, Zustand, Projekte, Versionen, Ausgabe kürzen."""
import json
import os
import re
from pathlib import Path

SUBDIRS = ("blend", "vorschau", "export", "messung", "skripte")
VERSION_RE = re.compile(r"^v(\d{3,})_(.+)$")
_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def root() -> Path:
    return Path(os.environ.get("BL_ROOT", "/mnt/build/blender"))


def session_key(env=None) -> str:
    env = os.environ if env is None else env
    s = env.get("BL_SESSION") or (env.get("CODEMAN_SESSION_ID") or "")[:8] or "default"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)


def state_base() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "bl"


def state_dir() -> Path:
    p = state_base() / session_key()
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_state() -> dict:
    f = state_dir() / "state.json"
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    f = state_dir() / "state.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(f)


def clean_label(s: str, maxlen: int = 40) -> str:
    s = s.strip().translate(_UMLAUTE).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)[:maxlen].strip("-")
    return s or "ohne-label"


def versions(projdir: Path) -> list:
    """Versionsordner eines Projekts, aufsteigend nach Nummer."""
    if not projdir.is_dir():
        return []
    out = []
    for d in projdir.iterdir():
        m = VERSION_RE.match(d.name)
        if m and d.is_dir():
            out.append((int(m.group(1)), d))
    return [d for _n, d in sorted(out)]


def next_version_name(projdir: Path, label: str) -> str:
    vs = versions(projdir)
    n = int(VERSION_RE.match(vs[-1].name).group(1)) + 1 if vs else 1
    return "v{:03d}_{}".format(n, clean_label(label))


def next_numbered(d: Path, stem: str, ext: str) -> Path:
    """Nächster freier Name NNN_<stem><ext> in d (zählt über alle Dateien mit Nummernpräfix)."""
    n = 0
    if d.is_dir():
        for f in d.iterdir():
            m = re.match(r"^(\d{3,})_", f.name)
            if m:
                n = max(n, int(m.group(1)))
    return d / "{:03d}_{}{}".format(n + 1, clean_label(stem), ext)


def newest_blend(projdir: Path, start_at: Path = None):
    """Neueste .blend: erst in der Version start_at, dann rückwärts durch ältere Versionen."""
    vs = versions(projdir)
    if start_at is not None and start_at in vs:
        vs = vs[: vs.index(start_at) + 1]
    for v in reversed(vs):
        bl = sorted((v / "blend").glob("*.blend"), key=lambda f: f.stat().st_mtime)
        if bl:
            return bl[-1]
    return None


def clip_lines(lines, n: int) -> list:
    lines = list(lines)
    if len(lines) > n:
        return lines[:n] + ["… +{} weitere Zeilen".format(len(lines) - n)]
    return lines


def clip_text(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def error_line(tb: str, prefer_file: str = None) -> str:
    """Eine Zeile aus einem Traceback: <datei>:<zeile>: <Fehler>. Bevorzugt Stellen in prefer_file."""
    lines = [ln for ln in tb.strip().splitlines() if ln.strip()]
    msg = lines[-1].strip() if lines else "unbekannter Fehler"
    where = None
    for ln in lines:
        m = re.match(r'\s*File "([^"]+)", line (\d+)', ln)
        if m and (prefer_file is None or m.group(1) == prefer_file):
            where = "{}:{}".format(Path(m.group(1)).name, m.group(2))
    if where is None:
        for ln in lines:
            m = re.match(r'\s*File "([^"]+)", line (\d+)', ln)
            if m:
                where = "{}:{}".format(Path(m.group(1)).name, m.group(2))
    return "{}: {}".format(where, msg) if where else msg


def image_tokens(w: int, h: int) -> int:
    """Faustformel der Anthropic-Doku: Token ≈ Breite × Höhe / 750."""
    return round(w * h / 750)
