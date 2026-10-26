import copy
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))

import config
import edl_check
import ffx
import minimap
import overlay
import overlaycheck
import pacing
import render
import stills
import textplan
from test_edl_check import CFG, INP, credits, edl, shot
from test_overlays import make_project

CUT = {"transition": "cut"}


def caps_of(shots, minimap_on=False, **kw):
    extra = {"minimap": {"enabled": True}} if minimap_on else None
    G = make_project(shots, extra=extra, **kw)
    rep = ffx.Report()
    plans = render.minimap_plans(G, rep)
    return G, plans, render.caption_intervals(G, plans, rep), rep


def of_kind(caps, kind):
    return [c for c in caps if c["kind"] == kind]


class FixedSizeTest(unittest.TestCase):
    def test_label_font_px_do_not_depend_on_the_text(self):
        for fmt, wh in (("tv", (3840, 2160)), ("celu", (1920, 1080)), ("chat", (640, 360)), ("reel", (1080, 1920))):
            pr = minimap.params(minimap.cfg_with({}), fmt, wh)
            font = config.font("main")
            place_px, date_px = set(), set()
            for place in ("Hi", "Mirador del valle", "Valley of the Four Lost Rivers National Park", None):
                rows = minimap.label_rows(place, "2025-06-12T10:00:00+02:00", pr, font)
                place_px |= {f.size for _, f, _ in rows[:-1]}
                date_px.add(rows[-1][1].size)
            self.assertEqual((place_px, date_px), ({pr["fp"]}, {pr["fl"]}))

    def test_label_and_captions_share_one_scale_and_margins(self):
        typo = overlay.params(overlay.cfg_with({}), "tv", (3840, 2160))
        pr = minimap.params(minimap.cfg_with({}), "tv", (3840, 2160), typo)
        self.assertEqual((pr["fp"], pr["fl"], pr["mx"], pr["my"]), (typo["fp"], typo["fl"], typo["mx"], typo["my"]))

    def test_long_name_wraps_to_two_lines_without_shrinking(self):
        pr = minimap.params(minimap.cfg_with({}), "tv", (3840, 2160))
        rows = minimap.label_rows("Valley of the Four Lost Rivers National Park", "2025-06-12T10:00:00+02:00", pr, config.font("main"))
        self.assertEqual(len(rows), 3)
        self.assertEqual({f.size for _, f, _ in rows[:2]}, {pr["fp"]})

    def test_tv_sizes_are_the_requested_ones(self):
        pr = minimap.params(minimap.cfg_with({}), "tv", (3840, 2160))
        self.assertEqual(pr["D"], round(2160 * 0.14))
        old = 2160 * 0.018
        self.assertAlmostEqual(pr["fp"] / old, 1.4, places=1)

    def test_cards_and_titles_wrap_instead_of_shrinking(self):
        style = {"font": config.font("main")}
        short, _ = stills.wrap_font(style, "Hola", 100, 600)
        long, lines = stills.wrap_font(style, "Una frase bastante larga que no entra en una sola línea de ancho", 100, 600)
        self.assertEqual(short.size, long.size)
        self.assertGreater(len(lines), 1)


