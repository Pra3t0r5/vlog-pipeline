import argparse
import hashlib
import json
import math
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

globals().update(config.constants("routefill", config.base()))
OSRM_PARAMS = "overview=full&geometries=geojson&steps=true"
ART = config.tzinfo(config.timezone_offset(config.base()))


def configure(project_cfg=None):
    cfg = config.activate(project_cfg)
    globals().update(config.constants("routefill", cfg))
    globals()["ART"] = config.tzinfo(config.timezone_offset(cfg))
    return cfg


def osrm_base():
    return config.get("http.osrm_url")


def user_agent():
    return f"vlog-pipeline-routefill/{config.VERSION} ({config.get('http.contact') or 'sin contacto'}; cached, max 1 req/s)"


def cache_dir():
    return config.vendor_path("osrm_cache_dir", "osrm-cache")


def parse_iso(s):
    return datetime.fromisoformat(s)


def fmt_iso(dt):
    dt = dt.astimezone(ART)
    off = dt.strftime("%z")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000") + off[:3] + ":" + off[3:]


def parse_local(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ART)


def hav_km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def xy_m(p, ref):
    k = math.cos(math.radians(ref[0]))
    return ((p[1] - ref[1]) * 111320.0 * k, (p[0] - ref[0]) * 110574.0)


def seg_dist_m(p, a, b):
    ref = a
    px, py = xy_m(p, ref)
    ax, ay = 0.0, 0.0
    bx, by = xy_m(b, ref)
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def path_len_km(path):
    return sum(hav_km(path[i], path[i + 1]) for i in range(len(path) - 1))


def simplify(path, tol_m):
    if len(path) < 3:
        return path
    keep = [False] * len(path)
    keep[0] = keep[-1] = True
    stack = [(0, len(path) - 1)]
    while stack:
        i, j = stack.pop()
        best, bi = 0.0, None
        for k in range(i + 1, j):
            d = seg_dist_m(path[k], path[i], path[j])
            if d > best:
                best, bi = d, k
        if bi is not None and best > tol_m:
            keep[bi] = True
            stack.append((i, bi))
            stack.append((bi, j))
    return [p for p, k in zip(path, keep) if k]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def has_word(text, key):
    return re.search(r"(?<![a-z0-9])" + re.escape(norm(key)) + r"(?![a-z0-9])", norm(text)) is not None


class Osrm:
    def __init__(self, cache_dir, offline=False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.last = 0.0
        self.requests = 0
        self.hits = 0

    def key(self, coords):
        body = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords) + "?" + OSRM_PARAMS
        return hashlib.sha1(body.encode()).hexdigest()[:16], body

    def route(self, coords):
        k, body = self.key(coords)
        f = self.cache_dir / f"{k}.json"
        if f.exists():
            self.hits += 1
            return k, json.loads(f.read_text())["response"]
        if self.offline:
            return k, None
        wait = MIN_INTERVAL_S - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        url = osrm_base() + body
        last_err = None
        for attempt in range(3):
            self.last = time.time()
            self.requests += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read())
                if data.get("code") != "Ok":
                    f.write_text(json.dumps({"url": url, "response": data}))
                    return k, data
                f.write_text(json.dumps({"url": url, "response": data}))
                return k, data
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_err = e
                time.sleep(5 * (attempt + 1))
        sys.stderr.write(f"osrm failed {k}: {last_err}\n")
        return k, None


def legs_of(resp):
    if not resp or resp.get("code") != "Ok":
        return None
    out = []
    for leg in resp["routes"][0]["legs"]:
        geom = []
        for st in leg["steps"]:
            g = [(c[1], c[0]) for c in st["geometry"]["coordinates"]]
            if geom and g and geom[-1] == g[0]:
                g = g[1:]
            geom.extend(g)
        out.append({"geom": geom, "km": leg["distance"] / 1000.0, "sec": leg["duration"]})
    wps = [(w["location"][1], w["location"][0], w.get("distance", 0.0)) for w in resp["waypoints"]]
    return out, wps


def load_inputs(proj):
    p = Path(proj)
    route = json.loads((p / "route/route.json").read_text())
    raw = json.loads((p / "route" / config.get("route.export_file", "Rutas.json")).read_text())
    inv = json.loads((p / "inv/inventory.json").read_text())
    media = json.loads((p / "inv/media.json").read_text())
    chrono = json.loads((p / "notes/chronology.json").read_text())
    caps = json.loads((p / "captions.json").read_text())
    labels = json.loads((p / "route/labels.json").read_text())
    return route, raw, inv, media, chrono, caps, labels


