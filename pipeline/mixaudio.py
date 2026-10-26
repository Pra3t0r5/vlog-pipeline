import hashlib
import json
import math
import pathlib
import re

import ffx

SR = 48000
FMT = f"aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo"


def digest(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:10]


def find(G, f):
    p = pathlib.Path(f)
    for root in ([None] if p.is_absolute() else [G.base, G.project]):
        c = p if root is None else root / p
        if c.exists():
            return c.resolve()
    return None


def normalize(G, path, report):
    st = G.style
    key = digest([ffx.sig(path), st["music_lufs"], st["music_tp"]])
    out = G.cache / f"music-{key}.wav"
    if out.exists():
        return out
    tgt = f"I={st['music_lufs']}:TP={st['music_tp']}:LRA=11"
    with report.stage("música: loudnorm"):
        r = ffx.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", f"loudnorm={tgt}:print_format=json", "-f", "null", "-"])
        m = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
        af = f"loudnorm={tgt}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,{FMT}"
        part = out.with_suffix(".part.wav")
        ffx.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-af", af, "-c:a", "pcm_s16le", str(part)])
        part.rename(out)
        (G.cache / f"music-{key}.json").write_text(json.dumps({"file": str(path), "measured": m, "target": tgt}, indent=1))
    return out


def raw_tracks(G, report):
    last = len(G.shots) - 1
    tracks = []
    for m in G.music_entries():
        p = find(G, m["file"])
        if p is None:
            report.warn(f"música ausente: {m['file']}; se omite ese tema")
            continue
        t = {"file": p, "from": int(m.get("from_shot", 0)), "to": int(m.get("to_shot", last)), "gain": float(m.get("gain_db", 0)), "beats": m.get("beats")}
        if not 0 <= t["from"] <= t["to"] <= last:
            raise ffx.RenderError(f"music {m['file']}: from_shot/to_shot fuera de rango (0..{last})")
        tracks.append(t)
    tracks.sort(key=lambda t: t["from"])
    for a, b in zip(tracks, tracks[1:]):
        if b["from"] <= a["to"]:
            raise ffx.RenderError("music: los rangos de shots de dos temas se pisan")
    for k, t in enumerate(tracks):
        t["joined"] = k > 0 and tracks[k - 1]["to"] + 1 == t["from"]
    return tracks


def tracks_of(G, report):
    tracks = raw_tracks(G, report)
    shots, fps = G.shots, G.fps
    for t in tracks:
        t["b"] = float(shots[t["from"]].start / fps)
        t["e"] = float((shots[t["to"]].start + shots[t["to"]].n) / fps)
    return tracks


def place(G, tracks):
    xf = G.style["music_xfade"]
    for k, t in enumerate(tracks):
        t["xf"] = xf
        t["P"] = t["b"] - xf if t["joined"] else t["b"]
    for k, t in enumerate(tracks):
        nxt = tracks[k + 1] if k + 1 < len(tracks) else None
        t["Q"] = nxt["b"] if nxt and nxt["joined"] else min(t["e"], G.total)
        t["L"] = t["Q"] - t["P"]
        need = (xf if t["joined"] else 0) + (xf if nxt and nxt["joined"] else 0) + 0.2
        if t["L"] < need:
            raise ffx.RenderError(f"music {t['file'].name}: cubre {t['L']:.1f}s y con los cruces de {xf}s necesita al menos {need:.1f}s")
    return tracks


def tempo_chain(speed):
    if speed == 1:
        return ""
    if not 0.5 <= speed <= 2:
        return None
    return f",atempo={speed:.6f}"


