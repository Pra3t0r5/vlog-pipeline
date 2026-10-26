import argparse, bisect, collections, datetime as D, hashlib, json, math, os, pathlib, re, statistics, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image
import imagehash

import config
import ffx

ap = argparse.ArgumentParser()
ap.add_argument("--drone-inv", required=True)
ap.add_argument("--album", required=True)
ap.add_argument("--route", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--geocache", required=True)
ap.add_argument("--proxy-dir")
ap.add_argument("--start-date", required=True)
ap.add_argument("--end-date", required=True)
ap.add_argument("--project")
ap.add_argument("--tz")
ap.add_argument("--owner", action="append", default=[])
ap.add_argument("--clock-offset", action="append", default=[])
ap.add_argument("--report")
ap.add_argument("--sources")
ap.add_argument("--cache")
ap.add_argument("--user-agent")
ap.add_argument("--no-geocode", action="store_true")
ap.add_argument("--no-lufs", action="store_true")
ap.add_argument("--proxies-only", action="store_true")
ap.add_argument("--no-proxy", action="store_true")
A = ap.parse_args()

CFG = config.activate_project(A.project) if A.project else config.activate(None)
ING = CFG["ingest"]
TZ = config.tzinfo(A.tz or config.timezone_offset(CFG))
OWNERS = [(re.compile(k), v) for k, v in (o.rsplit("=", 1) for o in A.owner)]
OFFSETS = {k: float(v) for k, v in (o.rsplit("=", 1) for o in A.clock_offset)}
D0 = D.date.fromisoformat(A.start_date)
D1 = D.date.fromisoformat(A.end_date)
OUT = pathlib.Path(A.out)
CACHE_PATH = pathlib.Path(A.cache) if A.cache else OUT.with_name("ingest_cache.json")
REPORT_PATH = pathlib.Path(A.report) if A.report else OUT.with_name("ingest_report.json")
FNAME_TS = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})(?!\d)")


def wait_for_ffmpeg_slot(limit):
    while int(subprocess.run("pgrep -x ffmpeg | wc -l", shell=True, capture_output=True, text=True).stdout.strip() or 0) >= limit:
        time.sleep(3)


def proxies_only():
    recs = json.load(open(A.out))
    proxy = pathlib.Path(A.proxy_dir)
    proxy.mkdir(parents=True, exist_ok=True)
    log = proxy / "_progress.log"
    todo = [r for r in recs if r["kind"] == "video" and r["source"].startswith("phone") and not r["exclude_reason"]]
    n = 0
    for r in todo:
        o = proxy / (pathlib.Path(r["path"]).stem + ".mp4")
        if o.exists() and o.stat().st_size > 0:
            continue
        wait_for_ffmpeg_slot(CFG["proxies"]["phone"]["max_parallel_ffmpeg"])
        tmp = o.with_suffix(".part.mp4")
        px = CFG["proxies"]["phone"]
        vf = f"scale={px['w']}:{px['h']}:force_original_aspect_ratio=decrease,pad={px['w']}:{px['h']}:(ow-iw)/2:(oh-ih)/2"
        cmd = ffx.nice() + ["ffmpeg", "-v", "error", "-y", "-i", r["path"], "-vf", vf, "-c:v", ffx.pick_codec("h264_videotoolbox"), "-b:v", px["bitrate"]]
        cmd += ["-c:a", "aac", "-b:a", px["audio_bitrate"], "-ac", "2"] if r["has_audio"] else ["-an"]
        cmd += ["-movflags", "+faststart", "-f", "mp4", str(tmp)]
        t0 = time.time()
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if p.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.rename(o)
            n += 1
            msg = f"ok {n} {o.name} {time.time() - t0:.1f}s"
        else:
            tmp.unlink(missing_ok=True)
            msg = f"FAIL {o.name} rc={p.returncode} {p.stderr.strip()[-200:]}"
        with open(log, "a") as f:
            f.write(f"{time.strftime('%T')} {msg}\n")
    with open(log, "a") as f:
        f.write(f"{time.strftime('%T')} DONE {n} new / {len(todo)} total\n")


if A.proxies_only:
    proxies_only()
    sys.exit(0)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def hav(a, b):
    R = 6371000
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl, dp = math.radians(b[1] - a[1]), p2 - p1
    return 2 * R * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


def iso(dt):
    return dt.astimezone(TZ).isoformat(timespec="seconds")