class RedundancyTest(unittest.TestCase):
    def test_card_title_naming_the_place_suppresses_caption_place_and_label_place(self):
        G, plans, caps, _ = caps_of([
            {"card": {"title": "Springfield · 12 de junio"}, "dur": 3},
            {"id": "drone.A", "dur": 7, "caption": {"place": "Springfield", "line": "Una frase corta aqui"}},
            {"id": "drone.A", "dur": 7, "caption": {"place": "Springfield", "line": "Otra frase corta alli"}, **CUT},
        ], minimap_on=True)
        self.assertEqual(of_kind(caps, "place"), [])
        self.assertTrue(of_kind(caps, "desc"))
        self.assertFalse(plans[1]["show_place"])
        self.assertFalse(plans[2]["show_place"])

    def test_other_place_is_still_shown(self):
        G, plans, caps, _ = caps_of([
            {"card": {"title": "Springfield · 12 de junio"}, "dur": 3},
            {"id": "drone.A", "dur": 7, "caption": {"place": "Mirador", "line": "Una frase corta aqui"}},
        ], minimap_on=True)
        self.assertEqual(len(of_kind(caps, "place")), 1)
        self.assertTrue(plans[1]["show_place"] is False)

    def test_lower_third_title_naming_the_place(self):
        G, plans, caps, _ = caps_of([{"id": "drone.A", "dur": 9, "title": {"text": "Springfield", "sub": "12 de junio"}, "caption": {"place": "Springfield", "line": "Una frase corta aqui"}}])
        self.assertEqual(of_kind(caps, "place"), [])

    def test_caption_place_equal_to_minimap_label_shows_only_the_description(self):
        G, plans, caps, _ = caps_of([{"id": "drone.A", "dur": 8, "caption": {"place": "Springfield", "line": "Una frase corta aqui"}}], minimap_on=True)
        self.assertTrue(plans[0]["show_place"])
        self.assertEqual(of_kind(caps, "place"), [])
        self.assertEqual(len(of_kind(caps, "desc")), 1)

    def test_without_minimap_the_place_is_kept(self):
        G, plans, caps, _ = caps_of([{"id": "drone.A", "dur": 8, "caption": {"place": "Springfield", "line": "Una frase corta aqui"}}])
        self.assertEqual(len(of_kind(caps, "place")), 1)

    def test_label_date_only_has_no_place_row(self):
        pr = minimap.params(minimap.cfg_with({}), "tv", (3840, 2160))
        self.assertEqual(len(minimap.label_rows(None, "2025-06-12T10:00:00+02:00", pr, config.font("main"))), 1)

    def test_norm_matches_accents_case_and_title_segments(self):
        self.assertTrue(textplan.names_place(textplan.names_of(["Peñón Rojo · 12 de junio"]), "penon rojo"))
        self.assertFalse(textplan.names_place(textplan.names_of(["Camino al Peñón Rojo"]), "penon rojo"))


