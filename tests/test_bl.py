"""Unit-Tests für bl/core.py (ohne Blender). Aufruf: <blender-python> -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bl"))
import core  # noqa: E402


class CoreTest(unittest.TestCase):
    def test_clean_label(self):
        self.assertEqual(core.clean_label("  Tür Griff v2!! "), "tuer-griff-v2")
        self.assertEqual(core.clean_label("///"), "ohne-label")
        self.assertEqual(len(core.clean_label("x" * 99)), 40)
        self.assertFalse(core.clean_label("a" * 39 + " b").endswith("-"))

    def test_session_key(self):
        self.assertEqual(core.session_key({"CODEMAN_SESSION_ID": "1ac48878-8b55"}), "1ac48878")
        self.assertEqual(core.session_key({"BL_SESSION": "a/b", "CODEMAN_SESSION_ID": "x"}), "a_b")
        self.assertEqual(core.session_key({}), "default")

    def test_versions_and_next(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            self.assertEqual(core.next_version_name(p, "Start"), "v001_start")
            for n in ("v001_a", "v010_b", "v002_c", "notes"):
                (p / n).mkdir()
            self.assertEqual([v.name for v in core.versions(p)], ["v001_a", "v002_c", "v010_b"])
            self.assertEqual(core.next_version_name(p, "Neu"), "v011_neu")

    def test_next_numbered(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            self.assertEqual(core.next_numbered(p, "x", ".py").name, "001_x.py")
            (p / "007_alt.py").write_text("")
            (p / "readme.txt").write_text("")
            self.assertEqual(core.next_numbered(p, "Mein Skript", ".py").name, "008_mein-skript.py")

    def test_newest_blend(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            for v in ("v001_a", "v002_b", "v003_c"):
                (p / v / "blend").mkdir(parents=True)
            (p / "v001_a/blend/x.blend").write_text("")
            self.assertEqual(core.newest_blend(p).name, "x.blend")
            (p / "v002_b/blend/y.blend").write_text("")
            self.assertEqual(core.newest_blend(p, p / "v003_c").parent.parent.name, "v002_b")
            self.assertEqual(core.newest_blend(p, p / "v001_a").parent.parent.name, "v001_a")

    def test_error_line(self):
        tb = ('Traceback (most recent call last):\n  File "<string>", line 2, in <module>\n'
              '  File "/x/bllib.py", line 90, in run_file\n  File "/p/skripte/003_box.py", line 7, in <module>\n'
              '  File "/x/bllib.py", line 30, in obj\nKeyError: "Objekt \'Kiste\' fehlt"')
        self.assertEqual(core.error_line(tb, "/p/skripte/003_box.py"), '003_box.py:7: KeyError: "Objekt \'Kiste\' fehlt"')
        self.assertTrue(core.error_line(tb).startswith("bllib.py:30"))
        self.assertEqual(core.error_line("SyntaxError: x"), "SyntaxError: x")

    def test_journal_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            lauf = lambda n: json.loads((p / n).read_text())  # noqa: E731
            j1, n1 = core.journal_file(p, "Körper", "a = 1")
            self.assertEqual((j1.name, n1), ("001_koerper.py", True))
            self.assertEqual(j1.read_text(), "a = 1\n")
            self.assertEqual(lauf("001_koerper.lauf.json"), {"args": {}, "runs": 0, "failed": 0})
            self.assertEqual(core.journal_count(j1, ok=False), 0)  # fehlgeschlagen zählt nicht als Lauf
            j2, n2 = core.journal_file(p, "Körper", "a = 1\n")  # gleicher Inhalt, letzte Datei → wiederverwendet
            self.assertEqual((j2, n2), (j1, False))
            self.assertEqual(core.journal_count(j2), 1)
            self.assertEqual(core.journal_count(j2), 2)
            self.assertEqual(lauf("001_koerper.lauf.json"), {"args": {}, "runs": 2, "failed": 1})
            j3, n3 = core.journal_file(p, "henkel", "b = 2")
            self.assertEqual((j3.name, n3), ("002_henkel.py", True))
            j4, n4 = core.journal_file(p, "Körper", "a = 1")  # koerper → henkel → koerper: eigener Eintrag
            self.assertEqual((j4.name, n4), ("003_koerper.py", True))
            j5, n5 = core.journal_file(p, "Körper", "a = 1", {"n": 3})  # andere Werte → neue Datei
            self.assertEqual((j5.name, n5), ("004_koerper.py", True))
            self.assertEqual(lauf("004_koerper.lauf.json")["args"], {"n": 3})
            self.assertEqual(core.journal_file(p, "Körper", "a = 1", {"n": 3}), (j5, False))
            j7, n7 = core.journal_file(p, "Körper", "a = 1", {"n": True})  # true ≠ 1
            self.assertEqual((j7.name, n7), ("005_koerper.py", True))
            (p / "005_koerper.lauf.json").write_text("{kaputt")  # kaputte Zähldatei → neue Datei statt Traceback
            j8, n8 = core.journal_file(p, "Körper", "a = 1", {"n": True})
            self.assertEqual((j8.name, n8), ("006_koerper.py", True))
            self.assertEqual(core.journal_count(j7), 1)

    def test_parse_set(self):
        self.assertEqual(core.parse_set(["n=3", "f=0.5", "l=[1,2]", "s=abc", "t=true", "leer="]),
                         {"n": 3, "f": 0.5, "l": [1, 2], "s": "abc", "t": True, "leer": ""})
        self.assertEqual(core.parse_set(None), {})
        for bad in ("ohne", "1x=2", "=3", "x=NaN", "x=1e999", "x=[1,-Infinity]"):
            with self.assertRaises(ValueError):
                core.parse_set([bad])

    def test_parse_section(self):
        self.assertEqual(core.parse_section("x=0"), ("x", 0.0))
        self.assertEqual(core.parse_section(" z = -12.5"), ("z", -12.5))
        for bad in ("x0", "w=1", "y=abc", ""):
            with self.assertRaises(ValueError):
                core.parse_section(bad)

    def test_clip(self):
        self.assertEqual(core.clip_lines(range(5), 3), [0, 1, 2, "… +2 weitere Zeilen"])
        self.assertEqual(core.clip_text("abcdef", 4), "abc…")
        self.assertEqual(core.image_tokens(768, 800), 819)


class TestDocs(unittest.TestCase):
    """bl docs: exakte Namen aus RST (ohne Blender, ohne echte Daten)."""

    def setUp(self):
        import docs
        self.docs = docs
        self.tmp = tempfile.TemporaryDirectory()
        api = Path(self.tmp.name) / "api"
        api.mkdir()
        (api / "bpy.types.ID.rst").write_text(
            "ID(bpy_struct)\n==============\n\n.. class:: ID(bpy_struct)\n\n   Base type\n\n"
            "   .. attribute:: name\n\n      Unique data-block ID name (default \"\")\n\n      :type: str\n")
        (api / "bpy.types.Object.rst").write_text(
            "Object(ID)\n==========\n\nbase classes --- :class:`bpy_struct`, :class:`ID`\n\n"
            ".. class:: Object(ID)\n\n   Object data-block\n\n"
            "   .. attribute:: matrix_world\n\n      Worldspace transformation matrix\n\n      :type: :class:`mathutils.Matrix`\n\n"
            "   .. data:: mode\n\n      Object interaction mode (default ``'OBJECT'``, readonly)\n\n      :type: str\n\n"
            "   .. method:: select_set(state, *, view_layer=None)\n\n      Select or deselect the object.\n")
        (api / "bmesh.ops.rst").write_text(
            "BMesh Operators (bmesh.ops)\n===========================\n\n.. module:: bmesh.ops\n\n"
            ".. function:: bevel(bm, geom, offset)\n\n   Bevel.\n\n.. function:: bisect_edges(bm, edges, cuts)\n\n   Split.\n")
        self.api = api

    def tearDown(self):
        self.tmp.cleanup()

    def test_attribut(self):
        f, lines = self.docs.lookup("bpy.types.Object.matrix_world", self.api)
        self.assertEqual(f.name, "bpy.types.Object.rst")
        self.assertEqual(lines[0], ".. attribute:: matrix_world")
        self.assertIn("Worldspace transformation matrix", lines)
        self.assertNotIn("mode", " ".join(lines))  # nächstes Mitglied gehört nicht dazu

    def test_ohne_praefix_und_methode(self):
        _f, lines = self.docs.lookup("Object.select_set", self.api)
        self.assertIn("select_set(state", lines[0])

    def test_basisklasse(self):
        f, lines = self.docs.lookup("bpy.types.Object.name", self.api)
        self.assertEqual(f.name, "bpy.types.ID.rst")
        self.assertIn(":type: str", lines)

    def test_klasse_kurz(self):
        _f, lines = self.docs.lookup("bpy.types.Object", self.api)
        self.assertIn("Mitglieder (3): matrix_world, mode, select_set", lines)

    def test_modul_funktion(self):
        _f, lines = self.docs.lookup("bmesh.ops.bevel", self.api)
        self.assertEqual(lines[0], ".. function:: bevel(bm, geom, offset)")
        self.assertNotIn("Split.", lines)
        _f, lines = self.docs.lookup("bmesh.ops", self.api)
        self.assertIn("bevel, bisect_edges", lines[-1])

    def test_unbekannt(self):
        self.assertIsNone(self.docs.lookup("bpy.types.Object.gibtsnicht", self.api))
        self.assertIsNone(self.docs.lookup("bevel", self.api))

    def test_clean(self):
        self.assertEqual(self.docs.clean(":type: :class:`mathutils.Matrix` (default ``'OBJECT'``)"),
                         ":type: mathutils.Matrix (default 'OBJECT')")


if __name__ == "__main__":
    unittest.main()
