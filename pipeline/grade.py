import hashlib
import json
import pathlib
import re
import subprocess
import sys
from fractions import Fraction

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
from PIL import Image, ImageOps

import config
import ffx

REV = "g2"
LUMA_W = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def cfg(key):
    return config.get("grade." + key)


def profiles():
    return config.get("grade.profiles")


def sunset_min():
    hh, mm = str(cfg("sunset")).split(":")
    return int(hh) * 60 + int(mm)


def night_shutter():
    return 1 / cfg("night_shutter_denominator")


def h(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:10]


def denoise_filter(tier):
    return f"hqdn3d={tier}" if tier else ""


def grade_filter(plan, yuv):
    p = profiles().get(plan.get("profile"))
    if not p:
        return ""
    head = "scale=in_color_matrix=bt709:in_range=tv:out_color_matrix=bt709:out_range=pc," if yuv else ""
    cur = f"curves=all='{p['curve']}'"
    k = plan.get("vib_k", 1.0)
    vib = f"vibrance=intensity={round(p['vibrance'] * k, 3)}" if p["vibrance"] and k > 0 else ""
    parts = [f"{head}format=gbrp"] + ([vib, cur] if p.get("vib_first") else [cur, vib])
    parts = [x for x in parts if x]
    if plan.get("warm") and p["warm"]:
        parts.append(f"colorbalance=rm={cfg('warm_amount')}:bm=-{cfg('warm_amount')}")
    parts.append("scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=bicubic")
    parts.append("format=yuv420p")
    return ",".join(parts)


def sharpen_filter(plan):
    return f"cas=strength={cfg('sharp_strength')}:planes=1" if plan.get("sharpen") else ""


def pieces(plan, yuv):
    if not plan:
        return {"dn": "", "grade": "", "sharp": ""}
    return {"dn": denoise_filter(plan.get("dn")), "grade": grade_filter(plan, yuv), "sharp": sharpen_filter(plan)}


def join(*fs):
    return ",".join(f for f in fs if f)


def spec(plan, kind):
    if not plan:
        return None
    return {"rev": REV, "plan": plan, "fc": pieces(plan, kind == "video")}


def measure(rgb):
    a = rgb.astype(np.float32)
    y = a @ LUMA_W
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    p5, p50, p95 = np.percentile(y, [5, 50, 95])
    return {
        "mean": float(y.mean()),
        "p5": float(p5),
        "p50": float(p50),
        "p95": float(p95),
        "clipY": float((y > 250).mean() * 100),
        "clipC": float((mx > 250).mean() * 100),
        "sat": float(sat.mean()),
    }


def lap_var(rgb):
    g = (rgb.astype(np.float32) @ LUMA_W)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def warmth(rgb):
    a = rgb.astype(np.float32)
    y = a @ LUMA_W
    m = (y > 50) & (y < 200)
    if m.sum() < 100:
        return 1.0
    return float(a[..., 0][m].mean() / max(a[..., 2][m].mean(), 1))