class RunTimingTest(unittest.TestCase):
    SHOTS = [
        {"id": "drone.A", "dur": 7, "caption": {"place": "Mirador", "line": "Primera frase de cuatro palabras"}},
        {"id": "drone.A", "dur": 7, "caption": {"place": "Mirador", "line": "Segunda frase de prueba aqui"}, **CUT},
        {"id": "drone.A", "dur": 7, "caption": {"place": "Mirador", "line": None}, **CUT},
    ]

    def test_place_is_one_continuous_layer_across_the_run(self):
        G, _, caps, _ = caps_of(self.SHOTS)
        places = of_kind(caps, "place")
        self.assertEqual(len(places), 1)
        self.assertEqual((places[0]["fin"], places[0]["fout"]), (round(overlay.fade_s() * float(G.fps)),) * 2)
        self.assertLessEqual(places[0]["f0"] / float(G.fps), 0.6)
        self.assertGreaterEqual(places[0]["f1"], G.shots[2].start + G.shots[2].n - round(float(G.fps)))

    def test_descriptions_crossfade_and_never_fade_at_a_cut_without_overlap(self):
        G, _, caps, _ = caps_of(self.SHOTS)
        a, b = of_kind(caps, "desc")
        df = round(overlay.fade_s() * float(G.fps))
        self.assertAlmostEqual(a["f1"] - df, b["f0"], delta=1)
        self.assertEqual((a["fin"], a["fout"], b["fin"], b["fout"]), (df,) * 4)
        cut = G.shots[1].start
        self.assertLess(b["f0"], cut)
        self.assertGreater(a["f1"], cut)

    def test_each_description_meets_its_minimum_time(self):
        G, _, caps, _ = caps_of(self.SHOTS)
        fps, d = float(G.fps), overlay.fade_s()
        for c in of_kind(caps, "desc"):
            on = (c["f1"] - c["f0"]) / fps - d
            self.assertGreaterEqual(on + 0.05, textplan.min_line_s(c["text"]))

    def test_short_shot_keeps_the_description_of_the_previous_one_until_its_minimum(self):
        shots = [
            {"id": "drone.A", "dur": 2.6, "caption": {"place": "Mirador", "line": "Una dos tres cuatro cinco seis"}},
            {"id": "drone.A", "dur": 8, "caption": {"place": "Mirador", "line": "Siguiente frase de prueba aqui"}, **CUT},
        ]
        G, _, caps, _ = caps_of(shots)
        first, second = of_kind(caps, "desc")
        fps = float(G.fps)
        need = textplan.min_line_s(first["text"])
        self.assertGreater(second["f0"], G.shots[1].start)
        self.assertGreaterEqual((second["f0"] - first["f0"]) / fps, need - 0.05)

    SHORT = [
        {"id": "drone.A", "dur": 8, "caption": {"place": "Mirador", "line": "Primera frase de prueba aqui"}},
        {"id": "drone.A", "dur": 1.5, "caption": {"place": "Mirador", "line": "Una dos tres cuatro cinco seis siete"}, **CUT},
        {"id": "drone.A", "dur": 6, "caption": {"place": "Mirador", "line": None}, **CUT},
    ]

    def test_persist_policy_shows_the_short_shot_description_across_the_next_shot(self):
        G, _, caps, _ = caps_of(self.SHORT)
        self.assertEqual([c["text"] for c in of_kind(caps, "desc")], ["Primera frase de prueba aqui", "Una dos tres cuatro cinco seis siete"])
        last = of_kind(caps, "desc")[1]
        self.assertGreater(last["f1"], G.shots[2].start)

    def test_skip_policy_drops_the_description_of_a_short_shot(self):
        G, _, caps, rep = caps_of(self.SHORT, yaml_text="name: t\ncaption:\n  on_short_shot: skip\n")
        self.assertEqual([c["text"] for c in of_kind(caps, "desc")], ["Primera frase de prueba aqui"])
        self.assertTrue(any("descripción omitida" in w for w in rep.warnings))

    def test_short_shots_show_only_the_place(self):
        shots = [
            {"id": "drone.A", "dur": 8, "caption": {"place": "Mirador", "line": "Una frase de prueba larga aqui"}},
            {"id": "drone.A", "dur": 3, "caption": {"place": "Mirador", "line": None}, **CUT},
        ]
        G, _, caps, _ = caps_of(shots)
        desc = of_kind(caps, "desc")[0]
        place = of_kind(caps, "place")[0]
        self.assertLess(desc["f1"], place["f1"])
        self.assertGreater(place["f1"], G.shots[1].start)

    def test_different_places_make_different_runs(self):
        shots = [
            {"id": "drone.A", "dur": 6, "caption": {"place": "Mirador", "line": None}},
            {"id": "drone.A", "dur": 6, "caption": {"place": "Cascada", "line": None}, **CUT},
        ]
        _, _, caps, _ = caps_of(shots)
        self.assertEqual(len(of_kind(caps, "place")), 2)

    def test_part_graph_has_no_fade_at_a_cut_inside_a_run(self):
        G, _, caps, _ = caps_of(self.SHOTS)
        place = of_kind(caps, "place")[0]
        fc, _ = render.part_graph(G, 0, G.total_frames, render.plan_parts(G, 8)[0][2], {i: f"/tmp/{i}.mp4" for i in range(3)}, render.part_overlays(0, G.total_frames, [place]))
        self.assertEqual(fc.count("fade=in:start_frame=0"), 1)
        self.assertEqual(fc.count("fade=out:start_frame"), 1)

    def test_caption_cache_key_is_independent_from_segments(self):
        G, _, caps, _ = caps_of(self.SHOTS)
        self.assertTrue(all(c["png"].exists() for c in caps))


class PacingTest(unittest.TestCase):
    def test_relaxed_is_the_default_and_multiplies_the_targets(self):
        st = pacing.settings({})
        self.assertEqual((st["mode"], st["multiplier"]), ("relaxed", 1.3))
        self.assertEqual((st["ranges"]["drone"], st["ranges"]["photo"], st["ranges"]["hero"]), ([5.0, 8.0], [3.5, 5.0], [5.0, 6.0]))
        self.assertAlmostEqual(st["max_cuts_per_min"], 13.8)

    def test_standard_keeps_the_original_ranges(self):
        st = pacing.settings({"pacing": "standard"})
        self.assertEqual((st["multiplier"], st["ranges"]["drone"], st["ranges"]["photo"]), (1.0, [4.0, 6.0], [2.5, 4.0]))

    def test_mapping_form_and_min_shot_override(self):
        st = pacing.settings({"pacing": {"mode": "standard", "min_shot_s": 2.0}})
        self.assertEqual((st["mode"], pacing.min_for(st, "drone")), ("standard", 2.0))

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(config.ConfigError):
            pacing.settings({"pacing": "frenetic"})

    def test_editor_prompt_carries_the_ranges(self):
        import prompts
        text = prompts.render("editor", tempfile.mkdtemp(), {"name": "t"})
        self.assertIn("5 a 8", text)
        self.assertIn("3,5 a 5", text)
        self.assertNotRegex(text, r"\{\{(pacing|drone|photo|hero|phone|min_shot|max_cuts)\w*\}\}")


