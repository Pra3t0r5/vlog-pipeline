import copy
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import edl_check

CFG = {"duration": {"floor_min": 0.1, "ceil_min": 5}, "edit": {"drone_share_max": 0.6}}


def media(i, kind="photo", source="phone", dur=None, **kw):
    m = {"id": i, "kind": kind, "source": source, "dur": dur, "exclude_reason": None}
    m.update(kw)
    return m


INP = {
    "media": {m["id"]: m for m in [media("p1"), media("p2"), media("p3"), media("v1", "video", "phone", 20), media("d1", "video", "drone", 30),
                                    media("bad", exclude_reason="screenshot")]},
    "codes": {"P1": "p1", "P2": "p2", "P3": "p3", "V1": "v1", "V2": "d1", "P9": "bad"},
    "triage": {"P1": {"keep": 3, "avoid": None}, "P2": {"keep": 1, "avoid": None}, "P3": {"keep": 2, "avoid": "cansancio"},
               "V1": {"keep": 2, "avoid": None}, "V2": {"keep": 2, "avoid": None}, "P9": {"keep": 2, "avoid": None}},
    "sharpness": {"p1": {"z": 0.5, "blurry": False, "motion_blur": False}, "p2": {"z": -2.0, "blurry": True, "motion_blur": False}},
    "variants": [], "captions": {}, "credits": [],
}


def shot(i, kind="photo", **kw):
    s = {"id": i, "kind": kind, "why": "x", "audio": "mute"}
    if kind == "video":
        s.update({"in": 2, "out": 6})
    else:
        s["dur"] = 3
    s.update(kw)
    return s


def credits(extra=None):
    return {"id": None, "kind": "card", "dur": 5, "title": {"text": "fin"}, "lines": ['Música: "x" — y', "Mapas: © OpenStreetMap contributors · Natural Earth"] + (extra or [])}


def edl(*shots, last=None):
    return {"acts": [{"name": "Uno", "shots": list(shots)}, {"name": "Créditos", "shots": [last or credits()]}], "crossfade_s": 0.6}


def rules(errs):
    return sorted(e.split()[0].rstrip(":") for e in errs)


class Check(unittest.TestCase):
    def run_check(self, e, inp=INP, cfg=CFG):
        return edl_check.check(e, inp, cfg)

    def test_clean_edl(self):
        errs, _ = self.run_check(edl(shot("p1"), shot("v1", "video")))
        self.assertEqual(errs, [])

    def test_each_rule_fires(self):
        errs, _ = self.run_check(edl(shot("zz"), shot("bad"), shot("p3"), shot("p2"), shot("v1", "video", out=99), shot("p1"), shot("p1")))
        got = rules(errs)
        for r in ("noid", "excluded", "avoid", "keep<2", "blurry", "range", "repeated"):
            self.assertIn(r, got, got)

    def test_filler_with_keep_1_is_allowed(self):
        errs, _ = self.run_check(edl(shot("p1"), shot("p3", why="relleno")))
        self.assertIn("avoid", rules(errs))
        inp = copy.deepcopy(INP)
        inp["sharpness"]["p2"] = {"z": 0.0, "blurry": False, "motion_blur": False}
        errs, _ = self.run_check(edl(shot("p1"), shot("p2", why="relleno: cierre")), inp)
        self.assertEqual(errs, [])

    def test_declared_exception_downgrades_to_warning(self):
        e = edl(shot("p1"), shot("p2", why="relleno"))
        errs, _ = self.run_check(e)
        self.assertIn("blurry", rules(errs))
        e["exceptions"] = [{"id": "p2", "rule": "blurry", "why": "única foto de ese momento"}]
        errs, warns = self.run_check(e)
        self.assertEqual(errs, [])
        self.assertTrue(any("excepción declarada" in w for w in warns))

    def test_not_sharpest_variant(self):
        inp = copy.deepcopy(INP)
        inp["variants"] = [{"group": "V001", "best": "p1", "members": [{"id": "p1"}, {"id": "p3"}]}]
        inp["triage"]["P3"]["avoid"] = None
        inp["sharpness"]["p3"] = {"z": 0.1, "blurry": False, "motion_blur": False}
        errs, _ = self.run_check(edl(shot("p3")), inp)
        self.assertIn("not-sharpest", rules(errs))
        inp["sharpness"]["p3"]["z"] = 0.4
        errs, _ = self.run_check(edl(shot("p3")), inp)
        self.assertNotIn("not-sharpest", rules(errs))

    def test_caption_rules(self):
        card = {"id": None, "kind": "card", "dur": 3, "title": {"text": "x"}, "caption": {"place": "a"}, "why": "cartel"}
        errs, _ = self.run_check(edl(shot("p1", dur=2, caption={"place": "a", "line": None}), card))
        self.assertEqual(rules(errs).count("caption-on-card"), 1)
        self.assertIn("caption-short", rules(errs))

    def test_duration_and_drone_share(self):
        errs, _ = self.run_check(edl(shot("p1")), cfg={"duration": {"floor_min": 5}})
        self.assertTrue(any("piso" in e for e in errs))
        errs, _ = self.run_check(edl(shot("d1", "video", out=20), shot("p1")), cfg={"edit": {"drone_share_max": 0.3}})
        self.assertTrue(any("drone_share" in e for e in errs))

    def test_credits_structure_and_attribution(self):
        bad = edl(shot("p1"), last={"id": None, "kind": "card", "dur": 5, "title": {"text": "fin"}, "lines": []})
        errs, _ = self.run_check(bad, cfg={"minimap": {"enabled": True}})
        self.assertTrue(any("OpenStreetMap" in e for e in errs))
        e = edl(shot("p1"))
        e["acts"][-1]["name"] = "Final"
        errs, _ = self.run_check(e)
        self.assertTrue(any("Créditos" in x for x in errs))

    def test_title_reveal_must_precede_credits(self):
        title = {"id": None, "kind": "card", "dur": 4, "role": "title", "title": {"text": "T"}, "why": "título"}
        errs, _ = self.run_check(edl(title, shot("p1")))
        self.assertTrue(any(e.startswith("title") for e in errs))
        e = edl(shot("p1"))
        e["acts"][-1]["shots"].insert(0, title)
        errs, _ = self.run_check(e)
        self.assertFalse(any(x.startswith("title") for x in errs))

    def test_total_subtracts_the_overlapping_crossfades(self):
        e = {"acts": [{"name": "a", "shots": [shot("p1", dur=10)]}, {"name": "b", "shots": [shot("p2", dur=10)]}], "crossfade_s": 0.6}
        self.assertAlmostEqual(edl_check.total_of(e), 19.4)


if __name__ == "__main__":
    unittest.main()
