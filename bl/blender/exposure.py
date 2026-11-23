"""Exposure numbers for a rendered image (PIL only, no bpy, so it is unit-testable).

Brightness of the final image depends on the material: a white mug is bright when it is lit correctly, a black one
dark. So the verdict uses a gray card: a small second render with the same camera, lights and world in which every
object is neutral gray (albedo 0.5). Its brightness on the object's pixels depends on the light only.
Pixels: silhouette mask from the same camera; fallback the projected bounding box, else the whole image.
"""

# Gray-card thresholds (mean luminance of the gray render on the object, % of white, AgX). Measured on the A/B-test
# mugs and test boxes: the agents' corrected final lights 68–76, `bl light studio` 75–78, the same lights ×4 (what the
# agents rendered first) 84–91, light ÷5 49. Independent of the material (white/gray/black box all 76).
OVER_LIGHT = 82.0
UNDER_LIGHT = 55.0
OVER_CLIPPED = 3.0   # % of object pixels in the final image with a channel ≥ CLIP_LEVEL
CLIP_LEVEL = 250
OVER_MEAN = 85.0     # without a gray card: absolute mean of the final image
UNDER_MEAN = 12.0


def _region(im, box, mask):
    """→ (image, mask or None, region name) restricted to the object."""
    if mask is not None:
        if mask.size != im.size:
            mask = mask.resize(im.size, 0)  # 0 = NEAREST: keep the silhouette hard
        if mask.getextrema()[1] > 0:
            return im, mask, "mask"
    if box is not None:
        x0, y0, x1, y1 = (int(round(v)) for v in box)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(im.width, x1), min(im.height, y1)
        if x1 - x0 >= 2 and y1 - y0 >= 2:
            return im.crop((x0, y0, x1, y1)), None, "box"
    return im, None, "image"


def _mean(im, mask):
    from PIL import ImageStat
    return 100.0 * ImageStat.Stat(im.convert("L"), mask).mean[0] / 255.0


def stats(im, box=None, mask=None, clay=None):
    """im: final render (PIL); box: (x0, y0, x1, y1) px of the object or None; mask: PIL 'L' silhouette (255 = object,
    any size) or None; clay: gray-card render (PIL, any size) or None.
    → {"mean": %, "clipped": %, "light": % (gray card) or None, "region", "verdict": "ok"|"over"|"under"}"""
    from PIL import ImageChops
    rgb, m, region = _region(im.convert("RGB"), box, mask)
    r, g, b = rgb.split()
    hist = ImageChops.lighter(ImageChops.lighter(r, g), b).histogram(m)
    clipped = 100.0 * sum(hist[CLIP_LEVEL:]) / max(sum(hist), 1)
    mean = _mean(rgb, m)
    light = None
    if clay is not None:
        scale = (clay.width / im.width, clay.height / im.height)
        cbox = None if box is None else (box[0] * scale[0], box[1] * scale[1], box[2] * scale[0], box[3] * scale[1])
        c, cm, _r = _region(clay.convert("RGB"), cbox, mask)
        light = _mean(c, cm)
    if clipped >= OVER_CLIPPED or (light is not None and light >= OVER_LIGHT) or (light is None and mean >= OVER_MEAN):
        verdict = "over"
    elif (light is not None and light < UNDER_LIGHT) or (light is None and mean < UNDER_MEAN):
        verdict = "under"
    else:
        verdict = "ok"
    return {"mean": round(mean, 1), "clipped": round(clipped, 1), "light": round(light, 1) if light is not None else None,
            "region": region, "verdict": verdict}


def describe(s):
    """One line for legend and CLI."""
    line = "exposure: object mean {:.0f} %, clipped {:.1f} %".format(s["mean"], s["clipped"])
    if s["light"] is not None:
        line += ", gray card {:.0f} % (ok {:.0f}–{:.0f})".format(s["light"], UNDER_LIGHT, OVER_LIGHT)
    if s["verdict"] == "over":
        line += "  ⚠ overexposed: lower light power/world strength, or `bl light studio`"
    elif s["verdict"] == "under":
        line += "  ⚠ underexposed: raise light power, or `bl light studio`"
    return line
