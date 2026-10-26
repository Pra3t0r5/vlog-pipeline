import datetime as D
import json
import os
import pathlib
import re

import config
import sharpness
import sources

DEFAULTS = {k: v for k, v in config.base_section("prefilter").items() if k != "screenshot_pattern"}
SCREENSHOT_NAME = re.compile(config.base_section("prefilter")["screenshot_pattern"], re.I)
EXCLUDE_REASON_MAP = (
    ("screenshot", "screenshot"),
    ("gif", "screenshot"),
    ("generated", "screenshot"),
    ("out_of_range", "out_of_range"),
    ("no_date", "out_of_range"),
    ("duplicate_of", "duplicate"),
)
ORDER = ("screenshot", "out_of_range", "duplicate", "excluded", "burst", "blurry", "variant")


def trip_range(cfg):
    for key in ("trip", "ingest", "rutas"):
        d = cfg.get(key) or {}
        lo = d.get("start_date") or d.get("from")
        hi = d.get("end_date") or d.get("to")
        if lo and hi:
            return str(lo), str(hi)
    return None, None


def params_of(cfg):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in (cfg.get("prefilter") or {}).items() if k in DEFAULTS})
    return p


def reason_from_ingest(rec):
    why = rec.get("exclude_reason")
    if not why:
        return None
    for prefix, reason in EXCLUDE_REASON_MAP:
        if why.startswith(prefix):
            return reason, why
    return "excluded", why


def screenshot_re():
    return re.compile(config.get("prefilter.screenshot_pattern") or SCREENSHOT_NAME.pattern, re.I)


def static_reason(rec, trip):
    r = reason_from_ingest(rec)
    if r:
        return r
    if screenshot_re().search(os.path.basename(rec["path"])):
        return "screenshot", "nombre de archivo"
    lo, hi = trip
    day = rec.get("day")
    if (lo or hi) and (not day or (lo and day < lo) or (hi and day > hi)):
        return "out_of_range", f"día {day} fuera de {lo}..{hi}"
    if rec.get("keep_in_burst") is False:
        return "burst", f"ráfaga {rec.get('burst_group')}"
    return None


def exact_duplicates(recs, hasher=sources.quick_hash, exists=os.path.exists):
    by_size = {}
    for r in recs:
        if exists(r["path"]):
            by_size.setdefault((r["kind"], os.path.getsize(r["path"])), []).append(r)
    dups = {}
    for group in by_size.values():
        if len(group) < 2:
            continue
        seen = {}
        for r in sorted(group, key=lambda x: x["id"]):
            h = hasher(r["path"])
            if h in seen:
                dups[r["id"]] = seen[h]
            else:
                seen[h] = r["id"]
    return dups


def decide(media, rows, trip, params, exact=None):
    exact = exact or {}
    dropped = {}
    alive = []
    for rec in sorted(media, key=lambda r: (r.get("time_art") or "", r["id"])):
        s = static_reason(rec, trip)
        if s is None and rec["id"] in exact:
            s = ("duplicate", f"idéntico a {exact[rec['id']]}")
        if s is None:
            sh = rows.get(rec["id"])
            if sh is not None:
                if sh["z"] < params["blurry_z"]:
                    s = ("blurry", f"z={sh['z']:.2f} < {params['blurry_z']}")
                elif sh["motion_blur"]:
                    s = ("blurry", f"movimiento, z={sh['z']:.2f}, dir_ratio={sh['dir_ratio']:.2f}")
        if s:
            dropped[rec["id"]] = {"reason": s[0], "detail": s[1]}
        else:
            alive.append(rec)
    alive_rows = {r["id"]: rows[r["id"]] for r in alive if r["id"] in rows}
    by_id = {r["id"]: r for r in alive}
    for g in sharpness.variants(alive_rows, by_id, {}, params["variant_phash"], params["variant_seconds"]):
        for m in g["members"][1:]:
            dropped[m["id"]] = {"reason": "variant", "detail": f"{g['group']}: más nítida {g['best']} (z={m['z']:.2f})"}
    kept = sorted(r["id"] for r in media if r["id"] not in dropped)
    return kept, dropped


def summarize(media, kept, dropped):
    by_reason = {k: 0 for k in ORDER}
    for d in dropped.values():
        by_reason[d["reason"]] = by_reason.get(d["reason"], 0) + 1
    keep = set(kept)
    kinds = {}
    for r in media:
        if r["id"] in keep:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    return {"total": len(media), "kept": len(kept), "dropped": len(dropped), "by_reason": by_reason, "kept_by_kind": kinds}


def path_of(proj):
    return pathlib.Path(proj) / "inv" / "prefilter.json"


def load(proj):
    p = path_of(proj)
    return json.loads(p.read_text()) if p.exists() else None


def survivors(proj):
    d = load(proj)
    return set(d["kept"]) if d else None


def run(proj, cfg, log=print):
    proj = pathlib.Path(proj)
    media = json.loads((proj / cfg.get("media", "inv/media.json")).read_text())
    params = params_of(cfg)
    trip = trip_range(cfg)
    by_id = {m["id"]: m for m in media}
    rows = sharpness.measure_all(str(proj), by_id, log=lambda *a, **k: None)
    exact = exact_duplicates([m for m in media if not m.get("exclude_reason")])
    kept, dropped = decide(media, rows, trip, params, exact)
    out = {
        "version": 1,
        "created": D.datetime.now().astimezone().isoformat(timespec="seconds"),
        "params": params,
        "trip": {"from": trip[0], "to": trip[1]},
        "unmeasured": sorted(i for i in kept if i not in rows),
        "counts": summarize(media, kept, dropped),
        "kept": kept,
        "dropped": dict(sorted(dropped.items())),
    }
    path_of(proj).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


def report(out):
    c = out["counts"]
    lines = [f"prefilter: {c['total']} -> {c['kept']} (descarta {c['dropped']})"]
    for k, n in c["by_reason"].items():
        if n:
            lines.append(f"  {k:13} {n}")
    if out["unmeasured"]:
        lines.append(f"  sin medir de nitidez (se conservan): {len(out['unmeasured'])}")
    return "\n".join(lines)

