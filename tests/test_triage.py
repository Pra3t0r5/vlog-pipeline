import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import cli
import prompts
import triage

CFG = {"name": "demo", "cost_mode": "standard", "people": ["Alice", "Bob"], "ingest": {"start_date": "2025-06-10", "end_date": "2025-06-11"}}


def p1(code, reject=False, why=None, kind="paisaje", sim=None):
    return {"code": code, "reject": reject, "why": why, "kind": kind, "sim": sim}


def p2(code, keep=2, best=None, **kw):
    r = {"code": code, "keep": keep, "kind": "familia", "who": ["alice"], "mood": "feliz", "desc": "algo", "avoid": None, "best": best, "sim": None}
    r.update(kw)
    return r


class Fixture(unittest.TestCase):
    def setUp(self):
        self.proj = pathlib.Path(tempfile.mkdtemp(prefix="triage."))
        (self.proj / "sheets").mkdir()
        (self.proj / "triage" / "pass1").mkdir(parents=True)
        (self.proj / "triage" / "pass2").mkdir(parents=True)
        idx = {"codes": {}, "sheets": {"d1-01.jpg": ["P1", "V1", "P2"], "d1-02.jpg": ["P3"], "d2-01.jpg": ["P4", "P5"]}}
        man = {"preset": "standard", "frames": 6, "sheets": {
            "d1-01.jpg": {"day": "d1", "n_items": 3, "tokens_est": 1000}, "d1-02.jpg": {"day": "d1", "n_items": 1, "tokens_est": 300},
            "d2-01.jpg": {"day": "d2", "n_items": 2, "tokens_est": 500}}}
        (self.proj / "sheets" / "index.json").write_text(json.dumps(idx))
        (self.proj / "sheets" / "manifest.json").write_text(json.dumps(man))
        (self.proj / "DIRECTION.md").write_text("# Brief\n\n## Qué se ve (prioridad)\n1. paisaje\n\n## Estructura\nactos\n\n## Prohibido\n- tomas movidas\n")

    def w(self, n, day, rows):
        triage.pass_file(self.proj, n, day).write_text(json.dumps(rows))


class Validation(Fixture):
    def test_pass1_complete_and_pending(self):
        st = triage.pass_status(self.proj, CFG, 1)
        self.assertEqual(st["d1"], ["no existe"])
        self.w(1, "d1", [p1("P1"), p1("V1"), p1("P2", True, "piso"), p1("P3")])
        self.w(1, "d2", [p1("P4"), p1("P5")])
        self.assertTrue(triage.done(self.proj, CFG, 1))

    def test_pass1_rejects_missing_duplicate_foreign_and_bad_fields(self):
        probs = triage.problems_p1([p1("P1"), p1("P1"), p1("PX"), p1("P2", True, "porque sí"), p1("V1", kind="rarisimo")], ["P1", "V1", "P2", "P3"])
        text = " | ".join(probs)
        for needle in ("repetido P1", "ajeno PX", "why 'porque sí'", "kind 'rarisimo'", "faltan 1 códigos: P3"):
            self.assertIn(needle, text)

    def test_pass2_only_covers_survivors_and_checks_best_range(self):
        probs = triage.problems_p2([p2("P1"), p2("V1", best=[2, 9]), p2("P2")], ["P1", "V1"], 6)
        text = " | ".join(probs)
        self.assertIn("ajeno o rechazado en pasada 1: P2", text)
        self.assertIn("V1: best", text)
        self.assertEqual(triage.problems_p2([p2("P1"), p2("V1", best=[2, 4])], ["P1", "V1"], 6), [])

    def test_invalid_json_is_pending_not_a_crash(self):
        triage.pass_file(self.proj, 1, "d1").write_text("{no json")
        self.assertIn("JSON inválido", triage.pass_status(self.proj, CFG, 1)["d1"][0])

    def test_pass2_waits_for_pass1_and_skips_days_without_survivors(self):
        self.assertEqual(triage.pass_status(self.proj, CFG, 2)["d1"], ["falta la pasada 1"])
        self.w(1, "d2", [p1("P4", True, "piso"), p1("P5", True, "dedos")])
        self.assertEqual(triage.pass_status(self.proj, CFG, 2)["d2"], [])


