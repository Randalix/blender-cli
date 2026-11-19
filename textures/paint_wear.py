"""T6 tunnel_paint_wear: Verwitterungs-Masken fuer gelb-schwarze Lackmarkierungen (Neon Getaway, Auftrag tunnel/Joe 19.11.).
Kachel 2,0 x 2,0 m = 1024 px (1,95 mm/px), beidseitig nahtlos (4D-Rauschen auf dem Clifford-Torus, Zeilen aus fract(UV)).
Masken (linear 0..1), als MASK_<name>-Nodes fuer bake_masks.py:
  chip    R  Lack abgeplatzt/abgeblaettert (1 = Lack weg): scharfe Blaetter/Chips 2 mm - 8 cm, gehaeuft in Nestern
  scratch G  Abrieb/Kratzer: ueberwiegend waagerecht, feine Scheuerspuren + einzelne Schrammen 20-80 cm
  fade    B  Ausbleichen/Kreiden: weiche, grossflaechige Wolken
  dirt    A  Schmutz-Haftung: feiner Grauschleier, Poren, Spritzer, Schmutz an Abplatzer-Raendern
  height     Lackschicht (Stufe an Abplatzern, Rillen in Kratzern) auf der Emission
Keine Hoehenverteilung eingebacken (macht der Shader).
Voronoi-Zellgroesse ~ 0,318 m / Scale (R = 1, Umfang 2π = 2 m).
  blender-gpu -b --factory-startup -P paint_wear.py -- --save out.blend [--seed 11] [--chip 1] [--scratch 1] [--dirt 1]"""
import argparse, os, sys
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nodekit as K
from nodekit import m, mr, sstep, comb, vmath

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--save", required=True); ap.add_argument("--seed", type=float, default=11.0)
ap.add_argument("--chip", type=float, default=1.0, help="Menge Abplatzer (verschiebt die Schwelle)")
ap.add_argument("--scratch", type=float, default=1.0); ap.add_argument("--dirt", type=float, default=1.0)
a = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_plane_add(size=2.0)
ob = bpy.context.active_object; ob.name = "T6_Paint"
mat = bpy.data.materials.new("M_T6"); ob.data.materials.append(mat)
u, v = K.init(mat, a.seed)
P0 = K.P0
P1, off1 = K.warp(P0, 2.0, 0.10)
P2, off2 = K.warp(P1, 9.0, 0.035, w_off=5.0)

# ---------------- R: Abplatzer ----------------
nest = sstep(K.noise_at(P1, 1.3, detail=3.0, w_off=11.0)[0], 0.42, 0.68)            # Nester (~25 cm)
# grosse Blaetter: hochdetailliertes, gewarptes Rauschen scharf geschwellt; Nester senken die Schwelle
cn, _ = K.noise_at(P2, 5.0, detail=8.0, rough=0.70, w_off=12.0)
thr = m("SUBTRACT", 0.73, m("MULTIPLY", m("ADD", m("MULTIPLY", nest, 0.22), 0.0), a.chip))
chip_big = mr(cn, thr, m("ADD", thr, 0.006), 0.0, 1.0, "LINEAR")
# Chips: Voronoi-Zellen, nur ein Teil lebt (Zell-Hash < Nest-Dichte), Radius schief verteilt


def chips(scale, keep_base, keep_nest, rmax, power, w_off):
    d, col = K.voronoi_at(P2, scale, w_off=w_off)
    r1, r2, _ = K.split(col)
    alive = m("LESS_THAN", r1, m("ADD", keep_base, m("MULTIPLY", nest, keep_nest)))
    rad = m("MULTIPLY", m("POWER", r2, power), rmax)
    return m("MULTIPLY", mr(m("SUBTRACT", d, rad), -0.01, 0.01, 1.0, 0.0, "LINEAR"), alive)


chip_mid = chips(14.0, 0.02, 0.45, 0.42, 1.5, 13.0)     # ~1-3 cm
chip_small = chips(55.0, 0.03, 0.30, 0.40, 2.0, 14.0)   # ~2-6 mm
chip_tiny = chips(130.0, 0.02, 0.20, 0.38, 2.5, 15.0)   # ~1-2 mm
chip = m("MINIMUM", m("MAXIMUM", m("MAXIMUM", chip_big, chip_mid), m("MAXIMUM", chip_small, chip_tiny)), 1.0)
chip_soft = m("MAXIMUM", mr(cn, m("SUBTRACT", thr, 0.03), thr, 0.0, 1.0), m("MULTIPLY", chip, 1.0))   # Rand-Zone

# ---------------- G: Kratzer/Abrieb (waagerecht) ----------------
# feine Scheuerspuren: ridged Rauschen auf stark in x gestrecktem Torus -> lange duenne waagerechte Linien
sc_n, _ = K.noise_at(K.torus(0.05, 1.0), 26.0, detail=3.0, rough=0.6, w_off=21.0)
ridge = mr(m("POWER", m("SUBTRACT", 1.0, m("ABSOLUTE", m("SUBTRACT", m("MULTIPLY", sc_n, 2.0), 1.0))), 60.0), 0.25, 0.6, 0.0, 1.0)
gate = sstep(K.noise_at(P1, 3.0, detail=2.0, w_off=22.0)[0], 0.52, 0.64)
scuff = m("MULTIPLY", m("MULTIPLY", ridge, gate), 0.7)


