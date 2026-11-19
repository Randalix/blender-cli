"""Gemeinsame Node-Helfer fuer kachelbare Blender-Shader (4D-Rauschen auf dem flachen Clifford-Torus).
Nutzung im Builder:
    import nodekit as K
    K.init(material, seed)          # leert den Node-Baum, legt UV an
    f, col = K.noise_at(K.P0, 3.0)  # Rauschen an einem 4D-Punkt (vec, w)
Fallstricke (Befunde 19.11., siehe Wiki „Prozedurales Rauschen natürlicher machen — Beton"):
- Scale nie raeumlich steuern (Phasenfehler -> Marmor-Wirbel); feste Skalen per Maske mischen.
- Interne Distortion > ~0,3 erzeugt Wirbel; Domain Warping ueber warp() nutzen.
- Ridged (1-|2n-1|) zeichnet Konturlinien des Rauschens - fuer Kratzer gewollt, sonst nur schwach."""
import math

N = L = None
SEED = 0.0
U = V = UVsock = None
P0 = None
TAU = 2 * math.pi
_X = [0]


def init(mat, seed=7.0):
    global N, L, SEED, U, V, UVsock, P0
    mat.use_nodes = True
    N, L = mat.node_tree.nodes, mat.node_tree.links
    for n in list(N): N.remove(n)
    SEED = seed
    tc = node("ShaderNodeTexCoord"); sep = node("ShaderNodeSeparateXYZ"); L.new(tc.outputs["UV"], sep.inputs[0])
    UVsock, U, V = tc.outputs["UV"], sep.outputs[0], sep.outputs[1]
    P0 = torus(1.0, 1.0)
    return U, V


def node(t, **kw):
    n = N.new(t); n.location = (_X[0] * 40 % 4000, -(_X[0] // 100) * 200); _X[0] += 1
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


def sstep(x, a0, a1, b0=0.0, b1=1.0):
    return mr(x, a0, a1, b0, b1, "SMOOTHERSTEP")


def comb(x, y, z):
    n = node("ShaderNodeCombineXYZ"); inp(n, 0, x); inp(n, 1, y); inp(n, 2, z); return n.outputs[0]


def vmath(op, x, y=None, sc=None):
    n = node("ShaderNodeVectorMath", operation=op); L.new(x, n.inputs[0])
    if y is not None:
        if isinstance(y, (tuple, list)): n.inputs[1].default_value = y
        else: L.new(y, n.inputs[1])
    if sc is not None: inp(n, 3, sc)
    return n.outputs[0]


def torus(ru, rv, u=None, v=None):
    """Clifford-Torus (ru cos2πu, ru sin2πu, rv cos2πv) + W = rv sin2πv + SEED. ru<rv -> lang in x."""
    u = U if u is None else u; v = V if v is None else v
    au = m("MULTIPLY", u, TAU); av = m("MULTIPLY", v, TAU)
    vec = comb(m("MULTIPLY", m("COSINE", au), ru), m("MULTIPLY", m("SINE", au), ru), m("MULTIPLY", m("COSINE", av), rv))
    return vec, m("ADD", m("MULTIPLY", m("SINE", av), rv), SEED)


def noise_at(P, scale, detail=4.0, rough=0.5, dist=0.0, lac=2.0, w_off=0.0):
    vec, w = P
    n = node("ShaderNodeTexNoise", noise_dimensions="4D"); L.new(vec, n.inputs["Vector"])
    L.new(m("ADD", w, w_off) if w_off else w, n.inputs["W"])
    for nm, val in (("Scale", scale), ("Detail", detail), ("Roughness", rough), ("Distortion", dist), ("Lacunarity", lac)):
        inp(n, n.inputs.find(nm), val)
    return n.outputs["Fac"], n.outputs["Color"]


def voronoi_at(P, scale, feature="F1", rand=1.0, w_off=0.0):
    vec, w = P
    n = node("ShaderNodeTexVoronoi", voronoi_dimensions="4D", feature=feature, distance="EUCLIDEAN")
    L.new(vec, n.inputs["Vector"]); L.new(m("ADD", w, w_off) if w_off else w, n.inputs["W"])
    inp(n, n.inputs.find("Scale"), scale); n.inputs["Randomness"].default_value = rand
    return n.outputs["Distance"], n.outputs.get("Color")


def warp(P, scale, amp, w_off=0.0, detail=3.0):
    fac, col = noise_at(P, scale, detail=detail, w_off=w_off)
    off = vmath("SCALE", vmath("SUBTRACT", col, (0.5, 0.5, 0.5)), sc=2 * amp)
    return (vmath("ADD", P[0], off), m("ADD", P[1], m("MULTIPLY", m("SUBTRACT", fac, 0.5), 2 * amp))), off


def split(col):
    s = node("ShaderNodeSeparateColor"); L.new(col, s.inputs[0]); return s.outputs[0], s.outputs[1], s.outputs[2]


def white(vec_sock):
    n = node("ShaderNodeTexWhiteNoise", noise_dimensions="3D"); L.new(vec_sock, n.inputs["Vector"])
    return n.outputs["Value"], n.outputs["Color"]


def mask_node(name, sock):
    """Benannter Node MASK_<name> fuer bake_masks.py."""
    n = node("ShaderNodeMath", operation="ADD"); inp(n, 0, sock); n.inputs[1].default_value = 0.0
    n.name = n.label = "MASK_" + name
    return n.outputs[0]


def finish(height_sock, base_gray=0.5):
    """Principled mit grauer Basis, Hoehe auf der Emission (fuer bake_masks 'height'), Bake-Ziel aktiv."""
    bsdf = node("ShaderNodeBsdfPrincipled"); bsdf.inputs["Base Color"].default_value = (base_gray,) * 3 + (1,)
    L.new(comb(height_sock, height_sock, height_sock), bsdf.inputs["Emission Color"]); bsdf.inputs["Emission Strength"].default_value = 1.0
    out = node("ShaderNodeOutputMaterial"); L.new(bsdf.outputs[0], out.inputs[0])
    t = node("ShaderNodeTexImage"); N.active = t
    return bsdf
