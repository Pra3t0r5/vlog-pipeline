import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import cli
import edl2guion
import ffx
import guion
import minimap
import overlay
import presets
import render
import stills
from test_guion import make

PROJECT_RECS = [
    {"id": "drone.A", "path": "/x/A.MP4", "kind": "video", "w": 3840, "h": 2160, "dur": 20.0, "has_audio": False, "place": "Springfield, Region", "lat": 10.5, "lon": 20.5, "time_art": "2025-06-12T11:00:00+02:00"},
    {"id": "phone.B", "path": "/x/B.mp4", "kind": "video", "w": 1080, "h": 1920, "dur": 10.0, "has_audio": True, "audio_lufs": -20, "place": "Springfield, Region", "lat": 10.5, "lon": 20.5, "time_art": "2025-06-12T11:00:00+02:00"},
    {"id": "phone.C", "path": "/x/C.jpg", "kind": "photo", "w": 3060, "h": 4080},
]


def make_project(shots, extra=None, mode="preview", yaml_text=None, guion_name="g.json", resolve=True):
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "inv").mkdir()
    (d / "route").mkdir()
    (d / "route" / "route.json").write_text(json.dumps({"points": [["2025-06-12T10:00:00+02:00", 10.5, 20.5, "gps"]]}))
    (d / "inv" / "media.json").write_text(json.dumps(PROJECT_RECS))
    if yaml_text:
        (d / "project.yaml").write_text(yaml_text)
    (d / guion_name).write_text(json.dumps({"name": "t", "shots": shots, **(extra or {})}))
    G = guion.Guion(d / guion_name, mode)
    if resolve:
        G.resolve(ffx.Report())
    return G


class ParseTest(unittest.TestCase):
    def test_caption_and_minimap_fields(self):
        G = make([{"id": "drone.A", "dur": 5, "caption": {"place": "Fort", "line": None}}, {"id": "drone.A", "dur": 5, "minimap": False}, {"id": "drone.A", "dur": 5, "minimap": {"opacity": 0.3}}, {"id": "drone.A", "dur": 5, "caption": {"place": None, "line": None}}])
        a, b, c, d = G.shots
        self.assertEqual(a.caption, {"place": "Fort", "line": None})
        self.assertEqual(a.minimap, {})
        self.assertIsNone(b.minimap)
        self.assertEqual(c.minimap, {"opacity": 0.3})
        self.assertIsNone(d.caption)

    def test_minimap_defaults_are_the_approved_design(self):
        G = make_project([{"id": "drone.A", "dur": 5}])
        self.assertFalse(G.minimap["enabled"])
        self.assertEqual((G.minimap["size"], G.minimap["opacity"], G.minimap["label_scale"], G.minimap["radius_km"], G.minimap["urban_km"], G.minimap["position"]), (None, 0.6, 0.8, 120.0, 1.2, "top-right"))
        self.assertEqual(G.minimap["presets"], {})

    def test_project_yaml_and_guion_override(self):
        G = make_project([{"id": "drone.A", "dur": 5}], extra={"minimap": {"size": 0.08}}, yaml_text="name: t\nminimap:\n  enabled: true\n  opacity: 0.5\n")
        self.assertTrue(G.minimap["enabled"])
        self.assertEqual((G.minimap["opacity"], G.minimap["size"]), (0.5, 0.08))

    def test_bad_position_rejected(self):
        with self.assertRaises(ValueError):
            minimap.cfg_with({"position": "middle"})

    def test_focus_x_range(self):
        with self.assertRaises(ffx.RenderError):
            make([{"id": "drone.A", "dur": 5, "focus_x": 1.5}])


