import json
import pathlib

import ffx
import mixaudio
from snap import snap_shots


def track_beats(G, wav, spec):
    if spec:
        p = mixaudio.find(G, spec)
        if p is None:
            raise ffx.RenderError(f"no existe el archivo de beats {spec}")
        return json.loads(p.read_text())
    cache = G.cache / f"beats-{mixaudio.digest(ffx.sig(wav))}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    import beats as beatlib

    res = beatlib.analyze(str(wav))
    cache.write_text(json.dumps(res))
    return res


def tiled(times, loop, until):
    out, rep = [], 0
    while True:
        chunk = [t + rep * loop for t in times]
        out += chunk
        if (chunk[-1] if chunk else until) >= until or loop <= 0:
            return out
        rep += 1


def apply(G, report):
    tracks = mixaudio.raw_tracks(G, report)
    if not tracks:
        report.warn("snap_to_beats: no hay temas disponibles, las duraciones quedan como están")
        return
    shots, fps, st = G.shots, float(G.fps), G.style
    tol = st["snap_tolerance"]
    for t in tracks:
        t["wav"] = mixaudio.normalize(G, t["file"], report)
        t["analysis"] = track_beats(G, t["wav"], t["beats"])
        t["loop"] = ffx.probe(t["wav"])["dur"]
    owner = {i: k for k, t in enumerate(tracks) for i in range(t["from"], t["to"] + 1)}
    placed = {}
    cursor = 0.0
    n = len(shots)
    done, shifts, clamped = 0, [], 0
    with report.stage("beat snap"):
        for i, s in enumerate(shots):
            x_i = s.xn / fps
            x_n = shots[i + 1].xn / fps if i + 1 < n else 0.0
            pref = s.dur - x_i / 2 - x_n / 2
            k = owner.get(i)
            if k is not None and k not in placed:
                b = cursor - x_i / 2
                placed[k] = b - st["music_xfade"] if tracks[k]["joined"] else b
            if k is None or not s.snap:
                cursor += pref
                continue
            t = tracks[k]
            ft0 = cursor - placed[k]
            grid = tiled(t["analysis"]["beats"], t["loop"], ft0 + 2 * pref + 20)
            downs = tiled(t["analysis"].get("downbeats", []), t["loop"], ft0 + 2 * pref + 20)
            floor = (x_i + x_n) / 2 + 4 / fps
            lo, hi = max(pref * (1 - tol), floor, 0.5), pref * (1 + tol)
            cap = None if s.avail is None else s.avail - x_i / 2 - x_n / 2
            if cap is not None:
                hi = min(hi, cap)
                lo = min(lo, hi)
            res = snap_shots([{"dur": pref, "min": lo, "max": hi}], [ft0] + [b for b in grid if b > ft0 + 1e-3], downbeats=downs)[0]
            d = res["dur_snapped"]
            if cap is not None and d > cap + 1e-6:
                d, clamped = cap, clamped + 1
                report.warn(f"shot {i}: no alcanzan los frames del video para llegar al beat, el corte queda fuera de pulso")
            shifts.append(d - pref)
            s.dur = d + x_i / 2 + x_n / 2
            cursor += d
            done += 1
    G.layout()
    report.snap = {"shots": done, "mean_shift": sum(abs(x) for x in shifts) / len(shifts) if shifts else 0.0, "clamped": clamped}
