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
ap.add_argument("--cloud-amt", type=float, default=4.0); ap.add_argument("--bump-dist", type=float, default=0.004); ap.add_argument("--grain-amt", type=float, default=0.03)
ap.add_argument("--warp", type=float, default=0.12); ap.add_argument("--meso-amt", type=float, default=0.07)
ap.add_argument("--grain-warp", type=float, default=0.04); ap.add_argument("--dbg", default="", help="Diagnose: einzelne Komponente auf die Emission legen (meso, stain, laitance, cloud, fine, pores, honey, crack, bleed, grain)"); ap.add_argument("--meso-dist", type=float, default=0.25); ap.add_argument("--meso-detail", type=float, default=3.0); ap.add_argument("--laitance-amt", type=float, default=0.035); ap.add_argument("--stain-amt", type=float, default=0.045)
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


R = 1.0  # Torusradius -> Umfang 2π entspricht 2,4 m; Noise-Scale s ~ Strukturgroesse 2,4 m / (2π s)


# ---------- v2-Helfer: Noise/Voronoi an beliebigem 4D-Punkt, Domain Warping (Gemini-Recherche 19.11.) ----------
def vmath(op, x, y=None, sc=None):
    n = node("ShaderNodeVectorMath", operation=op); L.new(x, n.inputs[0])
    if y is not None:
        if isinstance(y, (tuple, list)): n.inputs[1].default_value = y
        else: L.new(y, n.inputs[1])
    if sc is not None: inp(n, 3, sc)  # SCALE-Faktor
    return n.outputs[0]


def noise_at(P, scale, detail=4.0, rough=0.5, dist=0.0, lac=2.0, w_off=0.0):
    vec, w = P
    n = node("ShaderNodeTexNoise", noise_dimensions="4D"); L.new(vec, n.inputs["Vector"])
    L.new(m("ADD", w, w_off) if w_off else w, n.inputs["W"])
    inp(n, n.inputs.find("Scale"), scale); inp(n, n.inputs.find("Detail"), detail)
    inp(n, n.inputs.find("Roughness"), rough); inp(n, n.inputs.find("Distortion"), dist); inp(n, n.inputs.find("Lacunarity"), lac)
    return n.outputs["Fac"], n.outputs["Color"]


def voronoi_at(P, scale, feature="F1", rand=1.0, w_off=0.0):
    vec, w = P
    n = node("ShaderNodeTexVoronoi", voronoi_dimensions="4D", feature=feature, distance="EUCLIDEAN")
    L.new(vec, n.inputs["Vector"]); L.new(m("ADD", w, w_off) if w_off else w, n.inputs["W"])
    inp(n, n.inputs.find("Scale"), scale); n.inputs["Randomness"].default_value = rand
    return n.outputs["Distance"], n.outputs.get("Color")


def warp(P, scale, amp, w_off=0.0, detail=3.0):
    """P + amp*(noise_color-0.5)*2 (Vektor) und W + amp*(fac-0.5)*2 -> bleibt periodisch."""
    fac, col = noise_at(P, scale, detail=detail, w_off=w_off)
    off = vmath("SCALE", vmath("SUBTRACT", col, (0.5, 0.5, 0.5)), sc=2 * amp)
    return vmath("ADD", P[0], off), m("ADD", P[1], m("MULTIPLY", m("SUBTRACT", fac, 0.5), 2 * amp)), off


def sstep(x, a0, a1, b0=0.0, b1=1.0):
    return mr(x, a0, a1, b0, b1, "SMOOTHERSTEP")


P0 = torus(R, R)
# Zweistufiges Domain Warping (Quilez): grob, dann fein auf dem gewarpten Punkt
P1v, P1w, off1 = warp(P0, 2.2, a.warp)
P1 = (P1v, P1w)
P2v, P2w, off2 = warp(P1, 7.0, a.warp * 0.35, w_off=5.0)
P2 = (P2v, P2w)

# Je Tafel eigener W-Versatz (Diskontinuitaet liegt genau auf den Stoessen v=0/0,5 -> unsichtbar)
pw = node("ShaderNodeTexWhiteNoise", noise_dimensions="2D")
L.new(comb(m("FLOOR", m("MULTIPLY", v, 2.0)), a.seed, 0.0), pw.inputs["Vector"])
panel_r = pw.outputs["Value"]
panel = m("MULTIPLY", m("SUBTRACT", panel_r, 0.5), 0.05)
Pp = (P2v, m("ADD", P2w, m("MULTIPLY", panel_r, 13.0)))

