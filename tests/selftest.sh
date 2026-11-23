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
"$BL" save >/dev/null; o=$("$BL" look --compare --size 400); check "compare nach save: gegen gespeicherten Stand 0 %" grep -q "iso 0.0 %" <<<"$o"
o=$("$BL" look --compare "$BL_ROOT/test-kiste/v002_zweiter-stand/blend/test-kiste_start.blend" --size 400); check "compare gegen Startstand: Änderung bleibt sichtbar" bash -c "! grep -q 'kaum sichtbar' <<<\"$o\""
"$BL" run -e 'bpy.ops.mesh.primitive_plane_add(size=50); bpy.context.object.name="Boden"' >/dev/null
o=$("$BL" look --size 400); check "Boden aus Rahmung genommen" grep -q "Boden nicht gerahmt" <<<"$o"
check "Maßstab bleibt fein (< 10 mm/px)" bash -c "grep -qE '1 px = [0-9]\.[0-9]+ mm' <<<\"$o\""
o=$("$BL" ls); check "ls zeigt 2 Versionen" bash -c "[ \$(grep -c ' v00' <<<\"$o\") -eq 2 ]"
o=$(BL_ROOT=relativ "$BL" ls 2>&1); check "relatives BL_ROOT abgelehnt" grep -q "absoluter Pfad" <<<"$o"
o=$("$BL" doctor); check "doctor" grep -q "Blender 5.2" <<<"$o"; check "doctor: PIL ok" grep -q "PIL im Worker: ok" <<<"$o"
[ $fail -eq 0 ] && echo "== selftest OK" || echo "== selftest FEHLGESCHLAGEN"
exit $fail
