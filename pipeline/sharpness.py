import io
import json
import math
import os
import pathlib
import subprocess
import sys
from datetime import datetime as D

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import imagehash
import numpy as np
from PIL import Image
from scipy import ndimage

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

import config

_SHP = config.base_section("sharpness")
LONG = _SHP["long_side"]
BLURRY_Z = _SHP["blurry_z"]
MOTION_RATIO = _SHP["motion_ratio"]
VARIANT_SECONDS = _SHP["variant_seconds"]
VARIANT_PHASH = _SHP["variant_phash"]
FRAMES = _SHP["frames"]


def load_gray(im):
    im = im.convert("L")
    w, h = im.size
    s = config.get("sharpness.long_side", LONG) / max(w, h)
    if s < 1:
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    return im


def measures(im):
    g = np.asarray(im, dtype=np.float32)
    lap = ndimage.laplace(g)[1:-1, 1:-1]
    gx = ndimage.sobel(g, axis=1)[1:-1, 1:-1]
    gy = ndimage.sobel(g, axis=0)[1:-1, 1:-1]
    ten = float(np.mean(gx * gx + gy * gy))
    d1 = (gx + gy) / math.sqrt(2)
    d2 = (gx - gy) / math.sqrt(2)
    e = [float(np.mean(a * a)) for a in (gx, gy, d1, d2)]
    ratio = min(e) / max(e) if max(e) > 0 else 1.0
    return {"lapvar": float(lap.var()), "tenengrad": ten, "dir_ratio": ratio}


def photo_gray(path):
    im = Image.open(path)
    lng = config.get("sharpness.long_side", LONG)
    im.draft("RGB", (lng * 2, lng * 2))
    return load_gray(im)


