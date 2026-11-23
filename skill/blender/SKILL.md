---
name: blender
description: Drive Blender 5.2 by script (headless, no MCP) through the `bl` CLI — build models, materials, bakes, renders, exports, inspect and look at scenes. Entry point for any Blender, bpy or .blend task.
---

# blender — Blender by script with `bl`

## `bl` — open scene in a background worker
One Blender process per session keeps the scene open (start ≈ 1 s, then milliseconds per call, idle shutdown after 15 min).
Projects live under `$BL_ROOT/<project>/vNNN_<label>/{blend,preview,export,measurements,scripts}`.

```bash
bl doctor                         # first call: Blender, GPU, storage, PIL, running workers
bl project "door handle"          # create/select (creates v001_start)
bl version "chamfer on rim"       # new version; the open scene is saved into it
bl run script.py --report         # script in the open scene; copied to scripts/NNN_*.py (same as last one: run counter)
bl run a.py b.py c.py --set n=32 --set name=Handle   # chain, stops at the first error; --set → dict `args` in the script
bl run -e 'obj("Box").location.z = 2' --name raise   # short step without a file
bl info  |  bl info --obj Box     # numbers: objects, faces, dimensions, modifiers, materials
bl look --sheet                   # iso/front/right/top, 768 px, legend with mm/px
bl look --mode wire --obj Box     # wireframe; --mode cam = scene camera with the configured engine
bl look --compare [--view …|--mode cam]   # left: start state of the version, right: now, same camera, change in %
bl look --compare last            # against the last `bl save`; also `start` or a path to a .blend
bl look --focus 38,0,64 --radius 12 [--compare]   # closeup around point x,y,z or an object name; all in mm
bl look --view bottom             # underside: not part of the sheet
bl look --section y=0 [--obj X] [--compare]   # cut at the plane (mm), cut faces red: wall thickness, interior
bl look --mode cam --engine cycles --samples 64   # engine for this image only (eevee|cycles|workbench)
bl light studio [--obj X] [--strength 0.7]   # key/fill/rim scaled to the object; other lights off for rendering, world dimmed
bl docs bpy.types.Object.matrix_world   # API offline, matching 5.2: signature, description, type (incl. base classes)
bl docs bmesh.ops.bevel  |  bl docs <terms> [--manual] [--hit I]   # full-text search in API or manual; no worker needed
bl qa --profile game|render|print [--budget 5000]   # each mesh separately; --obj A --obj B = together as one asset; exit 1 on errors
bl save  |  bl close [--save|--discard]  |  bl ls [--all]  |  bl open [file.blend | --empty] [--discard]
```
`bl version` stores the start state as `<project>_start.blend`; `bl save` writes `<project>.blend` next to it. `bl look` leaves large flat ground planes out of the framing (the legend names them); `--obj` selects explicitly. Solid and wire images carry a scale bar at the bottom right. `⚠ EMPTY` after `bl look`: the closeup hit nothing.
`bl open` and `bl close` refuse after `bl run` without `bl save` (`--discard` forces). If the worker ends idle with unsaved runs, it saves `autosave.blend`; after that every command refuses until you choose `bl open <autosave>` (continue with it) or `bl open` (old state). The journal keeps `NNN_<name>.run.json` per script (values from `--set`, successful and failed runs, the full `result` of the last good run; `bl run --json` prints it unclipped). A section plane exactly on a vertex row is moved by a few µm and the output says so. `--compare --mode cam` warns if the old state has no lights. `--compare --mode cam` renders the old state with its own lights and world, using the current camera.
`bl qa` uses `qa_check` from skill `blender-asset-qa` plus broken faces and poly budget; mode and active object are preserved. Without `--obj` each mesh is checked separately, z-fighting between objects additionally together. With several `--obj` the objects count as *one* asset (what does not touch is "floating"). Profiles: `game` (UV, material, scale strict), `render` (lenient, degenerate geometry only a warning), `print` (watertight).
In scripts, without imports: `bpy`, `obj(name)`, `report(obj, …)` (marks for `--report`/`--look`), `mesh_stats(obj)` (v/f/tris, non-manifold edges, loose vertices; broken faces `tiny`/`zero_edges`/`slivers`/`folded`, warning `duplicates` (same thresholds and numbers as `bl qa`); `ngons` is info only: n-gons are not automatically a problem), `args` (from `--set`), `Vector`, `Matrix`, `math`, `bl` (helper library). Measuring without your own BVH: `bl.hits((x, y, z) in mm, direction)` → all hits of a ray in mm. Return values: `result = {...}` (JSON); `print` output comes back truncated.
Exit codes: 0 ok · 1 finding (`bl qa`) · 2 script error (one line `file:line: error`, full traceback in the named file) · 3 worker/Blender.

