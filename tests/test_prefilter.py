import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import prefilter


def rec(i, **kw):
    r = {"id": i, "path": f"/x/{i}.jpg", "source": "phone", "kind": "photo", "time_art": f"2025-06-11T10:{int(i[1:]):02d}:00+02:00",
         "day": "2025-06-11", "exclude_reason": None, "keep_in_burst": True, "burst_group": None}
    r.update(kw)
    return r


def row(z, phash="0" * 16, motion=False, ratio=0.8):
    return {"z": z, "phash": phash, "motion_blur": motion, "dir_ratio": ratio, "source": "phone", "kind": "photo"}


TRIP = ("2025-06-10", "2025-06-20")
P = prefilter.DEFAULTS


class Decide(unittest.TestCase):
    def test_each_reason_and_survivor(self):
        media = [
            rec("a1"),
            rec("a2", exclude_reason="screenshot"),
            rec("a3", path="/x/Screenshot_2026.png"),
            rec("a4", day="2025-07-02"),
            rec("a5", day=None, exclude_reason="no_date"),
            rec("a6", exclude_reason="duplicate_of:a1"),
            rec("a7", keep_in_burst=False, burst_group="B001"),
            rec("a8"),
            rec("a9", exclude_reason="drone_app_cache_unmatched"),
        ]
        rows = {"a1": row(0.2), "a8": row(-2.0)}
        kept, dropped = prefilter.decide(media, rows, TRIP, P)
        self.assertEqual(kept, ["a1"])
        why = {k: v["reason"] for k, v in dropped.items()}
        self.assertEqual(why, {"a2": "screenshot", "a3": "screenshot", "a4": "out_of_range", "a5": "out_of_range",
                               "a6": "duplicate", "a7": "burst", "a8": "blurry", "a9": "excluded"})

    def test_blur_threshold_and_motion(self):
        media = [rec("b1"), rec("b2"), rec("b3"), rec("b4")]
        rows = {"b1": row(-1.49), "b2": row(-1.51), "b3": row(-0.4, motion=True, ratio=0.1), "b4": row(0.1)}
        kept, dropped = prefilter.decide(media, rows, TRIP, P)
        self.assertEqual(kept, ["b1", "b4"])
        self.assertIn("movimiento", dropped["b3"]["detail"])

    def test_unmeasured_items_are_kept(self):
        kept, dropped = prefilter.decide([rec("c1")], {}, TRIP, P)
        self.assertEqual(kept, ["c1"])
        self.assertEqual(dropped, {})

    def test_variants_keep_only_the_sharpest_among_survivors(self):
        media = [rec("d1"), rec("d2"), rec("d3"), rec("d4", time_art="2025-06-11T15:00:00+02:00")]
        same = "f" * 16
        rows = {"d1": row(0.1, same), "d2": row(0.9, same), "d3": row(-2.0, same), "d4": row(0.0, same)}
        kept, dropped = prefilter.decide(media, rows, TRIP, P)
        self.assertEqual(kept, ["d2", "d4"])
        self.assertEqual(dropped["d1"]["reason"], "variant")
        self.assertEqual(dropped["d3"]["reason"], "blurry")

    def test_exact_duplicate_from_hash(self):
        kept, dropped = prefilter.decide([rec("e1"), rec("e2")], {}, TRIP, P, {"e2": "e1"})
        self.assertEqual(kept, ["e1"])
        self.assertEqual(dropped["e2"]["reason"], "duplicate")

    def test_no_trip_dates_keeps_everything_in_range(self):
        kept, _ = prefilter.decide([rec("f1", day="2031-01-01")], {}, (None, None), P)
        self.assertEqual(kept, ["f1"])

    def test_summarize_counts(self):
        media = [rec("g1"), rec("g2")]
        s = prefilter.summarize(media, ["g1"], {"g2": {"reason": "blurry", "detail": ""}})
        self.assertEqual((s["total"], s["kept"], s["dropped"], s["by_reason"]["blurry"]), (2, 1, 1, 1))


class Io(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="pf."))

    def test_exact_duplicates_by_content(self):
        for n, data in (("a1", b"x" * 100), ("b1", b"x" * 100), ("c1", b"y" * 100), ("d1", b"z" * 7)):
            (self.tmp / f"{n}.jpg").write_bytes(data)
        recs = [rec(n, path=str(self.tmp / f"{n}.jpg")) for n in ("a1", "b1", "c1", "d1")]
        self.assertEqual(prefilter.exact_duplicates(recs), {"b1": "a1"})

    def test_trip_range_sources(self):
        self.assertEqual(prefilter.trip_range({"ingest": {"start_date": "2025-06-10", "end_date": "2025-06-20"}}), ("2025-06-10", "2025-06-20"))
        self.assertEqual(prefilter.trip_range({"rutas": {"from": "2025-01-01", "to": "2025-01-03"}}), ("2025-01-01", "2025-01-03"))
        self.assertEqual(prefilter.trip_range({"trip": {"from": "a", "to": "b"}, "ingest": {"start_date": "x", "end_date": "y"}}), ("a", "b"))
        self.assertEqual(prefilter.trip_range({}), (None, None))

    def test_params_override_and_survivors_roundtrip(self):
        self.assertEqual(prefilter.params_of({"prefilter": {"blurry_z": -2.0}})["blurry_z"], -2.0)
        self.assertIsNone(prefilter.survivors(self.tmp))
        (self.tmp / "inv").mkdir()
        prefilter.path_of(self.tmp).write_text(json.dumps({"kept": ["a", "b"]}))
        self.assertEqual(prefilter.survivors(self.tmp), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
