import json, math, pathlib, datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import config
import overlay

MAJOR = {"motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link"}
SKIP = {"footway", "path", "steps", "cycleway", "pedestrian", "bridleway", "corridor", "service", "track"}
KM_LAT, KM_LON0 = 110.57, 111.32
REF_RADIUS_KM = 120.0
NE_FILES = config.NE_FILES

_cache = {}


class MissingData(Exception):
    pass


def _load(path):
    with open(path) as f:
        return json.load(f)


def _font(size):
    return ImageFont.truetype(config.font("main"), size)


def _geo(cfg=None):
    return (cfg or config.base_section("minimap"))["geometry"]


def _ne_dir():
    d = config.vendor_path("naturalearth_dir", "naturalearth")
    for fn in NE_FILES:
        if not (d / fn).exists():
            raise MissingData(f"falta {d / fn}: corré `vlog fetch-data` para bajar los datos de Natural Earth")
    return d


def _osm_dir():
    return config.vendor_path("osm_dir", "osm")


def _lines(geom):
    t, c = geom["type"], geom["coordinates"]
    if t == "LineString": return [c]
    if t == "MultiLineString": return c
    if t == "Polygon": return c
    if t == "MultiPolygon": return [r for poly in c for r in poly]
    return []


def _parse(ts):
    return datetime.datetime.fromisoformat(ts)


def load_route(route_path, lat_min=None, simplify_km=1.5):
    rp = pathlib.Path(route_path)
    filled = rp.with_name("route_filled.json")
    pts = _load(filled if filled.exists() else rp)["points"]
    runs, cur = [], []
    for ts, lat, lon, *_ in pts:
        if lat_min is None or lat > lat_min:
            cur.append((_parse(ts), lat, lon))
        elif cur:
            runs.append(cur); cur = []
    if cur: runs.append(cur)
    return [_simplify(r, simplify_km) for r in runs]


def _km(p, q0):
    return ((p[2] - q0[2]) * KM_LON0 * math.cos(math.radians(q0[1])), (p[1] - q0[1]) * KM_LAT)


