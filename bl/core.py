"""bl — pure helpers without Blender: session, state, projects, versions, output clipping."""
import json
import os
import re
from pathlib import Path

SUBDIRS = ("blend", "preview", "export", "measurements", "scripts")
VERSION_RE = re.compile(r"^v(\d{3,})_(.+)$")
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})


DEFAULT_ROOT = "~/blender-projects"


def root() -> Path:
    p = Path(os.path.expanduser(os.environ.get("BL_ROOT") or DEFAULT_ROOT))
    if not p.is_absolute():
        raise ValueError("BL_ROOT must be an absolute path, got {!r}".format(str(p)))
    return p


def session_key(env=None) -> str:
    """BL_SESSION, else the first 8 characters of the session id of a multi-agent host (CODEMAN_SESSION_ID), else 'default'."""
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
    s = s.strip().translate(_UMLAUTS).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)[:maxlen].strip("-")
    return s or "no-label"


def versions(projdir: Path) -> list:
    """Version folders of a project, ascending by number."""
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
    """Next free name NNN_<stem><ext> in d (counts over all files with a number prefix)."""
    n = 0
    if d.is_dir():
        for f in d.iterdir():
            m = re.match(r"^(\d{3,})_", f.name)
            if m:
                n = max(n, int(m.group(1)))
    return d / "{:03d}_{}{}".format(n + 1, clean_label(stem), ext)


def _run_meta(j: Path):
    """Read NNN_<stem>.run.json: {"args", "runs" (successful), "failed"}; missing/broken → None."""
    try:
        m = json.loads(j.with_name(j.stem + ".run.json").read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else None
    except (OSError, ValueError):
        return None


def journal_file(d: Path, stem: str, src: str, args: dict = None):
    """Write a script into journal d, next to it NNN_<stem>.run.json with the --set values and run counters.
    If the globally last journal file is identical (name, content, values), it is reused (no identical
    copies); journal_count counts the run only after execution. → (path, newly_written)"""
    src = src if src.endswith("\n") else src + "\n"
    args = args or {}
    key = json.dumps(args, sort_keys=True)  # 1 and true differ here
    st = clean_label(stem)
    if d.is_dir():
        nums = [(int(m.group(1)), f) for f in d.iterdir() for m in [re.match(r"^(\d{3,})_(.*)\.py$", f.name)] if m]
        if nums:
            n, last = max(nums, key=lambda t: t[0])
            meta = _run_meta(last)  # missing/broken → do not reuse
            if (last.name == "{:03d}_{}.py".format(n, st) and meta is not None
                    and json.dumps(meta.get("args", {}), sort_keys=True) == key
                    and last.read_text(encoding="utf-8") == src):
                return last, False
    j = next_numbered(d, stem, ".py")
    j.write_text(src, encoding="utf-8")
    j.with_name(j.stem + ".run.json").write_text(
        json.dumps({"args": args, "runs": 0, "failed": 0}, ensure_ascii=False), encoding="utf-8")
    return j, True


def journal_count(j: Path, ok: bool = True) -> int:
    """Count a run after execution: runs = successful, failed = failed. → runs"""
    meta = _run_meta(j) or {"args": {}, "runs": 0, "failed": 0}
    key = "runs" if ok else "failed"
    meta[key] = int(meta.get(key, 0)) + 1
    j.with_name(j.stem + ".run.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return int(meta.get("runs", 0))


def parse_set(items) -> dict:
    """--set k=v (repeatable) → dict. Values as JSON, else text: n=3 → 3, f=0.5 → 0.5, l=[1,2] → list, s=abc → 'abc'."""
    out = {}
    for it in items or []:
        k, sep, v = it.partition("=")
        if not sep or not k.strip().isidentifier():
            raise ValueError("--set needs name=value, not {!r}".format(it))
        try:
            val = json.loads(v)
        except ValueError:
            val = v
        try:
            json.dumps(val, allow_nan=False)
        except ValueError:
            raise ValueError("--set {}: NaN/Infinity is not a valid value".format(k))
        out[k.strip()] = val
    return out


def parse_section(s: str):
    """'x=0' / 'y=-12.5' / 'z=40' (mm) → ('x', 0.0)."""
    ax, sep, v = (s or "").replace(" ", "").partition("=")
    try:
        if not sep or ax not in ("x", "y", "z"):
            raise ValueError
        return ax, float(v)
    except ValueError:
        raise ValueError("--section needs x=MM, y=MM or z=MM, not {!r}".format(s))


def newest_blend(projdir: Path, start_at: Path = None):
    """Newest .blend: first in version start_at, then backwards through older versions."""
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
        return lines[:n] + ["… +{} more lines".format(len(lines) - n)]
    return lines


def clip_text(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def error_line(tb: str, prefer_file: str = None) -> str:
    """One line from a traceback: <file>:<line>: <error>. Prefers locations in prefer_file."""
    lines = [ln for ln in tb.strip().splitlines() if ln.strip()]
    msg = lines[-1].strip() if lines else "unknown error"
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
    """Rule of thumb from the Anthropic docs: tokens ≈ width × height / 750."""
    return round(w * h / 750)