def raw_gps_fixes(raw):
    out = []
    for r in raw.get("rawSignals", []):
        pos = r.get("position")
        if not pos or pos.get("source") != "GPS" or pos.get("accuracyMeters", 1e9) > RAW_ACC_M:
            continue
        lat, lon = (float(x) for x in re.findall(r"-?\d+\.\d+", pos["LatLng"])[:2])
        out.append((parse_iso(pos["timestamp"]), lat, lon, pos["accuracyMeters"]))
    out.sort()
    return out


def drop_contradicted(points, visits):
    dropped = []
    drop = set()
    for v in visits:
        s, e = parse_iso(v["start"]), parse_iso(v["end"])
        if (e - s) < timedelta(minutes=20):
            continue
        loc = (v["lat"], v["lon"])
        inside = [i for i, p in enumerate(points) if s < p["t"] < e]
        if not inside:
            continue
        if any(hav_km((points[i]["lat"], points[i]["lon"]), loc) <= VISIT_CONTRADICT_KM for i in inside):
            continue
        for i in inside:
            drop.add(i)
        dropped.append({"visit": v, "points": [points[i]["iso"] for i in inside]})
    return [p for i, p in enumerate(points) if i not in drop], dropped


def classify(a, b):
    dt = (b["t"] - a["t"]).total_seconds() / 60.0
    d = hav_km((a["lat"], a["lon"]), (b["lat"], b["lon"]))
    v = d / (dt / 60.0) if dt > 0 else float("inf")
    kinds = []
    if d > FLIGHT_KM:
        return dt, d, v, ["flight"]
    if dt > GAP_MIN and d > GAP_MIN_KM:
        kinds.append("time")
    elif dt > GAP_MIN:
        kinds.append("idle")
    if v > SPEED_KMH and d > SPEED_MIN_KM:
        kinds.append("speed")
    if d > JUMP_KM and dt <= GAP_MIN:
        kinds.append("jump")
    return dt, d, v, kinds


def insert_raw_fixes(points, fixes):
    added = []
    out = []
    fi = 0
    for i, p in enumerate(points):
        out.append(p)
        if i + 1 >= len(points):
            break
        q = points[i + 1]
        dt, d, v, kinds = classify(p, q)
        if "time" not in kinds:
            continue
        cand = [f for f in fixes if p["t"] + timedelta(seconds=60) < f[0] < q["t"] - timedelta(seconds=60)]
        prev = p
        for f in cand:
            fp = {"t": f[0], "iso": fmt_iso(f[0]), "lat": f[1], "lon": f[2], "src": "gps", "raw_acc": f[3]}
            dd = hav_km((prev["lat"], prev["lon"]), (fp["lat"], fp["lon"]))
            dtm = (fp["t"] - prev["t"]).total_seconds() / 3600.0
            if dtm <= 0 or dd / dtm > 150:
                continue
            if dd < 0.05:
                continue
            out.append(fp)
            added.append(fp)
            prev = fp
    return out, added


def caption_events(caps, media):
    by_id = {m["id"]: m for m in media}
    ev = []
    for k, c in caps.items():
        m = by_id.get(k)
        if not m or not m.get("time_art") or not c.get("place"):
            continue
        ev.append({"t": parse_iso(m["time_art"]), "place": c["place"], "conf": c.get("confidence"), "id": k})
    ev.sort(key=lambda e: e["t"])
    return ev


def caption_groups(events, max_gap_min=20):
    groups = []
    for e in events:
        if groups and groups[-1]["place"] == e["place"] and (e["t"] - groups[-1]["end"]).total_seconds() <= max_gap_min * 60:
            g = groups[-1]
            g["end"] = e["t"]
            g["n"] += 1
            g["confs"].append(e["conf"])
        else:
            groups.append({"place": e["place"], "start": e["t"], "end": e["t"], "n": 1, "confs": [e["conf"]]})
    return groups


