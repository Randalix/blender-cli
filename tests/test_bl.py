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
            j1, n1 = core.journal_file(p, "Körper", "a = 1")
            self.assertEqual((j1.name, n1), ("001_koerper.py", True))
            self.assertEqual(j1.read_text(), "a = 1\n")
            j2, n2 = core.journal_file(p, "Körper", "a = 1\n")  # gleicher Inhalt, letzte Datei → wiederverwendet
            self.assertEqual((j2, n2), (j1, False))
            j3, n3 = core.journal_file(p, "henkel", "b = 2")
            self.assertEqual((j3.name, n3), ("002_henkel.py", True))
            j4, n4 = core.journal_file(p, "Körper", "a = 1")  # koerper → henkel → koerper: drei Läufe im Journal
            self.assertEqual((j4.name, n4), ("003_koerper.py", True))
            j5, n5 = core.journal_file(p, "Körper", "a = 1", {"n": 3})  # andere Werte → neue Datei + args.json
            self.assertEqual((j5.name, n5), ("004_koerper.py", True))
            self.assertEqual(json.loads((p / "004_koerper.args.json").read_text()), {"n": 3})
            j6, n6 = core.journal_file(p, "Körper", "a = 1", {"n": 3})  # gleiche Werte → wiederverwendet
            self.assertEqual((j6.name, n6), ("004_koerper.py", False))
            j7, n7 = core.journal_file(p, "Körper", "a = 1")  # ohne Werte ≠ {"n": 3}
            self.assertEqual((j7.name, n7), ("005_koerper.py", True))
            self.assertFalse((p / "005_koerper.args.json").exists())

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


if __name__ == "__main__":
    unittest.main()
