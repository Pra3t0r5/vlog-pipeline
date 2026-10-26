import argparse
import json
import math
import pathlib
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import config
import minimap
import overlay

FORMATS = {"tv": "final", "celu": "celu", "chat": "chat", "reel": "reel"}
LAT, LON = 10.50, 20.50
TIME = "2025-06-12T10:45:00+02:00"
CASES = {
    "standard": {
        "map_place": "Lookout Ridge",
        "cap_place": "Old Quarry Trail",
        "cap_line": "Limestone beds here formed on an ancient seafloor",
    },
    "long-names": {
        "map_place": "Valley of the Four Lost Rivers National Park",
        "cap_place": "Old Quarry Trail",
        "cap_line": "The ridge line follows a fault that raised these limestone beds long before the first settlers arrived",
    },
    "date-only": {
        "map_place": None,
        "cap_place": "Old Quarry Trail",
        "cap_line": "Limestone beds here formed on an ancient seafloor",
    },
}


def synthetic_frame(W, H):
    im = Image.new("RGB", (W, H))
    px = ImageDraw.Draw(im)
    for y in range(H):
        t = y / H
        px.line([(0, y), (W, y)], fill=(int(70 + 120 * t), int(120 + 80 * t), int(190 - 20 * t)))
    sun = min(W, H) * 0.09
    px.ellipse([W * 0.62 - sun, H * 0.28 - sun, W * 0.62 + sun, H * 0.28 + sun], fill=(255, 236, 190))
    for k, (base, amp, col) in enumerate(((0.62, 0.16, (88, 104, 120)), (0.74, 0.12, (70, 88, 82)), (0.88, 0.08, (52, 66, 54)))):
        pts = [(0, H)] + [(x, H * (base - amp * (0.5 + 0.5 * math.sin(x / W * (5 + 2 * k) + k)))) for x in range(0, W + 1, max(1, W // 160))] + [(W, H)]
        px.polygon(pts, fill=col)
    return im.filter(ImageFilter.GaussianBlur(max(1, W // 900)))


def synthetic_data(work):
    ne = work / "ne"
    ne.mkdir(parents=True)
    line = lambda pts: {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": pts}}
    roads = [line([[LON - 1.0 + 0.1 * i, LAT - 0.7 + 0.04 * i + 0.1 * math.sin(i)] for i in range(25)]), line([[LON - 0.9, LAT + 0.5 - 0.08 * i] for i in range(15)])]
    provs = [line([[LON - 0.3 + 0.7 * math.cos(a / 8), LAT + 0.5 * math.sin(a / 8)] for a in range(0, 51)])]
    places = [{"type": "Feature", "properties": {"name": "Springfield"}, "geometry": {"type": "Point", "coordinates": [LON + 0.45, LAT + 0.3]}}]
    for name, feats in (("ne_10m_roads.geojson", roads), ("ne_10m_admin_1_states_provinces.geojson", provs), ("ne_10m_populated_places_simple.geojson", places)):
        (ne / name).write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    route = work / "route.json"
    pts = [[f"2025-06-12T{10 + i // 30:02d}:{(i * 2) % 60:02d}:00+02:00", LAT - 0.35 + 0.0125 * i, LON - 0.4 + 0.017 * i + 0.05 * math.sin(i / 4), "gps"] for i in range(60)]
    route.write_text(json.dumps({"points": pts}))
    return ne, route


def compose(fmt, W, H, case, route, labels, font):
    typo = overlay.params(overlay.cfg_with({}), fmt, (W, H))
    frame = synthetic_frame(W, H).convert("RGBA")
    mm = minimap.render_overlay(TIME, LAT, LON, case["map_place"], (W, H), "dark", route, labels, None, minimap.cfg_with({"enabled": True}), fmt, typo, font)
    frame.alpha_composite(mm)
    lay = overlay.caption_layout(case["cap_place"], [case["cap_line"]], W, H, font, None, fmt)
    tmp = pathlib.Path(tempfile.mkdtemp())
    for name, xy, draw in (("p", overlay.place_xy(lay), lambda f: overlay.place_png(lay, f)), ("d", overlay.desc_xy(lay, case["cap_line"]), lambda f: overlay.desc_png(lay, case["cap_line"], f))):
        draw(tmp / f"{name}.png")
        frame.alpha_composite(Image.open(tmp / f"{name}.png").convert("RGBA"), (xy[0], xy[1]))
    return frame.convert("RGB"), typo


def build(out_dir):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="vlog-overlay-check."))
    ne, route = synthetic_data(work)
    previous = config._active
    config.activate({"paths": {"naturalearth_dir": str(ne), "osm_dir": str(work / "osm")}})
    try:
        font = config.font("main")
        presets = config.base_section("presets")
        labels = {"Springfield": (LAT + 0.3, LON + 0.45), "Old Mill": (LAT - 0.2, LON - 0.3)}
        written, sizes = [], {}
        for fmt, mode in FORMATS.items():
            W, H = presets[mode]["w"], presets[mode]["h"]
            for case_name, case in CASES.items():
                im, typo = compose(fmt, W, H, case, route, labels, font)
                path = out_dir / f"{fmt}-{case_name}.png"
                im.save(path)
                written.append(path)
            sizes[fmt] = {"frame": [W, H], "place_px": typo["fp"], "line_px": typo["fl"], "margin_px": [typo["mx"], typo["my"]], "minimap_diameter_px": minimap.params(minimap.cfg_with({}), fmt, (W, H), typo)["D"]}
        return written, sizes
    finally:
        config._active = previous


def main(argv):
    ap = argparse.ArgumentParser(prog="overlay-check", description="Genera stills de un shot sintético con minimapa y caption en cada preset, para revisar tamaños sin material propio")
    ap.add_argument("--out", default=str(pathlib.Path(tempfile.gettempdir()) / "vlog-overlay-check"))
    a = ap.parse_args(argv)
    written, sizes = build(a.out)
    for p in written:
        print(p)
    for fmt, s in sizes.items():
        print(f"{fmt}: cuadro {s['frame'][0]}x{s['frame'][1]} · lugar {s['place_px']}px · descripción/fecha {s['line_px']}px · margen {s['margin_px'][0]}x{s['margin_px'][1]}px · minimapa {s['minimap_diameter_px']}px")


if __name__ == "__main__":
    main(sys.argv[1:])