class EdlCheckTest(unittest.TestCase):
    def run_check(self, e, cfg=CFG, inp=INP):
        return edl_check.check(e, copy.deepcopy(inp), cfg)

    def long_shot(self, i, **kw):
        s = shot(i, **kw)
        s["dur"] = 9
        return s

    def test_caption_duplicating_the_title_warns(self):
        e = edl(self.long_shot("p1", title={"text": "Springfield", "sub": "12 de junio"}, caption={"place": "Springfield", "line": None}))
        _, warns = self.run_check(e)
        self.assertTrue(any(w.startswith("caption-dup-title") for w in warns), warns)

    def test_caption_duplicating_the_minimap_label_warns_only_with_minimap(self):
        inp = copy.deepcopy(INP)
        inp["captions"] = {"p1": {"place": "Mirador", "confidence": "high"}}
        e = edl(self.long_shot("p1", caption={"place": "Mirador", "line": None}))
        _, warns = self.run_check(e, {**CFG, "minimap": {"enabled": True}}, inp)
        self.assertTrue(any(w.startswith("caption-dup-minimap") for w in warns), warns)
        _, warns = self.run_check(e, CFG, inp)
        self.assertFalse(any(w.startswith("caption-dup-minimap") for w in warns))

    def test_description_without_time_warns(self):
        e = edl(self.long_shot("p1", caption={"place": "Mirador", "line": None}), {**shot("v1", "video", caption={"place": "Mirador", "line": "una dos tres cuatro cinco seis siete ocho"}), "in": 2, "out": 4.6})
        _, warns = self.run_check(e)
        self.assertTrue(any(w.startswith("caption-min-time") for w in warns), warns)

    def test_run_of_short_shots_with_captions_is_not_an_error_when_it_is_long_enough(self):
        e = edl(shot("p1", dur=2, caption={"place": "Mirador", "line": None}), shot("v1", "video", caption={"place": "Mirador", "line": None}))
        errs, _ = self.run_check(e)
        self.assertNotIn("caption-short", [x.split()[0] for x in errs])

    def test_pacing_short_and_cuts_warn(self):
        e = edl(shot("p1"), {**shot("v1", "video"), "out": 5.5})
        _, warns = self.run_check(e)
        self.assertTrue(any(w.startswith("pacing-short v1") for w in warns), warns)
        _, warns = self.run_check(e, {**CFG, "pacing": "standard"})
        self.assertFalse(any(w.startswith("pacing-short v1") for w in warns), warns)
        _, warns = self.run_check(e, {**CFG, "pacing": {"min_shot_s": 1.0}})
        self.assertFalse(any(w.startswith("pacing-short v1") for w in warns), warns)
        _, warns = self.run_check(e)
        self.assertTrue(any(w.startswith("pacing-cuts") for w in warns), warns)


class OverlayCheckTest(unittest.TestCase):
    def test_synthetic_stills_per_preset(self):
        out = pathlib.Path(tempfile.mkdtemp())
        written, sizes = overlaycheck.build(out)
        self.assertEqual({p.name for p in written}, {f"{f}-{c}.png" for f in ("tv", "celu", "chat", "reel") for c in overlaycheck.CASES})
        self.assertTrue(all(p.exists() and p.stat().st_size > 0 for p in written))
        self.assertEqual((sizes["tv"]["place_px"], sizes["tv"]["line_px"], sizes["tv"]["minimap_diameter_px"]), (54, 45, 302))


if __name__ == "__main__":
    unittest.main()