# ---------- Masken-Ketten (1): grobe Zonen steuern Scale/Distortion/Dichte ----------
zoneA, _ = noise_at(P1, 1.1, detail=2.0)              # ~0,35 m Zonen
zoneB, _ = noise_at(P1, 1.7, detail=2.0, w_off=21.0)
zoneC, _ = noise_at(P0, 0.8, detail=1.0, w_off=33.0)  # sehr grob: Porennester

# ---------- Wolken: Krea-Kachel, UV ueber periodischen Warp verschoben (bleibt nahtlos) ----------
sepo = node("ShaderNodeSeparateXYZ"); L.new(off1, sepo.inputs[0])
uvw = comb(m("ADD", u, m("MULTIPLY", sepo.outputs[0], 0.06)), m("ADD", v, m("MULTIPLY", sepo.outputs[1], 0.06)), 0.0)
img = node("ShaderNodeTexImage", extension="REPEAT", interpolation="Cubic")
img.image = bpy.data.images.load(a.cloud); img.image.colorspace_settings.name = "Non-Color"
L.new(uvw, img.inputs["Vector"])
rgb2bw = node("ShaderNodeRGBToBW"); L.new(img.outputs["Color"], rgb2bw.inputs[0])
cloud = m("SUBTRACT", rgb2bw.outputs[0], 0.636)

# Mittlere Fleckung: Scale und Distortion von Zonen gesteuert, Histogramm zu Plateaus (4)
# Scale NICHT raeumlich steuern: variable Frequenz verschiebt die Phase (P·∇scale) -> Marmor-Wirbel (Befund 19.11.).
# Stattdessen zwei feste Skalen, per Zonenmaske ueberblendet (Masken-Kette ohne Phasenfehler).
mesoA, _ = noise_at(Pp, 11.0, detail=a.meso_detail, rough=0.5, dist=m("MULTIPLY", sstep(zoneB, 0.3, 0.7), a.meso_dist))
mesoB, _ = noise_at(Pp, 27.0, detail=a.meso_detail, rough=0.5, w_off=17.0)
mix = node("ShaderNodeMix", data_type="FLOAT"); L.new(sstep(zoneA, 0.35, 0.65), mix.inputs[0])
L.new(mesoA, mix.inputs[2]); L.new(mesoB, mix.inputs[3]); meso_raw = mix.outputs[0]
meso = m("SUBTRACT", sstep(meso_raw, 0.30, 0.72), 0.5)          # Plateaus statt Glocke (weich, sonst Konturbaender)
# Schlaemme/Laitance: hellere, glattere Flaechen (unterdrueckt Poren)
laitance = sstep(zoneB, 0.58, 0.74)
# Trennmittel-Flecken: weiche dunkle Blotches, gewarpt
stain_raw, _ = noise_at(P2, 1.9, detail=3.0, rough=0.6, w_off=44.0)
stain = sstep(stain_raw, 0.57, 0.68)

# ---------- Stoesse: Abstand in px ----------
du = m("MULTIPLY", m("MINIMUM", u, m("SUBTRACT", 1.0, u)), 1024.0)
fv = m("FRACT", m("MULTIPLY", v, 2.0))
dv = m("MULTIPLY", m("MINIMUM", fv, m("SUBTRACT", 1.0, fv)), 512.0)
dj = m("MINIMUM", du, dv)
groove = mr(dj, 0.4, 1.9, 1.0, 0.0)
ridge = m("MULTIPLY", mr(dj, 1.6, 2.4, 0.0, 1.0), mr(dj, 2.6, 3.6, 1.0, 0.0))
jn, _ = noise_at(P1, 9.0, detail=3.0, w_off=55.0)               # Ausdruck entlang der Fuge
ridge = m("MULTIPLY", ridge, sstep(jn, 0.35, 0.65, 0.15, 1.0))
# Bluten/Schlempe: 1-5 cm Band, entlang der Fuge stark schwankend (5)
bleed = m("MULTIPLY", mr(dj, 2.0, mr(jn, 0.3, 0.7, 6.0, 22.0, "LINEAR"), 1.0, 0.0), sstep(jn, 0.45, 0.7))
near_j = mr(dj, 4.0, 40.0, 1.0, 0.0, "SMOOTHERSTEP")            # Naehe fuer Kiesnester

