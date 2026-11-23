"""bl docs — look up the Blender Python API and manual offline, without a Blender worker.

Data: RST copy from the official Blender MCP (commit dbbf836, matches Blender 5.2: of 1746 RNA classes 3 internal ones
are missing), copied by tools/install.sh to <repo>/.docs/{api,manual}. Full-text search: vendor/bl_docs (GPL-3.0+).
Exact names (bpy.types.Object.matrix_world, bmesh.ops.bevel) are read directly from the RST file by this module."""
import os
import re
import sys
from pathlib import Path

REPO = Path(os.environ.get("BL_REPO") or Path(__file__).resolve().parent.parent)
DIRECTIVE = re.compile(r"^(\s*)\.\. (class|attribute|data|method|function|classmethod|staticmethod|property)::\s*(.+?)\s*$")
ROLE = re.compile(r":[\w:]+:`~?([^`]+)`")
SYMBOL = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+$")


def docs_dir() -> Path:
    return Path(os.environ.get("BL_DOCS_DIR") or REPO / ".docs")


def available() -> dict:
    """Number of RST files per scope; empty if the data is missing."""
    d = docs_dir()
    return {s: sum(1 for _ in (d / s).rglob("*.rst")) for s in ("api", "manual") if (d / s).is_dir()}


def clean(line: str) -> str:
    """Strip RST roles and literal markup: :class:`Material` → Material, ``'OBJECT'`` → 'OBJECT'."""
    return ROLE.sub(r"\1", line).replace("``", "")


def _name(sig: str) -> str:
    return re.split(r"[(\s]", sig, maxsplit=1)[0]


def member_block(text: str, name: str):
    """Block of directive `name` (attribute, method, function, class) from RST text, dedented.
    For a class only the header and description plus the names of its members. → list of lines or None."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = DIRECTIVE.match(ln)
        if not m or _name(m.group(3)) != name:
            continue
        ind = len(m.group(1))
        body = []
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= ind:
                break
            body.append(nxt)
        if m.group(2) == "class":
            head, members = [], []
            for b in body:
                mm = DIRECTIVE.match(b)
                if mm:
                    members.append(_name(mm.group(3)))
                elif not members:
                    head.append(b)
            out = [ln.strip()] + _dedent(head)
            if members:
                out += ["", "members ({}): {}".format(len(members), ", ".join(members))]
            return _trim(out)
        return _trim([ln.strip()] + _dedent(body))
    return None


def _dedent(body):
    ws = [len(b) - len(b.lstrip()) for b in body if b.strip()]
    cut = min(ws) if ws else 0
    return [b[cut:] if b.strip() else "" for b in body]


def _trim(lines):
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _bases(text: str):
    m = re.search(r"^base classes --- (.+)$", text, re.M)
    return [n.split(".")[-1] for n in ROLE.findall(m.group(1))] if m else []


def lookup(symbol: str, api=None):
    """Exact name → (file, lines) or None. Members are also looked up in base classes
    (bpy.types.Mesh.name is documented on ID). Without a module prefix bpy.types. is tried (Object.matrix_world)."""
    api = Path(api or docs_dir() / "api")
    if not SYMBOL.match(symbol) and "." not in symbol:
        if (api / "bpy.types.{}.rst".format(symbol)).is_file():
            symbol = "bpy.types." + symbol
        else:
            return None
    for sym in (symbol, "bpy.types." + symbol):
        parts = sym.split(".")
        for k in range(len(parts), 0, -1):
            f = api / (".".join(parts[:k]) + ".rst")
            if not f.is_file():
                continue
            rest = parts[k:]
            text = f.read_text(encoding="utf-8", errors="replace")
            if not rest:  # whole file: class or module
                cls = member_block(text, parts[-1])
                if cls:
                    return f, cls
                names = [_name(m.group(3)) for m in map(DIRECTIVE.match, text.splitlines()) if m]
                title = next((ln for ln in text.splitlines() if ln.strip()), sym)
                return f, [title, "", "entries ({}): {}".format(len(names), ", ".join(names))]
            if len(rest) != 1:
                break
            seen, todo = set(), [(f, text)]
            while todo:  # member, falling back to base classes
                ff, tt = todo.pop(0)
                blk = member_block(tt, rest[0])
                if blk:
                    return ff, blk
                for b in _bases(tt):
                    bf = api / "bpy.types.{}.rst".format(b)
                    if b not in seen and bf.is_file():
                        seen.add(b)
                        todo.append((bf, bf.read_text(encoding="utf-8", errors="replace")))
            break
    return None


def search(query: str, scope: str = "api", n: int = 5, hit=None) -> dict:
    """Full-text search (vendor/bl_docs, TF-IDF over paragraphs). hit=i: hit i with more context."""
    for p in (REPO / ".deps", REPO / "vendor"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    os.environ.setdefault("BL_DOCS_DIR", str(docs_dir()))
    from bl_docs import rst_doc_search  # noqa: E402  (needs docutils from .deps)
    return rst_doc_search.search(query=query, scope=scope, max_results=n, context=0, index=hit)