def drone_clusters(inv, t0, t1):
    clips = []
    for x in inv:
        if x.get("lat") is None:
            continue
        s = parse_local(x["start"])
        e = s + timedelta(seconds=x.get("dur") or 0)
        if s >= t0 and e <= t1:
            clips.append({"s": s, "e": e, "lat": x["lat"], "lon": x["lon"], "path": x["path"]})
    clips.sort(key=lambda c: c["s"])
    clusters = []
    for c in clips:
        if clusters:
            cl = clusters[-1]
            if (c["s"] - cl["e"]).total_seconds() <= 600 and hav_km((cl["lat"], cl["lon"]), (c["lat"], c["lon"])) <= 1.0:
                cl["e"] = max(cl["e"], c["e"])
                cl["items"].append(c)
                n = len(cl["items"])
                cl["lat"] += (c["lat"] - cl["lat"]) / n
                cl["lon"] += (c["lon"] - cl["lon"]) / n
                continue
        clusters.append({"s": c["s"], "e": c["e"], "lat": c["lat"], "lon": c["lon"], "items": [c]})
    return clusters


def build_gap_context(gap, series, inv, cap_events, cap_groups, labels, chrono, visits):
    a, b = gap["a"], gap["b"]
    t0, t1 = a["t"], b["t"]
    A, B = (a["lat"], a["lon"]), (b["lat"], b["lon"])

    def off_corridor(p):
        return seg_dist_m(p, A, B) / 1000.0 > OFF_CORRIDOR_KM and hav_km(p, A) > OFF_CORRIDOR_KM and hav_km(p, B) > OFF_CORRIDOR_KM

    day = t0.strftime("%Y-%m-%d")
    day_places = []
    for d in chrono.get("days", []):
        if d["date"] == day:
            day_places = d.get("places", [])
    in_caps = [e for e in cap_events if t0 <= e["t"] <= t1]
    waypoints = []
    for v in visits:
        s, e = parse_iso(v["start"]), parse_iso(v["end"])
        ov = (min(e, t1) - max(s, t0)).total_seconds()
        if ov < 15 * 60 or not off_corridor((v["lat"], v["lon"])):
            continue
        w = {"kind": "visit", "lat": v["lat"], "lon": v["lon"], "tin": max(s, t0), "tout": min(e, t1), "evidence": [f"Timeline visit {fmt_iso(s)[11:16]}-{fmt_iso(e)[11:16]} at ({v['lat']:.4f},{v['lon']:.4f}), place_id {v['place_id']}"], "name": None}
        waypoints.append(w)
    for cl in drone_clusters(inv, t0, t1):
        p = (cl["lat"], cl["lon"])
        if not off_corridor(p) or seg_dist_m(p, A, B) / 1000.0 < DRONE_OFF_KM:
            continue
        waypoints.append({"kind": "drone", "lat": p[0], "lon": p[1], "tin": cl["s"], "tout": cl["e"], "evidence": [f"{len(cl['items'])} drone clips {fmt_iso(cl['s'])[11:16]}-{fmt_iso(cl['e'])[11:16]} (DJI GPS)"], "name": None})
    for key, (llat, llon) in labels.items():
        allhits = [e for e in in_caps if has_word(e["place"], key) and e["conf"] != "low"]
        enroute = [e for e in allhits if re.match(config.get("routefill.enroute_pattern"), norm(e["place"]))]
        hits = [e for e in allhits if e not in enroute]
        if len(hits) < 3:
            continue
        L = (llat, llon)
        merged = None
        for w in waypoints:
            if hav_km((w["lat"], w["lon"]), L) <= 5.0:
                merged = w
                break
        ev = f"{len(hits)} captions place~'{key}' {fmt_iso(hits[0]['t'])[11:16]}-{fmt_iso(hits[-1]['t'])[11:16]}"
        if any(has_word(pl, key) for pl in day_places):
            ev += f"; chronology {day} places include '{key}'"
        ev += f"; label ({llat:.3f},{llon:.3f})"
        if merged:
            merged["name"] = key
            merged["evidence"].append(ev)
            merged["tin"] = min(merged["tin"], hits[0]["t"])
            merged["tout"] = max(merged["tout"], hits[-1]["t"])
            if enroute:
                merged["tin"] = max(merged["tin"], enroute[-1]["t"])
                merged["evidence"].append(f"{len(enroute)} captions 'camino a {key}' until {fmt_iso(enroute[-1]['t'])[11:16]}: still en route")
        elif off_corridor(L) and hav_km(L, ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)) < 80:
            waypoints.append({"kind": "label", "lat": llat, "lon": llon, "tin": hits[0]["t"], "tout": hits[-1]["t"], "evidence": [ev], "name": key})
    waypoints.sort(key=lambda w: w["tin"])
    dep, arr = t0, t1
    dep_ev, arr_ev = None, None
    wp_names = [w["name"] for w in waypoints if w["name"]]
    for cl in drone_clusters(inv, t0, t1):
        p = (cl["lat"], cl["lon"])
        if hav_km(p, A) <= OFF_CORRIDOR_KM and cl["e"] + timedelta(seconds=30) > dep and cl["e"] < t1 - timedelta(minutes=2):
            dep = cl["e"] + timedelta(seconds=30)
            dep_ev = f"drone clips at start until {fmt_iso(cl['e'])[11:16]}"
        if hav_km(p, B) <= OFF_CORRIDOR_KM and cl["s"] - timedelta(seconds=30) < arr and cl["s"] > t0 + timedelta(minutes=2):
            arr = cl["s"] - timedelta(seconds=30)
            arr_ev = f"drone clips at end from {fmt_iso(cl['s'])[11:16]}"
    gap["waypoints"] = waypoints
    gap["dep"], gap["arr"] = dep, arr
    gap["dep_ev"], gap["arr_ev"] = dep_ev, arr_ev
    return gap


