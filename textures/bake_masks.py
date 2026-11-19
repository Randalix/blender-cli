"""Mehrere Masken eines Materials in EINEM Blender-Lauf als Float backen und als 16-bit-PNG speichern.
Masken = Nodes mit Namen "MASK_<name>" (z. B. von formwork_wall.py angelegt). "height" = die aktuelle Emission.
  blender-gpu -b in.blend --factory-startup -P bake_masks.py -- --obj T5_Wall --outdir DIR [--masks height,spall,crack] [--res 1024] [--samples 8]
Ausgabe: DIR/<name>.png (16 bit, Non-Color, Raw-View)."""
import argparse, json, os, sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--obj", required=True); ap.add_argument("--outdir", required=True)
ap.add_argument("--masks", default=""); ap.add_argument("--res", type=int, default=1024); ap.add_argument("--samples", type=int, default=8)
a = ap.parse_args(argv)
os.makedirs(a.outdir, exist_ok=True)
sc = bpy.context.scene; sc.render.engine = "CYCLES"; sc.cycles.samples = a.samples; sc.render.bake.margin = 0
backend = "CPU"; prefs = bpy.context.preferences.addons["cycles"].preferences
for b in ("OPTIX", "CUDA"):
    try:
        prefs.compute_device_type = b; prefs.refresh_devices()
        if any(d.type == b for d in prefs.devices):
            for d in prefs.devices: d.use = d.type == b
            sc.cycles.device = "GPU"; backend = b; break
    except TypeError:
        continue
s = sc.render.image_settings; s.file_format = "PNG"; s.color_mode = "BW"; s.color_depth = "16"
try:
    s.color_management = "OVERRIDE"; s.view_settings.view_transform = "Raw"
except Exception:
    pass
ob = bpy.data.objects[a.obj]
for o in bpy.context.view_layer.objects: o.select_set(False)
ob.select_set(True); bpy.context.view_layer.objects.active = ob
nt = ob.material_slots[0].material.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
em_in = bsdf.inputs["Emission Color"]
orig = em_in.links[0].from_socket if em_in.links else None
names = [x for x in a.masks.split(",") if x] or ["height"] + [n.name[5:] for n in nt.nodes if n.name.startswith("MASK_")]
img = bpy.data.images.new("BAKE", a.res, a.res, alpha=False, float_buffer=True, is_data=True)
tgt = nt.nodes.new("ShaderNodeTexImage"); tgt.image = img; nt.nodes.active = tgt
comb = nt.nodes.new("ShaderNodeCombineXYZ")
done = {}
for nm in names:
    for l in list(em_in.links): nt.links.remove(l)
    if nm == "height":
        nt.links.new(orig, em_in)
    else:
        src = nt.nodes["MASK_" + nm].outputs[0]
        for i in range(3): nt.links.new(src, comb.inputs[i])
        nt.links.new(comb.outputs[0], em_in)
    r = bpy.ops.object.bake(type="EMIT")
    out = os.path.join(a.outdir, nm + ".png"); img.save_render(out, scene=sc)
    v = img.pixels[0::4]; done[nm] = {"ok": r == {"FINISHED"}, "max": round(max(v), 4), "cover>0.3": round(sum(1 for x in v if x > 0.3) / len(v) * 100, 2)}
for l in list(em_in.links): nt.links.remove(l)
if orig: nt.links.new(orig, em_in)
print("@@JSON@@" + json.dumps({"device": backend, "outdir": a.outdir, "masks": done}))