## Loop
1. Clarify goal and dimensions (reference, poly budget, target format).
2. Small steps with `bl run`; don't rebuild everything each time. The scene stays open. Before an API call whose signature you don't know for sure: `bl docs <name>` first, don't guess (5.x differs from older versions).
3. **Numbers first** (`--report`, `bl info`, `bl qa`, `bl.hits`), **then one image** (`bl look --sheet`, ≈ 830 tokens). Inner details (wall thickness, does something poke inside?) with `bl look --section`.
4. Before every change that should be visible: `bl version "<what changes>"`. Afterwards `bl look --compare` (fitting view; for details `--focus … --radius …`).
5. If `bl run --report` or `bl info --obj` reports **ERROR broken faces**, fix the mesh first: wireframe and shading show artifacts there that say nothing about the design.
6. Before the first camera image: `bl light studio` (watts are not intuitive at object scale; guessed lights come out ≈ 4× too bright). `bl look --mode cam` prints exposure from a gray card (independent of the material color): follow a `⚠ overexposed`/`underexposed` warning with `--strength`, don't judge brightness by eye.
7. Before finishing: `bl qa` with the fitting profile; every error is fixed or justified in the report.
8. Acceptance: image (plus wireframe) to the user; the user decides.

**Save tokens: every turn re-reads the whole context.** Fewer turns is the biggest lever:
- Related steps in **one** shell call: `bl run … --report && bl look --compare …`, `bl save; bl version …; bl run …`, several `bl look` in a row.
- Read all new images **in one turn** (several Read calls in parallel), not one per turn.
- Edit scripts as files in the project instead of rewriting them into the command each time.

## Seeing: evidence over impression
Whoever just made a change sees the expected improvement even when it is not there (test run: a fillet reported as "smooth", image changed by 0.4 %). Therefore:
- **A visible improvement only counts with evidence:** `bl look --compare` shows it (≥ 1 %, red frame at the right place). For local changes use a closeup `--focus … --radius …`; full views dilute the percentage. If `--compare` warns "barely visible", the change is not visible: strengthen it, check it in a closeup, or honestly report it as "not visible".
- **Look yourself:** read every image a decision depends on and note your finding.
- **Blind critic** only on request (task or user asks for it): subagent `bl-critic` (`agents/bl-critic.md`: Read only, Sonnet, ≈ 20k tokens per call). In our A/B test, three critic rounds cost ≈ 10 % of the run and found nothing that `--compare` or the agent had not already found. Give it **only** the brief and the image paths, never what you changed or what you expect, and all images in one call:
  > Images: <paths>. Brief: <brief verbatim>. Measured dimensions: <values>.
- **You measure, not the critic:** it estimates from pixels and is often wrong. Give it the measured values; it judges only what is visible: shape, transitions, shading, artifacts.
- **Log** per image: path · what you see · `--compare` % · what you do next.

## Pitfalls
- **Boolean seams shade streaky:** after a boolean union the seam vertices share an averaged normal, and wedge-shaped streaks appear on the wall. Fix: mark parts with a face attribute (e.g. `part` 0 body / 1 handle) and set the wall normals analytically (custom normals). Don't detect parts by geometry; that also catches fillet faces.
- **Boolean seams create near-degenerate geometry:** degenerate faces, zero-length edges, duplicate vertices. `bl run --report` shows them like `bl qa`; merge by distance and clean up before finishing.
- **Bevel on boolean intersection edges** creates tiny and folded faces (`mesh_stats` shows them); model a fillet directly in the sweep of the attached part instead.
- `LD_LIBRARY_PATH` from some shells breaks Blender (foreign glibc/alsa libs): `bl` removes it, raw `blender` doesn't.
- Find nodes by `type`, not by name (names are localized); read enum values instead of guessing.
- **Add-on enum values are missing from docs and enum lists:** `RenderSettings.engine` lists only `'BLENDER_EEVEE'`; Cycles is an add-on. Assign and check the result.
- Long bakes/renders: `bl run … --timeout 3600`.
- Never stop other sessions' workers (`bl doctor` lists all sessions).