def build(G, report):
    shots, fps, st, T = G.shots, G.fps, G.style, G.total
    clips = []
    for s in shots:
        if s.audio != "keep":
            continue
        tc = tempo_chain(s.speed)
        if tc is None:
            report.warn(f"shot {s.idx}: speed {s.speed} fuera de 0.5-2 no admite audio, se silencia")
            continue
        nxt = shots[s.idx + 1].xn if s.idx + 1 < len(shots) else 0
        fi = min(s.xn / float(fps), st["clip_fade"]) if s.xn else 0.04
        fo = min(nxt / float(fps), st["clip_fade"]) if nxt else (st["clip_fade"] if s.idx == len(shots) - 1 else 0.04)
        lufs = s.rec.get("audio_lufs")
        norm = 0.0 if lufs is None else max(min(st["clip_lufs"] - lufs, st["clip_gain_max"]), -20.0)
        clips.append({"s": s, "t": float(s.start / fps), "d": float(s.n / fps), "gain": norm + s.gain_db, "fi": fi, "fo": fo, "tc": tc})
        if lufs is None:
            report.warn(f"shot {s.idx} ({s.rec['id']}): sin audio_lufs medido, el clip entra sin normalizar")
    tracks = place(G, tracks_of(G, report))
    if not clips and not tracks:
        return silence(G, report)

    inputs, fc = [], []
    for j, c in enumerate(clips):
        s = c["s"]
        span = c["d"] * s.speed + 0.2
        inputs += ["-ss", f"{s.t_in:.6f}", "-t", f"{span:.6f}", "-i", s.rec["path"]]
        fc.append(
            f"[{j}:a]{FMT}{c['tc']},volume={c['gain']:.2f}dB,atrim=0:{c['d']:.6f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={c['fi']:.3f},afade=t=out:st={max(c['d'] - c['fo'], 0):.3f}:d={c['fo']:.3f},"
            f"adelay={round(c['t'] * SR)}S:all=1[c{j}]"
        )
    base = len(clips)
    if clips:
        inputs += ["-f", "lavfi", "-t", f"{T:.6f}", "-i", f"anullsrc=r={SR}:cl=stereo"]
        fc.append(f"[{base}:a]{FMT},anull[sil]")
        base += 1
        labels = "".join(f"[c{j}]" for j in range(len(clips)))
        fc.append(f"{labels}[sil]amix=inputs={len(clips) + 1}:normalize=0:duration=longest:dropout_transition=0[clips]")

    music_label = None
    if tracks:
        groups, cur = [], []
        for k, t in enumerate(tracks):
            wav = normalize(G, t["file"], report)
            t["wav"] = wav
            inputs += ["-stream_loop", "-1", "-i", str(wav)]
            t["in"] = base + k
            if ffx.probe(wav)["dur"] < t["L"]:
                report.warn(f"música {t['file'].name} dura {ffx.probe(wav)['dur']:.0f}s y el tramo pide {t['L']:.0f}s: se repite en bucle")
            if t["joined"]:
                cur.append(t)
            else:
                cur = [t]
                groups.append(cur)
        outs = []
        for g, grp in enumerate(groups):
            for t in grp:
                k = t["in"]
                fc.append(f"[{k}:a]{FMT},atrim=0:{t['L']:.6f},asetpts=PTS-STARTPTS,volume={t['gain']:.2f}dB[m{k}]")
            prev = f"m{grp[0]['in']}"
            for t in grp[1:]:
                nxt = f"x{t['in']}"
                fc.append(f"[{prev}][m{t['in']}]acrossfade=d={t['xf']}:c1=qsin:c2=qsin[{nxt}]")
                prev = nxt
            fc.append(f"[{prev}]afade=t=in:d={st['music_fade_in']},adelay={round(grp[0]['P'] * SR)}S:all=1,apad=whole_dur={T:.6f},atrim=0:{T:.6f}[g{g}]")
            outs.append(f"[g{g}]")
        fc.append(f"{''.join(outs)}amix=inputs={len(outs)}:normalize=0:duration=longest[music]" if len(outs) > 1 else f"{outs[0]}anull[music]")
        music_label = "music"

    fo = st["music_fade_out"]
    if music_label and clips:
        r = 4.0
        th = 10 ** ((st["clip_lufs"] + st["duck_offset_db"] + st["duck_db"] / (1 - 1 / r)) / 20)
        fc.append("[clips]asplit=2[sc][cl]")
        fc.append(f"[music][sc]sidechaincompress=threshold={th:.5f}:ratio={r}:attack=40:release=500:makeup=1[duck]")
        fc.append("[duck][cl]amix=inputs=2:normalize=0:duration=first[mix]")
    elif music_label:
        fc.append("[music]anull[mix]")
    else:
        fc.append("[clips]anull[mix]")
    fc.append(f"[mix]alimiter=limit=0.97:level=0,afade=t=out:st={T - fo:.6f}:d={fo},aresample={SR}[a]")

    fcs = ";".join(fc)
    key = digest([fcs, [i for i in inputs], [ffx.sig(c["s"].rec["path"]) for c in clips], [ffx.sig(t["wav"]) for t in tracks], G.preset["audio_bitrate"], T])
    out = G.cache / f"audio-{key}.m4a"
    if out.exists():
        report.audio_hit = True
        return out
    part = out.with_suffix(".part.m4a")
    with report.stage("audio: mezcla"):
        ffx.run(["ffmpeg", "-v", "error", "-y"] + inputs + ["-filter_complex", fcs, "-map", "[a]", "-c:a", "aac", "-b:a", G.preset["audio_bitrate"], "-ar", str(SR), "-ac", "2", "-t", f"{T:.6f}", str(part)])
        part.rename(out)
    report.audio_info = {"clips": len(clips), "tracks": len(tracks)}
    return out


def silence(G, report):
    T = G.total
    out = G.cache / f"audio-silence-{T:.3f}-{G.preset['audio_bitrate']}.m4a"
    if not out.exists():
        with report.stage("audio: mezcla"):
            ffx.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo", "-t", f"{T:.6f}", "-c:a", "aac", "-b:a", G.preset["audio_bitrate"], str(out)])
    return out