class PlanTest(unittest.TestCase):
    def plan(self, shots, **kw):
        G = make_project(shots, extra={"minimap": {"enabled": True}}, **kw)
        rep = ffx.Report()
        return G, [render.overlay_plan(G, s, rep) for s in G.shots], rep

    def intervals(self, shots, **kw):
        G, _, rep = self.plan(shots, **kw)
        return G, render.minimap_intervals(G, rep)

    def test_minimap_runs_break_on_cards_and_shots_without_gps(self):
        G, ivs = self.intervals([{"id": "drone.A", "dur": 6}, {"card": {"title": "x"}, "dur": 4}, {"id": "drone.A", "dur": 6}, {"id": "phone.C", "dur": 4}, {"id": "drone.A", "dur": 6, "minimap": False}])
        self.assertEqual([iv["idx"] for iv in ivs], [0, 2])
        self.assertTrue(all(iv["fin"] and iv["fout"] for iv in ivs))

    def test_minimap_key_changes_with_config_and_format(self):
        G, _, _ = self.plan([{"id": "drone.A", "dur": 6}])
        Go = make_project([{"id": "drone.A", "dur": 6, "minimap": {"opacity": 0.3}}], extra={"minimap": {"enabled": True}})
        k = lambda g: render.minimap_plan(g, g.shots[0], ffx.Report())["key"]
        self.assertNotEqual(k(G), k(Go))
        Gc = make_project([{"id": "drone.A", "dur": 6}], extra={"minimap": {"enabled": True}}, mode="celu", resolve=False)
        Gc.shots, Gc.W, Gc.H = G.shots, Gc.W, Gc.H
        self.assertNotEqual(k(G), k(Gc))

    def test_run_is_continuous_across_cuts_and_fades_only_at_the_edges(self):
        G, ivs = self.intervals([{"id": "drone.A", "dur": 6}, {"id": "drone.A", "dur": 6, "transition": "cut"}, {"id": "drone.A", "dur": 6, "transition": "cut"}])
        self.assertEqual([iv["idx"] for iv in ivs], [0, 1, 2])
        self.assertEqual(ivs[0]["f1"], ivs[1]["f0"])
        self.assertEqual(ivs[1]["f1"], ivs[2]["f0"])
        self.assertEqual((ivs[0]["fin"], ivs[1]["fin"], ivs[2]["fin"]), (round(overlay.MM_FADE_S * float(G.fps)), 0, 0))
        self.assertEqual((ivs[0]["fout"], ivs[1]["fout"], ivs[2]["fout"]), (0, 0, round(overlay.MM_FADE_S * float(G.fps))))

    def test_switch_happens_at_the_midpoint_of_a_crossfade(self):
        G, ivs = self.intervals([{"id": "drone.A", "dur": 6}, {"id": "drone.A", "dur": 6}])
        s1 = G.shots[1]
        self.assertEqual(ivs[0]["f1"], ivs[1]["f0"])
        self.assertEqual(ivs[1]["f0"], s1.start + s1.xn // 2)

    def test_run_starts_after_the_crossfade_from_a_card_and_ends_before_the_next_card(self):
        G, ivs = self.intervals([{"card": {"title": "x"}, "dur": 4}, {"id": "drone.A", "dur": 6}, {"card": {"title": "y"}, "dur": 4}])
        s1, s2 = G.shots[1], G.shots[2]
        self.assertEqual(ivs[0]["f0"], s1.start + s1.xn)
        self.assertEqual(ivs[0]["f1"], s2.start)

    def test_act_change_starts_a_new_run(self):
        shots = [{"id": "drone.A", "dur": 6, "act": "a"}, {"id": "drone.A", "dur": 6, "act": "b", "transition": "cut"}]
        G, ivs = self.intervals(shots)
        self.assertEqual((ivs[0]["fout"] > 0, ivs[1]["fin"] > 0), (True, True))

    def test_part_graph_overlays_minimap_with_no_fade_inside_a_run(self):
        G, ivs = self.intervals([{"id": "drone.A", "dur": 6}, {"id": "drone.A", "dur": 6, "transition": "cut"}])
        for iv in ivs:
            iv["png"], iv["x"], iv["y"] = pathlib.Path("/tmp/m.png"), 10, 20
        parts = render.plan_parts(G, 4)
        a, b, members = parts[0]
        fc, inputs = render.part_graph(G, a, b, members, {0: "/tmp/a.mp4", 1: "/tmp/b.mp4"}, render.part_overlays(a, b, ivs))
        self.assertEqual(fc.count("overlay=10:20"), 2)
        self.assertEqual(fc.count("fade=in:start_frame=0"), 1)
        self.assertEqual(fc.count("fade=out"), 1 + fc.count("fade=out:st="))
        self.assertEqual(inputs.count("-i"), 2)

    def test_format_params_scale_by_short_side(self):
        cfg = minimap.cfg_with({})
        d = {f: minimap.params(cfg, f, wh) for f, wh in (("tv", (3840, 2160)), ("celu", (1920, 1080)), ("chat", (640, 360)), ("reel", (1080, 1920)))}
        self.assertEqual(d["tv"]["D"], 216)
        self.assertEqual(d["celu"]["D"], 108)
        self.assertEqual(d["chat"]["D"], 50)
        self.assertEqual(d["reel"]["D"], 173)
        self.assertGreaterEqual(d["chat"]["min_px"], 11)
        over = minimap.cfg_with({"presets": {"chat": {"diameter": 0.2}}})
        self.assertEqual(minimap.params(over, "chat", (640, 360))["D"], 72)
        with self.assertRaises(ValueError):
            minimap.cfg_with({"presets": {"tablet": {}}})

    def test_chat_label_never_below_11px(self):
        cfg = minimap.cfg_with({})
        pr = minimap.params(cfg, "chat", (640, 360))
        lines = minimap._label_lines("Mirador del Valle Largo", "2025-06-16T14:33:31+02:00", pr["D"], pr["S"], pr["size_mult"], pr["fit_mult"], pr["min_px"])
        self.assertTrue(all(f.size >= 11 for _, f, _ in lines))

    def test_caption_params_per_format(self):
        c = overlay.cfg_with({})
        self.assertGreaterEqual(overlay.params(c, "chat", (640, 360))["fp"], 12)
        self.assertEqual(overlay.params(c, "tv", (3840, 2160))["fp"], round(2160 * 0.018))
        self.assertEqual(overlay.params(overlay.cfg_with({"presets": {"tv": {"place": 0.03}}}), "tv", (3840, 2160))["fp"], round(2160 * 0.03))

    def test_caption_window_and_short_shot(self):
        G, plans, rep = self.plan([{"id": "drone.A", "dur": 6, "caption": {"place": "a", "line": "b"}}, {"id": "drone.A", "dur": 2.4, "caption": {"place": "c"}}, {"id": "drone.A", "dur": 6}])
        w = plans[0]["cap"]
        self.assertAlmostEqual(w["in"], 0.5, places=2)
        self.assertAlmostEqual(w["out"], G.shots[0].n / float(G.fps) - G.shots[1].xn / float(G.fps) - overlay.FADE_S, places=2)
        self.assertNotIn("cap", plans[1])
        self.assertTrue(any("caption omitido" in x for x in rep.warnings))

    def test_caption_waits_for_title(self):
        G, plans, _ = self.plan([{"id": "drone.A", "dur": 9, "title": {"text": "t"}, "caption": {"place": "a"}}])
        self.assertGreaterEqual(plans[0]["cap"]["in"], 4.0)
        G, plans, rep = self.plan([{"id": "drone.A", "dur": 5, "title": {"text": "t"}, "caption": {"place": "a"}}])
        self.assertNotIn("cap", plans[0])

    def test_segments_carry_no_minimap(self):
        G, plans, _ = self.plan([{"id": "drone.A", "dur": 6, "caption": {"place": "a"}}])
        self.assertIn("cap", plans[0])
        self.assertNotIn("mm", plans[0])


class PresetTest(unittest.TestCase):
    def test_tv_is_final_with_its_own_name(self):
        G = make_project([{"id": "drone.A", "dur": 5}], mode="tv", resolve=False)
        self.assertEqual((G.mode, G.label, G.W, G.H), ("final", "tv", 3840, 2160))
        self.assertEqual(presets.out_path(G, "tv").name, "t-tv.mp4")

    def test_reel_geometry_and_default_fit(self):
        G = make_project([{"id": "drone.A", "dur": 5}, {"id": "phone.B", "dur": 5}, {"id": "phone.C", "dur": 4}, {"id": "drone.A", "dur": 5, "fit": "blur", "focus_x": 0.2}], mode="reel")
        self.assertEqual((G.W, G.H, G.vertical), (1080, 1920, True))
        self.assertEqual([s.fit for s in G.shots], ["fill", "blur", "blur", "blur"])
        self.assertEqual(G.shots[3].focus_x, 0.2)

    def test_reel_over_90_seconds_rejected(self):
        with self.assertRaises(ffx.RenderError):
            make_project([{"id": "drone.A", "dur": 19, "transition": "cut"}] * 5, mode="reel")

    def test_reel_90_seconds_ok(self):
        G = make_project([{"id": "drone.A", "dur": 18, "transition": "cut"}] * 5, mode="reel")
        self.assertLessEqual(G.total, 90)

    def test_celu_and_chat_render_natively(self):
        c = make_project([{"id": "drone.A", "dur": 5}], mode="celu", resolve=False)
        t = make_project([{"id": "drone.A", "dur": 5}], mode="chat", resolve=False)
        self.assertEqual((c.W, c.H, c.fmt), (1920, 1080, "celu"))
        self.assertEqual((t.W, t.H, t.fmt, t.preset["max_mb"]), (640, 360, "chat", 28))
        self.assertEqual(make_project([{"id": "drone.A", "dur": 5}], mode="preview", resolve=False).fmt, "tv")

    def test_outputs_in_project_yaml(self):
        cfg = {"name": "t", "guion": "g.json", "outputs": ["tv", "celu", {"preset": "reel", "guion": "r.json"}, "build/old.mp4", "nada"]}
        self.assertEqual(cli.output_entries(cfg), [("tv", None), ("celu", None), ("reel", "r.json")])
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "g.json").write_text(json.dumps({"name": "trip", "out_dir": "build"}))
        (d / "r.json").write_text(json.dumps({"name": "trip-reel", "out_dir": "build"}))
        outs = {p.name for p in cli.declared_outputs(d, cfg)}
        self.assertEqual(outs, {"trip-tv.mp4", "trip-final.mp4", "trip-celu.mp4", "trip-reel-reel.mp4", "old.mp4"})


