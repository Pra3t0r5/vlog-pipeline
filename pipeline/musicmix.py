import argparse
import json
import pathlib
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import librosa
import scipy.signal as ss
import soundfile as sf

import beats as beatmod
import config

ASR = 22050
HOP = 256
BPB = 4
POOL = 2
TOL_S = 0.5
GUION_KEYS = ("target_s", "total_s", "duration_s", "total_duration_s", "total_duration", "duration")
SR = WIN_BEATS = MIN_PLAY_BARS = MIN_LOOP_S = HEAD_TRIM_CAP = LAG_MS = SEARCH_TOL_S = GAP_BARS = DEFAULT_TARGET = None
LOUDNORM = None


def configure(project_cfg=None):
    cfg = config.activate(project_cfg)
    mm = cfg["musicmix"]
    g = globals()
    for key in ("sr", "win_beats", "min_play_bars", "min_loop_s", "head_trim_cap", "lag_ms", "search_tol_s", "gap_bars"):
        g[key.upper()] = mm[key]
    g["DEFAULT_TARGET"] = mm["default_target_s"]
    g["LOUDNORM"] = mm["loudnorm"]
    return cfg


configure(None)


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[-800:]}")
    return r


def default_target(guion_path):
    p = pathlib.Path(guion_path)
    if p.exists():
        try:
            d = json.loads(p.read_text())
        except ValueError:
            d = {}
        for scope in (d, d.get("output", {}) if isinstance(d.get("output"), dict) else {}):
            for k in GUION_KEYS:
                v = scope.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    return float(v), f"{p.name}:{k}"
    return DEFAULT_TARGET, "default"


def unit(X):
    return X / (np.linalg.norm(X, axis=-1, keepdims=True) + 1e-9)


def zs(X):
    return (X - X.mean(0)) / (X.std(0) + 1e-6)


def beat_features(wav_path, bt):
    y, _ = librosa.load(wav_path, sr=ASR, mono=True)
    ch = librosa.feature.chroma_cqt(y=y, sr=ASR, hop_length=HOP)
    mf = librosa.feature.mfcc(y=y, sr=ASR, hop_length=HOP, n_mfcc=13)[1:]
    rms = np.log(librosa.feature.rms(y=y, hop_length=HOP) + 1e-4)
    n = min(ch.shape[1], mf.shape[1], rms.shape[1])
    bf = np.clip(librosa.time_to_frames(bt, sr=ASR, hop_length=HOP), 0, n - 1)

    def sync(F):
        return librosa.util.sync(F[:, :n], bf, aggregate=np.median).T

    C, M, R = sync(ch), sync(mf), sync(rms)
    F = np.hstack([zs(C), 0.7 * zs(M), 1.5 * zs(R)])
    return F, y, rms[0]


def novelty(F, L=16):
    Fn = unit(F)
    S = Fn @ Fn.T
    g = np.exp(-0.5 * (np.linspace(-1, 1, 2 * L) / 0.5) ** 2)
    sgn = np.sign(np.arange(2 * L) - L + 0.5)
    K = np.outer(g, g) * np.outer(sgn, sgn)
    P = np.pad(S, L, mode="edge")
    nov = np.array([np.sum(P[i:i + 2 * L, i:i + 2 * L] * K) for i in range(len(S))])
    return np.maximum(nov, 0), S