# ---------- Poren (3): drei Groessen, Dichte clustert ueber Masken, an Stoessen dichter ----------
dens = m("MAXIMUM", sstep(zoneC, 0.42, 0.68), m("MULTIPLY", near_j, 0.8))
dens = m("MULTIPLY", dens, m("SUBTRACT", 1.0, m("MULTIPLY", laitance, 0.8)))
Ppore = (vmath("ADD", P0[0], vmath("SCALE", off2, sc=0.25)), P0[1])  # leicht gewarpt -> keine Rasterpunkte


def pore_layer(scale, power, rmax, w_off, dens_gain):
    d, col = voronoi_at(Ppore, scale, rand=1.0, w_off=w_off)
    sc_ = node("ShaderNodeSeparateColor"); L.new(col, sc_.inputs[0])
    rnd, keep = sc_.outputs[0], sc_.outputs[1]
    rad = m("MULTIPLY", m("POWER", rnd, power), rmax)
    alive = m("LESS_THAN", keep, m("ADD", 0.05, m("MULTIPLY", dens, dens_gain)))  # nur ein Teil der Zellen hat eine Pore
    return m("MULTIPLY", mr(m("SUBTRACT", d, rad), -0.03, 0.03, 1.0, 0.0), alive)


pin = pore_layer(110.0, 2.0, 0.40, 61.0, 0.85)    # Nadelporen ~1-2 mm
mid = pore_layer(45.0, 3.0, 0.40, 62.0, 0.55)     # Poren 2-5 mm
bug = pore_layer(16.0, 5.0, 0.38, 63.0, 0.35)     # Lunker bis ~15 mm, selten
pores = m("MAXIMUM", m("MAXIMUM", m("MULTIPLY", pin, 0.6), mid), bug)
# Kiesnester an den Stoessen: grobkoernige Zellen, nur wo Rauschen hoch
hc_mask = m("MULTIPLY", near_j, sstep(noise_at(P1, 5.0, detail=2.0, w_off=71.0)[0], 0.60, 0.72))
hc_d, _ = voronoi_at(P2, 70.0, w_off=72.0)
honey = m("MULTIPLY", hc_mask, mr(hc_d, 0.0, 0.5, 1.0, 0.0, "LINEAR"))

# ---------- Schalhaut: gestreckt + gewarpt, geriffelt (Fasern), je Tafel versetzt ----------
gP = torus(0.07, 1.0)
gPw = (vmath("ADD", gP[0], vmath("SCALE", off1, sc=a.grain_warp)), m("ADD", gP[1], m("MULTIPLY", panel_r, 7.0)))
g_raw, _ = noise_at(gPw, 10.0, detail=5.0, rough=0.6)
fiber = m("POWER", m("SUBTRACT", 1.0, m("ABSOLUTE", m("SUBTRACT", m("MULTIPLY", g_raw, 2.0), 1.0))), 10.0)  # geriffelt, duenn
grain = m("ADD", m("SUBTRACT", g_raw, 0.5), m("MULTIPLY", fiber, 0.6))
fine = m("SUBTRACT", noise_at(P0, 90.0, detail=2.0, w_off=81.0)[0], 0.5)

# ---------- Haarrisse (6): Voronoi Distance-to-Edge, gewarpt, nur in Zonen ----------
ce, _ = voronoi_at(P2, 2.6, feature="DISTANCE_TO_EDGE", w_off=91.0)
crack = m("MULTIPLY", mr(ce, 0.0, 0.012, 1.0, 0.0), sstep(zoneA, 0.66, 0.78))