def _simplify(run, tol):
    if len(run) < 3: return run
    o = run[0]
    xy = [_km(p, o) for p in run]
    keep = [False] * len(run)
    keep[0] = keep[-1] = True
    stack = [(0, len(run) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = xy[a]; bx, by = xy[b]
        L = math.hypot(bx - ax, by - ay)
        best, bi = -1, a
        for i in range(a + 1, b):
            x, y = xy[i]
            dd = math.hypot(x - ax, y - ay) if L == 0 else abs((bx - ax) * (ay - y) - (ax - x) * (by - ay)) / L
            if dd > best: best, bi = dd, i
        if best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(run, keep) if k]


def _data(route_path, cfg=None):
    cfg = cfg or config.base_section("minimap")
    wanted = dict(cfg.get("places", {}).get("natural_earth") or {})
    key = json.dumps([str(route_path), cfg.get("lat_min"), cfg.get("simplify_km"), sorted(wanted.items())])
    if key in _cache: return _cache[key]
    runs = load_route(route_path, cfg.get("lat_min"), cfg.get("simplify_km", 1.5))
    if not runs:
        raise MissingData(f"la ruta {route_path} no tiene puntos utilizables (¿minimap.lat_min descarta todo?)")
    ne = _ne_dir()
    lons = [p[2] for r in runs for p in r]
    lats = [p[1] for r in runs for p in r]
    x0, x1, y0, y1 = min(lons) - .8, max(lons) + .8, min(lats) - .8, max(lats) + .8
    roads, provs = [], []
    for fn, dst in (("ne_10m_roads.geojson", roads), ("ne_10m_admin_1_states_provinces.geojson", provs)):
        for f in _load(ne / fn)["features"]:
            for ln in _lines(f["geometry"]):
                if any(x0 < c[0] < x1 and y0 < c[1] < y1 for c in ln[:: max(1, len(ln) // 40)]):
                    dst.append([(c[0], c[1]) for c in ln])
    places = {}
    if wanted:
        for f in _load(ne / "ne_10m_populated_places_simple.geojson")["features"]:
            name = f["properties"]["name"]
            if name in wanted:
                places[wanted[name]] = (f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0])
    _cache[key] = (runs, roads, provs, places)
    return _cache[key]


def short_label(time_art, place):
    t = _parse(time_art)
    return f"{t.day} {config.get('locale.months')[t.month - 1]} · {place}"


def place_for(media_id, rec, captions, labels):
    cap = (captions.get(media_id) or {}).get("place")
    if cap: return cap
    best = min(labels.items(), key=lambda kv: (kv[1][0] - rec["lat"]) ** 2 + ((kv[1][1] - rec["lon"]) * 0.92) ** 2)
    return best[0]


def bearing(runs, t, lat, lon, min_km=0.4):
    pts = [p for r in runs for p in r]
    pts.sort(key=lambda p: p[0])
    i = max(range(len(pts)), key=lambda k: -abs((pts[k][0] - t).total_seconds()))
    dist = lambda a, b: math.hypot((a[2] - b[2]) * KM_LON0 * math.cos(math.radians(lat)), (a[1] - b[1]) * KM_LAT)
    a = b = pts[i]
    lo = hi = i
    while dist(a, b) < min_km and (lo > 0 or hi < len(pts) - 1):
        lo, hi = max(0, lo - 1), min(len(pts) - 1, hi + 1)
        a, b = pts[lo], pts[hi]
    dx = (b[2] - a[2]) * math.cos(math.radians(lat))
    dy = b[1] - a[1]
    return math.atan2(dx, dy)


def _osm(name):
    key = "osm:" + name
    if key not in _cache: _cache[key] = _load(_osm_dir() / f"{name}.json")
    return _cache[key]


def urban_town(lat, lon, urban_km=1.2):
    osm = _osm_dir()
    if not osm.exists(): return None
    for f in sorted(osm.glob("*.json")):
        d = _osm(f.stem)
        la, lo = d["center"]
        m = urban_km / KM_LAT
        if abs(lat - la) < d["r"] - m and abs(lon - lo) < d["r"] - m / math.cos(math.radians(la)):
            return f.stem
    return None


def unit(D, geo=None):
    return D / _geo_of(geo)["ref_diameter"]


def _geo_of(geo):
    return geo or config.base_section("minimap")["geometry"]


def _urban_circle(time_art, lat, lon, route_path, theme, D, town, urban_km, cfg):
    geo = cfg["geometry"]
    SS = geo["supersample"]
    th = {k: tuple(v) for k, v in cfg["themes"][theme].items()}
    accent = tuple(cfg["accent"])
    data = _osm(town)
    S = D * SS
    ul = max(unit(D, geo), geo["line_floor"])
    kmpx = (S / 2) / urban_km
    k = math.cos(math.radians(lat))
    xy = lambda lo, la: (S / 2 + (lo - lon) * k * KM_LON0 * kmpx, S / 2 - (la - lat) * KM_LAT * kmpx)
    im = Image.new("RGBA", (S, S), th["base"])
    d = ImageDraw.Draw(im)
    park = (70, 130, 90, 90) if theme == "dark" else (150, 190, 140, 120)
    water = (70, 120, 180, 110) if theme == "dark" else (130, 170, 210, 140)
    inb = lambda g: any(abs(c[0] - lon) < 0.03 and abs(c[1] - lat) < 0.03 for c in g[:: max(1, len(g) // 30)])
    for g in data["parks"]:
        if len(g) > 2 and inb(g): d.polygon([xy(*c) for c in g], fill=park)
    for g in data["water"]:
        if inb(g):
            (d.polygon if g[0] == g[-1] and len(g) > 3 else d.line)([xy(*c) for c in g], fill=water)
    minor, major = th["road"], tuple(min(255, v + 60) for v in th["road"][:3]) + (230,)
    for cls, g in sorted(data["roads"], key=lambda r: r[0] in MAJOR):
        if cls in SKIP or not inb(g): continue
        mj = cls in MAJOR
        d.line([xy(*c) for c in g], fill=major if mj else minor, width=max(1, int(SS * (2.2 if mj else 1.2) * ul)), joint="curve")
    c = S / 2
    r = SS * dot_radius(D, geo)
    d.ellipse([c - r, c - r, c + r, c + r], fill=accent + (255,), outline=(255, 255, 255, 255), width=max(1, int(SS * 1.5 * ul)))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, S - 1, S - 1], fill=255)
    im.putalpha(Image.composite(im.getchannel("A"), Image.new("L", (S, S), 0), mask))
    return im


def dot_radius(D, geo=None):
    geo = _geo_of(geo)
    return max(geo["dot_min"], 4.2 * unit(D, geo))


def _circle(time_art, lat, lon, route_path, theme, D, labels, radius_km, cfg):
    geo = cfg["geometry"]
    SS = geo["supersample"]
    runs, roads, provs, extra = _data(route_path, cfg)
    th = {k: tuple(v) for k, v in cfg["themes"][theme].items()}
    accent = tuple(cfg["accent"])
    always = set(cfg["places"].get("always") or [])
    t = _parse(time_art)
    S = D * SS
    ul = max(unit(D, geo), geo["line_floor"])
    kmpx = (S / 2) / radius_km
    k = math.cos(math.radians(lat))

    def xy(lo, la):
        return (S / 2 + (lo - lon) * k * KM_LON0 * kmpx, S / 2 - (la - lat) * KM_LAT * kmpx)

    box = radius_km / REF_RADIUS_KM
    near = lambda ln: any(abs(c[0] - lon) < 1.6 * box and abs(c[1] - lat) < 1.3 * box for c in ln[:: max(1, len(ln) // 60)])
    im = Image.new("RGBA", (S, S), th["base"])
    d = ImageDraw.Draw(im)
    for ln in roads:
        if near(ln): d.line([xy(*c) for c in ln], fill=th["road"], width=max(1, int(SS * ul)))
    for ln in provs:
        if near(ln): d.line([xy(*c) for c in ln], fill=th["prov"], width=max(1, int(SS * 1.1 * ul)))
    for r in runs:
        d.line([xy(p[2], p[1]) for p in r], fill=th["pend"], width=max(1, int(SS * 1.4 * ul)), joint="curve")
    for r in runs:
        done = [xy(p[2], p[1]) for p in r if p[0] <= t]
        if done and r[-1][0] > t: done.append((S / 2, S / 2))
        if len(done) >= 2: d.line(done, fill=accent + (255,), width=max(1, int(SS * 1.8 * ul)), joint="curve")
    c = S / 2
    fs = max(geo["label_min_px_map"], round(D * 0.075))
    font = _font(fs * SS)
    cand = {**{n: tuple(v) for n, v in labels.items()}, **extra}
    ranked = sorted(cand.items(), key=lambda kv: math.hypot((kv[1][1] - lon) * k * KM_LON0, (kv[1][0] - lat) * KM_LAT))
    keep = 8 * SS * ul
    placed = [(c - keep, c - keep, c + keep, c + keep)]
    shown, td = 0, ImageDraw.Draw(im)
    for name, (la, lo) in ([] if D < geo["label_min_diameter"] else ranked):
        if shown >= cfg["labels_max"] and name not in always: continue
        x, y = xy(lo, la)
        dist = math.hypot(x - c, y - c)
        if dist < 4 * radius_km / 120 * kmpx * 1.0 or dist > S / 2 * 0.86: continue
        tw = td.textlength(name, font=font)
        h = fs * SS
        for ox, oy in ((4, -h / 2), (-4 - tw, -h / 2), (-tw / 2, 3), (-tw / 2, -h - 3)):
            box = (x + ox, y + oy, x + ox + tw, y + oy + h)
            corners = [(box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])]
            if any(math.hypot(px - c, py - c) > S / 2 * 0.93 for px, py in corners): continue
            if any(not (box[2] < q[0] or box[0] > q[2] or box[3] < q[1] or box[1] > q[3]) for q in placed): continue
            placed.append(box)
            td.text((box[0], box[1]), name, font=font, fill=(255, 255, 255, 235), stroke_width=SS, stroke_fill=(0, 0, 0, 200))
            r = SS * 1.6 * ul
            td.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 255), outline=(0, 0, 0, 200), width=SS // 2)
            shown += 1
            break
    r = SS * dot_radius(D, geo)
    td.ellipse([c - r, c - r, c + r, c + r], fill=accent + (255,), outline=(255, 255, 255, 255), width=max(1, int(SS * 1.5 * ul)))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, S - 1, S - 1], fill=255)
    im.putalpha(Image.composite(im.getchannel("A"), Image.new("L", (S, S), 0), mask))
    return im


def label_rows(place, time_art, pr, font_path):
    pf = ImageFont.truetype(font_path, pr["fp"])
    lf = ImageFont.truetype(font_path, pr["fl"])
    d = _parse(time_art)
    date = config.get("locale.date_format").format(day=d.day, month=config.get("locale.months_full")[d.month - 1], year=d.year)
    rows = [(x, pf, 255) for x in overlay.wrap_balanced(place, pf, pr["label_w"], 2)] if place else []
    rows.append((date, lf, 205 if place else 235))
    return rows


FORMATS = ("tv", "celu", "chat", "reel")
POSITIONS = ("top-right", "top-left", "bottom-right", "bottom-left")
LAYOUTS = ("corner", "beside")
REV = "m4"
LEGACY_KEYS = ("enabled", "size", "opacity", "position", "label_scale", "radius_km", "urban_km", "break_on_act", "presets")


def cache_sig(cfg):
    pristine = config.defaults()["minimap"]
    sig = {k: cfg[k] for k in LEGACY_KEYS}
    extra = {k: v for k, v in cfg.items() if k not in LEGACY_KEYS and v != pristine.get(k)}
    if extra:
        sig["x"] = extra
    return sig


def cfg_with(*layers):
    out = config.base_section("minimap")
    out = json.loads(json.dumps(out))
    out["presets"] = {}
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        for k, v in layer.items():
            if k not in out or v is None:
                continue
            if k == "presets":
                for fmt, over in v.items():
                    out["presets"][fmt] = {**out["presets"].get(fmt, {}), **(over or {})}
            elif isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = config.deep_merge(out[k], v)
            else:
                out[k] = v
    if out["position"] not in POSITIONS:
        raise ValueError(f"minimap.position debe ser uno de {POSITIONS}")
    if out["layout"] not in LAYOUTS:
        raise ValueError(f"minimap.layout debe ser uno de {LAYOUTS}")
    for fmt in out["presets"]:
        if fmt not in FORMATS:
            raise ValueError(f"minimap.presets.{fmt}: formato desconocido (válidos: {FORMATS})")
    return out


def params(cfg, fmt, frame, typo=None):
    W, H = frame
    typo = typo or overlay.params(overlay.cfg_with({}), fmt, frame)
    fd = cfg["format_defaults"]
    p = {**fd.get(fmt, fd["tv"]), **cfg["presets"].get(fmt, {})}
    S = min(W, H)
    D = round(S * (cfg["size"] or p["diameter"]))
    mult = cfg["label_scale"] * p["label_size"]
    return dict(
        D=D,
        S=S,
        fp=max(1, round(typo["fp"] * mult)),
        fl=max(1, round(typo["fl"] * mult)),
        label_w=W * p["label_max_w"],
        mx=typo["mx"] if p.get("margin_x") is None else round(W * p["margin_x"]),
        my=typo["my"] if p.get("margin_y") is None else round(H * p["margin_y"]),
    )


def beside_geometry(cfg, fmt, frame, typo=None):
    W, H = frame
    pr = params(cfg, fmt, frame, typo)
    D = pr["D"]
    gap = overlay.spacing(pr["fp"], pr["fl"])[1]
    right = cfg["position"].endswith("right")
    left = W - pr["mx"] - D if right else pr["mx"]
    top = pr["my"] if cfg["position"].startswith("top") else H - pr["my"] - D
    gutter = round(D * cfg["beside_gap"])
    mid = top + D // 2
    half = (pr["fp"] + pr["fl"] + 2 * gap) // 2
    return {
        "left": left, "top": top, "D": D,
        "tx": left - gutter if right else left + D + gutter,
        "text_w": W * cfg["beside_text_w"],
        "label_top": mid - half, "desc_top": mid + half,
        "align": "right" if right else "left",
    }


def render_overlay(time_art, lat, lon, place, frame=(1920, 1080), theme="dark", route_path=None, labels=None, out=None, cfg=None, fmt="tv", typo=None, font=None):
    cfg = cfg_with(cfg or {})
    W, H = frame
    pr = params(cfg, fmt, frame, typo)
    geo = cfg["geometry"]
    SS = geo["supersample"]
    D, u = pr["D"], unit(pr["D"], geo)
    ring = max(2, round(2 * pr["S"] / 1080))
    town = urban_town(lat, lon, cfg["urban_km"])
    ci = _urban_circle(time_art, lat, lon, route_path, theme, D, town, cfg["urban_km"], cfg) if town else _circle(time_art, lat, lon, route_path, theme, D, labels or {}, cfg["radius_km"], cfg)
    S = D * SS
    glow_pad = D // 4
    cv = Image.new("RGBA", (S + 2 * glow_pad * SS, S + 2 * glow_pad * SS), (0, 0, 0, 0))
    g = Image.new("L", cv.size, 0)
    ImageDraw.Draw(g).ellipse([glow_pad * SS - ring * SS, glow_pad * SS - ring * SS, glow_pad * SS + S + ring * SS, glow_pad * SS + S + ring * SS], fill=130)
    g = g.filter(ImageFilter.GaussianBlur(SS * 4 * max(u, geo["line_floor"])))
    cv.paste((0, 0, 0, 255), (0, 0), g)
    cv.alpha_composite(ci, (glow_pad * SS, glow_pad * SS))
    ImageDraw.Draw(cv).ellipse([glow_pad * SS, glow_pad * SS, glow_pad * SS + S - 1, glow_pad * SS + S - 1], outline=(255, 255, 255, 255), width=ring * SS)
    cv = cv.resize((cv.width // SS, cv.height // SS), Image.LANCZOS)
    cv.putalpha(cv.getchannel("A").point(lambda v: int(v * cfg["opacity"])))

    pad = overlay.spacing(pr["fp"], pr["fl"])[0]
    if cfg["layout"] == "beside":
        b = beside_geometry(cfg, fmt, frame, typo)
        lab = overlay.block_image(label_rows(place, time_art, {**pr, "label_w": b["text_w"]}, font or config.font("main")), pr["fp"], pr["fl"], align=b["align"])
        lw, lh = lab.size
        cx, cy = b["left"] - glow_pad, b["top"] - glow_pad
        lx = b["tx"] + pad - lw if b["align"] == "right" else b["tx"] - pad
        ly = b["label_top"] - pad
    else:
        lab = overlay.block_image(label_rows(place, time_art, pr, font or config.font("main")), pr["fp"], pr["fl"], align="center", min_w=D)
        lw, lh = lab.size
        mx, my = pr["mx"], pr["my"]
        position = cfg["position"]
        stack = D + glow_pad // 2 - pad + lh
        cx = W - mx - D - glow_pad if position.endswith("right") else mx - glow_pad
        cy = my - glow_pad if position.startswith("top") else H - my - stack - glow_pad
        lx = cx + glow_pad + D // 2 - lw // 2
        lx = min(max(lx, mx - pad), W - mx + pad - lw)
        ly = cy + glow_pad + D + glow_pad // 2 - pad
    ov = Image.new("RGBA", frame, (0, 0, 0, 0))
    ov.alpha_composite(cv, (cx, cy))
    ov.alpha_composite(lab, (lx, ly))
    if out: ov.save(out)
    return ov


def render_minimap_png(time_art, lat, lon, place, frame, cfg, route_path, labels, out, fmt="tv", typo=None, font=None):
    out = pathlib.Path(out)
    meta = out.with_suffix(".json")
    if out.exists() and meta.exists():
        return tuple(json.loads(meta.read_text()))
    ov = render_overlay(time_art, lat, lon, place, tuple(frame), cfg_with(cfg or {})["theme"], route_path, labels, None, cfg, fmt, typo, font)
    x0, y0, x1, y1 = ov.getchannel("A").getbbox()
    ov.crop((x0, y0, x1, y1)).save(out, compress_level=1)
    meta.write_text(json.dumps([x0, y0]))
    return (x0, y0)