def pool(seg):
    return seg.reshape(len(seg) // POOL, POOL, -1).mean(1).reshape(-1)


def analyze(wav_path):
    ba = beatmod.analyze(wav_path)
    bt = np.array(ba["beats"])
    db = np.array(ba["downbeats"])
    d_idx = np.array([int(np.argmin(np.abs(bt - t))) for t in db])
    F, y, rms = beat_features(wav_path, bt)
    nb = len(bt)
    dur = len(y) / ASR
    nov, S = novelty(F)
    pk, _ = ss.find_peaks(nov, distance=12, prominence=0.15 * nov.max())
    bar_of_beat = lambda b: int(np.argmin(np.abs(d_idx - b)))
    bounds = sorted({bar_of_beat(int(p)) for p in pk})
    nbar = len(db)
    first_bar = 0
    intro_end = bounds[0] if bounds else 1
    if intro_end <= first_bar:
        intro_end = first_bar + 1
    body_bounds = [b for b in bounds if b > intro_end]
    outro_bar = None
    if body_bounds and db[body_bounds[-1]] > 0.85 * dur:
        outro_bar = body_bounds[-1]
        body_bounds = body_bounds[:-1]
    if outro_bar is None:
        outro_bar = nbar - 1
    while dur - db[outro_bar] < 2 * float(np.median(np.diff(db))) and outro_bar > intro_end + MIN_PLAY_BARS:
        outro_bar -= 1
    starts = [intro_end] + [b for b in body_bounds if b < outro_bar] + [outro_bar]
    sections = [{"kind": "intro", "start_bar": 0, "end_bar": intro_end, "start_s": 0.0, "end_s": round(float(db[intro_end]), 3)}]
    for a, b in zip(starts[:-1], starts[1:]):
        sections.append({"kind": "body", "start_bar": a, "end_bar": b, "start_s": round(float(db[a]), 3), "end_s": round(float(db[b]), 3)})
    sections.append({"kind": "outro", "start_bar": outro_bar, "end_bar": nbar, "start_s": round(float(db[outro_bar]), 3), "end_s": round(dur, 3)})
    frames = librosa.time_to_frames(bt, sr=ASR, hop_length=HOP)
    for s in sections:
        a = int(librosa.time_to_frames(s["start_s"], sr=ASR, hop_length=HOP))
        b = max(a + 1, int(librosa.time_to_frames(s["end_s"], sr=ASR, hop_length=HOP)))
        s["rms_logmean"] = round(float(np.mean(rms[a:b])), 3)
    W = WIN_BEATS
    post = np.full((nbar, W // POOL * F.shape[1]), np.nan)
    pre = np.full((nbar, W // POOL * F.shape[1]), np.nan)
    for k, b in enumerate(d_idx):
        if b + W <= nb:
            post[k] = pool(F[b:b + W])
        if b - W >= 0:
            pre[k] = pool(F[b - W:b])
    return {
        "bt": bt, "db": db, "d_idx": d_idx, "F": F, "y": y, "rms": rms, "dur": dur, "bpm": ba["bpm"],
        "sections": sections, "intro_bar": intro_end, "outro_bar": outro_bar, "starts": starts,
        "post": post, "pre": pre, "novelty": nov,
    }


def pair_scores(A):
    post, pre = A["post"], A["pre"]
    ok_post = ~np.isnan(post).any(1)
    ok_pre = ~np.isnan(pre).any(1)
    pu = unit(np.nan_to_num(post))
    qu = unit(np.nan_to_num(pre))
    Cp = pu @ pu.T
    Cq = qu @ qu.T
    lo, hi = A["intro_bar"], A["outro_bar"] - 1
    sec_start = set(A["starts"])
    pairs = []
    for i in range(lo + MIN_PLAY_BARS, hi + 1):
        for j in range(lo, i - MIN_PLAY_BARS + 1):
            if not (ok_post[i] and ok_post[j] and ok_pre[i] and ok_pre[j]):
                continue
            s_post, s_pre = float(Cp[i, j]), float(Cq[i, j])
            score = 0.6 * s_post + 0.4 * s_pre
            bonus = 0.0
            if j in sec_start:
                bonus += 0.03
            if (i + 1) in sec_start:
                bonus += 0.03
            pairs.append({"i": i, "j": j, "post": s_post, "pre": s_pre, "score": score, "rank": score + bonus})
    return pairs


class Planner:
    def __init__(self, A, pairs, target, trim_cap):
        self.A = A
        self.trim_cap = trim_cap
        self.db = A["db"]
        self.target = target
        self.lo = A["intro_bar"]
        self.hi = A["outro_bar"]
        self.nbody = self.hi - self.lo
        self.end = A["dur"]
        self.pairs = pairs
        self.by_start = {}
        for p in pairs:
            self.by_start.setdefault(p["j"], []).append(p)

    def play(self, segs):
        last = {}
        t = 0
        gaps_pen = 0.0
        visits = np.zeros(self.nbody)
        for a, b in segs:
            for bar in range(a, b):
                if self.lo <= bar < self.hi:
                    if bar in last:
                        gap = t - last[bar]
                        if gap < GAP_BARS:
                            gaps_pen += (GAP_BARS - gap) / GAP_BARS
                    last[bar] = t
                    visits[bar - self.lo] += 1
                t += 1
        return gaps_pen, visits

    def cost(self, segs, joins):
        gaps_pen, visits = self.play(segs)
        jc = sum(45.0 * (1.0 - p["score"]) - 20.0 * (p["rank"] - p["score"]) + 1.0 for p in joins)
        bal = float(np.std(visits)) * 3.0
        reuse = 0.0
        for n, p in enumerate(joins):
            for q in joins[:n]:
                reuse += (4.0 if (q["i"], q["j"]) == (p["i"], p["j"]) else 0.0) + (2.0 if q["i"] == p["i"] else 0.0) + (2.0 if q["j"] == p["j"] else 0.0)
        return jc + bal + 0.35 * gaps_pen + reuse

    def elapsed(self, segs):
        return sum(self.db[b] - self.db[a] if a > 0 else self.db[b] for a, b in segs)

    def search(self, width=40, per_group=4, bucket_s=5.0, seed=0):
        rng = np.random.default_rng(seed)
        P = self.pairs
        I = np.array([p["i"] for p in P])
        J = np.array([p["j"] for p in P])
        tj = self.db[J]
        ti = self.db[I]
        rank = np.array([p["rank"] for p in P]) + rng.random(len(P)) * 0.01
        grp = (I - J) // 6
        order = np.argsort(-rank)
        buckets = {}
        best = None

        def expand(joins, pos):
            nonlocal best
            segs = self._segs(joins)
            el = self.elapsed(segs)
            t0 = self.db[pos] if pos > 0 else 0.0
            valid = (I >= pos + MIN_PLAY_BARS) & (I < self.hi)
            tot = el + (ti - t0) + (self.end - tj)
            fin = valid & (tot - self.target >= -SEARCH_TOL_S) & (tot - self.target <= self.trim_cap)
            for k in np.nonzero(fin)[0]:
                nj = joins + (P[k],)
                c = self.cost(self._segs(nj) + [(P[k]["j"], self.hi)], nj) + 0.5 * abs(tot[k] - self.target)
                if best is None or c < best[0]:
                    best = (c, nj, float(tot[k]))
            ok = valid & (tot + MIN_LOOP_S <= self.target + self.trim_cap)
            count = {}
            for k in order:
                if not ok[k]:
                    continue
                g = grp[k]
                if count.get(g, 0) >= per_group:
                    continue
                count[g] = count.get(g, 0) + 1
                nj = joins + (P[k],)
                c = self.cost(self._segs(nj) + [(P[k]["j"], self.hi)], nj)
                buckets.setdefault(int(tot[k] // bucket_s), {})[tuple((q["i"], q["j"]) for q in nj)] = (c, nj, P[k]["j"])

        expand((), 0)
        while buckets:
            key = min(buckets)
            states = sorted(buckets.pop(key).values(), key=lambda v: v[0])[:width]
            for c, nj, pos in states:
                expand(nj, pos)
        return best

    def _segs(self, joins):
        segs = []
        start = 0
        for p in joins:
            segs.append((start, p["i"]))
            start = p["j"]
        return segs


def plan(A, target, trim_cap):
    pairs = pair_scores(A)
    P = Planner(A, pairs, target, trim_cap)
    best = None
    for seed, width in ((0, 40), (1, 60)):
        r = P.search(width=width, seed=seed)
        if r and (best is None or r[0] < best[0]):
            best = r
    if best is None:
        raise RuntimeError("no path hits target within tolerance; relax constraints")
    joins = list(best[1])
    segs = P._segs(joins) + [(joins[-1]["j"], None)]
    return joins, segs, pairs, P


def xf_len(A, i_bar, score, q_mid, q_hi):
    k = A["d_idx"][i_bar]
    bt = A["bt"]
    lo, hi = max(0, k - 4), min(len(bt) - 1, k + 4)
    beat = float(np.median(np.diff(bt[lo:hi + 1])))
    n = 1.0 if score >= q_hi else 1.5 if score >= q_mid else 2.0
    return beat * n


def best_lag(a, b, e, s, h):
    L = int(LAG_MS / 1000 * SR)
    n = 2 * h
    if e - h < 0 or e + h > len(a) or s - h - L < 0 or s + h + L > len(b):
        return 0
    ref = a[e - h:e + h]
    ref = ref - ref.mean()
    cand = b[s - h - L:s + h + L]
    num = ss.fftconvolve(cand, ref[::-1], mode="valid")
    c2 = np.cumsum(np.concatenate([[0.0], cand ** 2]))
    en = c2[n:] - c2[:-n]
    nc = num / (np.sqrt(en * np.sum(ref ** 2)) + 1e-9)
    return int(np.argmax(nc)) - L


def render(A, x, joins, segs, intro_keep, outro_keep, trim_head, q_mid, q_hi):
    db = A["db"]
    mono = x.mean(1)
    sr = SR
    sample = lambda t: int(round(t * sr))
    spec = []
    for n, (a, b) in enumerate(segs):
        s = 0 if a == 0 else sample(db[a])
        e = len(x) if b is None else sample(db[b])
        spec.append([s, e])
    info = []
    for n, p in enumerate(joins):
        xf = xf_len(A, p["i"], p["score"], q_mid, q_hi)
        h = int(xf * sr / 2)
        lag = best_lag(mono, mono, spec[n][1], spec[n + 1][0], h)
        spec[n + 1][0] += lag
        info.append({"h": h, "xf": xf, "lag": lag})
    parts = []
    out_t = 0
    join_out = []
    for n, (s, e) in enumerate(spec):
        h_in = info[n - 1]["h"] if n > 0 else 0
        h_out = info[n]["h"] if n < len(joins) else 0
        core = x[s + h_in:e - h_out]
        parts.append(core)
        out_t += len(core)
        if n < len(joins):
            nxt_s = spec[n + 1][0]
            hh = info[n]["h"]
            ramp = np.linspace(0, 1, 2 * hh)[:, None]
            seg = x[e - hh:e + hh] * np.cos(ramp * np.pi / 2) + x[nxt_s - hh:nxt_s + hh] * np.sin(ramp * np.pi / 2)
            join_out.append((out_t + hh) / sr)
            parts.append(seg)
            out_t += len(seg)
    y = np.concatenate(parts)
    y = y[int(round(trim_head * sr)):]
    for k in range(len(join_out)):
        join_out[k] -= trim_head
    if not intro_keep:
        f = int(0.25 * sr)
        y[:f] *= np.linspace(0, 1, f)[:, None]
    if not outro_keep:
        f = int(0.4 * sr)
        y[-f:] *= np.linspace(1, 0, f)[:, None]
    return y, join_out, info


def loudnorm_two_pass(src, dst, lufs=None, tp=None, lra=None):
    lufs = LOUDNORM["lufs"] if lufs is None else lufs
    tp = LOUDNORM["tp"] if tp is None else tp
    lra = LOUDNORM["lra"] if lra is None else lra
    tgt = f"I={lufs}:TP={tp}:LRA={lra}"
    r = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", f"loudnorm={tgt}:print_format=json", "-f", "null", "-"])
    m = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    af = (f"loudnorm={tgt}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
          f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample={SR},aformat=channel_layouts=stereo")
    sh(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", af, "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(dst)])
    return m


def measure_lufs(path):
    r = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"])
    tail = r.stderr[r.stderr.rindex("Summary:"):]
    I = float(tail.split("I:")[1].split("LUFS")[0])
    peak = float(tail.split("Peak:")[1].split("dBFS")[0])
    return I, peak


def mono22(path):
    y, _ = librosa.load(path, sr=ASR, mono=True)
    return y


def frame_feats(y):
    ch = librosa.feature.chroma_cqt(y=y, sr=ASR, hop_length=HOP)
    mf = librosa.feature.mfcc(y=y, sr=ASR, hop_length=HOP, n_mfcc=13)[1:]
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    flux = librosa.onset.onset_strength(y=y, sr=ASR, hop_length=HOP)
    n = min(ch.shape[1], mf.shape[1], len(rms), len(flux))
    return ch[:, :n], mf[:, :n], rms[:n], flux[:n]


def metrics_at(feats, t, xf, win=1.4, flux_pad=0.3):
    ch, mf, rms, flux = feats
    fps = ASR / HOP
    n = len(rms)

    def sl(a, b):
        return max(0, int(a * fps)), min(n, max(int(b * fps), int(a * fps) + 2))

    a0, a1 = sl(t - xf / 2 - win, t - xf / 2)
    b0, b1 = sl(t + xf / 2, t + xf / 2 + win)
    if a1 <= a0 + 1 or b1 <= b0 + 1:
        return None
    db = lambda a, b: 20 * np.log10(np.mean(rms[a:b]) + 1e-6)
    f0, f1 = sl(t - xf / 2, t + xf / 2 + flux_pad)
    vb = np.concatenate([np.mean(ch[:, a0:a1], 1), np.mean(mf[:, a0:a1], 1) / 20])
    va = np.concatenate([np.mean(ch[:, b0:b1], 1), np.mean(mf[:, b0:b1], 1) / 20])
    return {
        "level_step_db": float(abs(db(b0, b1) - db(a0, a1))),
        "flux_peak": float(np.max(flux[f0:f1])),
        "timbre_dist": float(np.linalg.norm(va - vb)),
    }


def validate(src_feats, A, out_feats, join_out, info):
    base = {"level_step_db": [], "flux_peak": [], "timbre_dist": []}
    for k, t in enumerate(A["db"]):
        if A["intro_bar"] <= k < A["outro_bar"]:
            xf = float(np.median(np.diff(A["bt"])))
            m = metrics_at(src_feats, float(t), xf)
            if m:
                for key in base:
                    base[key].append(m[key])
    stats = {k: {"median": float(np.median(v)), "p95": float(np.percentile(v, 95)), "mad": float(np.median(np.abs(np.array(v) - np.median(v))) * 1.4826 + 1e-9)} for k, v in base.items()}
    rows = []
    for t, inf in zip(join_out, info):
        m = metrics_at(out_feats, t, inf["xf"])
        row = {"out_s": round(t, 3)}
        flags = []
        for key, v in (m or {}).items():
            z = (v - stats[key]["median"]) / stats[key]["mad"]
            row[key] = round(v, 4)
            row[key + "_z"] = round(float(z), 2)
            if v > stats[key]["p95"]:
                flags.append(key)
        row["flags"] = flags
        row["stands_out"] = bool(flags)
        rows.append(row)
    return stats, rows


def snippets(wav, out_path, joins_rep, total):
    stem = out_path.with_suffix("")
    order = sorted(range(len(joins_rep)), key=lambda k: joins_rep[k]["score"])[:3]
    files = []
    for n, k in enumerate(order, 1):
        t = joins_rep[k]["out_s"]
        a = min(max(0.0, t - 6.0), max(0.0, total - 12.0))
        f = stem.parent / f"{stem.name}-join-{n}.m4a"
        sh(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", "12", "-i", str(wav), "-c:a", "aac", "-b:a", "192k", str(f)])
        joins_rep[k]["snippet"] = str(f)
        files.append(str(f))
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--target-s", type=float, default=None)
    ap.add_argument("--intro-keep", action="store_true")
    ap.add_argument("--outro-keep", action="store_true")
    ap.add_argument("--report", default=None)
    ap.add_argument("--guion")
    ap.add_argument("--project")
    a = ap.parse_args()
    configure(config.load_project(a.project) if a.project else None)
    if a.target_s is None:
        target, tsrc = default_target(a.guion) if a.guion else (DEFAULT_TARGET, "default")
    else:
        target, tsrc = a.target_s, "cli"
    out = pathlib.Path(a.output)
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        src = td / "src.wav"
        sh(["ffmpeg", "-v", "error", "-y", "-i", a.input, "-vn", "-ar", str(SR), "-ac", "2", "-c:a", "pcm_f32le", str(src)])
        A = analyze(str(src))
        x, _ = sf.read(src, dtype="float32", always_2d=True)
        cap = 0.4 if a.intro_keep else HEAD_TRIM_CAP
        joins, segs, pairs, P = plan(A, target, cap)
        total = float(sum(P.db[b] - P.db[s0] if s0 > 0 else P.db[b] for s0, b in segs[:-1]) + (P.end - P.db[segs[-1][0]]))
        trim_head = max(0.0, total - target) if not a.intro_keep else 0.0
        allsc = np.array([p["score"] for p in pairs])
        q_mid, q_hi = float(np.percentile(allsc, 95)), float(np.percentile(allsc, 99))
        y, join_out, info = render(A, x, joins, segs, a.intro_keep, a.outro_keep, trim_head, q_mid, q_hi)
        raw = td / "raw.wav"
        sf.write(raw, y, SR, subtype="FLOAT")
        loudnorm_two_pass(raw, out)
        lufs, peak = measure_lufs(out)
        final_dur = sf.info(str(out)).duration
        src_feats = frame_feats(A["y"])
        out_feats = frame_feats(mono22(out))
        stats, rows = validate(src_feats, A, out_feats, join_out, info)
    joins_rep = []
    for p, t, inf, row in zip(joins, join_out, info, rows):
        joins_rep.append({
            "from_s": round(float(A["db"][p["i"]]), 3), "to_s": round(float(A["db"][p["j"]]), 3), "out_s": round(t, 3),
            "from_bar": p["i"], "to_bar": p["j"],
            "score": round(p["score"], 4), "score_percentile": round(float((allsc < p["score"]).mean() * 100), 2), "sim_post_2bars": round(p["post"], 4), "sim_pre_2bars": round(p["pre"], 4),
            "crossfade_s": round(inf["xf"], 3), "align_lag_ms": round(inf["lag"] / SR * 1000, 2), "validation": row,
        })
    files = snippets(out, out, joins_rep, final_dur)
    rep = {
        "input": a.input, "output": str(out), "target_s": target, "target_source": tsrc,
        "intro_keep": a.intro_keep, "outro_keep": a.outro_keep,
        "bpm": A["bpm"], "downbeats": len(A["db"]),
        "sections": A["sections"], "joins": joins_rep, "n_joins": len(joins_rep),
        "planned_duration_s": round(total, 3), "head_trim_s": round(trim_head, 3),
        "final_duration_s": round(final_dur, 3), "duration_error_s": round(final_dur - target, 3),
        "lufs_integrated": lufs, "true_peak_dbfs": peak,
        "worst_join_score": min(j["score"] for j in joins_rep),
        "baseline_variation": stats,
        "joins_standing_out": [j["out_s"] for j in joins_rep if j["validation"].get("stands_out")],
        "snippets": files,
    }
    path = pathlib.Path(a.report) if a.report else out.with_suffix(".json")
    path.write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps({k: rep[k] for k in ("target_s", "final_duration_s", "n_joins", "worst_join_score", "lufs_integrated", "joins_standing_out")}))


if __name__ == "__main__":
    main()
