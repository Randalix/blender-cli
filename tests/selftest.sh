#!/usr/bin/env bash
# bl selftest with real Blender: throwaway storage and its own session, cleans up afterwards.
set -u
here="$(cd "$(dirname "$0")/.." && pwd)"
BL="$here/bin/bl"
mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}"
BL_ROOT="$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" bl-selftest.XXXX)" || { echo "mktemp failed"; exit 3; }
[ -d "$BL_ROOT" ] || { echo "BL_ROOT missing"; exit 3; }
export BL_ROOT BL_SESSION="selftest-$$"
fail=0
ok()   { echo "  ok   $*"; }
bad()  { echo "  FAIL $*"; fail=1; }
check(){ local d="$1"; shift; if "$@"; then ok "$d"; else bad "$d"; fi; }
has(){ local m; for m in "$@"; do grep -qE -- "$m" <<<"$o" || return 1; done; }  # all patterns in $o
hasnt(){ local m; for m in "$@"; do grep -qE -- "$m" <<<"$o" && return 1; done; return 0; }  # none of the patterns in $o
cleanup(){ "$BL" close --discard >/dev/null 2>&1; BL_SESSION="$BL_SESSION-idle" "$BL" close --discard >/dev/null 2>&1; rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/bl/$BL_SESSION-idle"; rm -rf "$BL_ROOT" "${XDG_STATE_HOME:-$HOME/.local/state}/bl/$BL_SESSION"; }
trap cleanup EXIT

echo "== bl selftest (BL_ROOT=$BL_ROOT)"
o=$("$BL" project "Test Box"); check "project creates v001_start" grep -q "v001_start" <<<"$o"
o=$("$BL" open); check "open empty scene" grep -q "scene empty" <<<"$o"
pid=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['pid'])" "${XDG_STATE_HOME:-$HOME/.local/state}/bl/$BL_SESSION/worker.json")
o=$("$BL" info); check "info: empty scene" grep -q "objects 0" <<<"$o"
o=$("$BL" run -e 'bpy.ops.mesh.primitive_cube_add(size=1); k=bpy.context.object; k.name="Box"
m=k.modifiers.new("Bevel","BEVEL"); m.width=0.05; m.segments=3; report(k); result={"faces": mesh_stats(k)["f"]}' --name box --report)
check "run -e: result" grep -q '"faces": 98' <<<"$o"
check "run --report: line" grep -q "Box  MESH  v .* f 98" <<<"$o"
check "script journaled" test -f "$BL_ROOT/test-box/v001_start/scripts/001_box.py"
o=$("$BL" run -e 'k=obj("Box"); k.location.z=2; print("z", k.location.z)'); check "scene stays open" grep -q "| z 2.0" <<<"$o"
# --- chain, --set, journal without identical copies
printf 'result = {"a": args.get("n", 0) * 2}\n' > "$BL_ROOT/ka.py"
printf 'bpy.app.driver_namespace["bl_kb"] = args.get("name", "-"); result = {"b": args.get("name", "-")}\n' > "$BL_ROOT/kb.py"
o=$("$BL" run "$BL_ROOT/ka.py" "$BL_ROOT/kb.py" --set n=21 --set name=Mug)
check "run chain: both scripts, --set" has '"a": 42' '"b": "Mug"'
o=$("$BL" run "$BL_ROOT/kb.py" --set n=21 --set name=Mug 2>&1); check "journal: last file identical → reused, run 2" has "_kb.py \(unchanged, run 2\)"
check "journal: run count in kb.run.json" grep -q '"runs": 2' "$BL_ROOT"/test-box/v001_start/scripts/*_kb.run.json
o=$("$BL" run "$BL_ROOT/ka.py" --set n=1 2>&1); rc=$?; check "journal: ka after kb, other values → new file" bash -c "[ $rc -eq 0 ]"; check "journal: new file reported" hasnt "unchanged"
check "journal: two ka runs, values next to them" bash -c "[ \$(command ls '$BL_ROOT'/test-box/v001_start/scripts/ | grep -c '_ka.py') -eq 2 ] && grep -q '\"n\": 1' '$BL_ROOT'/test-box/v001_start/scripts/*_ka.run.json"
o=$("$BL" run "$BL_ROOT/ka.py" --set x=NaN 2>&1); check "--set NaN → clear message" has "NaN/Infinity is not a valid value"
printf 'raise ValueError("broken")\n' > "$BL_ROOT/kf.py"
printf 'bpy.app.driver_namespace["bl_kc"] = 1\n' > "$BL_ROOT/kc.py"
o=$("$BL" run "$BL_ROOT/ka.py" "$BL_ROOT/kf.py" "$BL_ROOT/kc.py" 2>&1); rc=$?
check "chain: error → exit 2" bash -c "[ $rc -eq 2 ]"; check "chain: abort reported" has "chain aborted at script 2/3; not run: kc"
o=$("$BL" run -e 'result={"kc": "bl_kc" in bpy.app.driver_namespace}'); check "chain: script after error did not run" grep -q '"kc": false' <<<"$o"
o=$("$BL" run -e 'result={"h": bl.hits((0, 0, 5000), (0, 0, -1)), "sb": list(bl._scale_bar(0.4, 768))}')
check "bl.hits: top and bottom of the box (mm)" grep -q '"h": \[\[0.0, 0.0, 2500.0\], \[0.0, 0.0, 1500.0\]\]' <<<"$o"
check "scale bar 0.4 mm/px × 768 → 50 mm, 125 px" grep -q '"sb": \[50, 125\]' <<<"$o"
o=$("$BL" look --section z=2000 --obj Box --size 300); img=$(grep -o '/[^ ]*\.png' <<<"$o")
check "section: image" bash -c "grep -q section-z2000 <<<'$o' && test -s '$img'"
o=$("$BL" run -e 'from PIL import Image
im=Image.open(r"'"$img"'").convert("RGB"); px=list(im.getdata())
result={"red": sum(1 for r,g,b in px if r-g>50 and r-b>50), "objs": sorted(o.name for o in bpy.data.objects), "section_leftovers": [i.name for i in list(bpy.data.materials)+list(bpy.data.meshes)+list(bpy.data.cameras) if i.name.startswith("_bl")], "meshes": len(bpy.data.meshes)}')
check "section: red cut face visible" has '"red": [0-9]{3,}'
check "section: cleans up (objects, mesh, material, camera)" has '"objs": \["Box"\]' '"section_leftovers": \[\]' '"meshes": 1'
o=$("$BL" run -e 'bpy.ops.object.empty_add(); bpy.context.object.name="Empty"' >/dev/null; "$BL" look --section z=0 --obj Empty 2>&1); check "section without mesh → clear message" has "cuts meshes only"
"$BL" run -e 'bpy.data.objects.remove(obj("Empty"))' >/dev/null
o=$("$BL" look --section q=1 2>&1); check "section: wrong axis → error" has "x=MM, y=MM or z=MM"
printf 'x = 1\ny = obj("DoesNotExist")\n' > "$BL_ROOT/error.py"
o=$("$BL" run "$BL_ROOT/error.py" 2>&1); rc=$?
check "error → exit 2" test $rc -eq 2
check "failing script journaled" bash -c "ls \"$BL_ROOT\"/test-box/v001_start/scripts/ | grep -q _error.py"
check "error line with file:line" grep -q "error.py:2: KeyError" <<<"$o"
o=$("$BL" info --obj Box); check "info --obj: bevel" grep -q "mod Bevel (bevel) width=0.05 segments=3" <<<"$o"
o=$("$BL" look --sheet --size 512); check "look --sheet" grep -q "512×552 px" <<<"$o"
img=$(grep -o '/[^ ]*\.png' <<<"$o"); check "image exists" test -s "$img"
o=$("$BL" look --mode wire --obj Box --size 400); check "look wire" grep -q "400×440 px" <<<"$o"
o=$("$BL" run -e 'result={"objs": sorted(o.name for o in bpy.data.objects)}'); check "look cleans up (no _bl_ objects)" grep -q '"objs": \["Box"\]' <<<"$o"
o=$("$BL" run -e 'bpy.ops.mesh.primitive_cube_add(size=0.2, location=(1.5,0,0.5)); bpy.context.object.name="Marker"
from PIL import Image
def side(v):
    r=bl.look(r"'"$BL_ROOT"'/o_"+v+".png", views=[v], panel=200); im=Image.open(r["path"]).convert("L")
    xs=[x for x in range(200) for y in range(0,200,4) if im.getpixel((x,y))<200]
    return sum(xs)/len(xs) > 100
result={"top_like_front": side("top")==side("front"), "bottom_like_front": side("bottom")==side("front")}
bpy.data.objects.remove(obj("Marker"))'); check "top/bottom: +X on the same side as front" grep -q '"top_like_front": true, "bottom_like_front": true' <<<"$o"
o=$("$BL" save); check "save" grep -q "v001_start/blend/test-box.blend" <<<"$o"
o=$("$BL" version "Second State"); check "version saves the start state" grep -q "v002_second-state/blend/test-box_start.blend" <<<"$o"
o=$("$BL" close); check "close" grep -q "worker stopped" <<<"$o"
sleep 0.5; check "no process left" bash -c "! kill -0 $pid 2>/dev/null"
o=$("$BL" info); check "auto-open loads the newest file" grep -q "v002_second-state/blend/test-box_start.blend" <<<"$o"
check "box there after restart, z=2" bash -c "\"$BL\" info --obj Box | grep -q 'loc (0.0, 0.0, 2.0)'"
o=$("$BL" look --compare --size 400); check "compare without change: 0 %" grep -q "iso 0.0 %" <<<"$o"
check "compare without change: warning" grep -q "barely visible change" <<<"$o"
"$BL" run -e 'obj("Box").scale.x = 1.6' >/dev/null
o=$("$BL" look --compare --view iso --view top --size 400); check "compare after change: image 2×200+4 wide" grep -q "404×" <<<"$o"
check "compare after change: >1 %, no warning" bash -c "grep -qE 'iso [1-9][0-9]*\.[0-9] %' <<<\"$o\" && ! grep -q 'barely visible' <<<\"$o\""
o=$("$BL" run -e 'result={"objs": sorted(o.name for o in bpy.data.objects), "meshes": len(bpy.data.meshes)}'); check "compare cleans up" grep -q '"objs": \["Box"\], "meshes": 1' <<<"$o"
o=$("$BL" look --mode wire --compare --size 400); check "compare wire" grep -q "compared with" <<<"$o"
"$BL" save >/dev/null; o=$("$BL" look --compare --size 400); check "compare after save uses the start state" bash -c "grep -q 'test-box_start.blend' <<<\"$o\" && ! grep -q 'barely visible' <<<\"$o\""
o=$("$BL" look --compare "$BL_ROOT/test-box/v002_second-state/blend/test-box.blend" --size 400); check "compare against saved state: 0 %" grep -q "iso 0.0 %" <<<"$o"
o=$("$BL" look --focus Box --radius 100 --size 400); check "focus: finer scale" bash -c "grep -qE '1 px = 0\.[0-9]+ mm' <<<\"$o\""
o=$("$BL" look --focus 0,0,2000 --size 400 2>&1); rc=$?; check "focus point without radius → error" bash -c "[ $rc -eq 2 ] && grep -q 'needs --radius' <<<\"$o\""
o=$("$BL" look --focus 500,500,2500 --radius 200 --compare --size 400); check "focus in mm + compare" bash -c "grep -q 'compared with' <<<\"$o\" && ! grep -q EMPTY <<<\"$o\""
o=$("$BL" look --focus 0.5,0.5,2.5 --radius 50 --size 400); check "focus missed → warning EMPTY" grep -q "EMPTY" <<<"$o"
o=$("$BL" look --compare last --size 400); check "compare last: against bl save state 0 %" grep -q "iso 0.0 %" <<<"$o"
o=$("$BL" look --compare start --size 400); check "compare start" grep -q "test-box_start.blend" <<<"$o"
o=$("$BL" look --obj Box --compare --size 400 2>&1); check "compare with --obj" grep -q "compared with" <<<"$o"
o=$("$BL" run -e 'import bmesh
me=bpy.data.meshes.new("S"); bm=bmesh.new()
v=[bm.verts.new(p) for p in [(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0.5,-0.00001,0),(0.5,1.5,0)]]
bm.faces.new((v[0],v[3],v[2],v[1])); bm.faces.new((v[0],v[1],v[4])); bm.to_mesh(me)
s=bpy.data.objects.new("Sliver",me); bpy.context.scene.collection.objects.link(s); s.location=(5,0,0)
me2=bpy.data.meshes.new("N"); bm2=bmesh.new(); import math
vs=[bm2.verts.new((math.cos(i/6*math.tau), math.sin(i/6*math.tau), 0)) for i in range(6)]; bm2.faces.new(vs); bm2.to_mesh(me2)
n=bpy.data.objects.new("Hexagon",me2); bpy.context.scene.collection.objects.link(n); n.location=(8,0,0)
report(s, n); result={"s": mesh_stats(s), "n": mesh_stats(n)}' --report)
check "mesh_stats: sliver detected" grep -q '"slivers": 1' <<<"$o"
check "summary: ERROR on sliver" grep -q "Sliver  MESH .*ERROR slivers 1" <<<"$o"
check "n-gon is not an error" bash -c "grep -q 'Hexagon  MESH' <<<\"$o\" && ! grep -q 'Hexagon.*ERROR' <<<\"$o\""
o=$("$BL" info --obj Hexagon); check "info: n-gons as info" grep -q "n-gons 1 (info)" <<<"$o"
# broken faces like qa_check: small object (diagonal 0.1 m), flat triangle 5e-11 m² (the old threshold 1e-12 missed it),
# edge 1e-8 m (also a duplicate pair), one loose duplicate vertex → duplicates 2
o=$("$BL" run -e 'import bmesh
me=bpy.data.meshes.new("K"); bm=bmesh.new()
q=[bm.verts.new(p) for p in [(0,0,0),(0.05,0,0),(0.05,0.05,0),(0,0.05,0)]]; bm.faces.new(q)
w=[bm.verts.new(p) for p in [(0.06,0,0),(0.07,0,0),(0.065,1e-8,0)]]; bm.faces.new(w)
z=[bm.verts.new(p) for p in [(0.08,0,0),(0.08,1e-8,0),(0.09,0,0),(0.09,0.01,0)]]; bm.faces.new((z[0],z[2],z[3],z[1]))
bm.verts.new((0,0,0))
bm.to_mesh(me); k=bpy.data.objects.new("Broken",me); bpy.context.scene.collection.objects.link(k); k.location=(40,0,0)
report(k); result={"k": mesh_stats(k)}' --report)
check "mesh_stats: tiny 5e-11 m² detected (old threshold missed it)" has '"tiny": 1'
check "mesh_stats: edge 1e-8 m detected" has '"zero_edges": 1'
check "mesh_stats: duplicate vertices detected" has '"duplicates": 2'
check "mesh_stats: face with zero edge not also a sliver" has '"slivers": 0'
check "summary: ERROR tiny/zero_edges, warning duplicates" has "Broken  MESH .*ERROR tiny 1, zero_edges 1" "warning duplicate vertices 2"
o=$("$BL" info --obj Broken); check "info: ERROR broken faces + warning duplicates" has "ERROR broken faces: tiny 1, zero_edges 1" "warning duplicate vertices: 2"
o=$("$BL" qa --obj Broken --profile game 2>&1); check "qa: same numbers as mesh_stats" has "degenerate faces=1 zero-len edges=1" "duplicate verts=2"
check "qa: tiny not reported twice" hasnt "broken faces tiny"
o=$("$BL" run -e 'bpy.data.objects.remove(obj("Broken"))' 2>&1)
o=$("$BL" look --mode wire --obj Sliver --size 300); img=$(grep -o '/[^ ]*\.png' <<<"$o")
o=$("$BL" run -e 'from PIL import Image
im=Image.open(r"'"$img"'").convert("L"); w,h=im.width,im.height-40
rim=[im.getpixel((x,y)) for x in range(w) for y in range(h) if (x<10 or x>w-10 or y<10 or y>h-10) and not (x<120 and y<30) and not (x>w-160 and y>h-40)]
result={"dark_at_rim": sum(1 for p in rim if p<120)}')
check "wire: no spikes at the sliver" grep -q '"dark_at_rim": 0' <<<"$o"
"$BL" run -e 'bpy.data.objects.remove(obj("Sliver")); bpy.data.objects.remove(obj("Hexagon"))' >/dev/null
"$BL" run -e 'bpy.ops.mesh.primitive_plane_add(size=50); bpy.context.object.name="Ground"' >/dev/null
o=$("$BL" look --size 400); check "ground excluded from framing" grep -q "ground not framed" <<<"$o"
check "scale stays fine (< 10 mm/px)" bash -c "grep -qE '1 px = [0-9]\.[0-9]+ mm' <<<\"$o\""
# --- camera comparison with the lights of the old state, engine choice
"$BL" run -e 'c=bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam")); bpy.context.scene.collection.objects.link(c)
c.location=(0,-8,4); c.rotation_euler=(math.radians(65),0,0); bpy.context.scene.camera=c
L=bpy.data.objects.new("Sun", bpy.data.lights.new("Sun","SUN")); bpy.context.scene.collection.objects.link(L); L.data.energy=5
w=bpy.context.scene.world or bpy.data.worlds.new("W"); bpy.context.scene.world=w; w.use_nodes=True
next(n for n in w.node_tree.nodes if n.type=="BACKGROUND").inputs["Strength"].default_value=0.05' >/dev/null
"$BL" save >/dev/null
"$BL" run -e 'obj("Sun").data.energy=0.2' >/dev/null
o=$("$BL" look --mode cam --compare last --size 200 --samples 4)
check "cam compare: light change visible (old state with old light)" has 'cam [1-9][0-9]*\.[0-9] %'; check "cam compare: no warning" hasnt "barely visible"
o=$("$BL" run -e 'result={"lights": sorted(o.name for o in bpy.context.scene.objects if o.type=="LIGHT"), "e": round(obj("Sun").data.energy, 3), "scenes": len(bpy.data.scenes), "worlds": len(bpy.data.worlds), "world_set": bpy.context.scene.world is not None and bpy.context.scene.world.library is None and not bpy.context.scene.world.name.endswith(".001")}')
check "cam compare cleans up (light, world, scene)" has '"lights": \["Sun"\], "e": 0.2, "scenes": 1, "worlds": 1, "world_set": true'
state='s=bpy.context.scene; c=getattr(s,"cycles",None); result={"before": [s.render.engine, s.eevee.taa_render_samples, c.samples if c else None, c.device if c else None]}'
o=$("$BL" run -e "$state"); before=$(grep -o '"before": \[[^]]*\]' <<<"$o")
check "engine: state read before" test -n "$before"
o=$("$BL" look --mode cam --engine cycles --samples 2 --size 160); check "--engine cycles renders with Cycles" has "engine cycles \((OPTIX|CUDA|CPU)\)"
o=$("$BL" run -e "$state"); check "engine, samples, Cycles samples/device restored" grep -qF -- "$before" <<<"$o"
o=$("$BL" look --engine cycles 2>&1); check "--engine without cam → error" grep -q "only with --mode cam" <<<"$o"
# --- studio light scaled to the object, exposure numbers
o=$("$BL" light studio); check "light studio: key, fill, rim" has "bl_key .* W" "bl_fill" "bl_rim"
check "light studio: other light off for rendering" has "other lights off .*Sun"
check "light studio: previous world kept in the file" has "yours \(.+\) stays in the file"
o=$("$BL" look --mode cam --size 200 --samples 4); check "cam image: exposure line with gray card" has "exposure: object mean [0-9]+ %.*gray card [0-9]+ %"
check "studio light: no exposure warning" hasnt "overexposed|underexposed"
o=$("$BL" light studio --strength 8 >/dev/null; "$BL" look --mode cam --size 200 --samples 4); check "8× light → overexposed" has "⚠ overexposed"
o=$("$BL" run -e 'k=lambda: bpy.data.collections["bl_light"].objects["bl_key"].data.energy
r1=bl.light_studio(["Box"]); e1=k(); b=obj("Box"); sc=tuple(b.scale); b.scale=[x*0.01 for x in sc]; bpy.context.view_layer.update()
r2=bl.light_studio(["Box"]); e2=k(); b.scale=sc; bpy.context.view_layer.update(); bl.light_studio(["Box"])
result={"q": round((e2/e1) / (r2["diag_mm"]/r1["diag_mm"])**2, 2), "rig": len(bpy.data.collections["bl_light"].objects), "lights": len(bpy.data.lights), "clay_left": "_bl_clay" in bpy.data.materials}')
check "light studio: power ∝ diagonal²" has '"q": 1.0,'
check "gray card material removed" has '"clay_left": false'
check "light studio: repeated call replaces the rig" has '"rig": 3, "lights": 4'
# --- wishes from the A/B test: full result, section on a vertex row, camera compare without lights
o=$("$BL" run -e 'result={"xs": list(range(300))}' --name big); check "long result clipped, points to full result" has "full result: --json"
check "full result stored in run.json" grep -q '298, 299\]' "$BL_ROOT"/test-box/*/scripts/*_big.run.json
o=$("$BL" run -e 'result={"xs": list(range(300))}' --name big --json); check "--json prints the full result" has '298, 299\]\}'
"$BL" run -e 'bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.4, depth=1, location=(3,0,0.5)); bpy.context.object.name="Cyl"' >/dev/null
o=$("$BL" look --section y=0 --obj Cyl --size 300); check "section on a vertex row: plane moved and said so" has "moved [0-9.e-]+ mm off a vertex row"
img=$(grep -o "/[^ ]*section-y0[^ ]*\.png" <<<"$o")
o=$("$BL" run -e "from PIL import Image; px=list(Image.open('$img').convert('RGB').getdata()); result={'red': sum(1 for r,g,b in px if r-g>50 and r-b>50)}")
check "section on a vertex row: cut face red" has '"red": [0-9]{3,}'
o=$("$BL" look --section y=100 --obj Cyl --size 300); check "section off vertex rows: plane not moved" hasnt "off a vertex row"
"$BL" run -e 'L=[o for o in bpy.context.scene.objects if o.type=="LIGHT"]; st=[o.hide_render for o in L]
for o in L: o.hide_render=True
bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath("//") + "../nolight.blend" if bpy.data.filepath else "/tmp/x.blend", copy=True)
for o, h in zip(L, st): o.hide_render=h
result={"f": bpy.data.filepath}' >/dev/null
nl=$(ls "$BL_ROOT"/test-box/*/nolight.blend 2>/dev/null | head -1)
o=$("$BL" look --mode cam --compare "$nl" --size 160 --samples 2); check "cam compare against a state without lights: warning" has "comparison state has no lights"
o=$("$BL" look --mode cam --compare last --size 160 --samples 2); check "cam compare with lights: no such warning" hasnt "has no lights"
"$BL" run -e 'bpy.data.objects.remove(obj("Cyl"))' >/dev/null; rm -f "$nl"
# --- surface inspection: zebra / facing follow the shading normal
"$BL" run -e 'for i, flat in enumerate((0, 1)):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.5, location=(i * 1.2, 4, 0.5))
    o = bpy.context.object; o.name = ("ZFlat" if flat else "ZSmooth")
    if not flat: bpy.ops.object.shade_smooth()