def frame_gray(path, t):
    cmd = ["nice", "-n", "10", "ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", path,
           "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode or not r.stdout:
        return None
    return load_gray(Image.open(io.BytesIO(r.stdout)))


def frame_times(rec, best):
    dur = rec["dur"] or 0
    if dur <= 0:
        return []
    a, b = (best if best else (1, 6))
    a, b = max(1, min(6, int(a))), max(1, min(6, int(b)))
    ks = sorted({a, round((a + b) / 2), b})
    nf = config.get("sharpness.frames", FRAMES)
    if len(ks) < nf:
        ks = sorted(set(ks) | {k for k in range(1, 7) if a <= k <= b})[:nf] if b - a + 1 >= nf else ks
    return [dur * (k - 0.5) / 6 for k in ks]


def load_triage(root):
    codes = json.load(open(f"{root}/sheets/index.json"))["codes"]
    merged = f"{root}/triage/merged.json"
    files = [merged] if os.path.exists(merged) else [f"{root}/triage/{k}.json" for k in "ABCD"]
    tri = {}
    for f in files:
        for t in json.load(open(f)):
            t["id"] = codes.get(t["code"])
            tri[t["code"]] = t
    return tri


def compute(rec, best, cache):
    key = rec["id"]
    if key in cache:
        return cache[key]
    if rec["kind"] == "photo":
        im = photo_gray(rec["path"])
        m = measures(im)
        m["phash"] = str(imagehash.phash(im))
        m["frames"] = 1
    else:
        ms, ph = [], None
        for t in frame_times(rec, best):
            im = frame_gray(rec["path"], t)
            if im is None:
                continue
            ms.append(measures(im))
            if ph is None:
                ph = str(imagehash.phash(im))
        if not ms:
            return None
        m = {k: float(np.median([x[k] for x in ms])) for k in ("lapvar", "tenengrad", "dir_ratio")}
        m["phash"] = ph
        m["frames"] = len(ms)
    cache[key] = m
    return m


def zscores(rows):
    groups = {}
    for i, r in rows.items():
        groups.setdefault((r["source"], r["kind"]), []).append(i)
    for ids in groups.values():
        for f in ("lapvar", "tenengrad"):
            v = np.array([math.log(rows[i][f] + 1e-6) for i in ids])
            mu, sd = v.mean(), v.std() or 1.0
            for i, x in zip(ids, v):
                rows[i]["z_" + f] = float((x - mu) / sd)
    for r in rows.values():
        r["z"] = (r["z_lapvar"] + r["z_tenengrad"]) / 2


def hdist(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def variants(rows, media, tri, phash=VARIANT_PHASH, seconds=VARIANT_SECONDS):
    parent = {i: i for i in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    photos = sorted((i for i in rows if media[i]["kind"] == "photo"), key=lambda i: media[i]["time_art"] or "")
    for n, a in enumerate(photos):
        ta = D.fromisoformat(media[a]["time_art"]) if media[a]["time_art"] else None
        for b in photos[n + 1:]:
            if not ta or not media[b]["time_art"]:
                continue
            dt = (D.fromisoformat(media[b]["time_art"]) - ta).total_seconds()
            if dt > seconds:
                break
            if media[a]["source"] == media[b]["source"] and hdist(rows[a]["phash"], rows[b]["phash"]) <= phash:
                union(a, b)
    for t in tri.values():
        if t.get("sim") and t["id"] in rows and tri.get(t["sim"], {}).get("id") in rows:
            union(t["id"], tri[t["sim"]]["id"])
    comp = {}
    for i in rows:
        comp.setdefault(find(i), []).append(i)
    out = []
    for ms in comp.values():
        if len(ms) < 2:
            continue
        ms.sort(key=lambda i: -rows[i]["z"])
        out.append(ms)
    out.sort(key=lambda ms: media[ms[0]]["time_art"] or "")
    return [{"group": f"V{n + 1:03d}", "best": ms[0],
             "members": [{"id": i, "rank": r + 1, "z": round(rows[i]["z"], 3), "source": media[i]["source"]} for r, i in enumerate(ms)]}
            for n, ms in enumerate(out)]


def measure_all(root, media, best=None, log=print):
    best = best or {}
    cache_path = f"{root}/inv/sharpness_cache.json"
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    usable = [m for m in media.values() if not m["exclude_reason"] and (os.path.exists(m["path"]) or m["id"] in cache)]
    rows = {}
    for n, rec in enumerate(usable):
        try:
            m = compute(rec, best.get(rec["id"]), cache)
        except Exception as e:
            print("skip", rec["id"], e, file=sys.stderr)
            continue
        if m:
            rows[rec["id"]] = {**m, "source": rec["source"], "kind": rec["kind"]}
        if n % 50 == 0:
            log(n, len(usable), flush=True)
            json.dump(cache, open(cache_path, "w"))
    json.dump(cache, open(cache_path, "w"))
    zscores(rows)
    for r in rows.values():
        r["blurry"] = bool(r["z"] < config.get("sharpness.blurry_z", BLURRY_Z))
        r["motion_blur"] = bool(r["dir_ratio"] < config.get("sharpness.motion_ratio", MOTION_RATIO) and r["z"] < 0)
        r["blurry"] = r["blurry"] or r["motion_blur"]
    return rows


def main(root):
    config.activate_project(root)
    media = {m["id"]: m for m in json.load(open(f"{root}/inv/media.json"))}
    tri = load_triage(root)
    best = {t["id"]: t.get("best") for t in tri.values() if t.get("id")}
    rows = measure_all(root, media, best)
    out = {i: {"lapvar": round(r["lapvar"], 2), "tenengrad": round(r["tenengrad"], 2), "z": round(r["z"], 3),
               "blurry": r["blurry"], "motion_blur": r["motion_blur"], "dir_ratio": round(r["dir_ratio"], 3),
               "source": r["source"], "kind": r["kind"]} for i, r in rows.items()}
    json.dump(out, open(f"{root}/inv/sharpness.json", "w"), indent=1)
    json.dump(variants(rows, media, tri), open(f"{root}/inv/variants.json", "w"), indent=1)
    print("done", len(out))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit("uso: sharpness.py carpeta_del_proyecto")
    main(sys.argv[1])
