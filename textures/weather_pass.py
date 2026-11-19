#!/usr/bin/env python3
"""Hoehenbasierter Verwitterungs-Nachpass, kachelbar (alles mit Wrap). Laeuft mit numpy+scipy+Pillow
(z. B. /mnt/caches/ComfyUI/venv/bin/python3), NICHT in Blender.

Die Schichten reagieren aufeinander ueber die Hoehe (Joe 19.11.: „Texturen sollen miteinander funktionieren,
Height fuer sinnvolle Erosion nutzen"):
  1. Erosion: Bruchkanten von Abplatzungen/Rissen per Slope-Blur (min) abrunden -> neue Hoehe.
  2. Hohlraum (Kavitaet) = grosse Unschaerfe minus Hoehe + konkave Kruemmung: Schmutz sammelt sich in Poren, Rissen,
     Fugen, Ausbruchboeden.
  3. Schmutzfahnen: aus Kavitaeten (gewichtet mit Schmier-Zonen) nach UNTEN verschleppt (Schwerkraft = Bildzeile +).
  4. Naesse: tritt aus Rissen, der Oberkante waagerechter Stoesse und Nass-Keimen aus, laeuft nach unten, faechert leicht
     auf; dunkel + glatt; am Rand Ablagerung (dunkler Saum).
  5. Kantenabrieb: konvexe Kanten (Bruchraender, Grate) etwas heller.
Bild-Orientierung: Zeile 0 = oben (PNG wie gebacken), Schwerkraft nach unten.

weather_pass.py --albedo BC.png --masks DIR --out DIR [--normal-strength 120] [--seed 1] [Staerken ...]"""
import argparse, json, os
import numpy as np
from PIL import Image
import scipy.ndimage as ndi

W = dict(mode="wrap")


def load(p):
    im = Image.open(p)
    if im.mode in ("I;16", "I;16B", "I"):
        return np.asarray(im).astype(np.float64) / 65535.0
    return np.asarray(im.convert("L")).astype(np.float64) / 255.0


def save16(p, a):
    Image.fromarray((np.clip(a, 0, 1) * 65535 + 0.5).astype(np.uint16)).save(p)


def save8(p, a, mode="L"):
    Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8), mode).save(p)


def sobel(z):
    gx = ndi.sobel(z, 1, **W) / 8.0; gy = ndi.sobel(z, 0, **W) / 8.0
    return gx, gy


def smear_down(src, length, decay, spread=0.0, rng=None, jitter=0.0):
    """Gerichtete Verschleppung nach unten (periodisch): s[y] = max(src[y], s[y-1]*decay_spalte).
    jitter: zufaellige Abklingrate je Spalte (geglaettet) -> unterschiedlich lange Bahnen statt Vorhang."""
    H, W_ = src.shape
    if rng is not None and jitter > 0:
        dc = ndi.gaussian_filter1d(rng.standard_normal(W_), 1.5, mode="wrap")
        dc = decay + jitter * np.clip(dc / (dc.std() + 1e-9), -2, 2) / 2
        dc = np.clip(dc, 0.5, 0.999)[None, :]
    else:
        dc = decay
    s = src.copy(); cur = src.copy()
    for _ in range(length):
        cur = np.roll(cur, 1, axis=0) * dc
        if spread > 0: cur = ndi.gaussian_filter1d(cur, spread, axis=1, mode="wrap")
        s = np.maximum(s, cur)
    return s