class Plan(Fixture):
    def test_pass1_plan_lists_only_pending_with_rendered_prompt(self):
        self.w(1, "d2", [p1("P4"), p1("P5")])
        items = triage.plan(self.proj, CFG, 1)
        self.assertEqual([i["day"] for i in items], ["d1"])
        it = items[0]
        self.assertEqual((it["model"], it["n_items"], it["tokens_est"]), ("haiku", 4, 1300))
        self.assertIn(str(self.proj / "sheets" / "d1-01.jpg"), it["prompt"])
        self.assertIn("P1, V1, P2, P3", it["prompt"])
        self.assertIn(str(self.proj / "triage" / "pass1" / "d1.json"), it["prompt"])
        self.assertNotIn("{{", it["prompt"])
        self.assertNotIn("Reglas del director", it["prompt"])
        self.assertTrue(it["prompt"].startswith("Sos un asistente de triage visual"))
        self.assertEqual(len(triage.plan(self.proj, CFG, 1, only_pending=False)), 2)

    def test_low_mode_changes_nothing_in_pass1_model_but_pass2_sonnet(self):
        low = dict(CFG, cost_mode="low")
        self.assertEqual(triage.plan(self.proj, low, 1)[0]["model"], "haiku")

    def test_pass2_prompt_carries_brief_and_context(self):
        self.w(1, "d1", [p1("P1"), p1("V1"), p1("P2", True, "piso"), p1("P3")])
        self.w(1, "d2", [p1("P4"), p1("P5")])
        p2dir = self.proj / "sheets-p2"
        p2dir.mkdir()
        (p2dir / "index.json").write_text(json.dumps({"codes": {}, "sheets": {"d1-01.jpg": ["P1", "V1", "P3"], "d2-01.jpg": ["P4", "P5"]}}))
        (p2dir / "manifest.json").write_text(json.dumps({"preset": "standard", "frames": 6, "sheets": {
            "d1-01.jpg": {"day": "d1", "n_items": 3, "tokens_est": 700}, "d2-01.jpg": {"day": "d2", "n_items": 2, "tokens_est": 500}}}))
        (self.proj / "notes").mkdir()
        (self.proj / "notes" / "chronology.json").write_text(json.dumps({"days": [{"date": "d1", "base": "Base Town", "places": ["Hostel"], "avoid": ["cansancio"]}]}))
        it = triage.plan(self.proj, CFG, 2, "d1")[0]
        self.assertEqual(it["model"], "sonnet")
        self.assertIn("tomas movidas", it["prompt"])
        self.assertIn("Hostel", it["prompt"])
        self.assertIn("alice, bob", it["prompt"])
        self.assertIn(str(p2dir / "d1-01.jpg"), it["prompt"])
        self.assertNotIn("P2,", it["prompt"].split("Códigos a calificar")[1].splitlines()[0])
        self.assertNotIn("## Estructura", it["prompt"])


class Merge(Fixture):
    def test_merge_combines_passes_and_normalizes_best(self):
        self.w(1, "d1", [p1("P1"), p1("V1", kind="paisaje"), p1("P2", True, "piso"), p1("P3")])
        self.w(1, "d2", [p1("P4", True, "dedos", sim="P5"), p1("P5", True, "borroso")])
        self.w(2, "d1", [p2("P1", 3), p2("V1", 2, best=[2, 3]), p2("P3", 1)])
        merged = triage.merge(self.proj, CFG)
        by = {r["code"]: r for r in merged}
        self.assertEqual([r["code"] for r in merged], ["P1", "V1", "P2", "P3", "P4", "P5"])
        self.assertEqual((by["P2"]["keep"], by["P2"]["avoid"], by["P4"]["sim"]), (0, "piso", "P5"))
        self.assertEqual(by["V1"]["best"], [2, 3])
        self.assertTrue((self.proj / triage.MERGED).exists())

    def test_merge_refuses_when_a_pass_is_incomplete(self):
        self.w(1, "d1", [p1("P1")])
        with self.assertRaises(triage.TriageError) as e:
            triage.merge(self.proj, CFG)
        self.assertIn("faltan", str(e.exception))

    def test_normalize_best_for_four_frames(self):
        self.assertIsNone(triage.normalize_best(None, 4))
        self.assertEqual(triage.normalize_best([1, 4], 4), [1, 6])
        self.assertEqual(triage.normalize_best([2, 3], 4), [3, 4])
        self.assertEqual(triage.normalize_best([2, 5], 6), [2, 5])

    def test_merged_file_is_what_sharpness_loads(self):
        import sharpness
        self.w(1, "d1", [p1("P1"), p1("V1"), p1("P2"), p1("P3")])
        self.w(1, "d2", [p1("P4"), p1("P5")])
        self.w(2, "d1", [p2("P1"), p2("V1", best=[1, 2]), p2("P2"), p2("P3")])
        self.w(2, "d2", [p2("P4"), p2("P5")])
        triage.merge(self.proj, CFG)
        idx = json.loads((self.proj / "sheets" / "index.json").read_text())
        idx["codes"] = {c: f"id.{c}" for c in ("P1", "V1", "P2", "P3", "P4", "P5")}
        (self.proj / "sheets" / "index.json").write_text(json.dumps(idx))
        tri = sharpness.load_triage(str(self.proj))
        self.assertEqual(tri["V1"]["id"], "id.V1")
        self.assertEqual(tri["V1"]["best"], [1, 2])


class Prompts(Fixture):
    def test_every_template_renders_without_leftover_placeholders(self):
        cfg = dict(CFG, duration={"target_min": 7})
        for name in prompts.NAMES:
            text = prompts.render(name, self.proj, cfg)
            self.assertNotIn("{{", text, name)
            self.assertNotIn("Reglas del director", text, name)
            self.assertNotIn("=== PROMPT ===", text, name)
        self.assertIn("420 s", prompts.render("editor", self.proj, cfg))

    def test_editor_prompt_follows_the_cost_mode(self):
        std = prompts.render("editor", self.proj, dict(CFG, cost_mode="standard"))
        low = prompts.render("editor", self.proj, dict(CFG, cost_mode="low"))
        self.assertIn("Tenés hasta 2 ronda/s", std)
        self.assertIn("Tenés hasta 1 ronda/s", low)
        self.assertIn("music_default.json", low)

    def test_unknown_template(self):
        with self.assertRaises(prompts.PromptError):
            prompts.render("poema", self.proj, CFG)


if __name__ == "__main__":
    unittest.main()
