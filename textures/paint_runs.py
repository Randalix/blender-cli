"""Siff-Laeufe auf Lackmarkierungen (Joe 19.11.: "noch ein bisschen Siff, der runterlaeuft"), Kachel 2 x 2 m, nahtlos.
Analytisch je Spalten-Zelle (in u): Zelle aktiv per Hash, Ansatz v_s, Laenge log-verteilt, Breite, Maeander;
Lauf geht nach UNTEN (Bild-unten = kleineres v in Blender-UV), verjuengt sich, am Ansatz am dunkelsten,
gelegentlich Tropfen-Knubbel am Ende. Dazu wenige breite, schwache Schmutzschleier.
Ausgabe MASK_runs (0..1). Wird in T6.B gepackt (Kanal war Ausbleichen, von Joe gestrichen).
  blender-gpu -b --factory-startup -P paint_runs.py -- --save out.blend [--seed 31] [--density 0.3]"""
import argparse, math, os, sys
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nodekit as K
from nodekit import m, mr, sstep, comb

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--save", required=True); ap.add_argument("--seed", type=float, default=31.0)
ap.add_argument("--density", type=float, default=0.30)
ap.add_argument("--len-min", type=float, default=0.05); ap.add_argument("--len-max", type=float, default=1.0)
a = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_plane_add(size=2.0)
ob = bpy.context.active_object; ob.name = "T6_Runs"
mat = bpy.data.materials.new("M_T6runs"); ob.data.materials.append(mat)
u, v = K.init(mat, a.seed)
P0 = K.P0
TILE = 2.0


def runs(ncol, phase, wmin, wmax, chance, inten, w_off, blob=True):
    """ncol Spalten je Kachel; Breiten in m; liefert Laufmaske."""
    ub = m("ADD", m("MULTIPLY", u, ncol), phase)
    col = m("FLOOR", ub)
    fx = m("FRACT", ub)                                                    # 0..1 in der Spalte
    _, c1 = K.white(comb(col, K.SEED, w_off)); r1, r2, r3 = K.split(c1)
    _, c2 = K.white(comb(col, K.SEED, w_off + 0.5)); q1, q2, q3 = K.split(c2)
    active = m("LESS_THAN", r1, chance)
    v_s = r2                                                               # Ansatz (uv)
    lmin, lmax = a.len_min / TILE, a.len_max / TILE
    Lr = m("MULTIPLY", lmin, m("POWER", lmax / lmin, r3))                  # log-verteilt
    dy = m("FRACT", m("SUBTRACT", v_s, v))                                 # Strecke unter dem Ansatz (uv, periodisch)
    t = m("DIVIDE", dy, Lr)
    inside = m("LESS_THAN", t, 1.0)
    # Breite in Spalten-Einheiten; Maeander: Sinus ueber die Laufstrecke + Drift
    w = m("DIVIDE", m("ADD", wmin, m("MULTIPLY", q1, wmax - wmin)), TILE / ncol)
    xc = m("ADD", m("ADD", 0.5, m("MULTIPLY", m("SUBTRACT", q2, 0.5), 0.3)),
           m("ADD", m("MULTIPLY", m("SINE", m("ADD", m("MULTIPLY", dy, 90.0), m("MULTIPLY", q3, 6.28))), 0.06),
                    m("MULTIPLY", m("MULTIPLY", dy, m("SUBTRACT", q3, 0.5)), 2.0)))
    wt = m("MULTIPLY", w, m("SUBTRACT", 1.0, m("MULTIPLY", t, 0.6)))      # verjuengt sich
    across = mr(m("ABSOLUTE", m("SUBTRACT", fx, xc)), m("MULTIPLY", wt, 0.4), wt, 1.0, 0.0)
    # bis zum Ende sichtbar (sonst Luecke vor dem Knubbel -> "!"), am Ansatz am dunkelsten
    along = m("MULTIPLY", mr(t, 0.0, 0.03, 0.4, 1.0), m("ADD", 0.35, m("MULTIPLY", m("POWER", m("MAXIMUM", m("SUBTRACT", 1.0, t), 0.0), 0.8), 0.65)))
    shape = m("MULTIPLY", m("MULTIPLY", across, along), m("MULTIPLY", inside, active))
    if blob:   # Knubbel am Ende bei ~40 %
        has = m("LESS_THAN", q3, 0.4)
        ddx = m("DIVIDE", m("SUBTRACT", fx, xc), 1.0)
        ddy = m("MULTIPLY", m("SUBTRACT", dy, Lr), ncol)                  # uv -> Spalten-Einheiten
        d = m("SQRT", m("ADD", m("MULTIPLY", ddx, ddx), m("MULTIPLY", ddy, ddy)))
        bl = mr(d, m("MULTIPLY", w, 0.7), m("MULTIPLY", w, 1.05), 0.55, 0.0)
        shape = m("MAXIMUM", shape, m("MULTIPLY", m("MULTIPLY", bl, has), active))
    return m("MULTIPLY", shape, inten)


r_a = runs(60.0, 0.0, 0.003, 0.012, a.density, 1.0, 11.0)
r_b = runs(60.0, 0.5, 0.003, 0.010, a.density * 0.7, 0.85, 12.0)
veil = runs(14.0, 0.25, 0.03, 0.08, 0.40, 0.5, 13.0, blob=False)        # breite, schwache Schleier
jit, _ = K.noise_at(P0, 30.0, detail=3.0, w_off=14.0)                     # leichte Fleckigkeit im Lauf
runs_all = m("MULTIPLY", m("MINIMUM", m("MAXIMUM", m("MAXIMUM", r_a, r_b), veil), 1.0), m("ADD", 0.75, m("MULTIPLY", jit, 0.5)))
runs_all = m("MINIMUM", runs_all, 1.0)
K.mask_node("runs", runs_all)
K.finish(m("ADD", 0.5, 0.0))
bpy.ops.wm.save_as_mainfile(filepath=a.save)
print("@@JSON@@" + '{"ok": true, "nodes": %d, "save": "%s"}' % (len(K.N), a.save))
