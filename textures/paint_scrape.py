"""T6b tunnel_paint_scrape: Schrammen an Lackmarkierungen, bei denen Farbe verschmiert und teilweise abgetragen ist
(Joe 19.11.). Kachel 2,0 x 2,0 m = 1024 px, beidseitig nahtlos (passt zu T6).
Schrammen sind analytisch je Band-Zelle (Hoehe ~10 cm): Zelle aktiv per Hash, Start x0, Laenge log-verteilt 5 cm - 1,6 m, Dicke 2-8 cm,
Form wie ein Komet (scharfer Anfang, laeuft in Fahrtrichtung +x aus), Rand mit Rauschen ausgefranst.
Masken (MASK_<name> fuer bake_masks.py):
  abrade   R  Teilabtrag in der Schramme: gestreift laengs (1 = Lack bis auf den Beton weg)
  smear    G  Verschmier-Weg 0..1: waechst entlang der Schramme; im Shader das Lackmuster um smear * smear_len (m)
              gegen die Fahrtrichtung verschieben -> Farbe wird mitgezogen (Gelb ins Schwarz und umgekehrt)
  transfer B  Fremdabrieb (Reifen/Fremdlack, dunkel), nur in einem Teil der Schrammen
  edge     A  Kantenrauschen fuer die Streifenkanten (0,5 = neutral), siehe unten; zone (Schrammzone) nur als Pruefmaske
  height     Rillen der Schramme (Emission)
  blender-gpu -b --factory-startup -P paint_scrape.py -- --save out.blend [--seed 23] [--density 0.22]"""
import argparse, os, sys
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nodekit as K
from nodekit import m, mr, sstep, comb

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--save", required=True); ap.add_argument("--seed", type=float, default=23.0)
ap.add_argument("--density", type=float, default=0.42, help="Anteil aktiver Band-Zellen")
ap.add_argument("--len-min", type=float, default=0.05, help="kuerzeste Schramme (m)"); ap.add_argument("--len-max", type=float, default=1.6, help="laengste Schramme (m)")
a = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_plane_add(size=2.0)
ob = bpy.context.active_object; ob.name = "T6b_Scrape"
mat = bpy.data.materials.new("M_T6b"); ob.data.materials.append(mat)
u, v = K.init(mat, a.seed)
P0 = K.P0
P1, off1 = K.warp(P0, 3.0, 0.06)

NB = 20.0   # Band-Zellen in v (je 10 cm)


def scrape_layer(phase, w_off):
    """Eine Lage Schrammen; phase verschiebt das Bandraster (zwei Lagen -> Ueberlappungen moeglich)."""
    vb = m("ADD", m("MULTIPLY", v, NB), phase)
    cell = m("FLOOR", vb)
    fy = m("FRACT", vb)                                   # 0..1 in der Zelle
    val, col = K.white(comb(cell, K.SEED, w_off))
    r1, r2, r3 = K.split(col)
    val2, col2 = K.white(comb(cell, K.SEED, w_off + 0.5))
    q1, q2, q3 = K.split(col2)
    active = m("LESS_THAN", r1, a.density)
    # Laenge log-verteilt (Joe 19.11.): L = Lmin * (Lmax/Lmin)^r -> viele kurze, wenige sehr lange; Kachel 2 m -> uv = m / 2
    lmin, lmax = a.len_min / 2.0, a.len_max / 2.0
    Lr = m("MULTIPLY", lmin, m("POWER", lmax / lmin, r3))
    dx = m("FRACT", m("SUBTRACT", u, r2))
    t = m("DIVIDE", dx, Lr)                                              # 0..1 entlang der Schramme
    inside = m("LESS_THAN", t, 1.0)
    thick = m("ADD", 0.16, m("MULTIPLY", q1, 0.34))                     # halbe Dicke 0,16..0,5 der 10-cm-Zelle = 1,6..5 cm
    cy = m("ADD", 0.5, m("MULTIPLY", m("SUBTRACT", q2, 0.5), 0.3))
    slope = m("MULTIPLY", m("SUBTRACT", q3, 0.5), 0.25)                 # leicht schraeg
    yrel = m("SUBTRACT", m("SUBTRACT", fy, cy), m("MULTIPLY", t, slope))
    # Kometenform: scharfer Anfang (t klein) breit, laeuft schmaler aus; Rand ausgefranst
    width = m("MULTIPLY", thick, m("SUBTRACT", 1.0, m("MULTIPLY", t, 0.55)))
    fray, _ = K.noise_at(P1, 14.0, detail=4.0, rough=0.6, w_off=w_off + 3.0)
    width = m("MULTIPLY", width, m("ADD", 0.75, m("MULTIPLY", fray, 0.5)))
    across = mr(m("ABSOLUTE", yrel), m("MULTIPLY", width, 0.6), width, 1.0, 0.0)
    start = mr(t, 0.0, 0.04, 0.0, 1.0)                                   # harter Ansatz
    tail = mr(t, 0.55, 1.0, 1.0, 0.0)                                    # laeuft aus
    shape = m("MULTIPLY", m("MULTIPLY", m("MULTIPLY", across, start), m("MULTIPLY", tail, inside)), active)
    return shape, t, val2


