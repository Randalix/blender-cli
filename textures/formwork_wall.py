"""Sichtbetonwand aus Schalungstafeln als Blender-Shader-Nodes (Neon Getaway T5, 2,4 x 2,4 m). Ursprung: tools/blender_t5_build.py im Worktree neon_getaway-tunnelart (19.11.2026).
Baut Plane 2,4 x 2,4 m (UV 0..1) + prozedurales Material, speichert .blend; gebacken wird danach mit
blender-skills/blender-texture-baking/scripts/bake_maps.py (Self-Bake: basecolor roughness normal emit).
Kachelbar per Konstruktion: alle Rauschen auf dem flachen Clifford-Torus (cos/sin 2πu, cos/sin 2πv) in 4D,
Fugen/Anker aus fract(UV). Wolken = Krea-Torus-Kachel als Bild (Repeat). Emission = Height (fuer emit-Pass).
blender-gpu -b --factory-startup -P formwork_wall.py -- --cloud cloud.png --save out.blend [--seed 7] [--cloud-amt 4] [--bump-dist 1.5] [--grain-amt 0.12]"""
import argparse, math, sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--cloud", required=True); ap.add_argument("--save", required=True)
ap.add_argument("--seed", type=float, default=7.0); ap.add_argument("--bump", type=float, default=1.0)
ap.add_argument("--cloud-amt", type=float, default=0.55); ap.add_argument("--bump-dist", type=float, default=0.004); ap.add_argument("--grain-amt", type=float, default=0.035)
a = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_plane_add(size=2.4)
ob = bpy.context.active_object; ob.name = "T5_Wall"
mat = bpy.data.materials.new("M_T5"); mat.use_nodes = True; ob.data.materials.append(mat)
nt = mat.node_tree; N = nt.nodes; L = nt.links
for n in list(N): N.remove(n)
X = [0]


