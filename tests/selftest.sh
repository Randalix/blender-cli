#!/usr/bin/env bash
# Selbsttest bl mit echtem Blender: Wegwerf-Ablage und eigene Sitzung, räumt hinterher auf.
set -u
here="$(cd "$(dirname "$0")/.." && pwd)"
BL="$here/bin/bl"
mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}"
BL_ROOT="$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" bl-selftest.XXXX)" || { echo "mktemp fehlgeschlagen"; exit 3; }
[ -d "$BL_ROOT" ] || { echo "BL_ROOT fehlt"; exit 3; }
export BL_ROOT BL_SESSION="selftest-$$"
fail=0
ok()   { echo "  ok   $*"; }
bad()  { echo "  FAIL $*"; fail=1; }
check(){ local d="$1"; shift; if "$@"; then ok "$d"; else bad "$d"; fi; }
has(){ local m; for m in "$@"; do grep -qE -- "$m" <<<"$o" || return 1; done; }  # alle Muster in $o
cleanup(){ "$BL" close >/dev/null 2>&1; rm -rf "$BL_ROOT" "${XDG_STATE_HOME:-$HOME/.local/state}/bl/$BL_SESSION"; }
trap cleanup EXIT

echo "== bl selftest (BL_ROOT=$BL_ROOT)"
o=$("$BL" projekt "Test Kiste"); check "projekt legt v001_start an" grep -q "v001_start" <<<"$o"
o=$("$BL" open); check "open leere Szene" grep -q "Szene leer" <<<"$o"
pid=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['pid'])" "${XDG_STATE_HOME:-$HOME/.local/state}/bl/$BL_SESSION/worker.json")
o=$("$BL" info); check "info: leere Szene" grep -q "Objekte 0" <<<"$o"
o=$("$BL" run -e 'bpy.ops.mesh.primitive_cube_add(size=1); k=bpy.context.object; k.name="Kiste"
m=k.modifiers.new("Bevel","BEVEL"); m.width=0.05; m.segments=3; report(k); result={"faces": mesh_stats(k)["f"]}' --name kiste --report)
check "run -e: result" grep -q '"faces": 98' <<<"$o"
check "run --report: Zeile" grep -q "Kiste  MESH  v .* f 98" <<<"$o"
check "Skript protokolliert" test -f "$BL_ROOT/test-kiste/v001_start/skripte/001_kiste.py"
o=$("$BL" run -e 'k=obj("Kiste"); k.location.z=2; print("z", k.location.z)'); check "Szene bleibt offen" grep -q "| z 2.0" <<<"$o"
# --- Phase 2 A2/A3: Kette, --set, Journal ohne identische Kopien
printf 'result = {"a": args.get("n", 0) * 2}\n' > "$BL_ROOT/ka.py"
printf 'bpy.app.driver_namespace["bl_kb"] = args.get("name", "-"); result = {"b": args.get("name", "-")}\n' > "$BL_ROOT/kb.py"
o=$("$BL" run "$BL_ROOT/ka.py" "$BL_ROOT/kb.py" --set n=21 --set name=Tasse)
check "run Kette: beide Skripte, --set" has '"a": 42' '"b": "Tasse"'
o=$("$BL" run "$BL_ROOT/ka.py" --set n=1); check "Journal: gleicher Inhalt wiederverwendet" grep -q "_ka.py (unverändert" <<<"$o"
check "Journal: keine zweite ka-Kopie" bash -c "[ \$(ls \"$BL_ROOT\"/test-kiste/v001_start/skripte/ | grep -c '_ka.py') -eq 1 ]"
printf 'raise ValueError("kaputt")\n' > "$BL_ROOT/kf.py"
printf 'bpy.app.driver_namespace["bl_kc"] = 1\n' > "$BL_ROOT/kc.py"
o=$("$BL" run "$BL_ROOT/ka.py" "$BL_ROOT/kf.py" "$BL_ROOT/kc.py" 2>&1); rc=$?
check "Kette: Fehler → Exit 2" bash -c "[ $rc -eq 2 ]"; check "Kette: Abbruch gemeldet" has "Kette abgebrochen bei Skript 2/3; nicht ausgeführt: kc"
o=$("$BL" run -e 'result={"kc": "bl_kc" in bpy.app.driver_namespace}'); check "Kette: Skript nach Fehler nicht gelaufen" grep -q '"kc": false' <<<"$o"
o=$("$BL" run -e 'result={"h": bl.hits((0, 0, 5000), (0, 0, -1)), "sb": list(bl._scale_bar(0.4, 768))}')
check "A6 bl.hits: Ober- und Unterseite der Kiste (mm)" grep -q '"h": \[\[0.0, 0.0, 2500.0\], \[0.0, 0.0, 1500.0\]\]' <<<"$o"
check "A5 Maßstabsbalken 0,4 mm/px × 768 → 50 mm, 125 px" grep -q '"sb": \[50, 125\]' <<<"$o"
o=$("$BL" look --section z=2000 --obj Kiste --size 300); img=$(grep -o '/[^ ]*\.png' <<<"$o")
check "A4 section: Bild" bash -c "grep -q schnitt-z2000 <<<'$o' && test -s '$img'"
o=$("$BL" run -e 'from PIL import Image
im=Image.open(r"'"$img"'").convert("RGB"); px=list(im.getdata())
result={"rot": sum(1 for r,g,b in px if r-g>50 and r-b>50), "objs": sorted(o.name for o in bpy.data.objects), "mats": len(bpy.data.materials), "meshes": len(bpy.data.meshes)}')
check "A4 section: rote Schnittfläche sichtbar" has '"rot": [0-9]{3,}'
check "A4 section: räumt auf" has '"objs": \["Kiste"\]' '"meshes": 1'
o=$("$BL" look --section q=1 2>&1); check "A4 section: falsche Achse → Fehler" bash -c "grep -q 'x=MM, y=MM oder z=MM' <<<\"$o\""
printf 'x = 1\ny = obj("Gibtsnicht")\n' > "$BL_ROOT/fehler.py"
o=$("$BL" run "$BL_ROOT/fehler.py" 2>&1); rc=$?
check "Fehler → Exit 2" test $rc -eq 2
check "Fehlerskript protokolliert" bash -c "ls \"$BL_ROOT\"/test-kiste/v001_start/skripte/ | grep -q _fehler.py"
check "Fehlerzeile mit Datei:Zeile" grep -q "fehler.py:2: KeyError" <<<"$o"
o=$("$BL" info --obj Kiste); check "info --obj: Bevel" grep -q "mod Bevel (bevel) width=0.05 segments=3" <<<"$o"
o=$("$BL" look --sheet --size 512); check "look --sheet" grep -q "512×552 px" <<<"$o"
img=$(grep -o '/[^ ]*\.png' <<<"$o"); check "Bild existiert" test -s "$img"
o=$("$BL" look --mode wire --obj Kiste --size 400); check "look wire" grep -q "400×440 px" <<<"$o"
o=$("$BL" run -e 'result={"objs": sorted(o.name for o in bpy.data.objects)}'); check "look räumt auf (keine _bl_-Objekte)" grep -q '"objs": \["Kiste"\]' <<<"$o"
o=$("$BL" run -e 'bpy.ops.mesh.primitive_cube_add(size=0.2, location=(1.5,0,0.5)); bpy.context.object.name="Marke"
from PIL import Image
def seite(v):
    r=bl.look(r"'"$BL_ROOT"'/o_"+v+".png", views=[v], panel=200); im=Image.open(r["path"]).convert("L")
    xs=[x for x in range(200) for y in range(0,200,4) if im.getpixel((x,y))<200]
    return sum(xs)/len(xs) > 100
result={"top_wie_front": seite("top")==seite("front"), "bottom_wie_front": seite("bottom")==seite("front")}
bpy.data.objects.remove(obj("Marke"))'); check "top/bottom: +X auf derselben Seite wie front" grep -q '"top_wie_front": true, "bottom_wie_front": true' <<<"$o"
o=$("$BL" save); check "save" grep -q "v001_start/blend/test-kiste.blend" <<<"$o"
o=$("$BL" version "Zweiter Stand"); check "version speichert Startstand" grep -q "v002_zweiter-stand/blend/test-kiste_start.blend" <<<"$o"
o=$("$BL" close); check "close" grep -q "Worker beendet" <<<"$o"
sleep 0.5; check "kein Prozess übrig" bash -c "! kill -0 $pid 2>/dev/null"
o=$("$BL" info); check "Auto-Open lädt neueste Datei" grep -q "v002_zweiter-stand/blend/test-kiste_start.blend" <<<"$o"
check "Kiste nach Neustart da, z=2" bash -c "\"$BL\" info --obj Kiste | grep -q 'loc (0.0, 0.0, 2.0)'"
o=$("$BL" look --compare --size 400); check "compare ohne Änderung: 0 %" grep -q "iso 0.0 %" <<<"$o"
check "compare ohne Änderung: Warnung" grep -q "kaum sichtbare Änderung" <<<"$o"
"$BL" run -e 'obj("Kiste").scale.x = 1.6' >/dev/null
o=$("$BL" look --compare --view iso --view top --size 400); check "compare nach Änderung: Bild 2×200+4 breit" grep -q "404×" <<<"$o"
check "compare nach Änderung: >1 %, keine Warnung" bash -c "grep -qE 'iso [1-9][0-9]*\.[0-9] %' <<<\"$o\" && ! grep -q 'kaum sichtbar' <<<\"$o\""
o=$("$BL" run -e 'result={"objs": sorted(o.name for o in bpy.data.objects), "meshes": len(bpy.data.meshes)}'); check "compare räumt auf" grep -q '"objs": \["Kiste"\], "meshes": 1' <<<"$o"
o=$("$BL" look --mode wire --compare --size 400); check "compare wire" grep -q "Vergleich mit" <<<"$o"
"$BL" save >/dev/null; o=$("$BL" look --compare --size 400); check "compare nach save nutzt Startstand" bash -c "grep -q 'test-kiste_start.blend' <<<\"$o\" && ! grep -q 'kaum sichtbar' <<<\"$o\""
o=$("$BL" look --compare "$BL_ROOT/test-kiste/v002_zweiter-stand/blend/test-kiste.blend" --size 400); check "compare gegen gespeicherten Stand: 0 %" grep -q "iso 0.0 %" <<<"$o"
o=$("$BL" look --focus Kiste --radius 100 --size 400); check "focus: feinerer Maßstab" bash -c "grep -qE '1 px = 0\.[0-9]+ mm' <<<\"$o\""
o=$("$BL" look --focus 0,0,2000 --size 400 2>&1); rc=$?; check "focus Punkt ohne radius → Fehler" bash -c "[ $rc -eq 2 ] && grep -q 'braucht --radius' <<<\"$o\""
o=$("$BL" look --focus 500,500,2500 --radius 200 --compare --size 400); check "focus in mm + compare" bash -c "grep -q 'Vergleich mit' <<<\"$o\" && ! grep -q LEER <<<\"$o\""
o=$("$BL" look --focus 0.5,0.5,2.5 --radius 50 --size 400); check "focus daneben → Warnung LEER" grep -q "LEER" <<<"$o"
o=$("$BL" look --compare last --size 400); check "compare last: gegen bl-save-Stand 0 %" grep -q "iso 0.0 %" <<<"$o"
o=$("$BL" look --compare start --size 400); check "compare start" grep -q "test-kiste_start.blend" <<<"$o"
o=$("$BL" look --obj Kiste --compare --size 400 2>&1); check "compare mit --obj" grep -q "Vergleich mit" <<<"$o"
o=$("$BL" run -e 'import bmesh
me=bpy.data.meshes.new("S"); bm=bmesh.new()
v=[bm.verts.new(p) for p in [(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0.5,-0.00001,0),(0.5,1.5,0)]]
bm.faces.new((v[0],v[3],v[2],v[1])); bm.faces.new((v[0],v[1],v[4])); bm.to_mesh(me)
s=bpy.data.objects.new("Splitter",me); bpy.context.scene.collection.objects.link(s); s.location=(5,0,0)
me2=bpy.data.meshes.new("N"); bm2=bmesh.new(); import math
vs=[bm2.verts.new((math.cos(i/6*math.tau), math.sin(i/6*math.tau), 0)) for i in range(6)]; bm2.faces.new(vs); bm2.to_mesh(me2)
n=bpy.data.objects.new("Sechseck",me2); bpy.context.scene.collection.objects.link(n); n.location=(8,0,0)
report(s, n); result={"s": mesh_stats(s), "n": mesh_stats(n)}' --report)
check "mesh_stats: Splitter erkannt" grep -q '"splitter": 1' <<<"$o"
check "summary: FEHLER bei Splitter" grep -q "Splitter  MESH .*FEHLER splitter 1" <<<"$o"
check "N-Gon ist kein Fehler" bash -c "grep -q 'Sechseck  MESH' <<<\"$o\" && ! grep -q 'Sechseck.*FEHLER' <<<\"$o\""
o=$("$BL" info --obj Sechseck); check "info: N-Gons als Info" grep -q "N-Gons 1 (Info)" <<<"$o"
o=$("$BL" look --mode wire --obj Splitter --size 300); img=$(grep -o '/[^ ]*\.png' <<<"$o")
o=$("$BL" run -e 'from PIL import Image
im=Image.open(r"'"$img"'").convert("L"); w,h=im.width,im.height-40
rand=[im.getpixel((x,y)) for x in range(w) for y in range(h) if (x<10 or x>w-10 or y<10 or y>h-10) and not (x<120 and y<30) and not (x>w-160 and y>h-40)]
result={"dunkel_am_rand": sum(1 for p in rand if p<120)}')
check "wire: keine Strahlen am Splitter" grep -q '"dunkel_am_rand": 0' <<<"$o"
"$BL" run -e 'bpy.data.objects.remove(obj("Splitter")); bpy.data.objects.remove(obj("Sechseck"))' >/dev/null
"$BL" run -e 'bpy.ops.mesh.primitive_plane_add(size=50); bpy.context.object.name="Boden"' >/dev/null
o=$("$BL" look --size 400); check "Boden aus Rahmung genommen" grep -q "Boden nicht gerahmt" <<<"$o"
check "Maßstab bleibt fein (< 10 mm/px)" bash -c "grep -qE '1 px = [0-9]\.[0-9]+ mm' <<<\"$o\""
# --- Phase 2 A1/C: Kamera-Vergleich mit Licht des alten Stands, Engine-Wahl
"$BL" run -e 'c=bpy.data.objects.new("Kam", bpy.data.cameras.new("Kam")); bpy.context.scene.collection.objects.link(c)
c.location=(0,-8,4); c.rotation_euler=(math.radians(65),0,0); bpy.context.scene.camera=c
L=bpy.data.objects.new("Sonne", bpy.data.lights.new("Sonne","SUN")); bpy.context.scene.collection.objects.link(L); L.data.energy=5
w=bpy.context.scene.world or bpy.data.worlds.new("W"); bpy.context.scene.world=w; w.use_nodes=True
next(n for n in w.node_tree.nodes if n.type=="BACKGROUND").inputs["Strength"].default_value=0.05' >/dev/null
"$BL" save >/dev/null
"$BL" run -e 'obj("Sonne").data.energy=0.2' >/dev/null
o=$("$BL" look --mode cam --compare last --size 200 --samples 4)
check "A1 cam-compare: Lichtänderung sichtbar (alter Stand mit altem Licht)" bash -c "grep -qE 'cam ([1-9][0-9]*\.[0-9]) %' <<<\"$o\" && ! grep -q 'kaum sichtbar' <<<\"$o\""
o=$("$BL" run -e 'result={"lights": sorted(o.name for o in bpy.context.scene.objects if o.type=="LIGHT"), "e": round(obj("Sonne").data.energy, 3), "scenes": len(bpy.data.scenes), "worlds": len(bpy.data.worlds), "welt_gesetzt": bpy.context.scene.world is not None and bpy.context.scene.world.library is None and not bpy.context.scene.world.name.endswith(".001")}')
check "A1 cam-compare räumt auf (Licht, Welt, Szene)" has '"lights": \["Sonne"\], "e": 0.2, "scenes": 1, "worlds": 1, "welt_gesetzt": true'
o=$("$BL" look --mode cam --engine cycles --samples 2 --size 160); check "C --engine cycles" bash -c "grep -q 'Bild' <<<\"$o\""
o=$("$BL" run -e 'result={"engine": bpy.context.scene.render.engine}'); check "C Engine danach zurückgesetzt" bash -c "! grep -q CYCLES <<<\"$o\""
o=$("$BL" look --engine cycles 2>&1); check "C --engine ohne cam → Fehler" grep -q "nur mit --mode cam" <<<"$o"
# --- Phase 2 A7: bl open schaltet um, schützt ungespeicherte Änderungen
pid1=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['pid'])" "${XDG_STATE_HOME:-$HOME/.local/state}/bl/$BL_SESSION/worker.json")
o=$("$BL" open --leer 2>&1); rc=$?; check "A7 open bei Änderungen → Abbruch" bash -c "[ $rc -eq 2 ]"; check "A7 Meldung nennt ungespeicherte Änderungen" has "ungespeicherte Änderungen"
check "A7 Worker läuft nach Abbruch weiter" bash -c "kill -0 $pid1"
"$BL" save >/dev/null
o=$("$BL" open --leer); check "A7 open schaltet nach save um" grep -q "Szene leer" <<<"$o"
sleep 0.5; check "A7 alter Worker beendet" bash -c "! kill -0 $pid1 2>/dev/null"
"$BL" run -e 'bpy.ops.mesh.primitive_cube_add()' >/dev/null
o=$("$BL" open --verwerfen); check "A7 open --verwerfen lädt gespeicherte Datei" grep -q "test-kiste.blend" <<<"$o"
o=$("$BL" ls); check "ls zeigt 2 Versionen" bash -c "[ \$(grep -c ' v00' <<<\"$o\") -eq 2 ]"
o=$(BL_ROOT=relativ "$BL" ls 2>&1); check "relatives BL_ROOT abgelehnt" grep -q "absoluter Pfad" <<<"$o"
o=$("$BL" doctor); check "doctor" grep -q "Blender 5.2" <<<"$o"; check "doctor: PIL ok" grep -q "PIL im Worker: ok" <<<"$o"
[ $fail -eq 0 ] && echo "== selftest OK" || echo "== selftest FEHLGESCHLAGEN"
exit $fail