def local(naive_str):
    return D.datetime.strptime(naive_str.replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)


def exif_dt(s):
    return D.datetime.strptime(s[:19], "%Y:%m:%d %H:%M:%S")


def orient(w, h):
    return "square" if w == h else "landscape" if w > h else "portrait"


def source_of(device, name):
    for rx, v in OWNERS:
        if rx.search(name if rx.pattern.startswith("^") else device):
            return v
    return "other"


def load_cache():
    try:
        return json.load(open(CACHE_PATH))
    except Exception:
        return {}


CACHE = load_cache()


def fkey(path):
    st = os.stat(path)
    return f"{path}|{st.st_size}|{int(st.st_mtime)}"


def ffprobe(path):
    j = json.loads(run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate:stream_side_data=rotation", "-of", "json", path]) or "{}")
    v = next((s for s in j.get("streams", []) if s["codec_type"] == "video"), {})
    rot = 0
    for sd in v.get("side_data_list", []):
        rot = sd.get("rotation", rot)
    w, h = v.get("width", 0), v.get("height", 0)
    if abs(int(rot)) % 180 == 90:
        w, h = h, w
    return {"w": w, "h": h, "dur": round(float(j.get("format", {}).get("duration", 0) or 0), 2),
            "has_audio": any(s["codec_type"] == "audio" for s in j.get("streams", []))}


def lufs(path):
    k = "lufs|" + fkey(path)
    if k in CACHE:
        return CACHE[k]
    p = subprocess.run(ffx.nice() + ["ffmpeg", "-nostats", "-hide_banner", "-i", path, "-vn", "-af", "ebur128=peak=none", "-f", "null", "-"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    m = re.findall(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+|-inf)\s*LUFS", p.stderr)
    v = None if not m or m[-1] == "-inf" else float(m[-1])
    CACHE[k] = v
    return v


EXCLUDE_PATTERNS = {k: re.compile(v, re.I) for k, v in ING["exclude_name_patterns"].items()}


def name_reason(name, kind, ext, dev):
    if "screenshot" in EXCLUDE_PATTERNS and EXCLUDE_PATTERNS["screenshot"].search(name):
        return "screenshot"
    if ext == ".gif":
        return "gif"
    if ext == ".png" and not dev:
        return "generated_graphic"
    for key, rx in EXCLUDE_PATTERNS.items():
        if key == "screenshot" or (key == "drone_app_cache" and kind != "video"):
            continue
        if rx.search(name):
            return key
    return None


def photo_features(path):
    k = "img|" + fkey(path)
    if k in CACHE:
        return CACHE[k]
    im = Image.open(path)
    im.draft("RGB", (1024, 1024))
    im = im.convert("RGB")
    im.thumbnail((640, 640))
    ph = str(imagehash.phash(im))
    g = np.asarray(im.convert("L"), dtype=np.float32)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    CACHE[k] = {"phash": ph, "sharp": float(lap.var())}
    return CACHE[k]


def hdist(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def new(**kw):
    base = {"id": None, "path": None, "source": None, "kind": None, "time_art": None, "time_confidence": None, "lat": None, "lon": None,
            "geo_source": "none", "geo_err_min": None, "day": None, "place": None, "w": None, "h": None, "orientation": None,
            "dur": None, "has_audio": None, "audio_lufs": None, "burst_group": None, "keep_in_burst": False, "exclude_reason": None}
    base.update(kw)
    return base


recs = []
meta = {}

for r in json.load(open(A.drone_inv)):
    path = r["path"]
    stem = pathlib.Path(path).stem
    dt = local(r["start"]) if r.get("start") else None
    w, h = (int(x) for x in re.findall(r"\d+", r["res"] or "0x0")[:2])
    rec = new(id=f"drone.{stem}", path=path, source="drone", kind=r["kind"], time_art=iso(dt) if dt else None,
              time_confidence="high" if dt else None, w=w, h=h, orientation=orient(w, h))
    if r.get("lat") is not None and r.get("lon") is not None:
        rec.update(lat=r["lat"], lon=r["lon"], geo_source="gps", geo_err_min=0)
    if r["kind"] == "video":
        pr = ffprobe(path)
        rec.update(dur=pr["dur"], has_audio=pr["has_audio"])
    recs.append(rec)
    meta[rec["id"]] = {"dev": "drone"}

album = pathlib.Path(A.album)
ex = json.loads(run(["exiftool", "-j", "-n", "-r", "-ext", "jpg", "-ext", "jpeg", "-ext", "png", "-ext", "gif", "-ext", "mp4", "-ext", "mov", "-ext", "heic",
                     "-ImageSize", "-Orientation", "-Make", "-Model", "-AndroidMake", "-AndroidModel", "-SamsungModel",
                     "-DateTimeOriginal", "-OffsetTimeOriginal", "-CreateDate", str(album)]) or "[]")
for e in sorted(ex, key=lambda e: e["SourceFile"]):
    path = e["SourceFile"]
    name = pathlib.Path(path).name
    if name.startswith("._"):
        continue
    stem, ext = pathlib.Path(name).stem, pathlib.Path(name).suffix.lower()
    kind = "video" if ext in (".mp4", ".mov") else "photo"
    dev = " ".join(str(e[k]) for k in ("Model", "AndroidModel", "SamsungModel", "Make", "AndroidMake") if e.get(k))
    src = source_of(dev, name)
    rec = new(id=f"{src}.{stem}", path=path, source=src, kind=kind)
    fm = FNAME_TS.search(name)
    fname_dt = D.datetime(*(int(x) for x in fm.groups())).replace(tzinfo=TZ) if fm else None
    reason = None
    if kind == "video":
        pr = ffprobe(path)
        rec.update(w=pr["w"], h=pr["h"], dur=pr["dur"], has_audio=pr["has_audio"])
        cd = exif_dt(e["CreateDate"]).replace(tzinfo=D.timezone.utc) if e.get("CreateDate") else None
        if fname_dt:
            dt, conf = fname_dt, "high"
        elif cd:
            dt, conf = cd.astimezone(TZ) - D.timedelta(seconds=pr["dur"]), "medium"
        else:
            dt, conf = None, None
    else:
        w, h = (int(x) for x in str(e.get("ImageSize", "0x0")).replace(" ", "x").split("x")[:2])
        if e.get("Orientation") in (5, 6, 7, 8):
            w, h = h, w
        rec.update(w=w, h=h)
        if e.get("DateTimeOriginal"):
            dt = exif_dt(e["DateTimeOriginal"]).replace(tzinfo=TZ)
            conf = "high" if e.get("OffsetTimeOriginal") else "medium"
        elif fname_dt:
            dt, conf = fname_dt, "low"
        else:
            dt, conf = None, None
    rec["orientation"] = orient(rec["w"], rec["h"]) if rec["w"] else None
    if dt:
        rec.update(time_art=iso(dt), time_confidence=conf)
    reason = name_reason(name, kind, ext, dev)
    rec["exclude_reason"] = reason
    recs.append(rec)
    meta[rec["id"]] = {"dev": dev, "fname_dt": fname_dt, "exif_local": exif_dt(e["DateTimeOriginal"]).replace(tzinfo=TZ) if e.get("DateTimeOriginal") else None,
                       "create_utc": exif_dt(e["CreateDate"]).replace(tzinfo=D.timezone.utc) if e.get("CreateDate") else None}

for r in recs:
    if r["time_art"] and r["source"] in OFFSETS:
        r["time_art"] = iso(D.datetime.fromisoformat(r["time_art"]) - D.timedelta(seconds=OFFSETS[r["source"]]))

by_id = {r["id"]: r for r in recs}
T = lambda r: D.datetime.fromisoformat(r["time_art"]) if r["time_art"] else None

for r in recs:
    if r["kind"] == "photo":
        f = photo_features(r["path"])
        meta[r["id"]].update(f)

report = {"clock": {}, "notes": []}

cache_vids = [r for r in recs if r["exclude_reason"] == "drone_app_cache"]
drone_vids = [r for r in recs if r["source"] == "drone" and r["kind"] == "video" and r["time_art"]]
end_of = lambda d: T(d) + D.timedelta(seconds=d["dur"])
deltas = []
for c in cache_vids:
    best = min(drone_vids, key=lambda d: abs((end_of(d) - T(c)).total_seconds()) + 5 * abs(d["dur"] - c["dur"]))
    dt = (T(c) - end_of(best)).total_seconds()
    if abs(dt) <= 30 and abs(best["dur"] - c["dur"]) <= 3:
        deltas.append(dt)
        c["exclude_reason"] = f"duplicate_of:{best['id']}"
        c["time_art"] = iso(T(c) - D.timedelta(seconds=c["dur"]))
        c["day"] = T(c).date().isoformat()
    else:
        c["exclude_reason"] = "drone_app_cache_unmatched"
if deltas:
    report["clock"]["phone_dji_app_cache_end_minus_drone_srt_end_s"] = {"n": len(deltas), "median": statistics.median(deltas), "min": min(deltas), "max": max(deltas)}

chk = collections.defaultdict(list)
for r in recs:
    mt = meta[r["id"]]
    if r["source"] == "drone" or not mt.get("fname_dt"):
        continue
    if r["kind"] == "photo" and mt["exif_local"]:
        chk[(r["source"], "photo_exif_minus_filename_s")].append((mt["exif_local"] - mt["fname_dt"]).total_seconds())
    if r["kind"] == "video" and mt["create_utc"] and not r["id"].endswith("video_cache"):
        chk[(r["source"], "video_createdate_utc_to_art_minus_dur_minus_filename_s")].append((mt["create_utc"].astimezone(TZ) - mt["fname_dt"]).total_seconds() - r["dur"])
        chk[(r["source"], "video_createdate_if_it_were_local_minus_dur_minus_filename_s")].append((mt["create_utc"].replace(tzinfo=TZ) - mt["fname_dt"]).total_seconds() - r["dur"])
for (src, name), v in chk.items():
    report["clock"].setdefault("time_base_checks", {})[f"{src}.{name}"] = {"n": len(v), "median": round(statistics.median(v), 1), "within_10s": sum(abs(x) <= 10 for x in v)}

photos = [r for r in recs if r["kind"] == "photo" and r["time_art"] and r["source"] != "drone" and not r["exclude_reason"]]
srcs = sorted({r["source"] for r in photos if r["source"] != "other"})
for i, a in enumerate(srcs):
    for b in srcs[i + 1:]:
        near = []
        for x in (p for p in photos if p["source"] == a):
            for y in photos:
                dt = (T(y) - T(x)).total_seconds()
                if y["source"] == b and abs(dt) <= 900:
                    near.append((hdist(meta[x["id"]]["phash"], meta[y["id"]]["phash"]), dt))
        same = [dt for d, dt in near if d <= 10]
        report["clock"][f"{b}_vs_{a}_same_scene"] = {"pairs_within_15min": len(near), "min_phash_dist": min((d for d, _ in near), default=None),
                                                       "same_scene_pairs": len(same), "median_dt_s": statistics.median(same) if same else None,
                                                       "verdict": "verified" if len(same) >= 5 else "not_verifiable_no_shared_scenes"}

route = json.load(open(A.route))
pts = sorted((D.datetime.fromisoformat(t), la, lo) for t, la, lo in route["points"])
pt_t = [p[0].timestamp() for p in pts]
visits = [(D.datetime.fromisoformat(v["start"]), D.datetime.fromisoformat(v["end"]), v["lat"], v["lon"]) for v in route["visits"]]


def route_at(t):
    x = t.timestamp()
    i = bisect.bisect_left(pt_t, x)
    lo_p = pts[i - 1] if i > 0 else None
    hi_p = pts[i] if i < len(pts) else None
    if i < len(pts) and pt_t[i] == x:
        return pts[i][1], pts[i][2], 0.0, "exact"
    gl = (x - pt_t[i - 1]) / 60 if lo_p else None
    gh = (pt_t[i] - x) / 60 if hi_p else None
    if lo_p and hi_p and gl <= ING["route_gap_min"] and gh <= ING["route_gap_min"]:
        f = gl / (gl + gh)
        return lo_p[1] + (hi_p[1] - lo_p[1]) * f, lo_p[2] + (hi_p[2] - lo_p[2]) * f, min(gl, gh), "interp"
    near = [(g, p) for g, p in ((gl, lo_p), (gh, hi_p)) if p and g <= ING["route_gap_min"]]
    if near:
        g, p = min(near, key=lambda c: c[0])
        return p[1], p[2], g, "near"
    return None


def visit_at(t):
    inside = [v for v in visits if v[0] <= t <= v[1]]
    if inside:
        v = min(inside, key=lambda v: (v[1] - v[0]))
        return v[2], v[3], 0.0
    cand = []
    for v in visits:
        g = (v[0] - t).total_seconds() / 60 if t < v[0] else (t - v[1]).total_seconds() / 60
        if g <= ING["route_gap_min"]:
            cand.append((g, v))
    if cand:
        g, v = min(cand, key=lambda c: c[0])
        return v[2], v[3], g
    return None


offs = []
for off in range(-30, 31):
    ds = []
    for d in drone_vids:
        if d["lat"] is None:
            continue
        ra = route_at(T(d) + D.timedelta(minutes=off))
        if ra and ra[3] in ("interp", "exact"):
            ds.append(hav((d["lat"], d["lon"]), (ra[0], ra[1])))
    if len(ds) >= 20:
        offs.append((off, statistics.median(ds), len(ds)))
if offs:
    b = min(offs, key=lambda o: o[1])
    z = next(o for o in offs if o[0] == 0)
    report["clock"]["drone_srt_vs_route_best_offset_min"] = {"best_min": b[0], "median_dist_m_at_best": round(b[1]), "median_dist_m_at_0": round(z[1]), "n": b[2]}

for r in recs:
    if r["lat"] is not None or not r["time_art"]:
        continue
    t = T(r)
    ra = route_at(t)
    va = visit_at(t)
    if ra and va and hav((ra[0], ra[1]), (va[0], va[1])) > ING["visit_conflict_m"] and va[2] == 0.0:
        ra = None
    if ra:
        r.update(lat=round(ra[0], 6), lon=round(ra[1], 6), geo_source="route_interp", geo_err_min=round(ra[2], 1))
    elif va:
        r.update(lat=va[0], lon=va[1], geo_source="route_visit", geo_err_min=round(va[2], 1))

for r in recs:
    r["day"] = T(r).date().isoformat() if r["time_art"] else None
    if not r["exclude_reason"]:
        if not r["time_art"]:
            r["exclude_reason"] = "no_date"
        elif not (D0 <= T(r).date() <= D1):
            r["exclude_reason"] = "out_of_range"

rank = lambda r: (r["w"] * r["h"], r["source"] != "other", r["source"] == "drone")
usable = sorted([r for r in recs if r["kind"] == "photo" and not r["exclude_reason"]], key=rank, reverse=True)
for i, a in enumerate(usable):
    if a["exclude_reason"]:
        continue
    for b in usable[i + 1:]:
        if b["exclude_reason"] or hdist(meta[a["id"]]["phash"], meta[b["id"]]["phash"]) > (ING["duplicate_phash_same_source"] if a["source"] == b["source"] else ING["duplicate_phash_cross_source"]):
            continue
        if abs((T(a) - T(b)).total_seconds()) <= ING["duplicate_seconds"]:
            b["exclude_reason"] = f"duplicate_of:{a['id']}"
keepers = [r for r in usable if not r["exclude_reason"]]
for r in recs:
    if r["kind"] == "photo" and r["exclude_reason"] == "no_date":
        m = [k for k in keepers if hdist(meta[r["id"]]["phash"], meta[k["id"]]["phash"]) <= 6]
        if m:
            r["exclude_reason"] = f"duplicate_of:{max(m, key=rank)['id']}"

kept_photos = sorted([r for r in recs if r["kind"] == "photo" and not r["exclude_reason"]], key=lambda r: (r["source"], T(r)))
parent = {r["id"]: r["id"] for r in kept_photos}


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


for i, a in enumerate(kept_photos):
    for b in kept_photos[i + 1:]:
        if b["source"] != a["source"]:
            continue
        if (T(b) - T(a)).total_seconds() > ING["burst_seconds"]:
            break
        if hdist(meta[a["id"]]["phash"], meta[b["id"]]["phash"]) <= ING["burst_phash"]:
            parent[find(b["id"])] = find(a["id"])
groups = collections.defaultdict(list)
for r in kept_photos:
    groups[find(r["id"])].append(r)
bn = 0
for g in sorted(groups.values(), key=lambda g: T(g[0])):
    if len(g) == 1:
        g[0]["keep_in_burst"] = True
        continue
    bn += 1
    best = max(g, key=lambda r: meta[r["id"]]["sharp"])
    for r in g:
        r["burst_group"] = f"B{bn:03d}"
        r["keep_in_burst"] = r is best
for r in recs:
    if r["kind"] == "video" and not r["exclude_reason"]:
        r["keep_in_burst"] = True

if not A.no_lufs:
    vids = [r for r in recs if r["kind"] == "video" and r["has_audio"] and not (r["exclude_reason"] or "").startswith(("screenshot", "gif"))]
    for i, r in enumerate(vids):
        r["audio_lufs"] = lufs(r["path"])
        if i % 25 == 0:
            json.dump(CACHE, open(CACHE_PATH, "w"))


def cell(r):
    return (round(r["lat"] / ING["geocode_cell_deg"][0]), round(r["lon"] / ING["geocode_cell_deg"][1]))


def load_geocache():
    try:
        return json.load(open(A.geocache))
    except Exception:
        return {}


GEO = load_geocache()


def geocode(lat, lon):
    u = f"{CFG['http']['nominatim_url']}?format=jsonv2&zoom=14&accept-language={ING['geocode_language']}&lat={lat}&lon={lon}"
    try:
        j = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": A.user_agent or config.user_agent()}), timeout=30))
    except Exception:
        return None
    a = j.get("address", {})
    parts = [j.get("name"), a.get("village") or a.get("town") or a.get("city") or a.get("hamlet") or a.get("suburb"), a.get("state_district") or a.get("county"), a.get("state")]
    seen = []
    for x in parts:
        if x and x not in seen:
            seen.append(x)
    return ", ".join(seen) or ""


cells = collections.defaultdict(list)
for r in recs:
    if r["lat"] is not None and not r["exclude_reason"]:
        cells[cell(r)].append(r)
if not A.no_geocode and ING["geocode"]:
    for key, rs in sorted(cells.items()):
        lat = round(statistics.mean(r["lat"] for r in rs), 4)
        lon = round(statistics.mean(r["lon"] for r in rs), 4)
        k = f"{key[0]},{key[1]}"
        if k not in GEO or GEO[k] is None:
            GEO[k] = geocode(lat, lon)
            json.dump(GEO, open(A.geocache, "w"), ensure_ascii=False, indent=1)
            time.sleep(ING["geocode_delay_s"])
for key, rs in cells.items():
    for r in rs:
        r["place"] = GEO.get(f"{key[0]},{key[1]}") or None

if A.sources:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sources as SRC
    resolver = SRC.Resolver.from_manifest(A.sources)
    for r in recs:
        resolver.annotate(r)

recs.sort(key=lambda r: (r["time_art"] or "9999", r["id"]))
json.dump(recs, open(OUT, "w"), ensure_ascii=False, indent=1)
json.dump(CACHE, open(CACHE_PATH, "w"))

use = [r for r in recs if not r["exclude_reason"]]
cnt = collections.Counter
print("total", len(recs), "usable", len(use), "excluded", len(recs) - len(use))
print("por source/kind (usables):", dict(cnt((r["source"], r["kind"]) for r in use)))
print("por día (usables):", dict(sorted(cnt(r["day"] for r in use).items())))
print("excluidos:", dict(cnt(re.sub(r":.*", "", r["exclude_reason"]) for r in recs if r["exclude_reason"])))
ph = [r for r in use if r["kind"] == "photo"]
print("ráfagas:", bn, "fotos en ráfagas:", sum(1 for r in ph if r["burst_group"]), "descartadas por ráfaga:", sum(1 for r in ph if not r["keep_in_burst"]))
print("geo (usables):", dict(cnt(r["geo_source"] for r in use)))
print("clock:", json.dumps(report["clock"], ensure_ascii=False, indent=1))
report["summary"] = {"total": len(recs), "usable": len(use), "excluded_by_reason": dict(cnt(re.sub(r":.*", "", r["exclude_reason"]) for r in recs if r["exclude_reason"])),
                     "geo_source": dict(cnt(r["geo_source"] for r in use)), "bursts": bn}
json.dump(report, open(REPORT_PATH, "w"), ensure_ascii=False, indent=1)

if A.proxy_dir and not A.no_proxy:
    pathlib.Path(A.proxy_dir).mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-I", os.path.abspath(__file__)] + (["--project", A.project] if A.project else []) + ["--drone-inv", A.drone_inv, "--album", A.album, "--route", A.route, "--out", A.out,
            "--geocache", A.geocache, "--start-date", A.start_date, "--end-date", A.end_date, "--proxy-dir", A.proxy_dir, "--proxies-only"]
    log = open(pathlib.Path(A.proxy_dir) / "_ingest_proxy.out", "a")
    subprocess.Popen(ffx.nice() + argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    print("proxies en segundo plano ->", A.proxy_dir)
