import json
import pathlib
import sys
import tempfile
import unittest

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import sheets


def recs(n_photos, n_videos=0, days=1):
    out = []
    videos = 0
    for i in range(n_photos + n_videos):
        kind = "photo"
        if videos < n_videos and i % 4 == 0:
            kind = "video"
            videos += 1
        out.append({"id": f"r{i:03d}", "path": f"/x/{i}", "kind": kind, "time_art": f"2025-06-1{i % days}T10:{i % 60:02d}:00+02:00",
                    "day": f"2025-06-1{i % days}", "dur": 10, "has_audio": False, "code": ("V" if kind == "video" else "P") + str(i)})
    return out


class Layouts(unittest.TestCase):
    def test_presets_geometry(self):
        s, l = sheets.Layout("standard"), sheets.Layout("low")
        self.assertEqual((s.pw, s.ph, s.vw, s.vh, s.frames), (192, 144, 160, 90, 6))
        self.assertEqual((l.pw, l.ph, l.vw, l.vh, l.frames), (160, 120, 144, 81, 4))
        self.assertLessEqual(l.max_h, 1200)
        self.assertGreater(s.label_w, 0)
        self.assertGreater(l.label_w, 0)

    def test_unknown_preset(self):
        with self.assertRaises(ValueError):
            sheets.Layout("ultra")

    def test_every_sheet_stays_under_the_token_cap(self):
        for name in sheets.PRESETS:
            L = sheets.Layout(name)
            for sh in sheets.plan(L, recs(120, 30, days=2)):
                self.assertLessEqual(sheets.tokens_of(L.width, sh["height"]), L.max_tokens, (name, sh["name"]))
                self.assertLessEqual(sh["height"], L.max_px)

    def test_low_is_cheaper_than_standard_for_the_same_items(self):
        r = recs(100, 20)
        std = sheets.estimate(sheets.Layout("standard"), r)["tokens_est"]
        low = sheets.estimate(sheets.Layout("low"), r)["tokens_est"]
        self.assertLess(low, std)

    def test_sheets_never_mix_days_and_cover_every_item(self):
        L = sheets.Layout("low")
        r = recs(60, 6, days=3)
        planned = sheets.plan(L, r)
        self.assertEqual(sum(len(s["codes"]) for s in planned), len(r))
        for s in planned:
            self.assertTrue(s["name"].startswith(s["day"]))


class Build(unittest.TestCase):
    def setUp(self):
        self.proj = pathlib.Path(tempfile.mkdtemp(prefix="sheets."))
        (self.proj / "inv").mkdir()
        media = []
        for i in range(8):
            p = self.proj / f"p{i}.jpg"
            Image.new("RGB", (400, 300), (i * 20, 90, 120)).save(p)
            media.append({"id": f"p{i}", "path": str(p), "kind": "photo", "time_art": f"2025-06-11T10:0{i}:00+02:00", "day": "2025-06-11",
                          "dur": None, "has_audio": None, "exclude_reason": "screenshot" if i == 7 else None, "keep_in_burst": True})
        (self.proj / "inv" / "media.json").write_text(json.dumps(media))

    def test_manifest_reports_total_and_respects_prefilter(self):
        res = sheets.build(self.proj, {}, "low", log=lambda *a, **k: None)
        self.assertEqual(res["n_items"], 7)
        man = json.loads((self.proj / "sheets" / "manifest.json").read_text())
        self.assertEqual(man["total_tokens_est"], sum(s["tokens_est"] for s in man["sheets"].values()))
        self.assertEqual(man["preset"], "low")
        self.assertEqual(man["frames"], 4)
        (self.proj / "inv" / "prefilter.json").write_text(json.dumps({"kept": ["p0", "p1", "p7"]}))
        res = sheets.build(self.proj, {}, "low", log=lambda *a, **k: None)
        self.assertEqual(res["n_items"], 3)
        self.assertTrue(res["prefilter"])

    def test_changing_preset_rerenders(self):
        sheets.build(self.proj, {}, "low", log=lambda *a, **k: None)
        with Image.open(self.proj / "sheets" / "2025-06-11-01.jpg") as im:
            first = im.size
        sheets.build(self.proj, {}, "standard", log=lambda *a, **k: None)
        with Image.open(self.proj / "sheets" / "2025-06-11-01.jpg") as im:
            self.assertNotEqual(im.size, first)

    def test_only_keeps_original_codes(self):
        res = sheets.build(self.proj, {}, "low", out=self.proj / "p2", only={"P2", "P5"}, log=lambda *a, **k: None)
        idx = json.loads((self.proj / "p2" / "index.json").read_text())
        self.assertEqual(sorted(idx["codes"]), ["P2", "P5"])
        self.assertEqual(res["n_items"], 2)


if __name__ == "__main__":
    unittest.main()