def chain_requests(series, gaps):
    gap_at = {g["i"]: g for g in gaps}
    order = sorted(gap_at)
    blocks = []
    for i in order:
        if blocks:
            last = blocks[-1][-1]
            between = range(last + 1, i)
            ok = len(between) <= BRIDGE_MAX_SEGS and all(series[j + 1]["t"] - series[j]["t"] <= timedelta(minutes=GAP_MIN) and hav_km((series[j]["lat"], series[j]["lon"]), (series[j + 1]["lat"], series[j + 1]["lon"])) < FLIGHT_KM for j in between)
            if ok:
                blocks[-1].append(i)
                continue
        blocks.append([i])
    chains = []
    for blk in blocks:
        cur = None
        for i in range(blk[0], blk[-1] + 1):
            a, b = series[i], series[i + 1]
            A, B = (a["lat"], a["lon"]), (b["lat"], b["lon"])
            g = gap_at.get(i)
            seg = [B] if not g else [(w["lat"], w["lon"]) for w in g["waypoints"]] + [B]
            if cur is None or len(cur["coords"]) + len(seg) > CHAIN_MAX_COORDS:
                cur = {"coords": [A], "segs": {}, "gaps": []}
                chains.append(cur)
            leg0 = len(cur["coords"]) - 1
            n = 0
            for c in seg:
                if not g and hav_km(cur["coords"][-1], c) < 0.03:
                    continue
                cur["coords"].append(c)
                n += 1
            cur["segs"][i] = (leg0, n)
            if g:
                g["leg0"], g["nlegs"] = leg0, n
                g["coords"] = [A] + seg
                cur["gaps"].append(g)
    chains = [c for c in chains if c["gaps"]]
    return chains


def resolve_chain(chain, osrm):
    key, resp = osrm.route(chain["coords"])
    chain["key"] = key
    parsed = legs_of(resp)
    chain["legs"], chain["wps"] = parsed if parsed else (None, None)


def assemble_gap(g, chain):
    legs = chain["legs"]
    n = g["nlegs"]
    if legs is None:
        g["status"] = "osrm_unavailable"
        g["fill"] = False
        return
    g["legs"] = legs[g["leg0"]: g["leg0"] + n]
    g["snaps"] = chain["wps"][g["leg0"]: g["leg0"] + n + 1]
    chord = hav_km(g["coords"][0], g["coords"][-1])
    full = []
    for L in g["legs"]:
        full.extend(L["geom"])
    A, B = g["coords"][0], g["coords"][-1]
    dev = max((seg_dist_m(p, A, B) for p in full), default=0.0) if not g["waypoints"] else 1e9
    road_km = sum(L["km"] for L in g["legs"])
    g["road_km"] = road_km
    g["chord_km"] = chord
    g["max_dev_m"] = None if g["waypoints"] else round(dev)
    follows = (not g["waypoints"]) and dev <= ROAD_DEV_M and road_km <= chord * ROAD_RATIO + 0.05
    must = "time" in g["kinds"] or bool(g["waypoints"])
    if road_km > REJECT_RATIO * chord and road_km - chord > REJECT_EXTRA_KM and not g["waypoints"] and "time" not in g["kinds"]:
        g["status"] = "osrm_rejected_detour"
        g["fill"] = False
    elif follows and not must:
        g["status"] = "straight_ok"
        g["fill"] = False
    else:
        g["status"] = "filled"
        g["fill"] = True


