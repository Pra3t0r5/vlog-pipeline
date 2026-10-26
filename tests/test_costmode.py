import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import cli
import costmode

VLOG = [str(ROOT / "bin" / "vlog")]


def vlog(*a, cwd=None):
    return subprocess.run(VLOG + list(a), capture_output=True, text=True, cwd=cwd)


class Parsing(unittest.TestCase):
    def test_default_is_standard(self):
        self.assertEqual(costmode.mode_of({}), "standard")
        self.assertEqual(costmode.mode_of(None), "standard")

    def test_valid_modes(self):
        for m in costmode.MODES:
            self.assertEqual(costmode.profile({"cost_mode": m})["mode"], m)

    def test_invalid_mode_raises(self):
        with self.assertRaises(costmode.CostModeError):
            costmode.mode_of({"cost_mode": "turbo"})

    def test_low_has_no_opus_and_no_research(self):
        p = costmode.profile({"cost_mode": "low"})
        self.assertNotIn("opus", p["models"].values())
        self.assertIsNone(p["models"]["research"])
        self.assertFalse(p["research_subagents"])
        self.assertEqual((p["editor_rounds"], p["sheet_preset"], p["music"], p["reel"]), (1, "low", "user_or_list", "optional"))
        self.assertTrue(p["window_budget"])

    def test_standard_profile_matches_the_documented_table(self):
        p = costmode.profile({"cost_mode": "standard"})
        self.assertEqual(p["models"]["editor"], "opus")
        self.assertEqual((p["models"]["chronology"], p["models"]["triage_pass1"], p["models"]["triage_pass2"]), ("haiku", "haiku", "sonnet"))
        self.assertEqual((p["editor_rounds"], p["sheet_preset"], p["music"], p["reel"]), (2, "standard", "search", "required"))

    def test_sheets_preset_override(self):
        self.assertEqual(costmode.profile({"cost_mode": "low", "sheets": {"preset": "standard"}})["sheet_preset"], "standard")

    def test_reel_optional_in_low_unless_listed_in_outputs(self):
        self.assertFalse(costmode.reel_wanted({"cost_mode": "low"}))
        self.assertTrue(costmode.reel_wanted({"cost_mode": "low", "outputs": ["tv", {"preset": "reel", "guion": "g.json"}]}))
        self.assertTrue(costmode.reel_wanted({"cost_mode": "standard"}))

    def test_profile_does_not_leak_mutation(self):
        p = costmode.profile({"cost_mode": "low"})
        p["models"]["editor"] = "opus"
        self.assertEqual(costmode.PROFILES["low"]["models"]["editor"], "sonnet")

    def test_table_mentions_both_modes(self):
        t = costmode.table_md()
        self.assertIn("| Editor (EDL) | opus | sonnet |", t)

    def test_default_music_list_is_complete(self):
        lst = json.loads((ROOT / "config" / "music_default.json").read_text())
        self.assertGreaterEqual(len(lst), 3)
        for e in lst:
            for k in ("title", "artist", "source_url", "license", "credit_line"):
                self.assertTrue(e[k])


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="costmode."))

    def test_new_writes_cost_mode(self):
        r = vlog("new", "demo", "--yes", "--theme", "t", "--root", str(self.tmp), "--cost-mode", "low")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(cli.load(self.tmp / "demo")["cost_mode"], "low")
        r = vlog("profile", cwd=self.tmp / "demo")
        self.assertIn("modelo editor", r.stdout)
        self.assertIn("sonnet", r.stdout)

    def test_new_defaults_to_standard_and_rejects_unknown(self):
        vlog("new", "demo", "--yes", "--theme", "t", "--root", str(self.tmp))
        self.assertEqual(cli.load(self.tmp / "demo")["cost_mode"], "standard")
        r = vlog("new", "otro", "--yes", "--theme", "t", "--root", str(self.tmp), "--cost-mode", "turbo")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.tmp / "otro").exists())

    def test_bad_cost_mode_in_yaml_stops_status_and_sheets(self):
        vlog("new", "demo", "--yes", "--theme", "t", "--root", str(self.tmp))
        proj = self.tmp / "demo"
        cfg = cli.load(proj)
        cfg["cost_mode"] = "turbo"
        cli.save(proj, cfg)
        for cmd in ("status", "sheets", "profile"):
            r = vlog(cmd, cwd=proj)
            self.assertNotEqual(r.returncode, 0, cmd)
            self.assertIn("cost_mode", r.stderr)


class Docs(unittest.TestCase):
    def test_director_runbook_embeds_the_current_tables(self):
        import workflow
        doc = (ROOT / "docs" / "DIRECTOR.md").read_text()
        self.assertIn(costmode.table_md(), doc)
        self.assertIn(workflow.cost_table_md(), doc)

    def test_every_prompt_template_has_the_marker(self):
        import prompts
        for name in list(prompts.NAMES) + ["triage-pass1", "triage-pass2"]:
            self.assertTrue(prompts.MARKER_LINE.search((prompts.PROMPTS / f"{name}.md").read_text()), name)


if __name__ == "__main__":
    unittest.main()
