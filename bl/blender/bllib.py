"""bllib — läuft im bl-Worker (Blender). Skripte haben ohne Import: bpy, bl (dieses Modul), report, obj, mesh_stats, Vector.

Wichtig für Skript-Autoren:
- result = {...} setzen, um Werte (JSON) zurückzugeben; print() kommt gekürzt zurück.
- report(obj_oder_name, ...) markiert Objekte für `bl run --report` und `--look`.
- args: Dict aus `bl run --set name=wert` (leer ohne --set); args.get("n", 3) für Vorgaben.
- bl.hits(von_mm, richtung): Trefferpunkte (mm) eines Strahls durch die sichtbaren Netze.
"""
import json
import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Matrix, Vector

_quit = False
_reports = []
_cam_device = None  # Gerät des letzten Cycles-Renders (Legende)
_changed = False  # seit Start/letztem save ein Skript gelaufen? (bl open schaltet sonst ohne Rückfrage um)
GEOM_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME"}
FONT_PATHS = ("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def _request_quit():
    global _quit
    _quit = True


def changed():
    return _changed


# --------------------------------------------------------------------------- Skript-API

def obj(name):
    o = bpy.data.objects.get(name)
    if o is None:
        names = sorted(bpy.data.objects.keys())
        raise KeyError("Objekt {!r} fehlt; vorhanden: {}".format(name, ", ".join(names[:20]) + (" …" if len(names) > 20 else "")))
    return o


def report(*objs):
    for o in objs:
        name = o if isinstance(o, str) else o.name
        if name not in _reports:
            _reports.append(name)


def mesh_stats(o, manifold=True):
    """Zahlen des ausgewerteten Netzes (nach Modifiern): v/e/f/tris, Maße, offene/nicht-mannigfaltige Kanten.
    Fehler (kaputte Flächen): splitter (Ecke < 1°), winzig (Fläche ~0), gefaltet (Nachbarflächen > 170° geknickt).
    ngons ist nur Info: N-Gons sind nicht automatisch ein Problem."""
    dg = bpy.context.evaluated_depsgraph_get()
    oe = o.evaluated_get(dg)
    st = {"dims": [round(x, 4) for x in o.dimensions]}
    if o.type != "MESH" and not hasattr(oe, "to_mesh"):
        return st
    me = oe.to_mesh()
    try:
        st.update(v=len(me.vertices), e=len(me.edges), f=len(me.polygons),
                  tris=sum(len(p.vertices) - 2 for p in me.polygons))
        if manifold and len(me.vertices) <= 2_000_000:
            bm = bmesh.new()
            bm.from_mesh(me)
            st["nonmanifold"] = sum(1 for e in bm.edges if not e.is_manifold)
            st["loose_v"] = sum(1 for v in bm.verts if not v.link_edges)
            st["ngons"] = sum(1 for f in bm.faces if len(f.verts) > 4)
            diag = Vector(o.dimensions).length or 1.0
            tiny_a = (diag * 1e-5) ** 2
            st["winzig"] = sum(1 for f in bm.faces if f.calc_area() < tiny_a)
            st["splitter"] = sum(1 for f in bm.faces if f.calc_area() >= tiny_a and
                                 min(l.calc_angle() for l in f.loops) < math.radians(1.0))
            st["gefaltet"] = sum(1 for e in bm.edges if len(e.link_faces) == 2 and
                                 e.calc_face_angle(0.0) > math.radians(170))
            bm.free()
    finally:
        oe.to_mesh_clear()
    return st


def _fmt_dims(d):
    return "×".join("{:.3g}".format(x) for x in d) + " m"


def summary(o):
    parts = [o.name, o.type]
    if o.type in GEOM_TYPES:
        st = mesh_stats(o)
        if "f" in st:
            parts.append("v {} f {}".format(st["v"], st["f"]))
        parts.append(_fmt_dims(o.dimensions))
        if st.get("nonmanifold"):
            parts.append("offen/nm-Kanten {}".format(st["nonmanifold"]))
        bad = ["{} {}".format(k, st[k]) for k in ("splitter", "winzig", "gefaltet") if st.get(k)]
        if bad:
            parts.append("FEHLER " + ", ".join(bad))
    mats = [s.material.name for s in getattr(o, "material_slots", []) if s.material]
    if mats:
        parts.append("mat " + ",".join(mats[:4]) + ("…" if len(mats) > 4 else ""))
    if o.modifiers:
        parts.append("mod " + ",".join(m.type.lower() for m in o.modifiers))
    if o.parent:
        parts.append("parent " + o.parent.name)
    return "  ".join(parts)


def _jsonable(x):
    return json.loads(json.dumps(x, default=repr))


def run_file(path, args=None):
    """Führt ein Skript in der offenen Szene aus. Fehler fliegen durch (Traceback mit Datei und Zeile).
    args: Parameter aus `bl run --set` (im Skript als Dict `args`)."""
    global _changed
    _reports.clear()
    _changed = True
    g = {"__name__": "__bl_run__", "__file__": path, "bpy": bpy, "bl": sys.modules[__name__],
         "report": report, "obj": obj, "mesh_stats": mesh_stats, "Vector": Vector, "Matrix": Matrix,
         "math": math, "result": {}, "args": dict(args or {})}
    with open(path, encoding="utf-8") as fh:
        code = compile(fh.read(), path, "exec")
    t0 = time.time()
    exec(code, g)
    res = g.get("result")
    if not isinstance(res, dict):
        res = {"result": res}
    return {"result": _jsonable(res), "reports": [summary(bpy.data.objects[n]) for n in _reports if n in bpy.data.objects],
            "reported": list(_reports), "seconds": round(time.time() - t0, 3)}


def hits(origin_mm, direction, names=None, max_m=100.0):
    """Alle Treffer eines Strahls durch die ausgewerteten Netze (Welt), sortiert nach Abstand.
    origin_mm: (x, y, z) in mm, direction: Vektor (wird normiert), names: nur diese Objekte (sonst alle sichtbaren Meshes).
    → [[x, y, z], …] in mm, auf 0,01 mm gerundet."""
    from mathutils.bvhtree import BVHTree
    su = bpy.context.scene.unit_settings.scale_length or 1.0
    dg = bpy.context.evaluated_depsgraph_get()
    objs = [obj(n) for n in names] if names else [o for o in bpy.context.scene.objects
                                                   if o.type == "MESH" and o.visible_get()]
    bm = bmesh.new()
    for o in objs:
        tmp = bmesh.new()
        tmp.from_object(o, dg)
        tmp.transform(o.matrix_world)
        me = bpy.data.meshes.new("_bl_hits")
        tmp.to_mesh(me)
        tmp.free()
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    o = Vector(origin_mm) / 1000.0 / su
    d = Vector(direction).normalized()
    out = []
    for _ in range(10000):
        loc, _n, _i, _dist = tree.ray_cast(o, d, max_m / su)
        if loc is None:
            break
        out.append([round(x * su * 1000.0, 2) for x in loc])
        # Schritt hinter den Treffer: mind. 0,01 mm, bei großen Koordinaten relativ (float32 im BVH)
        eps = max(1e-5 / su, max(abs(x) for x in loc) * 1e-6)
        nxt = loc + d * eps
        if (nxt - loc).length < eps / 2:
            break
        o = nxt
    return out


# --------------------------------------------------------------------------- info

def info(name=None, limit=40):
    scene = bpy.context.scene
    if name:
        return {"lines": _info_obj(obj(name))}
    us = scene.unit_settings
    by_type = {}
    for o in scene.objects:
        by_type[o.type] = by_type.get(o.type, 0) + 1
    faces = 0
    for o in scene.objects:
        if o.type == "MESH":
            faces += mesh_stats(o, manifold=False).get("f", 0)
    missing = [i.name for i in bpy.data.images if i.source == "FILE" and i.filepath and not os.path.exists(bpy.path.abspath(i.filepath))]
    lines = ["Datei {}  Szene {}  Einheit {} (scale {})  Engine {}  Frame {}".format(
        bpy.data.filepath or "(ungespeichert)", scene.name, us.length_unit, us.scale_length, scene.render.engine, scene.frame_current),
        "Objekte {} ({})  Faces gesamt {}  Materialien {}  Bilder {}{}".format(
            len(scene.objects), ", ".join("{} {}".format(k.lower(), v) for k, v in sorted(by_type.items())), faces,
            len(bpy.data.materials), len(bpy.data.images), "  FEHLENDE Bilder: " + ", ".join(missing[:5]) if missing else "")]
    objs = sorted(scene.objects, key=lambda o: (o.type not in GEOM_TYPES, o.name))
    body = [summary(o) for o in objs[:limit]]
    if len(objs) > limit:
        body.append("… +{} weitere Objekte (bl info --obj NAME für Details)".format(len(objs) - limit))
    return {"lines": lines + body}


def _mod_desc(m):
    keys = {"BEVEL": ("width", "segments", "limit_method"), "SUBSURF": ("levels", "render_levels"),
            "ARRAY": ("count", "relative_offset_displace"), "MIRROR": ("use_axis",), "SOLIDIFY": ("thickness",),
            "BOOLEAN": ("operation", "object", "solver"), "WEIGHTED_NORMAL": ("weight",), "DECIMATE": ("ratio",),
            "WIREFRAME": ("thickness",), "REMESH": ("mode", "voxel_size")}.get(m.type, ())
    vals = []
    for k in keys:
        v = getattr(m, k, None)
        if hasattr(v, "name"):
            v = v.name
        elif hasattr(v, "__len__") and not isinstance(v, str):
            v = tuple(round(x, 4) if isinstance(x, float) else x for x in v)
        elif isinstance(v, float):
            v = round(v, 4)
        vals.append("{}={}".format(k, v))
    return "{} ({}){}{}".format(m.name, m.type.lower(), " " + " ".join(vals) if vals else "", "" if m.show_viewport else " [aus]")


def _info_obj(o):
    L = ["{}  {}  Collections {}".format(o.name, o.type, ", ".join(c.name for c in o.users_collection)),
         "loc {}  rot° {}  scale {}".format(tuple(round(x, 4) for x in o.location),
                                            tuple(round(math.degrees(x), 2) for x in o.rotation_euler),
                                            tuple(round(x, 4) for x in o.scale)),
         "Maße {}".format(_fmt_dims(o.dimensions))]
    if o.parent:
        L.append("parent {}".format(o.parent.name))
    if o.type in GEOM_TYPES:
        st = mesh_stats(o)
        L.append("ausgewertet: " + "  ".join(("{} {} (Info)" if k == "ngons" else "{} {}").format(k.replace("ngons", "N-Gons"), v) for k, v in st.items() if k != "dims" and not (k in ("splitter", "winzig", "gefaltet") and not v)))
        bad = ["{} {}".format(k, st[k]) for k in ("splitter", "winzig", "gefaltet") if st.get(k)]
        if bad:
            L.append("FEHLER kaputte Flächen: " + ", ".join(bad) + " (Wireframe/Shading können hier Artefakte zeigen)")
    for m in o.modifiers:
        L.append("mod " + _mod_desc(m))
    for s in getattr(o, "material_slots", []):
        mat = s.material
        if mat:
            n = len(mat.node_tree.nodes) if mat.use_nodes and mat.node_tree else 0
            L.append("mat {} ({} Nodes)".format(mat.name, n))
    d = o.data
    if o.type == "MESH":
        L.append("UV {}  Vertex-Gruppen {}  Shape-Keys {}".format(
            ",".join(u.name for u in d.uv_layers) or "-", len(o.vertex_groups),
            len(d.shape_keys.key_blocks) if d.shape_keys else 0))
    return L


# --------------------------------------------------------------------------- look

VIEW_DIRS = {"iso": (1.0, -1.0, 0.8), "front": (0, -1, 0), "back": (0, 1, 0), "right": (1, 0, 0),
             "left": (-1, 0, 0), "top": (0, 0, 1), "bottom": (0, 0, -1)}


def bbox_world(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in objs:
        oe = o.evaluated_get(dg)
        pts += [oe.matrix_world @ Vector(c) for c in oe.bound_box]
    if not pts:
        return Vector((-1, -1, -1)), Vector((1, 1, 1))
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx


def _font(size):
    from PIL import ImageFont
    for f in FONT_PATHS:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def _hide_others(scene, keep):
    keep_p = {o.as_pointer() for o in keep}
    hidden = []
    for o in scene.objects:
        if o.type in GEOM_TYPES and o.as_pointer() not in keep_p and not o.hide_render:
            o.hide_render = True
            hidden.append(o)
    return hidden


def _split_ground(objs):
    """Große flache Platten (Boden/Hintergrund) aus der Rahmung nehmen: flach (< 1 % Dicke) und > 4× so groß wie der Rest."""
    if len(objs) < 2:
        return objs, []
    flat = [o for o in objs if max(o.dimensions) > 0 and min(o.dimensions) < 0.01 * max(o.dimensions)]
    rest = [o for o in objs if o not in flat]
    if not rest or not flat:
        return objs, []
    mn, mx = bbox_world(rest)
    size = max((mx - mn).length, 1e-6)
    ground = [o for o in flat if Vector(o.dimensions).length > 4 * size]
    return [o for o in objs if o not in ground], ground


def _append_ref(path, names, tmpdir, env=False):
    """Lädt die Geometrie-Objekte eines gespeicherten Stands temporär in die Szene. → (objekte, neue IDs zum Entfernen, umgebung).
    env=True (Kamera-Vergleich): umgebung = {"lights": sichtbare Lichter des Stands (nicht verlinkt), "world": dessen Welt}."""
    import shutil
    colls = [c for c in dir(bpy.data) if c not in ("window_managers", "screens", "workspaces", "libraries")
             and isinstance(getattr(bpy.data, c, None), bpy.types.bpy_prop_collection)]
    tmp = os.path.join(tmpdir, "_bl_ref_{}.blend".format(os.getpid()))
    shutil.copyfile(path, tmp)  # Kopie: aus der gerade offenen Datei kann Blender nicht anhängen
    before = {c: {i.as_pointer() for i in getattr(bpy.data, c)} for c in colls}
    try:
        with bpy.data.libraries.load(tmp, link=False) as (src, dst):
            srcnames = list(src.objects)
            dst.objects = list(srcnames)  # eigene Liste: Blender ersetzt deren Einträge beim Laden durch Objekte
            if env:  # Szene mitladen: deren Welt und Lichter gehören zum alten Stand
                cur = bpy.context.scene.name
                want = cur if cur in src.scenes else (src.scenes[0] if src.scenes else None)
                dst.scenes = [want] if want else []
    finally:
        os.remove(tmp)
    scene = bpy.context.scene
    ref = []
    for n, o in zip(srcnames, dst.objects):
        if o is None or o.type not in GEOM_TYPES:
            continue
        if (names and n not in names) or (not names and o.hide_render):
            continue
        scene.collection.objects.link(o)
        ref.append(o)
    new = [i for c in colls for i in getattr(bpy.data, c) if i.as_pointer() not in before[c]]
    umg = None
    if env:
        rs = next((x for x in getattr(dst, "scenes", []) if x), None)
        lights = []
        if rs is not None:
            lights = [o for o in rs.objects if o.type == "LIGHT" and not o.hide_render]
        umg = {"world": rs.world if rs else None, "lights": lights}
    return ref, new, umg


SECTION_VIEW = {"x": "left", "y": "front", "z": "top"}  # Blick von der weggeschnittenen Seite


def _section_copies(scene, objs, section, mn, mx, temps, ids):
    """Schnittkopien: jedes Mesh mit Exact-Boolean gegen einen Quader auf der Kameraseite der Ebene.
    x=V / y=V: entfernt x<V / y<V (Blick von -x / -y); z=V: entfernt z>V (Blick von oben).
    Neue Objekte landen sofort in temps, Mesh/Material in ids (Aufräumen auch bei Teilfehlern). → kopien"""
    ax, v_mm = section
    su = scene.unit_settings.scale_length or 1.0
    v = v_mm / 1000.0 / su
    i = "xyz".index(ax)
    c = (mn + mx) / 2
    diag = max((mx - mn).length, 1e-3)
    size = 2 * (diag + abs(v - c[i])) + diag  # deckt die Szene auch, wenn die Ebene weit außerhalb liegt
    center = Vector(c)
    center[i] = v + size / 2 if ax == "z" else v - size / 2
    me = bpy.data.meshes.new("_bl_schnitt")
    ids.append(me)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(me)
    bm.free()
    mat = bpy.data.materials.new("_bl_schnitt")
    ids.append(mat)
    mat.diffuse_color = (0.85, 0.12, 0.1, 1)
    me.materials.append(mat)
    cutter = bpy.data.objects.new("_bl_schnitt", me)
    temps.append(cutter)
    scene.collection.objects.link(cutter)
    cutter.location = center
    cutter.hide_render = True
    cutter.display_type = "WIRE"
    copies = []
    for o in objs:
        if o.type != "MESH":
            continue
        k = o.copy()
        temps.append(k)
        k.name = "_bl_cut_" + o.name
        scene.collection.objects.link(k)
        m = k.modifiers.new("_bl_cut", "BOOLEAN")
        m.operation, m.solver, m.object = "DIFFERENCE", "EXACT", cutter
        if hasattr(m, "material_mode"):
            m.material_mode = "TRANSFER"  # Schnittfläche bekommt das rote Material des Quaders
        copies.append(k)
    return copies


def _section_check(objs):
    if not any(o.type == "MESH" for o in objs):
        raise ValueError("--section schneidet nur Meshes; gewählt: {}".format(", ".join(o.name for o in objs) or "-"))


def _render_views(out, objs, frame, views, mode, panel, tag, focus=None, section=None):
    """Workbench-Renders der Objekte objs (alles andere ausgeblendet), Kamera gerahmt auf frame. → [(view, RGBA, mm/px)]
    section=('x'|'y'|'z', mm): Schnittansicht, Blick senkrecht auf die Ebene."""
    from PIL import Image
    scene = bpy.context.scene
    mn, mx = bbox_world(frame)
    center = (mn + mx) / 2
    radius = max((mx - mn).length / 2, 1e-4)
    if focus:  # Ausschnitt: Kamera außerhalb der ganzen Szene, Bildausschnitt nur um den Punkt
        fc, fr = focus
        radius = radius + (fc - center).length
        center = fc
    r, sh = scene.render, scene.display.shading
    saved = {"engine": r.engine, "rx": r.resolution_x, "ry": r.resolution_y, "pct": r.resolution_percentage,
             "film": r.film_transparent, "fp": r.filepath, "cam": scene.camera, "fmt": r.image_settings.file_format,
             "cmode": r.image_settings.color_mode,
             "light": sh.light, "ctype": sh.color_type, "cav": sh.show_cavity, "outl": sh.show_object_outline}
    temps, colors, cut_ids, hidden, res = [], {}, [], [], []
    if section:
        _section_check(objs)
    try:  # alles Temporäre ab hier wird im finally entfernt, auch bei Fehlern
        cam_data = bpy.data.cameras.new("_bl_look_cam")
        cam = bpy.data.objects.new("_bl_look_cam", cam_data)
        scene.collection.objects.link(cam)
        temps.append(cam)
        if section:
            objs = _section_copies(scene, objs, section, mn, mx, temps, cut_ids)
            views = [SECTION_VIEW[section[0]]]
        hidden += _hide_others(scene, objs)
        r.engine = "BLENDER_WORKBENCH"
        r.resolution_x = r.resolution_y = panel
        r.resolution_percentage = 100
        r.film_transparent = True
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGBA"
        sh.light = "STUDIO"
        sh.show_cavity = True
        sh.show_object_outline = True
        if section:
            sh.color_type = "MATERIAL"
        if mode == "wire":
            sh.color_type = "OBJECT"
            for o in objs:
                if o.type != "MESH":
                    continue
                colors[o.as_pointer()] = (o, tuple(o.color))
                o.color = (0.78, 0.78, 0.78, 1)
                w = o.copy()
                w.name = "_bl_wire_" + o.name
                scene.collection.objects.link(w)
                mod = w.modifiers.new("_bl_wire", "WIREFRAME")
                mod.thickness = radius * 0.004
                mod.use_replace = True
                mod.use_even_offset = False  # True schießt an Splitterflächen meterlange Strahlen (23.11. nachgestellt)
                w.color = (0.08, 0.08, 0.1, 1)
                temps.append(w)
        cam_data.type = "ORTHO"
        scene.camera = cam
        for v in views:
            d = Vector(VIEW_DIRS[v]).normalized()
            dist = radius * 4
            cam.location = center + d * dist
            if v == "top":  # senkrecht: to_track_quat ist dort mehrdeutig (Bild war um 180° gedreht)
                cam.rotation_euler = (0.0, 0.0, 0.0)  # Blick -Z, oben = +Y, rechts = +X
            elif v == "bottom":
                cam.rotation_euler = (math.pi, 0.0, 0.0)  # Blick +Z, oben = -Y, rechts = +X
            else:
                cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
            bpy.context.view_layer.update()
            inv = cam.matrix_world.inverted()
            dg = bpy.context.evaluated_depsgraph_get()
            ext = 0.0
            for o in frame:
                oe = o.evaluated_get(dg)
                for c in oe.bound_box:
                    p = inv @ (oe.matrix_world @ Vector(c))
                    ext = max(ext, abs(p.x), abs(p.y))
            cam_data.ortho_scale = max((focus[1] if focus else ext) * 2 * 1.1, 1e-4)
            cam_data.clip_start = max(radius * 0.01, 1e-5)
            cam_data.clip_end = dist + radius * 4
            p = "{}.{}.{}.tmp.png".format(out, v, tag)
            r.filepath = p
            bpy.ops.render.render(write_still=True)
            im = Image.open(p).convert("RGBA")
            im.load()
            os.remove(p)
            res.append((v, im, cam_data.ortho_scale * scene.unit_settings.scale_length * 1000 / panel))
    finally:
        for o, c in colors.values():  # vor dem Löschen: Schnittkopien sind auch in colors
            o.color = c
        for o in temps:
            data = o.data if o.type == "CAMERA" else None
            bpy.data.objects.remove(o, do_unlink=True)
            if data is not None:
                bpy.data.cameras.remove(data)
        for i in cut_ids:
            (bpy.data.meshes if isinstance(i, bpy.types.Mesh) else bpy.data.materials).remove(i)
        for o in hidden:
            o.hide_render = False
        r.engine, r.resolution_x, r.resolution_y = saved["engine"], saved["rx"], saved["ry"]
        r.resolution_percentage, r.film_transparent, r.filepath = saved["pct"], saved["film"], saved["fp"]
        r.image_settings.file_format, r.image_settings.color_mode = saved["fmt"], saved["cmode"]
        scene.camera = saved["cam"]
        sh.light, sh.color_type, sh.show_cavity, sh.show_object_outline = saved["light"], saved["ctype"], saved["cav"], saved["outl"]
    return res


def _set_engine(r, name):
    """r.engine auf 'eevee'|'cycles'|'workbench' setzen. Die Enum-Liste meldet zu wenig (nur EEVEE), daher per Zuweisung probieren."""
    cands = {"eevee": ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"), "cycles": ("CYCLES",),
             "workbench": ("BLENDER_WORKBENCH",)}[name]
    if name == "cycles" and "cycles" not in bpy.context.preferences.addons:  # --factory-startup lädt Cycles evtl. nicht
        import addon_utils
        addon_utils.enable("cycles", default_set=True, persistent=False)
    last = None
    for c in cands:
        try:
            r.engine = c
            return c
        except TypeError as ex:
            last = ex
    raise ValueError("Engine {} nicht verfügbar: {}".format(name, last))


def _cycles_gpu(scene):
    """Cycles auf die GPU (OptiX, sonst CUDA), wenn vorhanden. → Gerätetext."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for typ in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = typ
            except TypeError:
                continue
            prefs.get_devices()
            devs = [d for d in prefs.devices if d.type == typ]
            if devs:
                for d in prefs.devices:
                    d.use = d.type == typ
                scene.cycles.device = "GPU"
                return typ
    except (KeyError, AttributeError):
        pass
    scene.cycles.device = "CPU"
    return "CPU"


def _render_cam(out, panel, objs, tag, engine=None, samples=None, umg=None):
    """Render der Szenenkamera mit eingestellter Engine, nur objs sichtbar (Licht/Boden bleiben).
    engine/samples: nur für dieses Bild. umg={"lights", "world"}: Licht und Welt eines anderen Stands statt der aktuellen."""
    global _cam_device
    from PIL import Image
    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("Szene hat keine Kamera (--mode cam braucht scene.camera)")
    r = scene.render
    saved = (r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath, r.image_settings.file_format, r.engine)
    s_eevee = scene.eevee.taa_render_samples
    s_cyc = dev = None
    world = scene.world
    aspect = r.resolution_y / max(r.resolution_x, 1)
    hidden = _hide_others(scene, objs) if objs is not None else []
    linked, lights_off = [], []
    p = "{}.cam.{}.tmp.png".format(out, tag)
    try:
        if umg is not None:
            for o in scene.objects:
                if o.type == "LIGHT" and not o.hide_render:
                    o.hide_render = True
                    lights_off.append(o)
            for o in umg["lights"]:
                if scene.collection.objects.get(o.name) is None:
                    scene.collection.objects.link(o)
                    linked.append(o)
            scene.world = umg["world"]
        if engine:
            _set_engine(r, engine)
        if hasattr(scene, "cycles"):  # erst hier: _set_engine lädt Cycles evtl. gerade erst
            s_cyc, dev = scene.cycles.samples, scene.cycles.device
        if r.engine == "CYCLES":
            _cam_device = _cycles_gpu(scene)
        if samples:
            if r.engine == "CYCLES":
                scene.cycles.samples = samples
            else:
                scene.eevee.taa_render_samples = samples
        r.resolution_x, r.resolution_y, r.resolution_percentage = panel, max(1, round(panel * aspect)), 100
        r.image_settings.file_format = "PNG"
        r.filepath = p
        bpy.ops.render.render(write_still=True)
        im = Image.open(p).convert("RGBA")
        im.load()
        os.remove(p)
    finally:
        for o in hidden + lights_off:
            o.hide_render = False
        for o in linked:
            scene.collection.objects.unlink(o)
        scene.world = world
        r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath, r.image_settings.file_format, r.engine = saved
        scene.eevee.taa_render_samples = s_eevee
        if s_cyc is not None:
            scene.cycles.samples, scene.cycles.device = s_cyc, dev
    return im


def _diff(a, b):
    """Anteil geänderter Pixel (in % der Objektfläche bzw. des Bilds) und Rahmen der Änderung."""
    import numpy as np
    A = np.asarray(a, dtype=np.int16)
    B = np.asarray(b, dtype=np.int16)
    if A.shape != B.shape:
        return None, None
    ina, inb = A[..., 3] > 0, B[..., 3] > 0
    ch = (np.abs(A[..., :3] - B[..., :3]).max(axis=2) > 12) | (ina != inb)
    area = int((ina | inb).sum())
    if area == 0 or area == ina.size:
        area = ina.size
    n = int(ch.sum())
    ys, xs = np.nonzero(ch)
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if n else None
    return 100.0 * n / area, bbox


def _scale_bar(mmpp, width, frac=0.25):
    """Runde Balkenlänge 1/2/5·10ⁿ mm (≤ frac der Breite). → (mm, px) oder None. Wie core.scale_bar."""
    if not mmpp or mmpp <= 0:
        return None
    target = mmpp * width * frac
    e = math.floor(math.log10(target))
    mm = max([k * 10 ** e for k in (1, 2, 5) if k * 10 ** e <= target] or [10 ** e])
    return mm, max(1, round(mm / mmpp))


def _tile(im, label, font, bg, mmpp=None):
    from PIL import Image, ImageDraw
    base = Image.new("RGBA", im.size, bg + (255,))
    base.alpha_composite(im)
    dr = ImageDraw.Draw(base)
    dr.text((6, 4), label, fill=(30, 30, 30), font=font)
    sb = _scale_bar(mmpp, base.width)
    if sb:  # Maßstabsbalken unten rechts
        mm, px = sb
        x1, y = base.width - 10, base.height - 12
        x0 = x1 - px
        txt = "{:g} mm".format(mm)
        tw = dr.textlength(txt, font=font)
        # helles Feld dahinter: Balken bleibt lesbar, wenn das Objekt bis in die Ecke reicht
        box = (min(x0, x1 - px / 2 - tw / 2) - 5, y - 14 - font.size, x1 + 5, y + 8)
        over = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(over).rectangle(box, fill=bg + (215,))
        base.alpha_composite(over)
        dr = ImageDraw.Draw(base)
        dr.rectangle((x0, y - 2, x1, y + 2), fill=(20, 20, 20))
        dr.line((x0, y - 7, x0, y + 5), fill=(20, 20, 20), width=2)
        dr.line((x1, y - 7, x1, y + 5), fill=(20, 20, 20), width=2)
        dr.text((x1 - px / 2 - tw / 2, y - 10 - font.size), txt, fill=(20, 20, 20), font=font)
    return base.convert("RGB")


def _parse_focus(focus, radius_mm):
    """focus: Objektname oder 'x,y,z' in mm (wie --radius). radius_mm: Radius des Ausschnitts in mm."""
    su = bpy.context.scene.unit_settings.scale_length or 1.0
    r = radius_mm / 1000.0 / su if radius_mm else None
    if focus in bpy.data.objects:
        mn, mx = bbox_world([bpy.data.objects[focus]])
        return (mn + mx) / 2, r or max((mx - mn).length / 2, 1e-4)
    try:
        c = Vector([float(x) / 1000.0 / su for x in focus.split(",")])  # mm → Szeneneinheiten
        assert len(c) == 3
    except (ValueError, AssertionError):
        raise ValueError("--focus braucht einen Objektnamen oder x,y,z in mm, nicht {!r}".format(focus))
    if r is None:
        raise ValueError("--focus x,y,z braucht --radius (mm)")
    return c, r


def look(out, views=("iso",), names=None, mode="solid", panel=768, sheet=False, compare=None, bg=(242, 242, 242),
         focus=None, radius_mm=None, section=None, engine=None, samples=None):
    """Rendert Ansichten in eine PNG mit Textstreifen. mode: solid|wire (Workbench, ortho, gerahmt) oder cam.
    compare=<.blend>: derselbe Blick auf den gespeicherten Stand links ("vorher"), aktuelle Szene rechts ("jetzt"),
    gleiche Kamera für beide; Änderung in % mit rotem Rahmen."""
    from PIL import Image, ImageDraw
    scene = bpy.context.scene
    if focus and mode == "cam":
        raise ValueError("--focus geht nur mit solid/wire, nicht mit --mode cam")
    fcs = _parse_focus(focus, radius_mm) if focus else None
    sec = None
    if section:
        ax, _s, v = section.replace(" ", "").partition("=")
        sec = (ax, float(v))
        if focus:
            raise ValueError("--section und --focus nicht zusammen")
    ref, new_ids, umg, eng = [], [], None, None
    try:
        if compare:
            ref, new_ids, umg = _append_ref(compare, names, os.path.dirname(out), env=(mode == "cam"))
            if not ref:
                raise RuntimeError("Vergleichsstand {} enthält keine passenden Geometrie-Objekte".format(compare))
        refp = {o.as_pointer() for o in ref}
        ground = []
        if names:
            objs = [obj(n) for n in names]
        else:
            objs = [o for o in scene.objects if o.type in GEOM_TYPES and o.visible_get() and o.as_pointer() not in refp]
            if mode != "cam":
                objs, ground = _split_ground(objs)
                if ref:
                    ref, _g = _split_ground(ref)
        if not objs:
            raise RuntimeError("Nichts zu sehen: keine sichtbaren Geometrie-Objekte in der Szene")
        if mode == "cam":
            cur = [("cam", _render_cam(out, panel, objs if compare else None, "jetzt", engine, samples), None)]
            old = [("cam", _render_cam(out, panel, ref, "vorher", engine, samples, umg), None)] if compare else []
        else:
            frame = objs + ref
            cur = _render_views(out, objs, frame, views, mode, panel, "jetzt", fcs, sec)
            old = _render_views(out, ref, frame, views, mode, panel, "vorher", fcs, sec) if compare else []
        faces = sum(mesh_stats(o, manifold=False).get("f", 0) for o in objs if o.type == "MESH")
        names_txt = ", ".join(o.name for o in objs[:8]) + (" …" if len(objs) > 8 else "")
        if ground:
            names_txt += "  (ohne Boden: {})".format(", ".join(o.name for o in ground))
        if sec:
            names_txt += "  · Schnitt {}={:g} mm{}".format(sec[0], sec[1], " (rot = Schnittfläche)" if mode == "solid" else "")
        if mode == "cam":
            eng = engine or {"CYCLES": "cycles", "BLENDER_WORKBENCH": "workbench"}.get(scene.render.engine, "eevee")
            names_txt += "  · Engine {}{}{}".format(eng, " ({})".format(_cam_device) if eng == "cycles" else "",
                                                    " · {} Samples".format(samples) if samples and eng != "workbench" else "")
        if fcs:
            su = scene.unit_settings.scale_length or 1.0
            names_txt += "  · Ausschnitt um ({}) mm, r {:.3g} mm".format(
                ", ".join("{:.4g}".format(x * su * 1000) for x in fcs[0]), fcs[1] * su * 1000)
    finally:
        if new_ids:
            bpy.data.batch_remove(new_ids)

    font, font_s = _font(max(11, panel // 40)), _font(12)
    changes = []
    if compare:
        rows = []
        for (v, im_new, mm_n), (_v, im_old, mm_o) in zip(cur, old):
            pct, bbox = _diff(im_old, im_new)
            pct = round(pct, 1)  # eine Rundung für Kachel, Legende und CLI
            changes.append({"view": v, "pct": pct, "bbox": bbox})
            a = _tile(im_old, v + " · vorher", font, bg, mm_o)
            b = _tile(im_new, "{} · jetzt · Änderung {:.1f} %".format(v, pct), font, bg, mm_n)
            if bbox:
                x0, y0, x1, y1 = bbox
                ImageDraw.Draw(b).rectangle((max(0, x0 - 4), max(0, y0 - 4), min(b.width - 1, x1 + 4), min(b.height - 1, y1 + 4)),
                                            outline=(220, 30, 30), width=2)
            rows.append((a, b))
        tw, th, gap = rows[0][0].width, rows[0][0].height, 4
        img = Image.new("RGB", (2 * tw + gap, len(rows) * th + gap * (len(rows) - 1)), (255, 255, 255))
        for i, (a, b) in enumerate(rows):
            img.paste(a, (0, i * (th + gap)))
            img.paste(b, (tw + gap, i * (th + gap)))
    else:
        tiles = [_tile(im, v, font, bg, m) for v, im, m in cur]
        if sheet and len(tiles) > 1:
            cols = 2
            grid = Image.new("RGB", (cols * panel, math.ceil(len(tiles) / cols) * panel), (200, 200, 200))
            for i, t in enumerate(tiles):
                grid.paste(t, ((i % cols) * panel, (i // cols) * panel))
            img = grid
        else:
            img = tiles[0]
    mmpp = [m for _v, _i, m in cur if m is not None]
    empty = [v for v, im, _m in cur if mode != "cam" and im.getextrema()[3][1] == 0]
    legend = ["{} · Modus {}{} · Objekte {} · Faces {}".format(
        "/".join(v for v, _i, _m in cur), mode,
        " · 1 px = {} mm".format("/".join("{:.3g}".format(x) for x in mmpp)) if mmpp else "", len(objs), faces), names_txt]
    if empty:
        legend.append("⚠ LEER: in {} ist nichts zu sehen (Ausschnitt verfehlt? Punkt in mm angeben)".format("/".join(empty)))
    if compare:
        mx = max(c["pct"] for c in changes)
        legend.append("Vergleich mit {}: {}{}".format(
            os.path.basename(os.path.dirname(os.path.dirname(compare))) + "/" + os.path.basename(compare),
            ", ".join("{} {:.1f} %".format(c["view"], c["pct"]) for c in changes),
            "  ⚠ kaum sichtbare Änderung (< 1 %)" if mx < 1 else ""))
    strip_h = len(legend) * 16 + 8
    final = Image.new("RGB", (img.width, img.height + strip_h), (255, 255, 255))
    final.paste(img, (0, 0))
    dr = ImageDraw.Draw(final)
    for i, ln in enumerate(legend):
        dr.text((6, img.height + 4 + i * 16), ln, fill=(20, 20, 20), font=font_s)
    final.save(out)
    return {"path": out, "w": final.width, "h": final.height, "mm_per_px": [round(x, 4) for x in mmpp],
            "views": [v for v, _i, _m in cur], "objects": len(objs), "faces": faces,
            "compare": compare, "changes": changes, "ground": [o.name for o in ground], "empty": empty,
            "engine": (eng + (" ({})".format(_cam_device) if eng == "cycles" else "")) if mode == "cam" else None}


# --------------------------------------------------------------------------- qa

def _qa_module(qa_dir):
    """qa_check aus EL4CTEO blender-asset-qa (MIT) laden; das Verzeichnis kommt hinten in sys.path (für _bpyx)."""
    import importlib
    if not os.path.isfile(os.path.join(qa_dir, "qa_check.py")):
        raise RuntimeError("qa_check.py fehlt unter {}".format(qa_dir))
    if qa_dir not in sys.path:
        sys.path.append(qa_dir)
    return importlib.import_module("qa_check")


# eigene Prüfungen → Schlüssel im qa_check-Profil (e = Fehler, w = Warnung, None = aus)
_QA_OWN = {"winzig": "dg", "splitter": "dg", "gefaltet": "inc"}


def qa(names=None, profile="game", budget=None, eps=None, tol=None, qa_dir=None):
    """Prüft Meshes mit qa_check (z-fighting, schwebend, Normalen, offene/nm-Kanten, Duplikate, Maßstab, UV, Material)
    plus eigene Prüfungen (kaputte Flächen, Schwere nach Profil) und Polybudget (Tris gesamt).
    names: diese Objekte zusammen als ein Asset. None: jedes sichtbare Mesh einzeln (ohne große Bodenplatten),
    sonst gelten getrennte Objekte als „schwebend“. Modus und aktives Objekt bleiben erhalten.
    → {"pass", "errors", "warnings", "objects", "ground", "tris"}"""
    scene = bpy.context.scene
    qc = _qa_module(qa_dir or os.path.expanduser("~/repos/blender-skills/skills/blender-asset-qa/scripts"))
    sev = qc.PROFILES[profile]
    ground = []
    if names:
        objs = [obj(n) for n in names]
        groups = [[o for o in objs if o.type == "MESH"]]
    else:
        objs = [o for o in scene.objects if o.type == "MESH" and o.visible_get()]
        objs, ground = _split_ground(objs)
        groups = [[o] for o in objs]
    groups = [g for g in groups if g]
    if not groups:
        raise RuntimeError("keine Meshes zu prüfen")
    kw = {"profile": profile}
    if eps is not None:
        kw["eps"] = eps
    if tol is not None:
        kw["tol"] = tol
    vl = bpy.context.view_layer
    act = vl.objects.active
    mode = act.mode if act is not None else "OBJECT"
    errors, warnings, per, total, gz = [], [], {}, 0, []
    try:
        for g in groups:
            r = qc.run(objects=[o.name for o in g], **kw)
            errors += r.get("errors", [])
            warnings += r.get("warnings", [])
            if r.get("ground_z") is not None:
                gz.append(r["ground_z"])
            for o in g:
                st = mesh_stats(o)
                q = (r.get("objects") or {}).get(o.name, {})
                tris = q.get("tris", st.get("tris", 0))
                total += tris
                per[o.name] = {"tris": tris, "faces": st.get("f"), "islands": q.get("islands"),
                               "dims_mm": [round(x * (scene.unit_settings.scale_length or 1.0) * 1000, 2) for x in o.dimensions]}
                for k, prof_key in _QA_OWN.items():
                    if st.get(k):
                        msg = "{}: kaputte Flächen {} {}".format(o.name, k, st[k])
                        level = sev.get(prof_key)
                        (errors if level == "e" else warnings if level == "w" else []).append(msg)
    finally:  # qa_check schaltet in den Object-Modus: Modus und aktives Objekt zurück
        if act is not None and act.name in vl.objects:
            vl.objects.active = act
            if act.mode != mode:
                try:
                    bpy.ops.object.mode_set(mode=mode)
                except RuntimeError:
                    pass
    if budget is not None and total > budget:
        errors.append("Polybudget überschritten: {} Tris > {}".format(total, budget))
    return {"pass": not errors, "profile": profile, "errors": errors, "warnings": warnings, "objects": per,
            "ground": [o.name for o in ground], "tris": total, "budget": budget,
            "ground_z": min(gz) if gz else None, "einzeln": not names}


# --------------------------------------------------------------------------- save

def save(path):
    global _changed
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False)
    _changed = False  # erst nach erfolgreichem Speichern
    return {"path": path, "bytes": os.path.getsize(path)}
