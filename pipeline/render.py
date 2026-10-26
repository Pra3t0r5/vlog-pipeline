import datetime
import hashlib
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import beatsnap
import config
import ffx
import grade
import guion
import minimap
import mixaudio
import overlay
import presets
import stills

REV = "r5"
PART_REV = "p2"
OVERLAY_YUV = "scale=out_color_matrix=bt709:out_range=tv:flags=bicubic,format=yuva420p"
STYLE_KEYS = ("font", "bg_sigma", "bg_dim", "card_dim", "card_color", "aspect_tol", "zoom_amt", "focus_zoom", "pan_zoom")


def h(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:10]


def credit_lines(G):
    p = G.project / "music" / "credits.json"
    if not p.exists():
        return []
    used = {pathlib.Path(m["file"]).name for m in G.music_entries()}
    out = []
    for e in json.loads(p.read_text()):
        f = e.get("file")
        if not f or (used and pathlib.Path(f).name not in used):
            continue
        if e.get("credit"):
            out.append(e["credit"])
        elif e.get("title"):
            out.append(f"{e['title']}" + (f" · {e['artist']}" if e.get("artist") else "") + (f" · {e['source']}" if e.get("source") else ""))
    return out


def card_lines(G, card):
    lines = list(card.get("lines", []))
    if card.get("music_credits"):
        lines += credit_lines(G)
    return lines


def card_bg_image(G, card, report):
    bg = card.get("bg") or {}
    if "id" not in bg:
        return None, None
    rec = G.lookup(bg["id"])
    if rec["kind"] == "photo":
        return stills.load(rec["path"]), ffx.sig(rec["path"])
    src = G.proxy_for(rec) if G.mode == "preview" else None
    src = src or rec["path"]
    at = float(bg.get("at", 1.0))
    png = G.cache / f"bgframe-{h([src, at])}.png"
    if not png.exists():
        ffx.run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", src, "-frames:v", "1", str(png)])
    return stills.load(png), ffx.sig(src) + [at]


def aux_json(G, rel):
    key = "aux:" + rel
    if key not in G.__dict__:
        p = G.project / rel
        G.__dict__[key] = json.loads(p.read_text()) if p.exists() else {}
    return G.__dict__[key]


def minimap_plan(G, s, report):
    if s.minimap is None:
        return None
    cfg = minimap.cfg_with(G.minimap, s.minimap)
    if not cfg["enabled"]:
        return None
    rec = s.rec
    if rec.get("lat") is None or rec.get("lon") is None or not rec.get("time_art"):
        report.warn(f"shot {s.idx} ({s.label}): sin GPS u hora, no lleva minimapa")
        return None
    route = G.project / "route" / "route.json"
    filled = route.with_name("route_filled.json")
    if not route.exists() and not filled.exists():
        report.warn("minimapa activo pero no existe route/route.json")
        return None
    t = datetime.datetime.fromisoformat(rec["time_art"]) + datetime.timedelta(seconds=s.t_in if s.kind == "video" else 0)
    labels = aux_json(G, "route/labels.json")
    captions = aux_json(G, "captions.json")
    place = (s.minimap or {}).get("place")
    if not place:
        if captions.get(rec["id"], {}).get("place") or labels:
            place = minimap.place_for(rec["id"], rec, captions, labels)
        else:
            place = (rec.get("place") or "").split(",")[0]
    if not place:
        return None
    tstr = t.isoformat()
    src = filled if filled.exists() else route
    key = h([minimap.REV, G.W, G.H, G.fmt, minimap.cache_sig(cfg), rec["lat"], rec["lon"], tstr, place, ffx.sig(src)])
    return {"key": key, "t": tstr, "place": place, "cfg": cfg}


def minimap_runs(G, plans):
    runs, cur = [], []
    for i, mm in enumerate(plans):
        if mm is None:
            if cur:
                runs.append(cur)
            cur = []
            continue
        if cur and mm["cfg"]["break_on_act"] and G.shots[i].raw.get("act") != G.shots[cur[-1]].raw.get("act"):
            runs.append(cur)
            cur = []
        cur.append(i)
    if cur:
        runs.append(cur)
    return runs


