import json
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "pipeline"))

import cli
import musicmix


class RenderGuionTest(unittest.TestCase):
    def project(self, outputs):
        proj = pathlib.Path(tempfile.mkdtemp())
        (proj / "project.yaml").write_text("name: demo\n" + ("outputs:\n" + "".join(f"- {o}\n" for o in outputs) if outputs else ""))
        for g in ("guion.json", "guion-reel.json", "otro-reel.json"):
            (proj / g).write_text("{}")
        return proj

    def rendered(self, proj, presets):
        calls = []
        with mock.patch.object(cli, "run", side_effect=lambda cmd: calls.append((pathlib.Path(cmd[2]).name, cmd[3]))):
            cli.cmd_render(types.SimpleNamespace(project=str(proj), presets=presets))
        return calls

    def test_reel_as_argument_uses_the_reel_guion_not_the_main_one(self):
        proj = self.project([])
        self.assertEqual(self.rendered(proj, ["reel"]), [("guion-reel.json", "reel")])

    def test_reel_as_argument_honours_the_guion_declared_in_outputs(self):
        proj = self.project(["tv", "{preset: reel, guion: otro-reel.json}"])
        self.assertEqual(self.rendered(proj, ["reel"]), [("otro-reel.json", "reel")])

    def test_other_presets_keep_the_main_guion(self):
        proj = self.project([])
        self.assertEqual(self.rendered(proj, ["tv", "chat"]), [("guion.json", "tv"), ("guion.json", "chat")])

    def test_bare_reel_in_outputs_uses_the_reel_guion(self):
        proj = self.project(["tv", "reel"])
        self.assertEqual(self.rendered(proj, []), [("guion.json", "tv"), ("guion-reel.json", "reel")])


class ShortTargetTrimTest(unittest.TestCase):
    def test_fade_is_capped_to_a_quarter_of_the_target(self):
        self.assertIn("afade=t=out:st=72.400:d=3.000", musicmix.trim_fade_filter(75.4, 3.0))
        self.assertIn("afade=t=out:st=6.000:d=2.000", musicmix.trim_fade_filter(8.0, 3.0))

    def test_unreachable_short_target_falls_back_to_trim_with_fade(self):
        td = pathlib.Path(tempfile.mkdtemp())
        src, out, rep = td / "tema.wav", td / "mix.wav", td / "mix.json"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=30", "-ac", "2", str(src)], check=True)
        argv = ["musicmix.py", str(src), str(out), "--target-s", "12", "--report", str(rep)]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(musicmix, "plan", side_effect=RuntimeError("no path hits target within tolerance; relax constraints")):
            musicmix.main()
        r = json.loads(rep.read_text())
        self.assertEqual(r["mode"], "trim")
        self.assertAlmostEqual(r["final_duration_s"], 12.0, delta=0.1)

    def test_unreachable_long_target_still_fails(self):
        td = pathlib.Path(tempfile.mkdtemp())
        src, out = td / "tema.wav", td / "mix.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=10", "-ac", "2", str(src)], check=True)
        argv = ["musicmix.py", str(src), str(out), "--target-s", "60"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(musicmix, "plan", side_effect=RuntimeError("no path")):
            with self.assertRaises(RuntimeError):
                musicmix.main()


if __name__ == "__main__":
    unittest.main()