def slope_blur_min(h, guide, steps=12, step_px=0.6):
    """Slope-Blur (Modus min): entlang des Gefaelles der Fuehrungskarte abtasten -> Kanten erodieren."""
    gx, gy = sobel(guide)
    n = np.sqrt(gx ** 2 + gy ** 2) + 1e-9
    dx, dy = gx / n, gy / n
    H, Wd = h.shape
    yy, xx = np.mgrid[0:H, 0:Wd].astype(np.float64)
    out = h.copy()
    for i in range(1, steps + 1):
        smp = ndi.map_coordinates(h, [(yy + dy * i * step_px) % H, (xx + dx * i * step_px) % Wd], order=1, mode="grid-wrap")
        a = 1.0 - i / (steps + 1.0)
        out = np.minimum(out, h * (1 - a) + smp * a)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--albedo", required=True); ap.add_argument("--masks", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1); ap.add_argument("--normal-strength", type=float, default=120.0)
    ap.add_argument("--dirt", type=float, default=0.30); ap.add_argument("--streak", type=float, default=0.22)
    ap.add_argument("--wet", type=float, default=0.14); ap.add_argument("--edgewear", type=float, default=0.06)
    ap.add_argument("--erode", type=float, default=1.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(a.seed)
    M = lambda n: load(os.path.join(a.masks, n + ".png"))
    alb = load(a.albedo); h = M("height")
    spall, rim, crack, groove = M("spall"), M("spall_rim"), M("crack"), M("groove")
    wetseed, smudgeseed, laitance = M("wetseed"), M("smudgeseed"), M("laitance")
    H, Wd = h.shape

    def lowfreq(sig, seed_off):
        r = np.random.default_rng(a.seed + seed_off).standard_normal((H, Wd))
        z = ndi.gaussian_filter(r, sig, **W); return (z - z.mean()) / (z.std() + 1e-9)

    # 1) Erosion an Bruchkanten: nur in der Naehe von Abplatzungen/Rissen
    near_break = np.clip(ndi.gaussian_filter(np.maximum(spall, crack), 4, **W) * 4, 0, 1)
    h_er = slope_blur_min(h, ndi.gaussian_filter(h, 1.5, **W), steps=12, step_px=0.6)
    h2 = h + a.erode * near_break * (h_er - h)

    # 2) Kavitaet aus der Hoehe
    cav = np.clip(ndi.gaussian_filter(h2, 6, **W) - h2, 0, None)
    lap = ndi.laplace(ndi.gaussian_filter(h2, 1.2, **W), **W)
    concave = np.clip(lap, 0, None); convex = np.clip(-lap, 0, None)
    cav_n = np.clip(cav / (np.percentile(cav, 99.5) + 1e-9), 0, 1)
    conc_n = np.clip(concave / (np.percentile(concave, 99.5) + 1e-9), 0, 1)
    conv_n = np.clip(convex / (np.percentile(convex, 99.5) + 1e-9), 0, 1)
    dirt_noise = np.clip(0.6 + 0.4 * lowfreq(20, 1), 0, 1.3)
    dirt = np.clip((0.65 * cav_n + 0.35 * conc_n) * dirt_noise, 0, 1)

    # 3) Schmutzfahnen nach unten aus Kavitaeten (ohne Fugen: die waeren ein durchgehendes Band), staerker in Schmier-Zonen
    zone = np.clip(0.35 + ndi.gaussian_filter(smudgeseed, 6, **W) * 1.2, 0, 1)
    nogroove = 1 - np.clip(ndi.gaussian_filter(groove, 2, **W) * 3, 0, 1)
    src = (dirt * nogroove) ** 1.3 * zone
    src = src / (np.percentile(src, 99.8) + 1e-9)
    streak = smear_down(np.clip(src, 0, 1), length=110, decay=0.972, spread=0.3, rng=rng, jitter=0.03)
    streak = np.clip(ndi.gaussian_filter(streak, (2.5, 0.7), **W) * (0.7 + 0.3 * lowfreq(12, 2)), 0, 1)

    # 4) Naesse: (a) weiche Flecken aus Nass-Keimen mit kurzem Nachlauf, (b) schmale Rinnspuren aus Rissen und
    #    wenigen Punkten an der Oberkante waagerechter Stoesse (Wasser staut sich auf dem Stoss), zufaellige Laenge
    patch = ndi.gaussian_filter(wetseed, 4, **W)
    patch = smear_down(patch, length=35, decay=0.97, spread=0.8)
    groove_top = np.clip(np.roll(groove, -3, axis=0) - groove, 0, 1)
    pts = (rng.random(groove.shape) < 0.012) * groove_top                      # wenige Austrittspunkte
    pts = ndi.gaussian_filter(pts.astype(float), 1.2, **W) * 6
    crack_src = crack * np.clip(lowfreq(15, 3) + 0.3, 0, 1)                      # nicht jeder Riss leckt
    trails = smear_down(np.clip(np.maximum(pts, crack_src * 0.9), 0, 1), length=260, decay=0.99, spread=0.25, rng=rng, jitter=0.012)
    trails = ndi.gaussian_filter(trails, (1.5, 1.0), **W)
    wet = np.clip(np.maximum(np.clip((patch - 0.05) / 0.35, 0, 1), np.clip(trails * 1.3, 0, 1)), 0, 1)
    wet = wet * np.clip(0.7 + 0.4 * lowfreq(25, 4), 0, 1)
    wet_edge = np.clip(np.abs(ndi.sobel(ndi.gaussian_filter(wet, 1.5, **W), 0, **W)) * 2.5, 0, 1)

    # 5) Kantenabrieb: konvex und an Bruchraendern
    wear = np.clip(conv_n * 0.7 + rim * 0.5, 0, 1) * near_break

    # --- Zusammensetzen
    out = alb.copy()
    out *= 1 - a.dirt * dirt
    out *= 1 - a.streak * streak
    out *= 1 - a.wet * 2.2 * wet            # nass = dunkler
    out *= 1 - a.wet * 0.6 * wet_edge       # Ablagerungssaum
    out = out + a.edgewear * wear * (1 - out)
    out = out - out.mean() + alb.mean()

    rough = np.clip(0.88 - 0.10 * laitance + 0.06 * dirt + 0.05 * spall - 0.55 * wet, 0.15, 1.0)

    gx, gy = sobel(h2)
    k = a.normal_strength
    n = np.dstack([-gx * k, gy * k, np.ones_like(h2)]); n /= np.linalg.norm(n, axis=-1, keepdims=True)

    save8(os.path.join(a.out, "albedo.png"), out)
    save16(os.path.join(a.out, "height16.png"), h2)
    save8(os.path.join(a.out, "roughness.png"), rough)
    save8(os.path.join(a.out, "normal.png"), n * 0.5 + 0.5, "RGB")
    for nm, arr in (("dirt", dirt), ("streak", streak), ("wet", wet), ("wear", wear)):
        save8(os.path.join(a.out, "mask_" + nm + ".png"), arr)
    print(json.dumps({"out": a.out, "albedo_mean": round(float(out.mean()), 3), "albedo_std": round(float(out.std()), 3),
                      "cover_%": {k_: round(float((v > 0.3).mean() * 100), 2) for k_, v in (("dirt", dirt), ("streak", streak), ("wet", wet), ("wear", wear))}}))


if __name__ == "__main__":
    main()