class Edl2GuionTest(unittest.TestCase):
    def test_caption_lines_and_music_plan_pass_through(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "music").mkdir()
        (d / "music" / "m.wav").write_text("x")
        edl = {"crossfade_s": 0.6, "music_plan": [{"slot": "mix", "file": "music/m.wav"}], "acts": [
            {"name": "A", "card": None, "music": "mix", "shots": [{"id": "drone.A", "kind": "video", "in": 0, "out": 4, "caption": {"place": "P", "line": "L"}}, {"id": "phone.C", "kind": "photo", "dur": 3, "caption": {"place": None, "line": None}}]},
            {"name": "Créditos", "card": None, "music": "mix", "shots": [{"id": None, "kind": "card", "dur": 5, "title": {"text": "Fin"}, "lines": ["uno", "dos"]}]},
        ]}
        shots, music = edl2guion.convert(edl, d, "map.mp4")
        self.assertEqual(shots[0]["caption"], {"place": "P", "line": "L"})
        self.assertNotIn("caption", shots[1])
        self.assertEqual(shots[2]["card"]["lines"], ["uno", "dos"])
        self.assertEqual(shots[2]["card"]["title"], "Fin")
        self.assertNotIn("music_credits", shots[2]["card"])
        self.assertEqual(music, [{"file": "music/m.wav", "from_shot": 0, "to_shot": 2}])

    def test_title_card_role_goes_before_the_credits_over_the_last_photo(self):
        d = pathlib.Path(tempfile.mkdtemp())
        edl = {"acts": [{"name": "Créditos", "card": None, "music": "x", "shots": [
            {"id": "phone.C", "kind": "photo", "dur": 5},
            {"id": None, "kind": "card", "dur": 4.5, "role": "title", "title": {"text": "Peli", "sub": "Sub"}},
            {"id": None, "kind": "card", "dur": 7, "title": {"text": "Fin"}, "lines": ["uno"]}]}]}
        shots, _ = edl2guion.convert(edl, d, "map.mp4")
        self.assertEqual(shots[1]["card"], {"title": "Peli", "sub": "Sub", "bg": {"id": "phone.C"}})
        self.assertEqual((shots[2]["card"]["title"], shots[2]["card"]["lines"]), ("Fin", ["uno"]))

    def test_legacy_credits_card_keeps_music_credits(self):
        d = pathlib.Path(tempfile.mkdtemp())
        edl = {"acts": [{"name": "Créditos", "card": None, "music": "x", "shots": [{"id": None, "kind": "card", "dur": 5, "title": None}]}]}
        shots, _ = edl2guion.convert(edl, d, "map.mp4")
        self.assertTrue(shots[0]["card"]["music_credits"])
        self.assertEqual(shots[0]["card"]["title"], edl2guion.CREDITS_TEXT)


class ColorMatrixTest(unittest.TestCase):
    def roundtrip(self, chain):
        d = pathlib.Path(tempfile.mkdtemp())
        from PIL import Image
        Image.new("RGB", (64, 64), (200, 40, 40)).save(d / "red.png")
        yuv = d / "o.mp4"
        ffx.run(["ffmpeg", "-v", "error", "-y", "-i", d / "red.png", "-vf", chain, "-frames:v", "1", "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", yuv])
        ffx.run(["ffmpeg", "-v", "error", "-y", "-i", yuv, "-vf", "scale=in_color_matrix=bt709:in_range=tv,format=rgb24", "-frames:v", "1", d / "back.png"])
        return Image.open(d / "back.png").convert("RGB").getpixel((10, 10))

    def test_photo_chain_is_bt709(self):
        got = self.roundtrip(f"{stills.RGB_TO_YUV709},format=yuv420p")
        self.assertLessEqual(max(abs(a - b) for a, b in zip(got, (200, 40, 40))), 3, got)


if __name__ == "__main__":
    unittest.main()