def minimap_intervals(G, report):
    shots, fps = G.shots, G.fps
    plans = [None if s.kind in ("card", "map") else minimap_plan(G, s, report) for s in shots]
    fade_n = max(1, round(overlay.mm_fade_s() * float(fps)))
    tail = G.total_frames - round(G.style["fade_out"] * float(fps))
    out = []
    for run in minimap_runs(G, plans):
        for j, i in enumerate(run):
            s = shots[i]
            first, last = j == 0, j == len(run) - 1
            f0 = s.start + s.xn if first else s.start + s.xn // 2
            if not last:
                f1 = shots[i + 1].start + shots[i + 1].xn // 2
            else:
                f1 = shots[i + 1].start if i + 1 < len(shots) else tail
            n = f1 - f0
            if n < 2:
                continue
            fin = min(fade_n, n // 2 if last else n) if first else 0
            fout = min(fade_n, n // 2 if first else n) if last else 0
            out.append({"idx": i, "f0": f0, "f1": f1, "fin": fin, "fout": fout, "mm": plans[i], "key": plans[i]["key"]})
    return out


def minimap_pngs(G, intervals, report):
    labels = aux_json(G, "route/labels.json")
    for iv in intervals:
        s, mm = G.shots[iv["idx"]], iv["mm"]
        png = G.cache / f"minimap-{mm['key']}.png"
        with report.stage("minimapas"):
            iv["x"], iv["y"] = minimap.render_minimap_png(mm["t"], s.rec["lat"], s.rec["lon"], mm["place"], (G.W, G.H), mm["cfg"], G.project / "route" / "route.json", labels, png, G.fmt)
        iv["png"] = png
    return intervals


def title_end(s, dur):
    if not s.title:
        return None
    return s.title.get("dur", min(3.5, dur)) + 0.5


def overlay_plan(G, s, report):
    if s.kind in ("card", "map"):
        return {}
    plan = {}
    if s.caption:
        fps = float(G.fps)
        nxt = G.shots[s.idx + 1].xn if s.idx + 1 < len(G.shots) else 0
        w = overlay.caption_window(s, nxt, fps, title_end(s, s.n / fps))
        if w:
            plan["cap"] = {**w, "cap": s.caption, "d": overlay.fade_s(), "key": h([overlay.params(G.caption_cfg, G.fmt, (G.W, G.H)), G.W, G.H, G.style["font"], s.caption])}
        else:
            report.warn(f"shot {s.idx} ({s.label}): caption omitido (el shot es corto o el título ocupa el lugar)")
    return plan


def spec_of(G, s, src, report, plan=None):
    sp = {"rev": REV, "W": G.W, "H": G.H, "fps": G.fps_s, "kind": s.kind, "n": s.n, "codec": G.preset["codec"], "br": G.preset["seg_bitrate"], "style": {k: G.style[k] for k in STYLE_KEYS}, "title": s.title}
    if s.kind in ("video", "map"):
        sp.update(src=ffx.sig(src), t_in=s.t_in, speed=s.speed, fit=s.fit, dims=[s.w, s.h])
        if s.focus_x != 0.5:
            sp["focus_x"] = s.focus_x
    elif s.kind == "photo":
        sp.update(src=ffx.sig(src), fit=s.fit, zoom=s.zoom, focus=s.focus, dir=s.direction, dims=[s.w, s.h])
        if s.focus_x != 0.5:
            sp["focus_x"] = s.focus_x
    else:
        sp.update(card=s.card, lines=card_lines(G, s.card))
    if s.gplan:
        sp["grade"] = grade.spec(s.gplan, s.kind)
    if plan:
        sp["ov"] = {k: {kk: vv for kk, vv in v.items() if kk not in ("cfg", "place", "t", "cap")} for k, v in plan.items()}
    return sp


def is_hevc(codec):
    return "hevc" in codec or codec == "libx265"


def enc_args(G):
    p = G.preset
    a = ["-c:v", p["codec"], "-b:v", p["seg_bitrate"], "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    return a + (["-tag:v", "hvc1"] if is_hevc(p["codec"]) else [])


def overlay_chain(G, base_fc, items, dur, k0=1):
    if not items:
        return [], base_fc, "[v]"
    inputs, fc, cur = [], base_fc, "v"
    for j, it in enumerate(items):
        k = k0 + j
        inputs += ["-framerate", G.fps_s, "-loop", "1", "-t", f"{dur:.6f}", "-i", str(it["png"])]
        fades = "".join(f",fade={kind}:st={st:.3f}:d={d:.3f}:alpha=1" for kind, st, d in it["fades"])
        nxt = "o" if j == len(items) - 1 else f"v{j}"
        fc += f";[{k}:v]format=rgba{fades},{OVERLAY_YUV}[ov{j}];[{cur}][ov{j}]overlay={it['x']}:{it['y']}:shortest=1[{nxt}]"
        cur = nxt
    return inputs, fc, "[o]"


def overlay_items(G, s, plan, key, dur, report):
    items = []
    if s.title and s.kind != "card":
        t = s.title
        png = G.cache / f"title-{key}.png"
        stills.title_png(t, G.W, G.H, G.style, png)
        td = t.get("dur", min(3.5, dur))
        items.append({"png": png, "x": 0, "y": 0, "fades": [("in", 0.3, 0.5), ("out", td, 0.5)]})
    cp = plan.get("cap")
    if cp:
        png = G.cache / f"caption-{cp['key']}.png"
        with report.stage("captions"):
            x, y = overlay.caption_png(cp["cap"], G.W, G.H, G.style, png, G.caption_cfg, G.fmt)
        items.append({"png": png, "x": x, "y": y, "fades": [("in", cp["in"], cp["d"]), ("out", cp["out"], cp["d"])]})
    return items


def build_clip(G, s, src, out, key):
    W, H = G.W, G.H
    gp = grade.pieces(s.gplan, True)
    chain = grade.join(gp["dn"], f"setpts=(PTS-STARTPTS)/{s.speed}", f"fps={G.fps_s}:round=near", "tpad=stop=4:stop_mode=clone")
    fin = grade.join("setsar=1", gp["grade"], "format=yuv420p", gp["sharp"])
    if s.fit != "fill" and not stills.is_wide(s.w, s.h, W, H, G.style["aspect_tol"]):
        dim, sig = G.style["bg_dim"], G.style["bg_sigma"]
        fc = (
            f"[0:v]{chain},split=2[a][b];"
            f"[a]scale={stills.BG[0]}:{stills.BG[1]}:force_original_aspect_ratio=increase,crop={stills.BG[0]}:{stills.BG[1]},gblur=sigma={sig},"
            f"lutyuv=y=16+(val-16)*{dim}:u=128+(val-128)*0.9:v=128+(val-128)*0.9,scale={W}:{H}:flags=bicubic[bg];"
            f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos[fg];"
            f"[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2:eval=init,{fin}[v]"
        )
    else:
        cx = "" if s.focus_x == 0.5 else f":x='min(max({s.focus_x}*iw-{W}/2,0),iw-{W})':y='(ih-{H})/2'"
        fc = f"[0:v]{chain},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}{cx},{fin}[v]"
    span = s.n / G.fps * s.speed + 0.5
    pre = ffx.hwaccel_args() if s.kind == "video" else []
    inputs = pre + ["-ss", f"{s.t_in:.6f}", "-t", f"{span:.6f}", "-i", src]
    return inputs, fc


def build_still(G, s, png, fc_tail, key):
    return ["-framerate", G.fps_s, "-loop", "1", "-t", f"{s.n / G.fps:.6f}", "-i", str(png)], f"[0:v]{fc_tail}[v]"


def segment(G, s, report):
    src = G.source_of(s, report) if s.kind in ("video", "photo") else s.src
    s.gplan = grade.plan(G, s, report)
    plan = overlay_plan(G, s, report)
    sp = spec_of(G, s, src, report, plan)
    key = h(sp)
    out = G.cache / f"{s.label}-{key}.mp4"
    if out.exists():
        report.hits += 1
        return out
    report.builds += 1
    W, H = G.W, G.H
    tail = f"fps={G.fps_s}:round=near,setsar=1,{stills.RGB_TO_YUV709},format=yuv420p"
    if s.kind in ("video", "map"):
        with report.stage("segmentos video"):
            inputs, fc = build_clip(G, s, src, out, key)
    elif s.kind == "photo":
        with report.stage("canvas fotos"):
            cw = min(2 * W, 3840)
            ch = round(cw * H / W / 2) * 2
            png = G.cache / f"canvas-{h([sp['src'], cw, ch, sp['fit'], sp['style']] + ([s.focus_x] if s.focus_x != 0.5 else []))}.png"
            if not png.exists():
                stills.compose(stills.load(src), cw, ch, G.style, s.fit, s.focus_x).save(png, compress_level=1)
            rect = stills.rect_for(s.w, s.h, cw, ch, G.style, s.fit)
        zoom = "" if s.zoom == "none" else stills.zoom_filter(s.n, s.zoom, G.style, s.focus, s.direction, rect) + ","
        gp = grade.pieces(s.gplan, False)
        fc_tail = f"{zoom}scale={W}:{H}:flags=area," + grade.join(gp["grade"] or stills.RGB_TO_YUV709, f"fps={G.fps_s}:round=near", "setsar=1", "format=yuv420p", gp["sharp"])
        inputs, fc = build_still(G, s, png, fc_tail, key)
    else:
        with report.stage("tarjetas"):
            bg_im, _ = card_bg_image(G, s.card, report)
            png = G.cache / f"card-{key}.png"
            stills.card_png(s.card, W, H, G.style, bg_im, card_lines(G, s.card), png)
        inputs, fc = build_still(G, s, png, tail, key)
    items = overlay_items(G, s, plan, key, s.n / G.fps, report)
    t_inputs, fc, out_label = overlay_chain(G, fc, items, float(s.n / G.fps))
    inputs = inputs + t_inputs
    part = out.with_suffix(".part.mp4")
    with report.stage("segmentos video" if s.kind in ("video", "map") else "segmentos imagen"):
        ffx.run(["ffmpeg", "-v", "error", "-y"] + inputs + ["-filter_complex", fc, "-map", out_label, "-an", "-frames:v", str(s.n)] + enc_args(G) + [str(part)])
        got = ffx.count_frames(part)
        if got != s.n:
            part.unlink()
            raise ffx.RenderError(f"shot {s.idx} ({s.label}): salieron {got} frames y se esperaban {s.n}")
        part.rename(out)
    return out


def plan_parts(G, k):
    shots = G.shots
    cuts = [0] + [shots[g].start + shots[g].xn for g in range(k, len(shots), k)] + [G.total_frames]
    parts = []
    for a, b in zip(cuts, cuts[1:]):
        members = []
        for s in shots:
            if s.start < b and s.start + s.n > a:
                ta = max(a - s.start, 0)
                tb = min(b - s.start + 1, s.n)
                members.append((s, ta, tb))
        parts.append((a, b, members))
    return parts


def part_overlays(a, b, intervals):
    out = []
    for iv in intervals:
        g0, g1 = max(iv["f0"], a), min(iv["f1"], b)
        if g1 > g0:
            out.append({**iv, "g0": g0, "g1": g1})
    return out


def minimap_chain(G, a, prev, ovs, k0=0):
    num, den = G.fps.numerator, G.fps.denominator
    inputs, fc = [], []
    for j, iv in enumerate(ovs):
        n = iv["f1"] - iv["f0"]
        inputs += ["-framerate", G.fps_s, "-loop", "1", "-t", f"{(n + 1) / float(G.fps):.6f}", "-i", str(iv["png"])]
        fades = ""
        if iv["fin"]:
            fades += f",fade=in:start_frame=0:nb_frames={iv['fin']}:alpha=1"
        if iv["fout"]:
            fades += f",fade=out:start_frame={n - iv['fout']}:nb_frames={iv['fout']}:alpha=1"
        cur = f"mm{j}"
        fc.append(f"[{k0 + j}:v]format=rgba{fades},{OVERLAY_YUV},trim=start_frame={iv['g0'] - iv['f0']}:end_frame={iv['g1'] - iv['f0']},settb=1/{num},setpts=(N+{iv['g0'] - a})*{den}[ov{j}]")
        fc.append(f"[{prev}][ov{j}]overlay={iv['x']}:{iv['y']}:eof_action=pass[{cur}]")
        prev = cur
    return inputs, fc, prev


def part_graph(G, a, b, members, segs, ovs=()):
    fps = G.fps
    tb = f"settb=1/{fps.numerator},setpts=N*{fps.denominator}"
    fc = []
    for j, (s, ta, tbk) in enumerate(members):
        fc.append(f"movie='{segs[s.idx]}',trim=start_frame={ta}:end_frame={tbk},{tb}[s{j}]")
    prev, acc = "s0", members[0][2] - members[0][1]
    for j in range(1, len(members)):
        s, ta, tbk = members[j]
        cur = f"x{j}"
        if s.xn and ta == 0:
            fc.append(f"[{prev}][s{j}]xfade=transition=fade:duration={float(s.xn / fps):.9f}:offset={float((acc - s.xn) / fps):.9f}[{cur}]")
            acc += (tbk - ta) - s.xn
        else:
            fc.append(f"[{prev}][s{j}]concat=n=2:v=1:a=0,{tb}[{cur}]")
            acc += tbk - ta
        prev = cur
    inputs, extra, prev = minimap_chain(G, a, prev, ovs)
    fc += extra
    tail = [f"format=yuv420p"]
    if a == 0:
        tail.insert(0, f"fade=in:d={G.style['fade_in']}")
    if b == G.total_frames:
        fo = G.style["fade_out"]
        tail.insert(0, f"fade=out:st={float((G.total_frames - a) / fps) - fo:.6f}:d={fo}")
    fc.append(f"[{prev}]{','.join(tail)}[v]")
    return ";".join(fc), inputs


def video_enc(G):
    p = G.preset
    enc = ["-c:v", p["codec"], "-b:v", p["bitrate"], "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    return enc + (["-tag:v", "hvc1"] if is_hevc(p["codec"]) else [])


def assemble(G, segs, audio, report):
    spp = config.get("render.shots_per_part", {"default": 4}, cfg=G.cfg)
    k = int(G.raw.get("output", {}).get("shots_per_part", spp.get(G.mode, spp.get("default", 4))))
    plan = plan_parts(G, k)
    intervals = minimap_pngs(G, minimap_intervals(G, report), report)
    files = []
    for a, b, members in plan:
        ovs = part_overlays(a, b, intervals)
        fc, mm_inputs = part_graph(G, a, b, members, segs, ovs)
        key = h([fc, mm_inputs, [(o["key"], o["x"], o["y"]) for o in ovs], [m[0].idx for m in members], G.total_frames, G.preset, G.style["fade_in"], G.style["fade_out"], REV, PART_REV])
        out = G.cache / f"part-{G.mode}-{key}.mp4"
        files.append(out)
        if out.exists():
            report.part_hits += 1
            continue
        tmp = out.with_suffix(".part.mp4")
        with report.stage("ensamble y codificación"):
            ffx.run(["ffmpeg", "-v", "error", "-y"] + mm_inputs + ["-filter_complex", fc, "-map", "[v]", "-frames:v", str(b - a), "-r", G.fps_s] + video_enc(G) + [str(tmp)])
            got = ffx.count_frames(tmp)
            if got != b - a:
                tmp.unlink()
                raise ffx.RenderError(f"la parte {a}-{b} salió con {got} frames y se esperaban {b - a}")
            tmp.rename(out)
    listing = G.cache / f"parts-{G.mode}.txt"
    listing.write_text("".join(f"file '{f}'\n" for f in files))
    out = G.out_dir / f"{G.name}-{G.label}.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing)]
    maps = ["-map", "0:v"]
    if audio:
        cmd += ["-i", str(audio)]
        maps += ["-map", "1:a"]
    with report.stage("mux"):
        ffx.run(cmd + maps + ["-c", "copy", "-t", f"{G.total:.6f}", "-movflags", "+faststart", str(out)])
    return out


def render_one(path, mode, report):
    G = guion.Guion(path, mode)
    with report.stage("resolver guion"):
        G.resolve(report)
    if G.raw.get("snap_to_beats"):
        beatsnap.apply(G, report)
    segs = [segment(G, s, report) for s in G.shots]
    audio = mixaudio.build(G, report)
    out = assemble(G, segs, audio, report)
    return G, out


def main(argv):
    if len(argv) < 2 or argv[1] not in presets.ALL:
        sys.exit("uso: render.py guion.json " + "|".join(presets.ALL))
    report = ffx.Report()
    mode = argv[1]
    try:
        G, out = render_one(argv[0], mode, report)
        presets.fit_size(G, out, report)
    except (ffx.RenderError, config.ConfigError) as e:
        sys.exit(f"render: {e}")
    print_report(G, out, report)


def print_report(G, out, report):
    kinds = {}
    for s in G.shots:
        kinds[s.kind] = kinds.get(s.kind, 0) + 1
    detail = ", ".join(f"{k} {v}" for k, v in kinds.items())
    print(f"{out}")
    print(f"duración {G.total:.1f}s · {len(G.shots)} shots ({detail}) · {G.W}x{G.H} {G.fps_s} {G.preset['codec']}")
    print(f"caché: segmentos {report.hits} hit / {report.builds} build · partes {report.part_hits} hit · audio {'hit' if report.audio_hit else 'build'}")
    print("etapas: " + " · ".join(f"{k} {v:.1f}s" for k, v in report.stages.items()) + f" · total {time.time() - report.t0:.1f}s")
    if report.snap:
        sn = report.snap
        print(f"beat snap: {sn['shots']} shots ajustados · desvío medio {sn['mean_shift'] * 1000:.0f} ms · {sn['clamped']} sin frames suficientes")
    for w in report.warnings:
        print(f"aviso: {w}")


if __name__ == "__main__":
    main(sys.argv[1:])
