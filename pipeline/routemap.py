import json, math, subprocess, sys, pathlib
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config

if len(sys.argv) < 8:
    sys.exit("uso: routemap.py sessions.json carpeta_natural_earth salida.mp4 ancho alto segundos labels.json [carpeta_del_proyecto]")
RM = (config.activate_project(sys.argv[8]) if len(sys.argv) > 8 else config.activate(None))["routemap"]
sessions, ne, out = json.load(open(sys.argv[1])), pathlib.Path(sys.argv[2]), sys.argv[3]
W, H, FPS, SECS = int(sys.argv[4]), int(sys.argv[5]), RM["fps"], float(sys.argv[6])
font = config.font("main")
pts = [(s["lon"], s["lat"], "") for s in sessions if s.get("lat") is not None]
labels = json.load(open(sys.argv[7]))
lons, lats = [p[0] for p in pts], [p[1] for p in pts]
pad = RM["pad_deg"]
x0, x1, y0, y1 = min(lons) - pad, max(lons) + pad, min(lats) - pad, max(lats) + pad
k = math.cos(math.radians((y0 + y1) / 2))
sx = W / ((x1 - x0) * k)
sy = H / (y1 - y0)
s_ = min(sx, sy)
cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
P = lambda lon, lat: (W / 2 + (lon - cx) * k * s_, H / 2 - (lat - cy) * s_)


def lines(geom):
    t, c = geom["type"], geom["coordinates"]
    if t == "LineString": return [c]
    if t == "MultiLineString": return c
    if t == "Polygon": return c
    if t == "MultiPolygon": return [r for poly in c for r in poly]
    return []


def inside(line):
    return any(x0 - 1 < x < x1 + 1 and y0 - 1 < y < y1 + 1 for x, y in line[:: max(1, len(line) // 50)])


BG = tuple(RM["background"])
base = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(base)
for f in json.load(open(ne / "ne_10m_admin_1_states_provinces.geojson"))["features"]:
    for ln in lines(f["geometry"]):
        if inside(ln):
            d.line([P(*c[:2]) for c in ln], fill=tuple(RM["province_line"]), width=max(2, W // 640))
for f in json.load(open(ne / "ne_10m_roads.geojson"))["features"]:
    for ln in lines(f["geometry"]):
        if inside(ln):
            d.line([P(*c[:2]) for c in ln], fill=tuple(RM["road_line"]), width=max(1, W // 960))
small = ImageFont.truetype(font, H // 32)
R = 8
lab = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ld = ImageDraw.Draw(lab)
HALO = max(3, H // 540)
placed = []
dots = []
items = []
for name, (lat, lon) in labels.items():
    x, y = P(lon, lat)
    items.append((name, x, y))
    dots.append((x - R, y - R, x + R, y + R))


def hit(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def candidates(x, y, w, h):
    g = 14
    for k in (1, 2, 3, 4):
        e = g * k
        yield (x + e, y - h / 2)
        yield (x - e - w, y - h / 2)
        yield (x - w / 2, y - e - h)
        yield (x - w / 2, y + e)
        yield (x + e, y - e - h)
        yield (x - e - w, y - e - h)
        yield (x + e, y + e)
        yield (x - e - w, y + e)


for name, x, y in items:
    l, t, r, b = d.textbbox((0, 0), name, font=small)
    w, h = r - l, b - t
    best = None
    for bx, by in candidates(x, y, w, h):
        box = (bx - 6, by - 6, bx + w + 6, by + h + 6)
        if box[0] < 10 or box[1] < 10 or box[2] > W - 10 or box[3] > H - 10:
            continue
        if any(hit(box, o) for o in placed) or any(hit(box, o) for o in dots):
            continue
        best = (bx - l, by - t, box)
        break
    if best is None:
        best = (x + 14 - l, y - h / 2 - t, None)
        print("sin hueco para", name)
    if best[2]:
        placed.append(best[2])
    ld.ellipse([x - R, y - R, x + R, y + R], fill=(90, 70, 50), outline=BG, width=HALO)
    ld.text((best[0], best[1]), name, font=small, fill=(70, 55, 40), stroke_width=HALO, stroke_fill=BG + (255,))
d.text((W - W // 4, H - H // 18), RM["attribution"], font=ImageFont.truetype(font, H // 50), fill=(150, 135, 115))

seg = [math.dist(P(*pts[i][:2]), P(*pts[i + 1][:2])) for i in range(len(pts) - 1)]
total = sum(seg)
n = int(SECS * FPS)
ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", out], stdin=subprocess.PIPE)
for fr in range(n):
    prog = min(1, fr / (n * 0.85)) * total
    im = base.convert("RGBA"); dd = ImageDraw.Draw(im)
    acc, path = 0, [P(*pts[0][:2])]
    for i, L in enumerate(seg):
        a, b = P(*pts[i][:2]), P(*pts[i + 1][:2])
        if acc + L <= prog:
            path.append(b); acc += L; continue
        t = (prog - acc) / L if L else 0
        path.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)); break
    RL = tuple(RM["route_line"])
    dd.line(path, fill=RL, width=max(4, W // 320), joint="curve")
    x, y = path[-1]
    r = max(7, W // 200)
    dd.ellipse([x - r, y - r, x + r, y + r], fill="white", outline=RL, width=3)
    im.alpha_composite(lab)
    ff.stdin.write(im.convert("RGB").tobytes())
ff.stdin.close(); ff.wait()
print(out, n, "frames")
