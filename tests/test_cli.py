import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import cli

VLOG = [str(ROOT / "bin" / "vlog")]


def vlog(*a, cwd=None):
    return subprocess.run(VLOG + list(a), capture_output=True, text=True, cwd=cwd)


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="vlogtest."))

    def test_disk_guard_math(self):
        self.assertFalse(cli.check_disk(self.tmp, 10**15)[0])
        self.assertTrue(cli.check_disk(self.tmp, 1)[0])

    def test_new_refuses_when_not_enough_space(self):
        src = self.tmp / "src"
        src.mkdir()
        (src / "a.bin").write_bytes(b"x" * 1000)
        r = vlog("new", "x", "--yes", "--root", str(self.tmp / "v"), "--drone", str(src), cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        import unittest.mock as m
        with m.patch.object(cli, "free_bytes", return_value=1500):
            ok, have, need = cli.check_disk(self.tmp, 1000)
        self.assertFalse(ok)
        self.assertEqual(need, 2000)

    def test_new_skeleton_and_idempotent_refusal(self):
        r = vlog("new", "demo", "--yes", "--theme", "t", "--root", str(self.tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        for d in cli.SKELETON:
            self.assertTrue((self.tmp / "demo" / d).is_dir())
        self.assertTrue((self.tmp / "demo" / "DIRECTION.md").exists())
        self.assertNotEqual(vlog("new", "demo", "--yes", "--theme", "t", "--root", str(self.tmp)).returncode, 0)

    def test_album_utf8_names_and_resume(self):
        vlog("new", "demo", "--yes", "--theme", "t", "--root", str(self.tmp))
        z = self.tmp / "a.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("Álbum/Cañón año.jpg", b"1")
            f.writestr("Álbum/x.jpg", b"2")
        proj = self.tmp / "demo"
        cfg = cli.load(proj)
        cfg["storage"] = {"originals_dir": str(self.tmp / "originales")}
        cli.save(proj, cfg)
        r = vlog("album", str(z), cwd=proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2 archivos", r.stdout)
        self.assertIn("ya extraído", vlog("album", str(z), cwd=proj).stdout)

    def test_rutas_from_file_runs_route(self):
        vlog("new", "demo", "--yes", "--theme", "t", "--root", str(self.tmp))
        f = self.tmp / "R.json"
        f.write_text(json.dumps({"semanticSegments": [{"startTime": "2025-06-11T10:00:00.000+02:00", "endTime": "2025-06-11T11:00:00.000+02:00",
                                                       "timelinePath": [{"time": "2025-06-11T10:05:00.000+02:00", "point": "10.5000°, 20.5000°"}]}]}))
        r = vlog("rutas", "--from", "2025-06-10", "--to", "2025-06-12", "--file", str(f), cwd=self.tmp / "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "demo" / "route" / "route.json").exists())

    def test_rutas_bad_date(self):
        vlog("new", "demo", "--yes", "--theme", "t", "--root", str(self.tmp))
        self.assertNotEqual(vlog("rutas", "--from", "11/10", "--to", "2025-06-12", cwd=self.tmp / "demo").returncode, 0)

    def test_preview_without_guion_says_what_is_missing(self):
        vlog("new", "demo", "--yes", "--theme", "t", "--root", str(self.tmp))
        r = vlog("preview", cwd=self.tmp / "demo")
        self.assertEqual(r.returncode, 4)
        self.assertIn("guion", r.stdout)


if __name__ == "__main__":
    unittest.main()
