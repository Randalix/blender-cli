"""Hoehe (auf der Emission des Materials) als Float backen und als 16-bit-PNG (Non-Color) speichern.
Grund: bake_maps.py aus blender-skills backt 8 bit. Glatte Hoehen-Plateaus quantisieren dann zu Treppen
(T5: nur 134 Stufen), und Sobel macht daraus wurmartige Konturlinien in der Normal-Map.
  blender-gpu -b in.blend --factory-startup -P bake_height16.py -- --obj T5_Wall --out H16.png [--res 1024] [--samples 16]"""
import argparse, json, sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--obj", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--res", type=int, default=1024); ap.add_argument("--samples", type=int, default=16)
a = ap.parse_args(argv)

sc = bpy.context.scene
sc.render.engine = "CYCLES"; sc.cycles.samples = a.samples
backend = "CPU"
prefs = bpy.context.preferences.addons["cycles"].preferences
for b in ("OPTIX", "CUDA"):
    try:
        prefs.compute_device_type = b; prefs.refresh_devices()
        if any(d.type == b for d in prefs.devices):
            for d in prefs.devices: d.use = d.type == b
            sc.cycles.device = "GPU"; backend = b; break
    except TypeError:
        continue
sc.render.bake.margin = 0
ob = bpy.data.objects[a.obj]
img = bpy.data.images.new("H16", a.res, a.res, alpha=False, float_buffer=True, is_data=True)
for slot in ob.material_slots:
    nt = slot.material.node_tree
    n = nt.nodes.new("ShaderNodeTexImage"); n.image = img; nt.nodes.active = n
for o in bpy.context.view_layer.objects: o.select_set(False)
ob.select_set(True); bpy.context.view_layer.objects.active = ob
# Emission ohne Farbmanagement-Einfluss: Bake schreibt lineare Werte in das Float-Bild
res = bpy.ops.object.bake(type="EMIT")
# Speichern ueber save_render mit Raw-View, damit kein AgX/Filmic auf die Daten kommt, als 16-bit-Graustufe
s = sc.render.image_settings
s.file_format = "PNG"; s.color_mode = "BW"; s.color_depth = "16"
try:
    s.color_management = "OVERRIDE"; s.view_settings.view_transform = "Raw"  # kein AgX/Filmic auf Daten
except Exception:
    pass
img.save_render(a.out, scene=sc)
px = img.pixels[:]
vals = px[0::4]
print("@@JSON@@" + json.dumps({"ok": res == {"FINISHED"}, "device": backend, "out": a.out, "min": round(min(vals), 4), "max": round(max(vals), 4)}))