def node(t, **kw):
    n = N.new(t); n.location = (X[0] * 40 % 4000, -(X[0] // 100) * 200); X[0] += 1
    for k, v in kw.items(): setattr(n, k, v)
    return n


def inp(n, i, v):
    if isinstance(v, (int, float)): n.inputs[i].default_value = v
    else: L.new(v, n.inputs[i])


def m(op, x, y=None, z=None):
    n = node("ShaderNodeMath", operation=op); inp(n, 0, x)
    if y is not None: inp(n, 1, y)
    if z is not None: inp(n, 2, z)
    return n.outputs[0]


def mr(x, a0, a1, b0, b1, interp="SMOOTHSTEP", clamp=True):
    n = node("ShaderNodeMapRange", interpolation_type=interp, clamp=clamp); inp(n, 0, x)
    for i, v in zip((1, 2, 3, 4), (a0, a1, b0, b1)): inp(n, i, v)
    return n.outputs[0]


def comb(x, y, z):
    n = node("ShaderNodeCombineXYZ"); inp(n, 0, x); inp(n, 1, y); inp(n, 2, z); return n.outputs[0]


tc = node("ShaderNodeTexCoord"); sep = node("ShaderNodeSeparateXYZ"); L.new(tc.outputs["UV"], sep.inputs[0])
u, v = sep.outputs[0], sep.outputs[1]
TAU = 2 * math.pi


def torus(ru, rv, off=0.0):
    """Clifford-Torus: (ru cos2πu, ru sin2πu, rv cos2πv) + W = rv sin2πv. Radius r ~ Kachel/(2π) in Rausch-Einheiten."""
    au = m("MULTIPLY", u, TAU); av = m("MULTIPLY", v, TAU)
    vec = comb(m("ADD", m("MULTIPLY", m("COSINE", au), ru), off), m("MULTIPLY", m("SINE", au), ru), m("MULTIPLY", m("COSINE", av), rv))
    w = m("ADD", m("MULTIPLY", m("SINE", av), rv), a.seed)
    return vec, w


def noise4(ru, rv, scale, detail=4.0, rough=0.5, off=0.0):
    vec, w = torus(ru, rv, off)
    n = node("ShaderNodeTexNoise", noise_dimensions="4D"); L.new(vec, n.inputs["Vector"]); L.new(w, n.inputs["W"])
    n.inputs["Scale"].default_value = scale; n.inputs["Detail"].default_value = detail; n.inputs["Roughness"].default_value = rough
    return n.outputs["Fac"]


def voronoi4(r, scale, off=0.0):
    vec, w = torus(r, r, off)
    n = node("ShaderNodeTexVoronoi", voronoi_dimensions="4D", feature="F1", distance="EUCLIDEAN")
    L.new(vec, n.inputs["Vector"]); L.new(w, n.inputs["W"]); n.inputs["Scale"].default_value = scale
    return n.outputs["Distance"], n.outputs["Color"]


R = 1.0  # Torusradius -> Umfang 2π entspricht 2,4 m; Scale 1 ~ 0,38 m Strukturgroesse

# --- Wolken: Krea-Kachel (Repeat), Luma, weich
img = node("ShaderNodeTexImage", extension="REPEAT", interpolation="Cubic")
img.image = bpy.data.images.load(a.cloud); img.image.colorspace_settings.name = "Non-Color"
L.new(tc.outputs["UV"], img.inputs["Vector"])
rgb2bw = node("ShaderNodeRGBToBW"); L.new(img.outputs["Color"], rgb2bw.inputs[0])
cloud = m("SUBTRACT", rgb2bw.outputs[0], 0.636)  # um 0 zentriert (Quelle Mittel ~0,62)

# --- Poren: Voronoi-F1 klein -> Loch, Radius je Zelle zufaellig; zwei Groessen
d1, c1 = voronoi4(R, 60.0)            # ~6 mm Zellen -> feine Poren
sep_c = node("ShaderNodeSeparateColor"); L.new(c1, sep_c.inputs[0])
rad1 = m("MULTIPLY", m("POWER", sep_c.outputs[0], 3.5), 0.42)   # meist winzig, wenige groesser
pore1 = mr(m("SUBTRACT", d1, rad1), -0.02, 0.03, 1.0, 0.0)
d2, c2 = voronoi4(R, 14.0, off=3.3)   # Lunker, selten
sep_c2 = node("ShaderNodeSeparateColor"); L.new(c2, sep_c2.inputs[0])
rad2 = m("MULTIPLY", m("POWER", sep_c2.outputs[0], 14.0), 0.32)
pore2 = mr(m("SUBTRACT", d2, rad2), -0.02, 0.025, 1.0, 0.0)
pores = m("MAXIMUM", pore1, pore2)

# --- Schalhaut-Maserung: Noise stark horizontal gestreckt (kleiner Radius in u = lange Struktur in x), je Tafel versetzt
grain = m("SUBTRACT", noise4(0.08, 1.0, 9.0, detail=6.0, rough=0.6), 0.5)
fine = m("SUBTRACT", noise4(R, R, 160.0, detail=2.0, rough=0.5, off=7.0), 0.5)  # feine Koernung

# --- Fugen: Abstand in px (1024er-Raster), senkrecht an u=0, waagerecht an v=0 und v=0,5
du = m("MULTIPLY", m("MINIMUM", u, m("SUBTRACT", 1.0, u)), 1024.0)
fv = m("FRACT", m("MULTIPLY", v, 2.0))
dv = m("MULTIPLY", m("MINIMUM", fv, m("SUBTRACT", 1.0, fv)), 512.0)
dj = m("MINIMUM", du, dv)
groove = mr(dj, 0.4, 1.9, 1.0, 0.0)
ridge = m("MULTIPLY", mr(dj, 1.6, 2.4, 0.0, 1.0), mr(dj, 2.6, 3.6, 1.0, 0.0))
ridge = m("MULTIPLY", ridge, mr(noise4(0.5, 0.5, 6.0, off=11.0), 0.35, 0.65, 0.2, 1.0))
seam_tint = mr(dj, 2.0, 14.0, 1.0, 0.0)

# --- Ankerloecher: Zellen 4x4 (0,6 m), Zentrum je Zelle; Zufall je Zelle ueber White Noise auf floor(UV*4)
cu = m("SUBTRACT", m("FRACT", m("MULTIPLY", u, 4.0)), 0.5); cv = m("SUBTRACT", m("FRACT", m("MULTIPLY", v, 4.0)), 0.5)
dr = m("MULTIPLY", m("SQRT", m("ADD", m("MULTIPLY", cu, cu), m("MULTIPLY", cv, cv))), 256.0)  # px
cell = comb(m("FLOOR", m("MULTIPLY", u, 4.0)), m("FLOOR", m("MULTIPLY", v, 4.0)), a.seed)
wn = node("ShaderNodeTexWhiteNoise", noise_dimensions="3D"); L.new(cell, wn.inputs["Vector"])
wsep = node("ShaderNodeSeparateColor"); L.new(wn.outputs["Color"], wsep.inputs[0])
r_out = m("ADD", 5.0, m("MULTIPLY", wsep.outputs[0], 1.2))
r_plug = m("SUBTRACT", r_out, m("ADD", 1.0, m("MULTIPLY", wsep.outputs[1], 0.8)))
hole = mr(m("SUBTRACT", dr, r_out), -0.6, 0.6, 1.0, 0.0)
plug = mr(m("SUBTRACT", dr, r_plug), -0.6, 0.6, 1.0, 0.0)
is_open = m("GREATER_THAN", wsep.outputs[2], 0.8)             # ~20 % offen
plug_eff = m("MULTIPLY", plug, m("SUBTRACT", 1.0, is_open))
ring = m("SUBTRACT", hole, plug_eff)
halo = m("MULTIPLY", mr(m("SUBTRACT", dr, m("ADD", r_out, 3.0)), -3.5, 3.5, 1.0, 0.0, "LINEAR"),
         mr(m("ABSOLUTE", m("SUBTRACT", dr, m("ADD", r_out, 3.0))), 0.0, 3.5, 1.0, 0.0))
plug_tone = m("SUBTRACT", m("MULTIPLY", wsep.outputs[0], 0.5), 0.45)  # -0,45..0,05

# --- Tafel-Tonversatz (zwei Tafeln je Kachel)
pw = node("ShaderNodeTexWhiteNoise", noise_dimensions="2D")
L.new(comb(m("FLOOR", m("MULTIPLY", v, 2.0)), a.seed, 0.0), pw.inputs["Vector"])
panel = m("MULTIPLY", m("SUBTRACT", pw.outputs["Value"], 0.5), 0.05)

# --- Albedo (Anzeige-Raum, Mittel ~0,5) -> linear (pow 2.2) fuer Base Color
alb = m("ADD", 0.5, m("MULTIPLY", cloud, a.cloud_amt))
for term, w in ((grain, a.grain_amt), (fine, 0.05), (panel, 1.0)):
    alb = m("ADD", alb, m("MULTIPLY", term, w))
for term, w in ((pores, -0.33), (groove, -0.16), (seam_tint, -0.03), (ring, -0.30), (halo, 0.02)):
    alb = m("ADD", alb, m("MULTIPLY", term, w))
alb = m("ADD", alb, m("MULTIPLY", plug_eff, m("MULTIPLY", plug_tone, 0.30)))
alb = m("ADD", alb, m("MULTIPLY", m("MULTIPLY", plug, is_open), -0.25))
alb_lin = m("POWER", m("MAXIMUM", alb, 0.0), 2.2)

# --- Height (0,5 = Flaeche)
h = m("ADD", 0.5, m("MULTIPLY", pores, -0.25))
for term, w in ((groove, -0.30), (ridge, 0.06), (hole, -0.28), (plug_eff, 0.15), (grain, 0.0006), (fine, 0.0008), (cloud, 0.002)):
    h = m("ADD", h, m("MULTIPLY", term, w))

bump = node("ShaderNodeBump"); bump.inputs["Strength"].default_value = a.bump; bump.inputs["Distance"].default_value = a.bump_dist
L.new(h, bump.inputs["Height"])
bsdf = node("ShaderNodeBsdfPrincipled")
L.new(comb(alb_lin, alb_lin, alb_lin), bsdf.inputs["Base Color"])
L.new(mr(m("ADD", pores, groove), 0.0, 1.0, 0.82, 0.95, "LINEAR"), bsdf.inputs["Roughness"])
L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
L.new(comb(h, h, h), bsdf.inputs["Emission Color"]); bsdf.inputs["Emission Strength"].default_value = 1.0
out = node("ShaderNodeOutputMaterial"); L.new(bsdf.outputs[0], out.inputs[0])
# Bake-Ziel
bimg = node("ShaderNodeTexImage"); N.active = bimg
bpy.ops.wm.save_as_mainfile(filepath=a.save)
print("@@JSON@@" + '{"ok": true, "nodes": %d, "save": "%s"}' % (len(N), a.save))
