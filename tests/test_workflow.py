import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import cli
import workflow

VLOG = [str(ROOT / "bin" / "vlog")]


def vlog(*a, cwd=None):
    return subprocess.run(VLOG + list(a), capture_output=True, text=True, cwd=cwd)


class Status(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="status."))

    def project(self, mode):
        r = vlog("new", "demo", "--yes", "--theme", "t", "--root", str(self.tmp), "--cost-mode", mode)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.tmp / "demo"

    def test_fresh_project_starts_at_the_brief(self):
        proj = self.project("standard")
        st = workflow.compute(proj, cli.load(proj))
        self.assertEqual(st["next"]["id"], "brief")
        self.assertFalse(any(s["done"] for s in st["stages"]))

    def test_filled_brief_moves_on(self):
        proj = self.project("standard")
        (proj / "DIRECTION.md").write_text("# Brief\n\n## Qué se ve\n1. paisaje\n2. gente\n")
        self.assertEqual(workflow.compute(proj, cli.load(proj))["next"]["id"], "rutas")

    def test_remaining_tokens_standard_in_target_and_low_cheaper(self):
        std = workflow.compute(self.project("standard"), {"name": "demo", "cost_mode": "standard"})
        low_proj = self.tmp / "otro"
        low_proj.mkdir()
        low = workflow.compute(low_proj, {"name": "demo", "cost_mode": "low"})
        self.assertGreater(std["remaining_tokens"], 1_000_000)
        self.assertLessEqual(std["remaining_tokens"], 1_600_000)
        self.assertLess(low["remaining_tokens"], 0.6 * std["remaining_tokens"])
        self.assertLess(low["remaining_tokens"], 1_000_000)

    def test_low_mode_splits_into_windows_under_the_budget(self):
        low_proj = self.tmp / "otro"
        low_proj.mkdir()
        st = workflow.compute(low_proj, {"name": "demo", "cost_mode": "low"})
        budget = st["profile"]["window_budget"]
        self.assertGreater(len(st["windows"]), 2)
        for w in st["windows"]:
            self.assertLessEqual(sum(s["tokens"] for s in w), budget)
        flat = [s["id"] for w in st["windows"] for s in w]
        self.assertEqual(flat, [s["id"] for s in st["stages"] if not s["done"] and not s["optional"]])

    def test_standard_has_no_windows_split(self):
        proj = self.tmp / "otro"
        proj.mkdir()
        self.assertEqual(len(workflow.compute(proj, {"name": "demo"})["windows"]), 1)

    def test_reel_is_optional_in_low_and_required_in_standard(self):
        proj = self.tmp / "otro"
        proj.mkdir()
        low = {s["id"]: s for s in workflow.compute(proj, {"name": "d", "cost_mode": "low"})["stages"]}
        std = {s["id"]: s for s in workflow.compute(proj, {"name": "d"})["stages"]}
        self.assertTrue(low["reel"]["optional"])
        self.assertFalse(std["reel"]["optional"])

    def test_preview_needs_the_owner_ok_before_final(self):
        proj = self.project("low")
        cfg = cli.load(proj)
        (proj / "demo-preview.mp4").write_bytes(b"x")
        ids = {s["id"]: s["done"] for s in workflow.compute(proj, cfg)["stages"]}
        self.assertTrue(ids["preview"])
        self.assertFalse(ids["preview_ok"])
        self.assertEqual(vlog("approve", "preview", cwd=proj).returncode, 0)
        ids = {s["id"]: s["done"] for s in workflow.compute(proj, cfg)["stages"]}
        self.assertTrue(ids["preview_ok"])

    def test_cli_status_writes_status_md_for_a_fresh_session(self):
        proj = self.project("low")
        r = vlog("status", cwd=proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Siguiente:", r.stdout)
        self.assertIn("ventana 1", r.stdout)
        md = (proj / "STATUS.md").read_text()
        self.assertIn("Modo de costo: **low**", md)
        self.assertIn("docs/DIRECTOR.md", md)
        self.assertIn("## Siguiente", md)
        self.assertIn("Ventanas de 5 horas", md)

    def test_status_reports_pending_triage_groups(self):
        proj = self.project("low")
        (proj / "sheets").mkdir(exist_ok=True)
        (proj / "sheets" / "index.json").write_text(json.dumps({"codes": {}, "sheets": {"d1-01.jpg": ["P1"], "d2-01.jpg": ["P2"]}}))
        (proj / "sheets" / "manifest.json").write_text(json.dumps({"frames": 4, "sheets": {
            "d1-01.jpg": {"day": "d1", "tokens_est": 10}, "d2-01.jpg": {"day": "d2", "tokens_est": 10}}}))
        (proj / "DIRECTION.md").write_text("# b\n")
        (proj / "route" / "route.json").write_text("{}")
        (proj / "album").mkdir()
        (proj / "album" / "a.jpg").write_bytes(b"x")
        (proj / "inv" / "media.json").write_text("[]")
        (proj / "proxy" / "a.mp4").write_bytes(b"x")
        (proj / "notes" / "chronology.json").write_text("{}")
        (proj / "inv" / "prefilter.json").write_text(json.dumps({"kept": []}))
        r = vlog("status", cwd=proj)
        self.assertIn("Siguiente: Triage pasada 1", r.stdout)
        self.assertIn("faltan 2 de 2 grupos: d1, d2", r.stdout)


if __name__ == "__main__":
    unittest.main()