def schedule(g):
    t0, t1 = g["a"]["t"], g["b"]["t"]
    anchors = [{"t_arr": None, "t_dep": g["dep"]}]
    for w in g["waypoints"]:
        anchors.append({"t_arr": w["tin"], "t_dep": w["tout"]})
    anchors.append({"t_arr": g["arr"], "t_dep": None})
    notes = []
    last = len(anchors) - 2
    for i, L in enumerate(g["legs"]):
        a, b = anchors[i], anchors[i + 1]
        if i == last:
            window = (b["t_arr"] - a["t_dep"]).total_seconds() / 3600.0
            if window > 0 and L["km"] / window > FEASIBLE_KMH:
                notes.append(f"source timestamps imply {L['km'] / window:.0f} km/h over {L['km']:.1f} km of road on the last leg; kept uniform between the gap endpoints")
            continue
        need = timedelta(hours=L["km"] / FEASIBLE_KMH)
        if b["t_arr"] - a["t_dep"] < need:
            if i == 0:
                a["t_dep"] = max(t0, b["t_arr"] - need)
            if b["t_arr"] - a["t_dep"] < need:
                shift = a["t_dep"] + need
                notes.append(f"leg {i}: {int((b['t_arr'] - a['t_dep']).total_seconds() / 60)} min for {L['km']:.1f} km exceeds {FEASIBLE_KMH:.0f} km/h; waypoint arrival moved {b['t_arr'].strftime('%H:%M')}->{shift.strftime('%H:%M')}")
                b["t_arr"] = shift
                if b["t_dep"] < shift:
                    b["t_dep"] = shift
    return anchors, notes


def leg_points(L, A, B, t_a, t_b, first_snap, last_snap):
    geom = list(L["geom"])
    if not geom:
        geom = [A, B]
    path = [A] + geom + [B]
    path = simplify(path, SIMPLIFY_M)
    cum = [0.0]
    for i in range(len(path) - 1):
        cum.append(cum[-1] + hav_km(path[i], path[i + 1]))
    total = cum[-1] or 1e-9
    span = (t_b - t_a).total_seconds()
    pts = []
    for p, c in zip(path, cum):
        pts.append((t_a + timedelta(seconds=span * c / total), p[0], p[1]))
    return pts


def build_fill_points(g):
    anchors, notes = schedule(g)
    g["timing_notes"] = notes
    A, B = g["coords"][0], g["coords"][-1]
    pts = []
    stops = [A] + [(s[0], s[1]) for s in g["snaps"][1:-1]] + [B]
    if anchors[0]["t_dep"] > g["a"]["t"]:
        pts.append((anchors[0]["t_dep"], A[0], A[1]))
    for i, L in enumerate(g["legs"]):
        a, b = anchors[i], anchors[i + 1]
        lp = leg_points(L, stops[i], stops[i + 1], a["t_dep"], b["t_arr"], None, None)
        pts.extend(lp)
        if b["t_dep"] is not None and b["t_dep"] > b["t_arr"]:
            pts.append((b["t_dep"], stops[i + 1][0], stops[i + 1][1]))
    t0, t1 = g["a"]["t"], g["b"]["t"]
    pts = [p for p in pts if t0 < p[0] < t1 or (p[0] >= t1 and False)]
    dedup = []
    for p in pts:
        if dedup and dedup[-1][0] == p[0] and abs(dedup[-1][1] - p[1]) < 1e-6 and abs(dedup[-1][2] - p[2]) < 1e-6:
            continue
        dedup.append(p)
    return dedup


