import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import adbui
import config
import edl2guion
import guion
import minimap
import routefill
import sources
import triage

VLOG = [str(ROOT / "bin" / "vlog")]


def vlog(*a, cwd=None, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(VLOG + list(a), capture_output=True, text=True, cwd=cwd, env=e)


class Layers(unittest.TestCase):
    def tearDown(self):
        config.reset()

    def test_defaults_file_is_valid_and_has_every_section(self):
        d = config.defaults()
        for sec in ("paths", "fonts", "style", "presets", "minimap", "caption", "grade", "sheets", "costmode", "workflow", "ingest", "routefill", "adb", "musicmix"):
            self.assertIn(sec, d)

    def test_deep_merge_merges_maps_and_replaces_lists(self):
        base = {"a": {"b": 1, "c": 2}, "l": [1, 2]}
        out = config.deep_merge(base, {"a": {"c": 3}, "l": [9]})
        self.assertEqual(out, {"a": {"b": 1, "c": 3}, "l": [9]})
        self.assertEqual(base["a"]["c"], 2)

    def test_project_overrides_defaults_without_losing_siblings(self):
        cfg = config.build({"minimap": {"opacity": 0.3}, "style": {"xfade": 1.0}})
        self.assertEqual(cfg["minimap"]["opacity"], 0.3)
        self.assertEqual(cfg["minimap"]["radius_km"], 120.0)
        self.assertEqual((cfg["style"]["xfade"], cfg["style"]["photo_dur"]), (1.0, 3.0))

    def test_user_layer_sits_between_defaults_and_project(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "u.yaml").write_text("style: {xfade: 0.9, photo_dur: 5}\n")
        os.environ["VLOG_CONFIG"] = str(d / "u.yaml")
        try:
            config.reset()
            cfg = config.build({"style": {"photo_dur": 4}})
            self.assertEqual((cfg["style"]["xfade"], cfg["style"]["photo_dur"]), (0.9, 4))
        finally:
            del os.environ["VLOG_CONFIG"]

    def test_missing_user_config_is_an_error_not_a_silent_default(self):
        os.environ["VLOG_CONFIG"] = "/nonexistent/vlog.yaml"
        try:
            config.reset()
            with self.assertRaises(config.ConfigError):
                config.base()
        finally:
            del os.environ["VLOG_CONFIG"]

    def test_font_resolution_and_error(self):
        d = pathlib.Path(tempfile.mkdtemp())
        config.activate({"fonts": {"main": str(d / "nope.ttf")}})
        with self.assertRaises(config.ConfigError):
            config.font()
        config.activate({"fonts": {"main": None, "candidates": [str(d / "a.ttf")]}})
        with self.assertRaises(config.ConfigError):
            config.font()
        (d / "a.ttf").write_bytes(b"x")
        self.assertEqual(config.font(), str(d / "a.ttf"))

    def test_timezone_parsing(self):
        self.assertEqual(config.tzinfo("+05:30").utcoffset(None).total_seconds(), 19800)
        self.assertEqual(config.tzinfo("-03:00").utcoffset(None).total_seconds(), -10800)
        for bad in ("3", "+0300", "UTC"):
            with self.assertRaises(config.ConfigError):
                config.tzinfo(bad)

    def test_timezone_priority(self):
        self.assertEqual(config.timezone_offset({"ingest": {"tz": "+01:00"}, "timezone": "+02:00"}), "+01:00")
        self.assertEqual(config.timezone_offset({"ingest": {"tz": None}, "timezone": "+02:00"}), "+02:00")
        self.assertRegex(config.timezone_offset({}), r"^[+-]\d\d:\d\d$")

    def test_projects_root_env_wins(self):
        os.environ["VLOG_ROOT"] = "/tmp/somewhere"
        try:
            self.assertEqual(str(config.projects_root()), "/tmp/somewhere")
        finally:
            del os.environ["VLOG_ROOT"]


FREE_FORM = {"presets", "minimap.themes", "minimap.format_defaults", "minimap.presets", "minimap.geometry", "caption.format_defaults", "caption.presets", "grade.profiles", "sheets.presets",
             "costmode.profiles", "workflow.stage_tokens", "osm.towns", "minimap.places.natural_earth", "ingest.exclude_name_patterns", "grade.soft_lap", "proxies.drone", "proxies.phone",
             "musicmix.loudnorm", "render.shots_per_part"}


def leaf_keys(d, pre=""):
    out = []
    for k, v in d.items():
        p = f"{pre}{k}"
        if isinstance(v, dict) and p not in FREE_FORM and v:
            out += leaf_keys(v, p + ".")
        else:
            out.append(p)
    return out


class Docs(unittest.TestCase):
    def test_every_configuration_key_is_documented(self):
        doc = (ROOT / "docs" / "CONFIG.md").read_text()
        missing = [k for k in leaf_keys(config.defaults()) if f"`{k}`" not in doc]
        self.assertEqual(missing, [], "claves sin documentar en docs/CONFIG.md")

    def test_example_project_only_uses_known_top_level_keys(self):
        known = set(config.defaults()) | {"name", "title", "theme", "audience", "cost_mode", "duration", "sources", "rutas", "trip", "guion", "edl", "inventory", "media", "proxy_dir",
                                           "outputs", "people", "source_bytes"}
        example = yaml.safe_load((ROOT / "examples" / "project.example.yaml").read_text())
        self.assertEqual(set(example) - known, set())
        merged = config.build(example)
        self.assertEqual(merged["minimap"]["lat_min"], example["minimap"]["lat_min"])


class Cli(unittest.TestCase):
    def test_config_command_prints_defaults_and_keys(self):
        r = vlog("config", "--defaults")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, (ROOT / "config" / "defaults.yaml").read_text())
        r = vlog("config", "minimap.opacity")
        self.assertEqual(r.stdout.strip(), "0.6")
        self.assertNotEqual(vlog("config", "no.existe").returncode, 0)

    def test_config_uses_the_project_layer(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.assertEqual(vlog("new", "demo", "--yes", "--theme", "t", "--root", str(tmp)).returncode, 0)
        cfg = yaml.safe_load((tmp / "demo" / "project.yaml").read_text())
        cfg["minimap"] = {"opacity": 0.25}
        (tmp / "demo" / "project.yaml").write_text(yaml.safe_dump(cfg))
        self.assertEqual(vlog("config", "minimap.opacity", cwd=tmp / "demo").stdout.strip(), "0.25")

    def test_doctor_runs_and_reports_features(self):
        r = vlog("doctor")
        self.assertIn(r.returncode, (0, 1))
        for needle in ("filtro:xfade", "encoder:libx264", "exiftool", "python:Pillow", "adb"):
            self.assertIn(needle, r.stdout)

    def test_doctor_fails_with_a_nonzero_exit_when_a_required_tool_is_missing(self):
        r = vlog("doctor", env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("[FALTA] ffmpeg", r.stdout)
        self.assertIn("problema(s) obligatorio(s)", r.stdout)

    def test_new_flow_end_to_end_in_a_temp_dir(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        r = vlog("new", "demo", "--yes", "--theme", "un viaje", "--minutes", "5", "--res", "1920x1080", "--tz", "+02:00", "--root", str(tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        proj = tmp / "demo"
        cfg = yaml.safe_load((proj / "project.yaml").read_text())
        self.assertEqual(cfg["output"], {"fps": "30000/1001", "final": {"w": 1920, "h": 1080}})
        self.assertEqual(cfg["ingest"]["tz"], "+02:00")
        self.assertIn("# Brief de dirección — «demo»", (proj / "DIRECTION.md").read_text())
        for cmd in (("status",), ("profile",), ("prompt", "editor")):
            r = vlog(*cmd, cwd=proj)
            self.assertEqual(r.returncode, 0, (cmd, r.stderr))
        self.assertTrue((proj / "STATUS.md").exists())
        self.assertEqual(vlog("sources", "build", cwd=proj).returncode, 0)
        self.assertIn("Dry-run", vlog("clean", cwd=proj).stdout)

    def test_new_rejects_bad_resolution_minutes_and_timezone(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        for extra in (("--res", "4k"), ("--minutes", "abc"), ("--minutes", "-2"), ("--tz", "UTC")):
            r = vlog("new", "demo", "--yes", "--theme", "t", "--root", str(tmp), *extra)
            self.assertNotEqual(r.returncode, 0, extra)
            self.assertNotIn("Traceback", r.stderr, extra)
        self.assertFalse((tmp / "demo").exists())

    def test_final_resolution_chosen_in_new_is_honored_by_the_renderer(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        vlog("new", "demo", "--yes", "--theme", "t", "--res", "1920x1080", "--root", str(tmp))
        proj = tmp / "demo"
        (proj / "inv" / "media.json").write_text("[]")
        (proj / "g.json").write_text(json.dumps({"name": "demo", "shots": [{"card": {"title": "x"}, "dur": 3}]}))
        G = guion.Guion(proj / "g.json", "final")
        self.assertEqual((G.W, G.H), (1920, 1080))


class Fixes(unittest.TestCase):
    def test_album_extracts_with_the_standard_library_when_ditto_and_zipinfo_are_missing(self):
        import argparse
        import unittest.mock as mock
        import zipfile
        import cli
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.assertEqual(vlog("new", "demo", "--yes", "--theme", "t", "--root", str(tmp)).returncode, 0)
        proj = tmp / "demo"
        cfg = cli.load(proj)
        cfg["storage"] = {"originals_dir": str(tmp / "originals")}
        cli.save(proj, cfg)
        z = tmp / "a.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("Álbum/Cañón año.jpg", b"1")
            f.writestr("Álbum/x.jpg", b"2")
            f.writestr("__MACOSX/Álbum/._x.jpg", b"3")
        with mock.patch("shutil.which", return_value=None):
            cli.cmd_album(argparse.Namespace(project=str(proj), zip=str(z), force=False))
        got = sorted(p.name for p in (tmp / "originals").rglob("*") if p.is_file())
        self.assertEqual(got, ["Cañón año.jpg", "x.jpg"])

    def test_guion_without_inventory_or_shots_fails_with_a_message(self):
        import ffx
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "g.json").write_text(json.dumps({"name": "x", "shots": [{"card": {"title": "x"}}]}))
        with self.assertRaises(ffx.RenderError) as e:
            guion.Guion(tmp / "g.json", "preview")
        self.assertIn("vlog ingest", str(e.exception))
        (tmp / "inv").mkdir()
        (tmp / "inv" / "media.json").write_text("[]")
        (tmp / "g.json").write_text(json.dumps({"name": "x", "shots": []}))
        with self.assertRaises(ffx.RenderError):
            guion.Guion(tmp / "g.json", "preview")

    def tearDown(self):
        config.reset()

    def test_people_come_from_owner_names_not_from_the_regex(self):
        cfg = {"ingest": {"owners": ["^IMG_=phone_a", "Pixel=phone_b"]}}
        self.assertEqual(triage.people(cfg), "phone_a, phone_b")

    def test_default_album_target_never_lands_at_the_filesystem_root(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        z = tmp / "album-1-2.zip"
        z.write_bytes(b"x")
        proj = tmp / "demo"
        proj.mkdir()
        orig = sources.mount_of
        try:
            sources.mount_of = lambda p: pathlib.Path("/")
            target = sources.default_album_target(proj, {}, z)
        finally:
            sources.mount_of = orig
        self.assertNotEqual(target.parts[:2], ("/", "originales"))
        self.assertEqual(target.parent, tmp.resolve() / "originales")
        self.assertEqual(sources.default_album_target(proj, {"storage": {"originals_dir": str(tmp / "o")}}, z).parent, tmp / "o")

    def test_routefill_timestamps_carry_the_configured_offset(self):
        from datetime import datetime, timezone
        try:
            routefill.configure({"ingest": {"tz": "+05:30"}})
            dt = datetime(2025, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
            self.assertEqual(routefill.fmt_iso(dt), "2025-06-10T17:30:00.000+05:30")
            routefill.configure({"ingest": {"tz": "-03:00"}})
            self.assertEqual(routefill.fmt_iso(dt), "2025-06-10T09:00:00.000-03:00")
        finally:
            routefill.configure(None)

    def test_inventory_finds_lowercase_extensions_and_parses_fps_without_eval(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        clip = tmp / "media" / "clip.mp4"
        clip.parent.mkdir()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x48:rate=30000/1001", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
        out = tmp / "inv.json"
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "inventory.py"), str(clip.parent), str(out)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(out.read_text())
        self.assertEqual([x["kind"] for x in rows], ["video"])
        self.assertAlmostEqual(rows[0]["fps"], 29.97, places=2)

    def test_route_points_are_not_filtered_unless_lat_min_is_set(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        pts = [["2025-06-10T10:00:00+02:00", -40.0, 10.0, "gps"], ["2025-06-10T10:10:00+02:00", -39.0, 10.5, "gps"], ["2025-06-10T10:20:00+02:00", 5.0, 11.0, "gps"]]
        (tmp / "route.json").write_text(json.dumps({"points": pts}))
        self.assertEqual(sum(len(r) for r in minimap.load_route(tmp / "route.json")), 3)
        runs = minimap.load_route(tmp / "route.json", lat_min=-25.6)
        self.assertEqual([round(p[1]) for r in runs for p in r], [5])

    def test_missing_natural_earth_data_explains_how_to_get_it(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "route.json").write_text(json.dumps({"points": [["2025-06-10T10:00:00+02:00", 10.0, 10.0, "gps"], ["2025-06-10T10:10:00+02:00", 10.1, 10.1, "gps"]]}))
        cfg = config.activate({"paths": {"naturalearth_dir": str(tmp / "nada")}})
        mm = minimap.cfg_with(cfg["minimap"])
        with self.assertRaises(minimap.MissingData) as e:
            minimap._data(tmp / "route.json", mm)
        self.assertIn("vlog fetch-data", str(e.exception))

    def test_minimap_cache_key_ignores_new_keys_at_their_defaults(self):
        mm = minimap.cfg_with({})
        self.assertEqual(set(minimap.cache_sig(mm)), set(minimap.LEGACY_KEYS))
        changed = minimap.cfg_with({"lat_min": -25.6})
        self.assertIn("x", minimap.cache_sig(changed))

    def test_adb_forbidden_words_and_labels_come_from_config(self):
        config.activate({"adb": {"forbidden_words": ["erase"]}})
        self.assertTrue(adbui.is_forbidden("Erase everything"))
        self.assertFalse(adbui.is_forbidden("Borrar datos"))

    def test_credits_act_name_is_configurable_in_edl2guion(self):
        d = pathlib.Path(tempfile.mkdtemp())
        edl = {"acts": [{"name": "Credits", "card": None, "music": "x", "shots": [{"id": None, "kind": "card", "dur": 5, "title": None}]}]}
        config.activate({"edit": {"credits_act": "Credits"}, "credits": {"fallback_title": "The end"}})
        shots, _ = edl2guion.convert(edl, d, "map.mp4")
        self.assertEqual(shots[0]["card"]["title"], "The end")
        self.assertTrue(shots[0]["card"]["music_credits"])


if __name__ == "__main__":
    unittest.main()
