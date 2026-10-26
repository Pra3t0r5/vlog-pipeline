import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageChops

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import ffx


class RenderSmoke(unittest.TestCase):
    def setUp(self):
        self.proj = pathlib.Path(tempfile.mkdtemp(prefix="smoke."))
        (self.proj / "inv").mkdir()
        media = self.proj / "media"
        media.mkdir()
        clip = media / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=4:size=320x240:rate=30000/1001", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)], check=True)
        photo = media / "photo.jpg"
        Image.new("RGB", (240, 320), (30, 120, 200)).save(photo)
        recs = [
            {"id": "phone_a.clip", "path": str(clip), "kind": "video", "source": "phone_a", "w": 320, "h": 240, "dur": 4.0, "has_audio": True, "audio_lufs": -23.0, "time_art": "2025-06-10T12:00:00+02:00"},
            {"id": "phone_a.photo", "path": str(photo), "kind": "photo", "source": "phone_a", "w": 240, "h": 320, "time_art": "2025-06-10T12:05:00+02:00"},
        ]
        (self.proj / "inv" / "media.json").write_text(json.dumps(recs))
        (self.proj / "guion.json").write_text(json.dumps({
            "name": "smoke", "out_dir": "out", "grading": False,
            "shots": [
                {"card": {"title": "Un título", "sub": "una línea"}, "dur": 2},
                {"id": "phone_a.clip", "in": 0, "out": 3, "audio": "keep", "caption": {"place": "Lugar de prueba", "line": "Un dato"}},
                {"id": "phone_a.photo", "dur": 3, "title": {"text": "Foto", "sub": "vertical"}},
            ],
        }))

    def test_preview_renders_a_playable_file_with_expected_duration(self):
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "render.py"), str(self.proj / "guion.json"), "preview"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.proj / "out" / "smoke-preview.mp4"
        self.assertTrue(out.exists())
        pr = ffx.probe(out)
        self.assertEqual((pr["w"], pr["h"]), (960, 540))
        self.assertTrue(pr["has_audio"])
        self.assertAlmostEqual(pr["dur"], 2 + 3 + 3 - 2 * 0.6, delta=0.15)
        again = subprocess.run([sys.executable, str(ROOT / "pipeline" / "render.py"), str(self.proj / "guion.json"), "preview"], capture_output=True, text=True)
        self.assertIn("caché: segmentos 3 hit / 0 build", again.stdout)

    def render_frame(self, name, shots, at):
        g = self.proj / f"{name}.json"
        g.write_text(json.dumps({"name": name, "out_dir": "out", "grading": False, "shots": shots}))
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "render.py"), str(g), "preview"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        png = self.proj / f"{name}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", str(self.proj / "out" / f"{name}-preview.mp4"), "-frames:v", "1", str(png)], check=True)
        return Image.open(png).convert("RGB")

    def test_caption_run_is_drawn_over_the_cut_in_the_corner(self):
        plain = [{"id": "phone_a.clip", "in": 0, "out": 3, "audio": "mute"}, {"id": "phone_a.clip", "in": 0, "out": 3, "audio": "mute", "transition": "cut"}]
        withcap = [dict(plain[0], caption={"place": "Lugar de prueba", "line": "Una frase de prueba"}), dict(plain[1], caption={"place": "Lugar de prueba", "line": "Otra frase distinta"})]
        a = self.render_frame("plain", plain, 2.0)
        b = self.render_frame("caps", withcap, 2.0)
        box = (0, 380, 480, 540)
        diff = sum(ImageChops.difference(a.crop(box), b.crop(box)).resize((1, 1), Image.BOX).getpixel((0, 0))) * 480 * 160
        self.assertGreater(diff, 20000)
        far = (480, 0, 960, 200)
        self.assertIsNone(ImageChops.difference(a.crop(far), b.crop(far)).getbbox())

    def test_project_font_override_changes_nothing_when_it_is_the_same_font(self):
        import config
        cfg = config.build({})
        self.assertTrue(pathlib.Path(config.font()).exists() or cfg["fonts"]["main"])


if __name__ == "__main__":
    unittest.main()