s1, t1, h1 = scrape_layer(0.0, 61.0)
s2, t2, h2 = scrape_layer(0.5, 62.0)
zone = m("MAXIMUM", s1, s2)
sel = m("GREATER_THAN", s1, s2)                                         # welche Lage dominiert
tz = m("ADD", m("MULTIPLY", t1, sel), m("MULTIPLY", t2, m("SUBTRACT", 1.0, sel)))
hz = m("ADD", m("MULTIPLY", h1, sel), m("MULTIPLY", h2, m("SUBTRACT", 1.0, sel)))

# Laengsstreifen in der Schramme (stark in x gestreckt) -> gestreifter Teilabtrag
st, _ = K.noise_at(K.torus(0.04, 1.0), 70.0, detail=3.0, rough=0.6, w_off=71.0)
streaks = sstep(st, 0.45, 0.62)
abrade = m("MULTIPLY", zone, m("ADD", m("MULTIPLY", streaks, 0.75), m("MULTIPLY", mr(tz, 0.0, 0.3, 0.4, 0.0), 1.0)))  # am Ansatz staerker
abrade = m("MINIMUM", abrade, 1.0)
# Verschmier-Weg: waechst entlang der Schramme, in den Streifen etwas mehr
smear = m("MULTIPLY", zone, m("MULTIPLY", sstep(tz, 0.0, 0.8), m("ADD", 0.7, m("MULTIPLY", streaks, 0.3))))
# Fremdabrieb: nur ~40 % der Schrammen, dunkel, streifig, eher in der Mitte/hinten
tr_on = m("LESS_THAN", hz, 0.4)
st2, _ = K.noise_at(K.torus(0.05, 1.0), 45.0, detail=3.0, w_off=72.0)
transfer = m("MULTIPLY", m("MULTIPLY", zone, tr_on), m("MULTIPLY", sstep(st2, 0.4, 0.65), mr(tz, 0.1, 0.5, 0.3, 1.0)))

h = m("SUBTRACT", 0.5, m("MULTIPLY", abrade, 0.05))
h = m("SUBTRACT", h, m("MULTIPLY", m("MULTIPLY", zone, streaks), 0.015))

# Kantenrauschen fuer die Lackstreifen (Joe 19.11.: "Kanten gestochen scharf, modellierte Unschaerfe"):
# 0,5 = neutral; Welligkeit wie Abdeckband (~2-3 cm) + Ausfransen in die Betonporen (~3 mm). Im Shader:
#   t_edge = t + (edge - 0.5) * edge_shift;  Breite w = w0 + w1 * abs(edge - 0.5) * 2  (Sprühnebel variabel)
wob, _ = K.noise_at(P0, 12.0, detail=2.0, rough=0.5, w_off=81.0)
fray, _ = K.noise_at(P1, 90.0, detail=4.0, rough=0.7, w_off=82.0)
edge = m("MINIMUM", m("MAXIMUM", m("ADD", 0.5, m("ADD", m("MULTIPLY", m("SUBTRACT", wob, 0.5), 1.1), m("MULTIPLY", m("SUBTRACT", fray, 0.5), 0.7))), 0.0), 1.0)
for nm, sck in (("abrade", abrade), ("smear", smear), ("transfer", transfer), ("edge", edge), ("zone", zone)):
    K.mask_node(nm, sck)
K.finish(h)
bpy.ops.wm.save_as_mainfile(filepath=a.save)
print("@@JSON@@" + '{"ok": true, "nodes": %d, "save": "%s"}' % (len(K.N), a.save))