def run(proj, out_path, osrm, dry=False):
    route, raw, inv, media, chrono, caps, labels = load_inputs(proj)
    base = []
    for iso, lat, lon in route["points"]:
        base.append({"t": parse_iso(iso), "iso": iso, "lat": lat, "lon": lon, "src": "gps"})
    base.sort(key=lambda p: p["t"])
    series, dropped = drop_contradicted(base, route["visits"])
    series, raw_added = insert_raw_fixes(series, raw_gps_fixes(raw))
    series.sort(key=lambda p: p["t"])
    events = caption_events(caps, media)
    groups = caption_groups(events)

    gaps, idle, flights = [], [], []
    for i in range(len(series) - 1):
        a, b = series[i], series[i + 1]
        dt, d, v, kinds = classify(a, b)
        rec = {"i": i, "a": a, "b": b, "dt_min": dt, "km": d, "kmh": v, "kinds": kinds}
        if "flight" in kinds:
            flights.append(rec)
            continue
        if any(k in kinds for k in ("time", "speed", "jump")):
            gaps.append(rec)
        elif "idle" in kinds:
            idle.append(rec)
    for g in gaps:
        build_gap_context(g, series, inv, events, groups, labels, chrono, route["visits"])
    chains = chain_requests(series, gaps)
    summary = {"points": len(base), "dropped_contradicted": dropped, "raw_fixes_added": len(raw_added), "gaps": len(gaps), "idle": len(idle), "flights": len(flights), "requests_needed": len(chains)}
    if dry:
        return summary, gaps, idle, flights, chains, series
    for ch in chains:
        resolve_chain(ch, osrm)
        for g in ch["gaps"]:
            assemble_gap(g, ch)
            g["chain_key"] = ch["key"]
    filled_by_gap = {}
    for g in gaps:
        if g.get("fill"):
            filled_by_gap[g["i"]] = build_fill_points(g)
    out_points = []
    for i, p in enumerate(series):
        out_points.append([p["iso"], p["lat"], p["lon"], "gps"])
        for t, lat, lon in filled_by_gap.get(i, []):
            out_points.append([fmt_iso(t), round(lat, 7), round(lon, 7), "filled"])
    fills = []
    for g in gaps:
        rec = {
            "gap": {"from": g["a"]["iso"], "to": g["b"]["iso"], "minutes": round(g["dt_min"]), "km_straight": round(g["km"], 1), "kinds": g["kinds"]},
            "status": g.get("status"),
            "waypoints": [{"name": w["name"], "kind": w["kind"], "lat": round(w["lat"], 5), "lon": round(w["lon"], 5), "arrive": fmt_iso(w["tin"]), "leave": fmt_iso(w["tout"]), "evidence": w["evidence"]} for w in g["waypoints"]],
            "evidence": [e for e in (g.get("dep_ev"), g.get("arr_ev")) if e],
            "km": round(g.get("road_km", 0.0), 1),
            "max_dev_from_straight_m": g.get("max_dev_m"),
            "osrm_cache_key": g.get("chain_key"),
            "filled_points": len(filled_by_gap.get(g["i"], [])),
            "timing_notes": g.get("timing_notes", []),
        }
        if not g["waypoints"] and not rec["evidence"]:
            rec["evidence"] = ["no waypoint evidence; routed directly between the gap endpoints"]
        fills.append(rec)
    result = {
        "points": out_points,
        "visits": route["visits"],
        "activities": route["activities"],
        "fills": fills,
        "dropped_points": dropped,
        "raw_gps_fixes_added": [[fmt_iso(f["t"]), f["lat"], f["lon"], f["raw_acc"]] for f in raw_added],
        "idle_gaps": [[g["a"]["iso"], g["b"]["iso"], round(g["dt_min"]), round(g["km"], 2)] for g in idle],
        "flight_segments": [[g["a"]["iso"], g["b"]["iso"], round(g["km"])] for g in flights],
        "attribution": ATTRIBUTION,
        "generator": "pipeline/routefill.py",
    }
    Path(out_path).write_text(json.dumps(result, indent=1, ensure_ascii=False))
    summary["filled"] = sum(1 for g in gaps if g.get("fill"))
    summary["straight_ok"] = sum(1 for g in gaps if g.get("status") == "straight_ok")
    summary["rejected"] = sum(1 for g in gaps if g.get("status") in ("osrm_rejected_detour", "osrm_unavailable"))
    summary["out_points"] = len(out_points)
    summary["osrm_requests"] = osrm.requests
    summary["cache_hits"] = osrm.hits
    return summary, gaps, idle, flights, chains, series