def load_small(path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((cfg("sample_w"), cfg("sample_w")), Image.LANCZOS)
    return np.asarray(im)


def grab(src, t, out):
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", "-vf", f"scale={cfg('sample_w')}:{cfg('sample_w')}:force_original_aspect_ratio=decrease:flags=area", str(out)]
    ffx.run(cmd)
    return np.asarray(Image.open(out).convert("RGB"))


def srt_frames(video_path, t0, t1):
    p = pathlib.Path(video_path).with_suffix(".SRT")
    if not p.exists():
        p = pathlib.Path(video_path).with_suffix(".srt")
    if not p.exists():
        return None
    txt = p.read_text(errors="replace")
    rows = re.findall(r"\[iso : (\d+)\] \[shutter : ([\d/.]+)\].*?\[focal_len : (\d+)\] \[dzoom_ratio: (\d+)", txt)
    if not rows:
        return None
    fps = float(Fraction(cfg("srt_fps")))
    a, b = int(t0 * fps), max(int(t1 * fps), int(t0 * fps) + 1)
    rows = rows[a:b] or rows
    num = lambda s: (lambda n, d: float(n) / float(d))(*s.split("/")) if "/" in s else float(s)
    iso = [int(r[0]) for r in rows]
    sh = [num(r[1]) for r in rows]
    fl = [int(r[2]) for r in rows]
    dz = [int(r[3]) for r in rows]
    return {
        "iso_med": float(np.median(iso)),
        "iso_max": max(iso),
        "shutter_med": float(np.median(sh)),
        "focal": sorted(set(fl)),
        "dz_max": max(dz) / 10000,
        "dz_frac": sum(1 for d in dz if d > 10000) / len(dz),
        "n": len(rows),
    }


def exif_of(path):
    r = subprocess.run(["exiftool", "-j", "-n", "-DigitalZoomRatio", "-FocalLength", "-FocalLengthIn35mmFormat", "-Model", "-ExposureTime", "-ISO", str(path)], capture_output=True, text=True)
    if r.returncode:
        return {}
    try:
        return json.loads(r.stdout)[0]
    except (ValueError, IndexError):
        return {}


def art_minutes(rec):
    t = (rec.get("time_art") or "")[11:16]
    if len(t) != 5:
        return None
    return int(t[:2]) * 60 + int(t[3:])


def probe_shot(G, s, report):
    rec = s.rec
    span = s.dur * s.speed
    dflt = config.defaults()["grade"]
    extra = [] if (cfg("probe_fractions"), cfg("sample_w")) == (dflt["probe_fractions"], dflt["sample_w"]) else [cfg("probe_fractions"), cfg("sample_w")]
    key = h([REV, rec["id"], rec["path"], s.t_in, round(span, 3), s.kind] + extra)
    cache = G.project / "build" / "gprobe"
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text())
    src = pathlib.Path(rec["path"])
    out = {"id": rec["id"], "kind": s.kind, "source": rec.get("source"), "minute": art_minutes(rec)}
    frames = []
    if s.kind == "photo":
        if not src.exists():
            report.warn(f"grade: falta {src}, shot {s.idx} sin medición")
            return None
        frames.append(load_small(src))
        if rec.get("source", "").startswith("drone"):
            out["exif"] = {}
        else:
            out["exif"] = exif_of(src)
    else:
        probe_src = src if src.exists() else (pathlib.Path(G.proxy_for(rec)) if G.proxy_for(rec) else None)
        if probe_src is None:
            report.warn(f"grade: falta {src}, shot {s.idx} sin medición")
            return None
        for k, fr in enumerate(cfg("probe_fractions")):
            frames.append(grab(probe_src, s.t_in + span * fr, cache / f"{key}-{k}.png"))
        out["srt"] = srt_frames(src, s.t_in, s.t_in + span) if rec.get("source") == "drone" and src.exists() else None
    ms = [measure(x) for x in frames]
    out["luma"] = float(np.mean([m["mean"] for m in ms]))
    out["sat"] = float(np.mean([m["sat"] for m in ms]))
    mid = frames[len(frames) // 2]
    out["lap"] = float(np.median([lap_var(x) for x in frames]))
    out["rb"] = warmth(mid)
    f.write_text(json.dumps(out))
    for k in range(3):
        (cache / f"{key}-{k}.png").unlink(missing_ok=True)
    return out


def zoom_reason(pr):
    if pr["kind"] == "photo":
        ex = pr.get("exif") or {}
        dz = ex.get("DigitalZoomRatio") or 1
        f35 = ex.get("FocalLengthIn35mmFormat") or 0
        if dz > 1.05:
            return f"DigitalZoomRatio {dz:g}"
        if f35 > 30:
            return f"focal 35mm {f35:g} mm"
        return None
    sr = pr.get("srt")
    if not sr:
        return None
    if sr["dz_frac"] >= cfg("zoom_frac"):
        return f"dzoom_ratio hasta {sr['dz_max']:g}x en {sr['dz_frac'] * 100:.0f} % de los cuadros"
    if len(sr["focal"]) > 1:
        return f"focal_len cambia {sr['focal']}"
    return None


def vibrance_taper(sat):
    lo, hi = cfg("vibrance_taper")
    if sat is None or sat <= lo:
        return 1.0
    if sat >= hi:
        return 0.0
    return round((hi - sat) / (hi - lo), 2)


def is_night(pr, rec):
    sr = pr.get("srt")
    if sr:
        if sr["iso_med"] >= cfg("night_iso") or sr["shutter_med"] > night_shutter():
            return "ISO %d, obturador 1/%d" % (sr["iso_med"], round(1 / sr["shutter_med"]))
    m = pr.get("minute")
    if m is not None and m >= sunset_min() and pr["luma"] < cfg("night_luma"):
        return "después de la puesta de sol y luma %.0f" % pr["luma"]
    return None


def denoise_tier(pr, night):
    if not night:
        return None
    sr = pr.get("srt")
    iso = sr["iso_max"] if sr else (pr.get("exif") or {}).get("ISO", 300)
    if pr["kind"] == "photo":
        return None
    for lim, tier in cfg("denoise"):
        if iso <= lim:
            return tier


def plan(G, s, report):
    if not G.grading or s.kind not in ("video", "photo"):
        return None
    g = s.raw.get("grade", "auto")
    sh = s.raw.get("sharpen", "auto")
    if g not in ("auto", "none") and g not in profiles():
        raise ffx.RenderError(f"shot {s.idx}: grade debe ser auto|none|{'|'.join(profiles())}")
    if sh not in ("auto", True, False):
        raise ffx.RenderError(f"shot {s.idx}: sharpen debe ser auto|true|false")
    pr = None
    if g == "auto" or sh == "auto":
        pr = probe_shot(G, s, report)
    prof, why, warm, dn, vib_k = None, None, False, None, 1.0
    if g == "auto":
        if pr:
            night = is_night(pr, s.rec)
            if night:
                prof, why = "night", night
            elif s.rec.get("source") != "drone" and (pr.get("minute") or 0) >= sunset_min():
                why = "fuera de grading: toma de teléfono de noche con luma %.0f" % pr["luma"]
            else:
                prof = "day_drone" if s.rec.get("source") == "drone" else "day_phone"
                warm = cfg("warm_rb")[0] <= pr["rb"] <= cfg("warm_rb")[1]
                vib_k = vibrance_taper(pr.get("sat"))
            dn = denoise_tier(pr, bool(night))
    elif g != "none":
        prof = g
        if prof == "night" and pr:
            dn = denoise_tier(pr, True)
        elif pr:
            warm = cfg("warm_rb")[0] <= pr["rb"] <= cfg("warm_rb")[1]
    sharp = False
    zr = None
    if sh is True:
        sharp = True
    elif sh == "auto" and pr:
        zr = zoom_reason(pr)
        group = "drone" if s.rec.get("source") == "drone" else "phone"
        sharp = bool(zr) and pr["lap"] < cfg("soft_lap")[group]
    if not prof and not sharp:
        return None
    out = {"profile": prof, "sharpen": sharp, "dn": dn if prof == "night" else None, "warm": warm}
    if vib_k < 1.0:
        out["vib_k"] = vib_k
    s.ginfo = {"plan": out, "night": why, "zoom": zr, "lap": pr["lap"] if pr else None, "luma": pr["luma"] if pr else None}
    return out
