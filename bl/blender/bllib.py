"""bllib — läuft im bl-Worker (Blender). Skripte haben ohne Import: bpy, bl (dieses Modul), report, obj, mesh_stats, Vector.

Wichtig für Skript-Autoren:
- result = {...} setzen, um Werte (JSON) zurückzugeben; print() kommt gekürzt zurück.
- report(obj_oder_name, ...) markiert Objekte für `bl run --report` und `--look`.
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
GEOM_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME"}
FONT_PATHS = ("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def _request_quit():
    global _quit
    _quit = True


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
    """Zahlen des ausgewerteten Netzes (nach Modifiern): v/e/f/tris, Maße, offene/nicht-mannigfaltige Kanten."""
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


def run_file(path):
    """Führt ein Skript in der offenen Szene aus. Fehler fliegen durch (Traceback mit Datei und Zeile)."""
    _reports.clear()
    g = {"__name__": "__bl_run__", "__file__": path, "bpy": bpy, "bl": sys.modules[__name__],
         "report": report, "obj": obj, "mesh_stats": mesh_stats, "Vector": Vector, "Matrix": Matrix,
         "math": math, "result": {}}
    with open(path, encoding="utf-8") as fh:
        code = compile(fh.read(), path, "exec")
    t0 = time.time()
    exec(code, g)
    res = g.get("result")
    if not isinstance(res, dict):
        res = {"result": res}
    return {"result": _jsonable(res), "reports": [summary(bpy.data.objects[n]) for n in _reports if n in bpy.data.objects],
            "reported": list(_reports), "seconds": round(time.time() - t0, 3)}


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
        L.append("ausgewertet: " + "  ".join("{} {}".format(k, v) for k, v in st.items() if k != "dims"))
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


_ID_COLLS = ("objects", "meshes", "materials", "images", "node_groups", "textures", "curves", "collections",
             "cameras", "lights", "actions", "metaballs", "lattices", "armatures", "volumes", "pointclouds",
             "hair_curves", "grease_pencils", "fonts", "particles")


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


def _append_ref(path, names, tmpdir):
    """Lädt die Geometrie-Objekte eines gespeicherten Stands temporär in die Szene. → (objekte, neue IDs zum Entfernen)."""
    import shutil
    colls = [c for c in _ID_COLLS if hasattr(bpy.data, c)]
    tmp = os.path.join(tmpdir, "_bl_ref_{}.blend".format(os.getpid()))
    shutil.copyfile(path, tmp)  # Kopie: aus der gerade offenen Datei kann Blender nicht anhängen
    before = {c: {i.as_pointer() for i in getattr(bpy.data, c)} for c in colls}
    try:
        with bpy.data.libraries.load(tmp, link=False) as (src, dst):
            srcnames = list(src.objects)
            dst.objects = srcnames
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
    return ref, new


def _render_views(out, objs, frame, views, mode, panel, tag):
    """Workbench-Renders der Objekte objs (alles andere ausgeblendet), Kamera gerahmt auf frame. → [(view, RGBA, mm/px)]"""
    from PIL import Image
    scene = bpy.context.scene
    mn, mx = bbox_world(frame)
    center = (mn + mx) / 2
    radius = max((mx - mn).length / 2, 1e-4)
    r, sh = scene.render, scene.display.shading
    saved = {"engine": r.engine, "rx": r.resolution_x, "ry": r.resolution_y, "pct": r.resolution_percentage,
             "film": r.film_transparent, "fp": r.filepath, "cam": scene.camera, "fmt": r.image_settings.file_format,
             "cmode": r.image_settings.color_mode,
             "light": sh.light, "ctype": sh.color_type, "cav": sh.show_cavity, "outl": sh.show_object_outline}
    temps, colors = [], {}
    cam_data = bpy.data.cameras.new("_bl_look_cam")
    cam = bpy.data.objects.new("_bl_look_cam", cam_data)
    scene.collection.objects.link(cam)
    temps.append(cam)
    hidden = _hide_others(scene, objs)
    res = []
    try:
        r.engine = "BLENDER_WORKBENCH"
        r.resolution_x = r.resolution_y = panel
        r.resolution_percentage = 100
        r.film_transparent = True
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGBA"
        sh.light = "STUDIO"
        sh.show_cavity = True
        sh.show_object_outline = True
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
                mod.use_even_offset = True
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
            cam_data.ortho_scale = max(ext * 2 * 1.1, 1e-4)
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
        for o in temps:
            data = o.data if o.type == "CAMERA" else None
            bpy.data.objects.remove(o, do_unlink=True)
            if data is not None:
                bpy.data.cameras.remove(data)
        for o in hidden:
            o.hide_render = False
        for o, c in colors.values():
            o.color = c
        r.engine, r.resolution_x, r.resolution_y = saved["engine"], saved["rx"], saved["ry"]
        r.resolution_percentage, r.film_transparent, r.filepath = saved["pct"], saved["film"], saved["fp"]
        r.image_settings.file_format, r.image_settings.color_mode = saved["fmt"], saved["cmode"]
        scene.camera = saved["cam"]
        sh.light, sh.color_type, sh.show_cavity, sh.show_object_outline = saved["light"], saved["ctype"], saved["cav"], saved["outl"]
    return res


def _render_cam(out, panel, objs, tag):
    """Render der Szenenkamera mit eingestellter Engine, nur objs sichtbar (Licht/Boden bleiben)."""
    from PIL import Image
    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("Szene hat keine Kamera (--mode cam braucht scene.camera)")
    r = scene.render
    saved = (r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath, r.image_settings.file_format)
    aspect = r.resolution_y / max(r.resolution_x, 1)
    hidden = _hide_others(scene, objs) if objs is not None else []
    p = "{}.cam.{}.tmp.png".format(out, tag)
    try:
        r.resolution_x, r.resolution_y, r.resolution_percentage = panel, max(1, round(panel * aspect)), 100
        r.image_settings.file_format = "PNG"
        r.filepath = p
        bpy.ops.render.render(write_still=True)
        im = Image.open(p).convert("RGBA")
        im.load()
        os.remove(p)
    finally:
        for o in hidden:
            o.hide_render = False
        r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath, r.image_settings.file_format = saved
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


def _tile(im, label, font, bg):
    from PIL import Image, ImageDraw
    base = Image.new("RGBA", im.size, bg + (255,))
    base.alpha_composite(im)
    ImageDraw.Draw(base).text((6, 4), label, fill=(30, 30, 30), font=font)
    return base.convert("RGB")


def look(out, views=("iso",), names=None, mode="solid", panel=768, sheet=False, compare=None, bg=(242, 242, 242)):
    """Rendert Ansichten in eine PNG mit Textstreifen. mode: solid|wire (Workbench, ortho, gerahmt) oder cam.
    compare=<.blend>: derselbe Blick auf den gespeicherten Stand links ("vorher"), aktuelle Szene rechts ("jetzt"),
    gleiche Kamera für beide; Änderung in % mit rotem Rahmen."""
    from PIL import Image, ImageDraw
    scene = bpy.context.scene
    ref, new_ids = [], []
    try:
        if compare:
            ref, new_ids = _append_ref(compare, names, os.path.dirname(out))
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
            cur = [("cam", _render_cam(out, panel, objs if compare else None, "jetzt"), None)]
            old = [("cam", _render_cam(out, panel, ref, "vorher"), None)] if compare else []
        else:
            frame = objs + ref
            cur = _render_views(out, objs, frame, views, mode, panel, "jetzt")
            old = _render_views(out, ref, frame, views, mode, panel, "vorher") if compare else []
        faces = sum(mesh_stats(o, manifold=False).get("f", 0) for o in objs if o.type == "MESH")
        names_txt = ", ".join(o.name for o in objs[:8]) + (" …" if len(objs) > 8 else "")
        if ground:
            names_txt += "  (ohne Boden: {})".format(", ".join(o.name for o in ground))
    finally:
        if new_ids:
            bpy.data.batch_remove(new_ids)

    font, font_s = _font(max(11, panel // 40)), _font(12)
    changes = []
    if compare:
        rows = []
        for (v, im_new, _), (_v, im_old, _m) in zip(cur, old):
            pct, bbox = _diff(im_old, im_new)
            pct = round(pct, 1)  # eine Rundung für Kachel, Legende und CLI
            changes.append({"view": v, "pct": pct, "bbox": bbox})
            a = _tile(im_old, v + " · vorher", font, bg)
            b = _tile(im_new, "{} · jetzt · Änderung {:.1f} %".format(v, pct), font, bg)
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
        tiles = [_tile(im, v, font, bg) for v, im, _ in cur]
        if sheet and len(tiles) > 1:
            cols = 2
            grid = Image.new("RGB", (cols * panel, math.ceil(len(tiles) / cols) * panel), (200, 200, 200))
            for i, t in enumerate(tiles):
                grid.paste(t, ((i % cols) * panel, (i // cols) * panel))
            img = grid
        else:
            img = tiles[0]
    mmpp = [m for _v, _i, m in cur if m is not None]
    legend = ["{} · Modus {} · 1 px = {} mm · Objekte {} · Faces {}".format(
        "/".join(v for v, _i, _m in cur), mode, "/".join("{:.3g}".format(x) for x in mmpp) or "-", len(objs), faces), names_txt]
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
            "compare": compare, "changes": changes, "ground": [o.name for o in ground]}


# --------------------------------------------------------------------------- save

def save(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False)
    return {"path": path, "bytes": os.path.getsize(path)}