def rows(nrow, chance, lmin, lmax, width, w_off):
    """Analytische Kratzer je Zeile: Zeile aktiv per Hash, Start x0, Laenge L (uv), Enden ausgeduennt."""
    vw = m("ADD", v, m("MULTIPLY", m("SINE", m("ADD", m("MULTIPLY", u, K.TAU * 2.0), w_off)), 0.0012))   # leichtes Wandern
    row = m("FLOOR", m("MULTIPLY", vw, nrow))
    val, col = K.white(comb(row, K.SEED, w_off))
    r1, r2, r3 = K.split(col)
    active = m("LESS_THAN", r1, chance)
    Lr = m("ADD", lmin, m("MULTIPLY", m("POWER", r3, 2.0), lmax - lmin))
    dx = m("FRACT", m("SUBTRACT", u, r2))
    inside = m("LESS_THAN", dx, Lr)
    ends = m("MINIMUM", m("DIVIDE", m("MINIMUM", dx, m("SUBTRACT", Lr, dx)), m("MULTIPLY", Lr, 0.25)), 1.0)
    fy = m("ABSOLUTE", m("SUBTRACT", m("FRACT", m("MULTIPLY", vw, nrow)), 0.5))
    line = mr(fy, 0.0, width, 1.0, 0.0)
    return m("MULTIPLY", m("MULTIPLY", m("MULTIPLY", line, active), m("MULTIPLY", inside, ends)), m("ADD", 0.7, m("MULTIPLY", val, 0.3)))


scr_fine = rows(520.0, 0.16, 0.02, 0.15, 0.30, 31.0)    # Zeile ~3,8 mm, kurze Kratzer 4-30 cm
scr_long = rows(160.0, 0.12, 0.10, 0.40, 0.22, 32.0)    # Schrammen 20-80 cm, etwas breiter
scratch = m("MULTIPLY", m("MINIMUM", m("MAXIMUM", m("MAXIMUM", scuff, scr_fine), scr_long), 1.0), a.scratch)

# ---------------- B: Ausbleichen ----------------
fade_raw, _ = K.noise_at(P1, 0.9, detail=4.0, rough=0.5, w_off=41.0)
fade_mid, _ = K.noise_at(P1, 4.0, detail=3.0, w_off=42.0)
fade = m("MINIMUM", m("MAXIMUM", m("ADD", sstep(fade_raw, 0.35, 0.72), m("MULTIPLY", m("SUBTRACT", fade_mid, 0.5), 0.25)), 0.0), 1.0)

# ---------------- A: Schmutz-Haftung ----------------
veil, _ = K.noise_at(P2, 30.0, detail=4.0, rough=0.6, w_off=51.0)
veil = sstep(veil, 0.35, 0.75, 0.0, 0.45)
pd, pc = K.voronoi_at(P0, 140.0, w_off=52.0)
pr1, pr2, _ = K.split(pc)
pores = m("MULTIPLY", mr(m("SUBTRACT", pd, m("MULTIPLY", pr2, 0.30)), -0.02, 0.02, 1.0, 0.0, "LINEAR"), m("LESS_THAN", pr1, 0.25))
spd, spc = K.voronoi_at(P1, 25.0, w_off=53.0)
sr1, sr2, _ = K.split(spc)
splat = m("MULTIPLY", mr(m("SUBTRACT", spd, m("MULTIPLY", m("POWER", sr2, 3.0), 0.35)), -0.02, 0.02, 1.0, 0.0, "LINEAR"),
          m("LESS_THAN", sr1, m("MULTIPLY", sstep(K.noise_at(P0, 1.6, detail=2.0, w_off=54.0)[0], 0.5, 0.7), 0.5)))
edge_dirt = m("MULTIPLY", m("SUBTRACT", chip_soft, chip), 0.8)
dirt = m("MULTIPLY", m("MINIMUM", m("MAXIMUM", m("MAXIMUM", veil, m("MULTIPLY", pores, 0.7)), m("MAXIMUM", m("MULTIPLY", splat, 0.8), edge_dirt)), 1.0), a.dirt)

# ---------------- Hoehe: Lackschicht ----------------
h = m("ADD", 0.5, m("MULTIPLY", m("SUBTRACT", 1.0, chip), 0.08))          # Lack 0,58, Beton 0,50 -> Stufe
h = m("SUBTRACT", h, m("MULTIPLY", scratch, 0.025))
h = m("ADD", h, m("MULTIPLY", m("SUBTRACT", veil, 0.2), 0.004))

for nm, s in (("chip", chip), ("scratch", scratch), ("fade", fade), ("dirt", dirt)):
    K.mask_node(nm, s)
K.finish(h)
bpy.ops.wm.save_as_mainfile(filepath=a.save)
print("@@JSON@@" + '{"ok": true, "nodes": %d, "save": "%s"}' % (len(K.N), a.save))