result = {"vt": bpy.context.scene.view_settings.view_transform, "eng": bpy.context.scene.render.engine}' >/dev/null
st0=$("$BL" run -e 'result={"vt": bpy.context.scene.view_settings.view_transform, "eng": bpy.context.scene.render.engine, "ov": str(bpy.context.view_layer.material_override)}' | tail -1)
o=$("$BL" look --mode zebra --view front --obj ZSmooth --size 300 --stripes 8); check "zebra: image" has "_zebra|zebra"
zimg=$(grep -o "/[^ ]*\.png" <<<"$o")
o=$("$BL" run -e "from PIL import Image; im=Image.open('$zimg').convert('RGBA'); px=[p for p in im.crop((0,0,im.width,im.width)).getdata() if p[3]>0 and p[:3]!=(242,242,242)]
bw=sum(1 for r,g,b,a in px if max(r,g,b)<40 or min(r,g,b)>215); result={'bw': round(100*bw/max(len(px),1)), 'black': sum(1 for r,g,b,a in px if max(r,g,b)<40)>500, 'white': sum(1 for r,g,b,a in px if min(r,g,b)>215 and (r,g,b)!=(242,242,242))>500}")
check "zebra: black and white stripes" has '"bw": (9[0-9]|100), "black": true, "white": true'
o=$("$BL" look --mode zebra --view front --obj ZFlat --size 300); fimg=$(grep -o "/[^ ]*\.png" <<<"$o")
o=$("$BL" run -e "from PIL import Image, ImageChops; a=Image.open('$zimg').convert('L'); b=Image.open('$fimg').convert('L'); d=ImageChops.difference(a,b); result={'diff': round(100*sum(1 for v in d.getdata() if v>100)/(a.width*a.height),1)}")
check "zebra: flat shading looks different from smooth" has '"diff": ([3-9]|[1-9][0-9])'
o=$("$BL" look --mode facing --view front --obj ZSmooth --size 300); cimg=$(grep -o "/[^ ]*\.png" <<<"$o")
o=$("$BL" run -e "from PIL import Image; im=Image.open('$cimg').convert('HSV'); hs={h//32 for h,s,v in im.getdata() if s>120}; result={'hues': len(hs)}")
check "facing: rainbow bands" has '"hues": [5-8]'
o=$("$BL" run -e 'result={"vt": bpy.context.scene.view_settings.view_transform, "eng": bpy.context.scene.render.engine, "ov": str(bpy.context.view_layer.material_override)}' | tail -1)
check "zebra/facing: render settings restored" test "$o" = "$st0"
o=$("$BL" run -e 'result={"m": sorted(m.name for m in bpy.data.materials if m.name.startswith("_bl_"))}'); check "zebra/facing: no leftover material" has '"m": \[\]'
"$BL" run -e 'for n in ("ZFlat", "ZSmooth"): bpy.data.objects.remove(obj(n))' >/dev/null
# --- bl open switches scenes, protects unsaved changes
pid1=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['pid'])" "${XDG_STATE_HOME:-$HOME/.local/state}/bl/$BL_SESSION/worker.json")
o=$("$BL" open --empty 2>&1); rc=$?; check "open with changes → abort" bash -c "[ $rc -eq 2 ]"; check "open: message names unsaved changes" has "unsaved changes"
check "open: worker keeps running after abort" bash -c "kill -0 $pid1"
o=$("$BL" open "$BL_ROOT/doesnotexist.blend" --discard 2>&1); check "open wrong target: error" has "file missing"; check "open wrong target: worker stays" bash -c "kill -0 $pid1"
"$BL" run -e 'def broken(): raise RuntimeError("x")
bl.changed = broken' >/dev/null; "$BL" save >/dev/null
o=$("$BL" open --empty 2>&1); rc=$?; check "open state unknown → abort" bash -c "[ $rc -eq 2 ]"; check "open: message state unknown" has "state unknown"
"$BL" run -e 'bl.changed = lambda: bl._changed' >/dev/null
"$BL" save >/dev/null
o=$("$BL" open --empty); check "open switches after save" grep -q "scene empty" <<<"$o"
sleep 0.5; check "open: old worker stopped" bash -c "! kill -0 $pid1 2>/dev/null"
"$BL" run -e 'bpy.ops.mesh.primitive_cube_add()' >/dev/null
o=$("$BL" open --discard); check "open --discard loads the saved file" grep -q "test-box.blend" <<<"$o"
# --- bl qa finds built-in errors, a clean cube passes
"$BL" run -e 'import bmesh
m=bpy.data.materials.new("Q")
def cube(n, loc, size=1):
    bpy.ops.mesh.primitive_cube_add(size=size, location=loc); o=bpy.context.object; o.name=n; o.data.materials.append(m); return o