# ---------- Ankerloecher (wie v1) ----------
cu = m("SUBTRACT", m("FRACT", m("MULTIPLY", u, 4.0)), 0.5); cv = m("SUBTRACT", m("FRACT", m("MULTIPLY", v, 4.0)), 0.5)
dr = m("MULTIPLY", m("SQRT", m("ADD", m("MULTIPLY", cu, cu), m("MULTIPLY", cv, cv))), 256.0)  # px
cell = comb(m("FLOOR", m("MULTIPLY", u, 4.0)), m("FLOOR", m("MULTIPLY", v, 4.0)), a.seed)
wn = node("ShaderNodeTexWhiteNoise", noise_dimensions="3D"); L.new(cell, wn.inputs["Vector"])
wsep = node("ShaderNodeSeparateColor"); L.new(wn.outputs["Color"], wsep.inputs[0])
r_out = m("ADD", 5.0, m("MULTIPLY", wsep.outputs[0], 1.2))
r_plug = m("SUBTRACT", r_out, m("ADD", 1.0, m("MULTIPLY", wsep.outputs[1], 0.8)))
hole = mr(m("SUBTRACT", dr, r_out), -0.6, 0.6, 1.0, 0.0)
plug = mr(m("SUBTRACT", dr, r_plug), -0.6, 0.6, 1.0, 0.0)
is_open = m("GREATER_THAN", wsep.outputs[2], 0.8)
plug_eff = m("MULTIPLY", plug, m("SUBTRACT", 1.0, is_open))
ring = m("SUBTRACT", hole, plug_eff)
halo = m("MULTIPLY", mr(m("SUBTRACT", dr, m("ADD", r_out, 3.0)), -3.5, 3.5, 1.0, 0.0, "LINEAR"),
         mr(m("ABSOLUTE", m("SUBTRACT", dr, m("ADD", r_out, 3.0))), 0.0, 3.5, 1.0, 0.0))
plug_tone = m("SUBTRACT", m("MULTIPLY", wsep.outputs[0], 0.5), 0.45)

# ---------- Albedo (Anzeige-Raum, Mittel ~0,5) ----------
alb = m("ADD", 0.5, m("MULTIPLY", cloud, a.cloud_amt))
for term, w in ((meso, a.meso_amt), (laitance, a.laitance_amt), (stain, -a.stain_amt), (grain, a.grain_amt), (fine, 0.04), (panel, 1.0),
                (pores, -0.30), (honey, -0.10), (crack, -0.07), (groove, -0.16), (bleed, -0.05), (ring, -0.30), (halo, 0.02)):
    alb = m("ADD", alb, m("MULTIPLY", term, w))
alb = m("ADD", alb, m("MULTIPLY", plug_eff, m("MULTIPLY", plug_tone, 0.30)))
alb = m("ADD", alb, m("MULTIPLY", m("MULTIPLY", plug, is_open), -0.25))
alb_lin = m("POWER", m("MAXIMUM", alb, 0.0), 2.2)

# ---------- Height (0,5 = Flaeche): Plateau, Tiefen nur fuer Poren/Fugen/Risse/Nester ----------
h = m("ADD", 0.5, m("MULTIPLY", pores, -0.25))
for term, w in ((groove, -0.30), (ridge, 0.06), (hole, -0.28), (plug_eff, 0.15), (honey, -0.10), (crack, -0.08),
                (grain, m("MULTIPLY", a.grain_amt, 0.04)), (fine, m("MULTIPLY", m("SUBTRACT", 1.0, laitance), 0.0012)), (meso, 0.003), (bleed, 0.004)):
    h = m("ADD", h, m("MULTIPLY", term, w))

bump = node("ShaderNodeBump"); bump.inputs["Strength"].default_value = a.bump; bump.inputs["Distance"].default_value = a.bump_dist
L.new(h, bump.inputs["Height"])
bsdf = node("ShaderNodeBsdfPrincipled")
L.new(comb(alb_lin, alb_lin, alb_lin), bsdf.inputs["Base Color"])
L.new(mr(m("SUBTRACT", m("ADD", m("ADD", pores, groove), honey), m("MULTIPLY", laitance, 0.5)), -0.5, 1.0, 0.72, 0.95, "LINEAR"), bsdf.inputs["Roughness"])
L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
dbg_terms = {"meso": meso, "stain": stain, "laitance": laitance, "cloud": cloud, "fine": fine, "pores": pores, "honey": honey,
             "crack": crack, "bleed": bleed, "grain": grain, "alb": alb}
if a.dbg:
    t = dbg_terms[a.dbg]
    if a.dbg in ("meso", "cloud", "fine", "grain"): t = m("ADD", t, 0.5)
    h = t
L.new(comb(h, h, h), bsdf.inputs["Emission Color"]); bsdf.inputs["Emission Strength"].default_value = 1.0
out = node("ShaderNodeOutputMaterial"); L.new(bsdf.outputs[0], out.inputs[0])
# Bake-Ziel
bimg = node("ShaderNodeTexImage"); N.active = bimg
bpy.ops.wm.save_as_mainfile(filepath=a.save)
print("@@JSON@@" + '{"ok": true, "nodes": %d, "save": "%s"}' % (len(N), a.save))
