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
| `normal_from_height.py` | Tangent-Normal (OpenGL, `--directx` optional) aus gebackener Höhe per Sobel mit Wrap. Grund: Bump-Node liefert beim Backen zu schwache Normals. |

## Ablauf (Beispiel T5)
```
blender-gpu -b --factory-startup -P textures/formwork_wall.py -- --cloud cloud.png --save t5.blend --cloud-amt 4 --bump-dist 1.5
BLENDER_EXE=$HOME/bin/blender-gpu python3 ~/repos/blender-skills/skills/blender-core/scripts/run_in_blender.py --blend t5.blend \
    ~/repos/blender-skills/skills/blender-texture-baking/scripts/bake_maps.py -- --low T5_Wall \
    --maps basecolor roughness normal emit --res 1024 --samples 16 --margin-px 0 --out //bake --name T5    # ~25 s mit OptiX
blender-gpu -b --factory-startup -P textures/normal_from_height.py -- --height bake/T_T5_E.png --out bake/T_T5_N.png
```