cube("QClean", (20,0,0.5))
o=cube("QHole", (23,0,0.5)); bm=bmesh.new(); bm.from_mesh(o.data); bm.faces.ensure_lookup_table(); bmesh.ops.delete(bm, geom=[bm.faces[0]], context="FACES_ONLY"); bm.to_mesh(o.data); bm.free()
o=cube("QFlipped", (26,0,0.5)); bm=bmesh.new(); bm.from_mesh(o.data); bmesh.ops.reverse_faces(bm, faces=bm.faces[:]); bm.to_mesh(o.data); bm.free()
cube("QFloating", (20,0,3), 0.2)
o=cube("QScaled", (29,0,1)); o.scale=(2,2,2)
me=bpy.data.meshes.new("QS"); bm=bmesh.new()
v=[bm.verts.new(p) for p in [(0,0,0),(1,0,0),(1,1,1),(0,1,1),(0.5,-0.00001,0)]]
bm.faces.new((v[0],v[1],v[2],v[3])); bm.faces.new((v[0],v[4],v[1])); bm.to_mesh(me); bm.free()
s=bpy.data.objects.new("QSliver",me); bpy.context.scene.collection.objects.link(s); s.location=(32,0,0); me.materials.append(m)' >/dev/null
o=$("$BL" qa --obj QClean --profile game 2>&1); rc=$?; check "qa: clean cube passes (exit 0)" bash -c "[ $rc -eq 0 ]"; check "qa: header passed" has "✓ qa passed · profile game · as one asset · tris 12"
check "qa: report in measurements/" has "measurements/[0-9]{3}_qa-game.json"
o=$("$BL" qa --obj QHole --profile print 2>&1); rc=$?; check "qa: hole → exit 1" bash -c "[ $rc -eq 1 ]"; check "qa: hole detected" has "ERROR   QHole: 4 open boundary edges"
o=$("$BL" qa --obj QFlipped --profile print 2>&1); check "qa: flipped normals" has "QFlipped: 1 closed parts with normals pointing inward"
o=$("$BL" qa --obj QClean --obj QFloating --profile render 2>&1); check "qa: floating part" has "floating/detached part in QFloating"
o=$("$BL" qa --obj QScaled --profile game 2>&1); check "qa: unapplied scale" has "ERROR   QScaled: unapplied scale"
o=$("$BL" qa --obj QSliver --profile render 2>&1); rc=$?; check "qa: sliver only a warning with render (exit 0)" bash -c "[ $rc -eq 0 ]"; check "qa: sliver warning" has "warning QSliver: broken faces slivers 1"
o=$("$BL" qa --obj QSliver --profile game 2>&1); rc=$?; check "qa: sliver an error with game (exit 1)" bash -c "[ $rc -eq 1 ]"; check "qa: sliver error" has "ERROR   QSliver: broken faces slivers 1"
o=$("$BL" qa --obj QClean --profile game --budget 10 2>&1); rc=$?; check "qa: poly budget" bash -c "[ $rc -eq 1 ]"; check "qa: poly budget message" has "poly budget exceeded: 12 tris > 10"
o=$("$BL" qa --obj DoesNotExist 2>&1); rc=$?; check "qa: unknown object → exit 2" bash -c "[ $rc -eq 2 ]"
o=$(BL_QA_DIR=/doesnotexist "$BL" qa 2>&1); rc=$?; check "qa: qa_check missing → exit 3" bash -c "[ $rc -eq 3 ]"
o=$("$BL" qa --budget 0 2>&1); rc=$?; check "qa: --budget 0 rejected" bash -c "[ $rc -eq 2 ]"
"$BL" run -e 'bpy.context.view_layer.objects.active=obj("QClean"); bpy.ops.object.mode_set(mode="EDIT")' >/dev/null
o=$("$BL" qa --obj QClean --profile game 2>&1); o=$("$BL" run -e 'result={"mode": bpy.context.object.mode, "active": bpy.context.view_layer.objects.active.name}')
check "qa: edit mode and active object preserved" has '"mode": "EDIT", "active": "QClean"'
"$BL" run -e 'bpy.ops.object.mode_set(mode="OBJECT")' >/dev/null
"$BL" run -e 'for n in ("QClean","QHole","QFlipped","QFloating","QScaled","QSliver"): bpy.data.objects.remove(obj(n))' >/dev/null
# --- qa without --obj checks each object separately (separate parts on a ground plane are not an error)
"$BL" open --empty --discard >/dev/null
"$BL" run -e 'm=bpy.data.materials.new("Q")
for n, x in (("Table", 0), ("Chair", 3)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x,0,0.5)); o=bpy.context.object; o.name=n; o.data.materials.append(m)
bpy.ops.mesh.primitive_plane_add(size=50); bpy.context.object.name="Ground"' >/dev/null
o=$("$BL" qa --profile game 2>&1); rc=$?; check "qa per object: table and chair pass separately" bash -c "[ $rc -eq 0 ]"; check "qa per object: header" has "each object separately"; check "qa per object: no floating" hasnt "floating"
o=$("$BL" qa --obj Table --obj Chair --profile game 2>&1); check "qa as one asset: separate parts → floating" has "floating"
"$BL" run -e 'bpy.ops.mesh.primitive_plane_add(size=0.4, location=(0,0,1.0)); o=bpy.context.object; o.name="Sticker"; o.data.materials.append(bpy.data.materials["Q"])' >/dev/null
o=$("$BL" qa --profile game 2>&1); rc=$?; check "qa per object: z-fighting between objects detected (exit 1)" bash -c "[ $rc -eq 1 ]"; check "qa per object: z-fighting pair" has "z-fighting: (Table<->Sticker|Sticker<->Table)"
"$BL" run -e 'bpy.data.objects.remove(obj("Sticker"))' >/dev/null
# --- close protects unsaved work, idle exit backs it up
o=$("$BL" close 2>&1); rc=$?; check "close with changes → abort" bash -c "[ $rc -eq 2 ]"; check "close: message" has "close --discard"
"$BL" save >/dev/null
idle_sd="${XDG_STATE_HOME:-$HOME/.local/state}/bl/$BL_SESSION-idle"
(
  export BL_SESSION="$BL_SESSION-idle" BL_IDLE=3
  "$BL" project "Test Box" >/dev/null; "$BL" open --empty >/dev/null
  sleep 7
)
check "idle without changes: no backup" test ! -e "$idle_sd/autosave.blend"
(
  export BL_SESSION="$BL_SESSION-idle" BL_IDLE=3
  "$BL" open --empty >/dev/null; "$BL" run -e 'bpy.ops.mesh.primitive_cube_add()' >/dev/null
  sleep 7
)
check "idle: backup written" test -s "$idle_sd/autosave.blend"
check "idle: no pending file left" test ! -e "$idle_sd/autosave.blend.pending"
o=$(BL_SESSION="$BL_SESSION-idle" "$BL" info 2>&1); rc=$?; check "idle: silent start aborts (does not continue on the old state)" bash -c "[ $rc -eq 2 ]"; check "idle: message names bl open" has "bl open .*autosave.blend"
o=$(BL_SESSION="$BL_SESSION-idle" "$BL" open "$idle_sd/autosave.blend" 2>&1); check "idle: bl open <backup> loads it" has "backup: .*autosave_[0-9-]+\.blend"
o=$(BL_SESSION="$BL_SESSION-idle" "$BL" info 2>&1); check "idle: cube from the backup is there" has "Cube"
BL_SESSION="$BL_SESSION-idle" "$BL" close --discard >/dev/null
o=$("$BL" ls); check "ls shows 2 versions" bash -c "[ \$(grep -c ' v00' <<<\"$o\") -eq 2 ]"
o=$(BL_ROOT=relative "$BL" ls 2>&1); check "relative BL_ROOT rejected" grep -q "absolute path" <<<"$o"
# --- bl docs (real data from .docs, no worker)
o=$("$BL" docs bpy.types.Object.matrix_world 2>&1); check "docs: exact name" has "attribute:: matrix_world" "Worldspace transformation matrix" ":type: mathutils.Matrix"
o=$("$BL" docs bmesh.ops.bevel 2>&1); check "docs: bmesh function with signature" has "function:: bevel\\(bm" "mark_sharp=False"
o=$("$BL" docs bpy.types.Mesh.name 2>&1); check "docs: member from base class ID" has "bpy.types.ID.rst" "attribute:: name"
o=$("$BL" docs bevel modifier --manual 2>&1); check "docs: manual search" has "manual/modeling/modifiers/generate/bevel.rst" "--manual --hit i"
o=$("$BL" docs bevel modifier --manual --hit 0 2>&1); check "docs: deepen a hit" has "^\\[0\\] manual/modeling/modifiers/generate/bevel.rst"
o=$("$BL" docs xyzzyqq plugh 2>&1); rc=$?; check "docs: nothing found → exit 1" bash -c "[ $rc -eq 1 ]"
o=$(BL_DOCS_DIR=/nonexistent "$BL" docs bevel 2>&1); rc=$?; check "docs: data missing → exit 3 with hint" bash -c "[ $rc -eq 3 ]"
o=$("$BL" doctor); check "doctor" grep -q "Blender 5.2" <<<"$o"; check "doctor: PIL ok" grep -q "PIL in worker: ok" <<<"$o"; check "doctor: docs ok" has "docs \(bl docs\): ok \(api [0-9]+, manual [0-9]+ files\)"
[ $fail -eq 0 ] && echo "== selftest OK" || echo "== selftest FAILED"
exit $fail
