"""Tangent-Normal-Map aus einer kachelbaren Hoehenkarte (Sobel, umlaufend -> bleibt nahtlos).
Grund: Blenders Bump-Node liefert beim Backen schwache, stark unterproportionale Normals (feinstes Rauschen
dominiert, kleine scharfe Poren kommen kaum durch). Besser: Hoehe backen (Emission), Normal hier ableiten.
Laeuft in Blender (bringt numpy mit, kein scipy noetig):
  blender-gpu -b --factory-startup -P normal_from_height.py -- --height H.png --out N.png [--strength 60] [--directx]
--strength: Gradient-Faktor (Hoehe 0..1 je Pixel); 60 entspricht dem Tunnel-T5-Stand (xy-Streuung ~0,2)."""
import argparse, json, sys
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--height", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--strength", type=float, default=60.0); ap.add_argument("--directx", action="store_true")
a = ap.parse_args(argv)

img = bpy.data.images.load(a.height); img.colorspace_settings.name = "Non-Color"
w, h = img.size
px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)  # Blender: Zeile 0 = unten
H = px[..., :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def sobel(z, axis):
    """Sobel mit Wrap (np.roll) -> Ableitung entlang axis, /8 normiert."""
    other = 1 - axis
    d = np.roll(z, -1, axis) - np.roll(z, 1, axis)
    return (np.roll(d, 1, other) + 2 * d + np.roll(d, -1, other)) / 8.0


gx = sobel(H, 1)            # nach rechts
gy_up = sobel(H, 0)         # Zeilen laufen in Blender nach oben -> direkt +Y
nx, ny = -gx * a.strength, -gy_up * a.strength
if a.directx: ny = -ny
nz = np.ones_like(H)
ln = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2)
n = np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5
out = bpy.data.images.new("N", w, h, alpha=False, float_buffer=False)
out.colorspace_settings.name = "Non-Color"
out.pixels[:] = np.concatenate([n, np.ones((h, w, 1), np.float32)], -1).ravel()
out.filepath_raw = a.out; out.file_format = "PNG"; out.save()
print("@@JSON@@" + json.dumps({"ok": True, "out": a.out, "size": [w, h], "xy_std": [round(float(n[..., 0].std() * 2), 3), round(float(n[..., 1].std() * 2), 3)],
                              "convention": "DirectX" if a.directx else "OpenGL"}))
