# blender-tools

Blender-Skripte für Agenten, headless per Kommandozeile (kein MCP). Erster Einsatz: kachelbare PBR-Texturen
für Neon Getaway (Tunnel-Sichtbeton). Doku und Befunde im Wiki: `Software/Blender Agent Skills (EL4CTEO blender-skills)`.

## Setup (Hufflepuff)
- Blender **5.2.4 LTS** (offizielles Archiv, CUDA + OptiX) unter `/mnt/caches/ComfyUI/_tools/blender-5.2.4-linux-x64/`.
  Das Nix-Blender 5.1.1 hat keine CUDA-Kernel und kein OptiX, auf der GPU hängt es (Testbake: 860 s statt 3 s auf der CPU).
- `bin/blender-gpu`: startet 5.2.4 und entfernt `LD_LIBRARY_PATH` (eine Nix-alsa-lib darin bricht Blender mit
  `GLIBC_2.43 not found` ab). Installiert als `~/bin/blender-gpu`.
- Baking über die Skill-Bibliothek `~/repos/blender-skills` (EL4CTEO, MIT):
  `export BLENDER_EXE=$HOME/bin/blender-gpu`, dann wählt `bake_maps.py` selbst OptiX.

## textures/
| Skript | Zweck |
|---|---|
| `formwork_wall.py` | Baut Plane 2,4 × 2,4 m + prozedurales Node-Material (Fugen, Ankerlöcher, Poren, Maserung, Krea-Wolken als Bild). Kachelbar per Konstruktion: 4D-Rauschen auf dem flachen Clifford-Torus, Raster aus `fract(UV)`. Höhe liegt auf der Emission. |
| `bake_height16.py` | Höhe (Emission) als Float backen, als 16-bit-PNG speichern. 8 bit quantisiert glatte Plateaus zu Treppen → Konturlinien in der Normal. |
| `nodekit.py` | Gemeinsame Node-Helfer (Clifford-Torus, noise_at, voronoi_at, warp, Masken-Nodes) für neue Builder. |
| `paint_wear.py` | T6 Lack-Verwitterung (2 × 2 m): MASK_chip/scratch/fade/dirt + Lackhöhe. |
| `bake_masks.py` | Alle `MASK_<name>`-Nodes eines Materials (plus Höhe) in einem Lauf als 16-bit-PNG backen. |
| `weather_pass.py` | Höhenbasierte Verwitterung (numpy/scipy, kachelbar): Erosion an Bruchkanten (Slope-Blur), Schmutz in Kavitäten, Schmutzfahnen und Nässe nach unten, Kantenabrieb; schreibt Albedo, Höhe, Rauheit, Normal und Masken. |
| `normal_from_height.py` | Tangent-Normal (OpenGL, `--directx` optional) aus gebackener Höhe per Sobel mit Wrap. Grund: Bump-Node liefert beim Backen zu schwache Normals. |

## Ablauf (Beispiel T5)
```
blender-gpu -b --factory-startup -P textures/formwork_wall.py -- --cloud cloud.png --save t5.blend --cloud-amt 4 --bump-dist 1.5
BLENDER_EXE=$HOME/bin/blender-gpu python3 ~/repos/blender-skills/skills/blender-core/scripts/run_in_blender.py --blend t5.blend \
    ~/repos/blender-skills/skills/blender-texture-baking/scripts/bake_maps.py -- --low T5_Wall \
    --maps basecolor roughness --res 1024 --samples 16 --margin-px 0 --out //bake --name T5    # ~25 s mit OptiX
blender-gpu -b t5.blend --factory-startup -P textures/bake_height16.py -- --obj T5_Wall --out bake/T_T5_H16.png
blender-gpu -b --factory-startup -P textures/normal_from_height.py -- --height bake/T_T5_H16.png --out bake/T_T5_N.png --strength 120
```

## Fallstricke (Shader-Nodes)
- `Scale` eines Noise nie räumlich steuern (Phasenfehler → Marmor-Wirbel); stattdessen feste Skalen per Maske mischen.
- Interne `Distortion` > ~0,3 erzeugt Wirbel; Domain Warping über externe Vektor-Offsets nutzen.
- Diagnose: `formwork_wall.py … --dbg meso|stain|cloud|pores|…` legt eine Komponente auf die Emission, dann mit `bake_height16.py` backen.

## Ablauf mit Verwitterung (v3)
```
blender-gpu -b --factory-startup -P textures/formwork_wall.py -- --cloud cloud.png --save t5.blend --wet-amt 0 --smudge-amt 0
# Albedo sauber backen (bake_maps.py --maps basecolor), dann alle Masken + Höhe:
blender-gpu -b t5.blend --factory-startup -P textures/bake_masks.py -- --obj T5_Wall --outdir bake/masks
/mnt/caches/ComfyUI/venv/bin/python3 textures/weather_pass.py --albedo bake/T_T5_BC.png --masks bake/masks --out bake/weathered
```