def check_image(proj, filled_path, out_path):
    from PIL import Image, ImageDraw, ImageFont
    route = json.loads((Path(proj) / "route/route.json").read_text())
    filled = json.loads(Path(filled_path).read_text())
    labels = json.loads((Path(proj) / "route/labels.json").read_text())
    before = [(p[1], p[2], "gps") for p in route["points"]]
    after = [(p[1], p[2], p[3]) for p in filled["points"]]
    views = [(v["title"], tuple(v["bbox"])) for v in config.get("routefill.check_views") or []]
    if not views:
        lats = [p[0] for p in before]
        lons = [p[1] for p in before]
        views = [("Recorrido completo", (min(lats) - 0.1, max(lats) + 0.1, min(lons) - 0.1, max(lons) + 0.1))]
    PW, PH, M = 1100, 800, 30
    W, H = PW * 2 + M * 3, (PH + 70) * len(views) + M
    img = Image.new("RGB", (W, H), (245, 242, 235))
    d = ImageDraw.Draw(img)
    f_big = ImageFont.truetype(config.font("ui"), 30)
    f_lab = ImageFont.truetype(config.font("ui"), 22)
    red, orange, grey = (205, 40, 40), (255, 140, 0), (150, 150, 150)
    for row, (title, (la0, la1, lo0, lo1)) in enumerate(views):
        k = math.cos(math.radians((la0 + la1) / 2))
        sc = min((PW - 20) / ((lo1 - lo0) * k), (PH - 20) / (la1 - la0))
        ox = (PW - (lo1 - lo0) * k * sc) / 2
        oy = (PH - (la1 - la0) * sc) / 2
        for col, (name, pts) in enumerate((("antes: route.json", before), ("después: route_filled.json", after))):
            x0 = M + col * (PW + M)
            y0 = M + row * (PH + 70) + 50
            ImageDraw.Draw(img).text((x0, y0 - 44), f"{title} - {name}", fill=(30, 30, 30), font=f_big)
            panel = Image.new("RGB", (PW, PH), (252, 251, 248))
            d = ImageDraw.Draw(panel)

            def proj_pt(lat, lon):
                return (ox + (lon - lo0) * k * sc, oy + (la1 - lat) * sc)

            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                if hav_km(a[:2], b[:2]) > FLIGHT_KM:
                    col_ = grey
                    wdt = 2
                elif a[2] == "filled" or b[2] == "filled":
                    col_ = orange
                    wdt = 5
                else:
                    col_ = red
                    wdt = 4
                d.line([proj_pt(*a[:2]), proj_pt(*b[:2])], fill=col_, width=wdt)
            for nm, (lat, lon) in labels.items():
                if la0 <= lat <= la1 and lo0 <= lon <= lo1:
                    x, y = proj_pt(lat, lon)
                    d.ellipse([x - 6, y - 6, x + 6, y + 6], outline=(20, 20, 20), width=3)
                    d.text((x + 10, y - 12), nm, fill=(20, 20, 20), font=f_lab)
            d.rectangle([0, 0, PW - 1, PH - 1], outline=(190, 190, 185))
            img.paste(panel, (x0, y0))
            d = ImageDraw.Draw(img)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=88)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--out")
    ap.add_argument("--cache")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--check-image")
    a = ap.parse_args()
    configure(config.load_project(a.project))
    out = a.out or str(Path(a.project) / "route/route_filled.json")
    osrm = Osrm(a.cache or cache_dir(), offline=a.offline)
    summary, gaps, idle, flights, chains, series = run(a.project, out, osrm, dry=a.dry)
    print(json.dumps({k: v for k, v in summary.items() if k != "dropped_contradicted"}, ensure_ascii=False))
    for d in summary["dropped_contradicted"]:
        print("dropped", d["visit"]["start"], d["points"])
    for g in gaps:
        print(g["a"]["iso"][5:16], g["b"]["iso"][11:16], f"{g['dt_min']:.0f}m {g['km']:.1f}km {g['kmh']:.0f}kmh", ",".join(g["kinds"]), "WP:" + ",".join(f"{w['name'] or w['kind']}" for w in g["waypoints"]), g.get("status", ""), f"road={g.get('road_km', 0):.1f}", g.get("dep_ev") or "", g.get("arr_ev") or "")
    print("idle gaps", len(idle), "flights", [(f["a"]["iso"][:16], round(f["km"])) for f in flights])
    print(json.dumps({k: v for k, v in summary.items() if k != "dropped_contradicted"}))
    if a.check_image and not a.dry:
        check_image(a.project, out, a.check_image)


if __name__ == "__main__":
    main()
