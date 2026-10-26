import sys, json, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np, soundfile as sf
import musicmix as mm
if len(sys.argv) != 4:
    sys.exit("uso: shortmix.py entrada salida.wav duracion_en_segundos")
src_in, out, target = sys.argv[1], pathlib.Path(sys.argv[2]), float(sys.argv[3])
with tempfile.TemporaryDirectory() as td:
    td = pathlib.Path(td); src = td / "src.wav"
    mm.sh(["ffmpeg", "-v", "error", "-y", "-i", src_in, "-vn", "-ar", str(mm.SR), "-ac", "2", "-c:a", "pcm_f32le", str(src)])
    A = mm.analyze(str(src)); x, _ = sf.read(src, dtype="float32", always_2d=True)
    db, dur = A["db"], A["dur"]
    pu = mm.unit(np.nan_to_num(A["post"])); qu = mm.unit(np.nan_to_num(A["pre"]))
    okp = ~np.isnan(A["post"]).any(1); okq = ~np.isnan(A["pre"]).any(1)
    Cp, Cq = pu @ pu.T, qu @ qu.T
    cands = []
    for i in range(A["intro_bar"] + mm.MIN_PLAY_BARS, len(db)):
        for j in range(i + mm.MIN_PLAY_BARS, A["outro_bar"] + 1):
            if not (okp[i] and okp[j] and okq[i] and okq[j]): continue
            tot = db[i] + (dur - db[j]); err = tot - target
            if -mm.SEARCH_TOL_S <= err <= 3.0:
                sc = 0.6 * float(Cp[i, j]) + 0.4 * float(Cq[i, j])
                cands.append((sc - 0.05 * abs(err), sc, i, j, tot))
    allsc = [0.6 * float(Cp[i, j]) + 0.4 * float(Cq[i, j]) for i in range(len(db)) for j in range(len(db)) if j > i + 3 and okp[i] and okp[j] and okq[i] and okq[j]]
    q_mid, q_hi = float(np.percentile(allsc, 95)), float(np.percentile(allsc, 99))
    _, sc, i, j, tot = max(cands)
    p = {"i": i, "j": j, "post": float(Cp[i, j]), "pre": float(Cq[i, j]), "score": sc}
    trim = 0.0
    y, join_out, info = mm.render(A, x, [p], [(0, i), (j, None)], False, False, trim, q_mid, q_hi)
    n = int(round(target * mm.SR))
    tail_trim = max(0, len(y) - n) / mm.SR
    if len(y) > n:
        y = y[:n].copy(); f = int(1.5 * mm.SR); y[-f:] *= np.linspace(1, 0, f)[:, None]
    raw = td / "raw.wav"; sf.write(raw, y, mm.SR, subtype="FLOAT")
    mm.loudnorm_two_pass(raw, out)
    lufs, peak = mm.measure_lufs(out); fd = sf.info(str(out)).duration
rep = {"input": src_in, "output": str(out), "target_s": target, "method": "forward jump (shortener), musicmix.render", "bpm": A["bpm"],
       "join": {"from_s": round(float(db[i]), 3), "to_s": round(float(db[j]), 3), "out_s": round(join_out[0], 3), "score": round(sc, 4),
                "score_percentile": round(float((np.array(allsc) < sc).mean() * 100), 1), "crossfade_s": round(info[0]["xf"], 3)},
       "head_trim_s": round(trim, 3), "tail_trim_s": round(tail_trim, 3), "final_duration_s": round(fd, 3), "lufs_integrated": lufs, "true_peak_dbfs": peak}
out.with_suffix(".json").write_text(json.dumps(rep, indent=1, default=float)); print(json.dumps(rep, default=float))
