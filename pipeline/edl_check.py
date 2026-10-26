import json
import pathlib

import config
import pacing
import textplan

_EDL = config.base_section("edit")
TIE_Z = _EDL["tie_z"]
MIN_CAPTION_S = _EDL["min_caption_s"]
EDGE_S = _EDL["edge_s"]
MAX_DRONE_RUN = _EDL["max_drone_run"]
REAL = ("video", "photo")


def dur_of(s):
    return s["dur"] if "dur" in s else s["out"] - s["in"]


def total_of(edl, xfade=None):
    xf = edl.get("crossfade_s", config.get("edit.crossfade_s", 0.6)) if xfade is None else xfade
    acts = edl["acts"]
    return sum(dur_of(s) for a in acts for s in a["shots"]) - xf * max(0, len(acts) - 1)


def load_inputs(proj, cfg):
    proj = pathlib.Path(proj)

    def j(rel, default):
        p = proj / rel
        return json.loads(p.read_text()) if p.exists() else default

    return {
        "media": {m["id"]: m for m in j(cfg.get("media", "inv/media.json"), [])},
        "codes": j("sheets/index.json", {"codes": {}})["codes"],
        "triage": {t["code"]: t for t in j("triage/merged.json", [])},
        "sharpness": j("inv/sharpness.json", {}),
        "variants": j("inv/variants.json", []),
        "captions": j("captions.json", {}),
        "credits": j("music/credits.json", []),
    }


def check(edl, inp, cfg):
    full = config.build(cfg)
    ed = full["edit"]
    tie_z, min_caption_s, edge_s, max_run = ed["tie_z"], ed["min_caption_s"], ed["edge_s"], ed["max_drone_run"]
    credits_act = ed["credits_act"]
    errs, warns = [], []
    media, codes, triage, sharp = inp["media"], inp["codes"], inp["triage"], inp["sharpness"]
    rev = {v: k for k, v in codes.items()}
    exc = {(e.get("id"), e.get("rule")) for e in edl.get("exceptions", [])} | {(e.get("id"), None) for e in edl.get("exceptions", [])}
    group = {m["id"]: g for g in inp["variants"] for m in g["members"]}

    def err(rule, sid, msg):
        if (sid, rule) in exc:
            warns.append(f"{rule} {sid}: {msg} (excepción declarada)")
        else:
            errs.append(f"{rule} {sid}: {msg}")

    acts = edl["acts"]
    seen = set()
    flat = [s for a in acts for s in a["shots"]]
    for s in flat:
        k = s["kind"]
        if k in ("card", "map"):
            if s.get("caption"):
                err("caption-on-card", s.get("why"), "una tarjeta o un mapa no lleva caption")
            continue
        sid = s["id"]
        m = media.get(sid)
        if m is None:
            err("noid", sid, "no está en media.json")
            continue
        if sid in seen:
            err("repeated", sid, "el mismo medio aparece dos veces")
        seen.add(sid)
        if m.get("exclude_reason"):
            err("excluded", sid, m["exclude_reason"])
        code = rev.get(sid)
        if code is None:
            err("not-in-sheets", sid, "no pasó el prefiltro: no tiene código ni triage")
            continue
        t = triage.get(code, {})
        if t.get("avoid"):
            err("avoid", sid, f"{code} avoid={t['avoid']!r}")
        why = (s.get("why") or "").lower()
        if t.get("keep", 0) < 2 and not why.startswith(("relleno", "variante")):
            err("keep<2", sid, f"{code} keep={t.get('keep')}")
        sh = sharp.get(sid, {})
        if sh.get("blurry"):
            err("blurry", sid, f"{code} z={sh.get('z')}")
        if sh.get("motion_blur"):
            err("motion_blur", sid, code)
        g = group.get(sid)
        if g and g["best"] != sid:
            bc = rev.get(g["best"])
            bt = triage.get(bc, {})
            usable = bc and not bt.get("avoid") and bt.get("keep", 0) >= 1 and media[g["best"]]["kind"] == m["kind"] and not media[g["best"]].get("exclude_reason")
            dz = sharp.get(g["best"], {}).get("z", 0) - sh.get("z", 0)
            if usable and dz >= tie_z:
                err("not-sharpest", sid, f"{bc} es más nítida en {g['group']} (dz {dz:+.2f})")
        if k == "video":
            if not (s["in"] >= 0 and s["out"] > s["in"]):
                err("range", sid, f"in={s['in']} out={s['out']}")
            elif m.get("dur") and s["out"] > m["dur"] + 1e-6:
                err("range", sid, f"out {s['out']} > dur {m['dur']}")
            elif m.get("dur") and (s["in"] < edge_s or s["out"] > m["dur"] - edge_s):
                warns.append(f"edge {sid}: tramo pegado al borde del clip")
        elif not s.get("dur"):
            err("range", sid, "foto sin dur")
        c = inp["captions"].get(sid, {})
        if s.get("caption") and c.get("confidence") == "low":
            warns.append(f"caption {sid}: el dato es de confianza baja")
    entries = textplan.entries_from_edl(edl)
    named = textplan.named_in_effect(entries)
    runs = textplan.caption_runs(entries)
    for run in runs:
        span = sum(dur_of(e["ref"]) for e in run)
        if span < min_caption_s:
            err("caption-short", run[0]["ref"].get("id"), f"caption en un tramo de {span:.1f}s")
    mm_on = full["minimap"]["enabled"]
    for e in entries:
        cap = e["caption"]
        if e["kind"] not in REAL or not cap or not cap.get("place"):
            continue
        sid = e["ref"].get("id")
        if textplan.names_place(named[e["idx"]], cap["place"]):
            warns.append(f"caption-dup-title {sid}: el lugar «{cap['place']}» ya lo nombra el título o la tarjeta del acto; el render lo omite")
        elif mm_on and e["ref"].get("minimap") is not False:
            mm_place = (inp["captions"].get(sid) or {}).get("place") or (media.get(sid, {}).get("place") or "").split(",")[0]
            if textplan.norm(mm_place) == textplan.norm(cap["place"]):
                warns.append(f"caption-dup-minimap {sid}: el lugar «{cap['place']}» ya está en la etiqueta del minimapa; dejá solo la descripción (place null)")
    fade = full["caption"]["fade_s"]
    xf = edl.get("crossfade_s", full["edit"]["crossfade_s"])
    first_of_act = {id(a["shots"][0]) for a in acts if a["shots"]}
    start, prev_end, timing = 0.0, 0.0, {}
    for i, e in enumerate(entries):
        d_i = dur_of(e["ref"])
        x_i = xf if (id(e["ref"]) in first_of_act and i > 0) else 0.0
        start = prev_end - x_i if i else 0.0
        prev_end = start + d_i
        timing[e["idx"]] = (start, d_i, x_i)
    for run in runs:
        spans = []
        for e in run:
            st, d_i, x_i = timing[e["idx"]]
            nxt = timing.get(e["idx"] + 1)
            spans.append({
                "caption": e["caption"], "vis_a": st + x_i, "vis_b": st + d_i - (nxt[2] if nxt else 0.0), "anchor": st + x_i / 2,
                "title_end": st + min(3.5, d_i) + 0.5 if e["has_title"] else None,
            })
        rid = run[0]["ref"].get("id")
        plan = textplan.plan_run(spans, fade, full)
        if plan is None:
            warns.append(f"caption-no-room {rid}: el tramo no deja lugar al caption (corto, o el título ocupa el rincón); el render lo omite")
            continue
        for text in plan["skipped"]:
            warns.append(f"caption-min-time {rid}: «{text}» no alcanza {textplan.min_line_s(text, full):.1f}s en pantalla; el render la omite")
    ps = pacing.settings(cfg)
    for e in entries:
        if e["kind"] not in REAL:
            continue
        s, sid = e["ref"], e["ref"].get("id")
        keep = triage.get(rev.get(sid), {}).get("keep")
        kind = pacing.kind_of(s, media.get(sid, {}), keep)
        floor = pacing.min_for(ps, kind)
        if dur_of(s) < floor - 1e-6:
            warns.append(f"pacing-short {sid}: {dur_of(s):.1f}s por debajo de {floor:g}s ({kind}, ritmo {ps['mode']})")
    total = total_of(edl)
    if total and len(flat) / (total / 60) > ps["max_cuts_per_min"]:
        warns.append(f"pacing-cuts: {len(flat) / (total / 60):.1f} planos por minuto superan el tope de {ps['max_cuts_per_min']:g} (ritmo {ps['mode']})")
    dur = cfg.get("duration") or {}
    if dur.get("floor_min") and total < dur["floor_min"] * 60:
        errs.append(f"duration: {total:.0f}s por debajo del piso de {dur['floor_min']} min")
    if dur.get("ceil_min") and total > dur["ceil_min"] * 60:
        errs.append(f"duration: {total:.0f}s por encima del techo de {dur['ceil_min']} min")
    if edl.get("total_s") and abs(edl["total_s"] - total) > 1.0:
        warns.append(f"total_s declarado {edl['total_s']} y calculado {total:.1f}")
    cap = (cfg.get("edit") or {}).get("drone_share_max", full["edit"]["drone_share_max"])
    drone = sum(dur_of(s) for s in flat if s["kind"] in REAL and media.get(s["id"], {}).get("source") == "drone")
    if total and drone / total > cap:
        errs.append(f"drone_share: {drone / total:.2f} supera {cap}")
    run = best = 0
    for s in flat:
        run = run + 1 if s["kind"] in REAL and media.get(s.get("id"), {}).get("source") == "drone" else 0
        best = max(best, run)
    if best > max_run:
        warns.append(f"drone-run: {best} planos de dron seguidos")
    last = acts[-1] if acts else None
    credits = [s for s in (last["shots"] if last else []) if s["kind"] == "card" and s.get("role") != "title"]
    if not last or last["name"] != credits_act or not credits:
        errs.append(f"credits: el último acto debe llamarse «{credits_act}» y tener una tarjeta")
    else:
        text = " ".join((credits[-1].get("lines") or []) + [(credits[-1].get("title") or {}).get("text") or ""])
        if any(s["kind"] == "map" for s in flat) or (cfg.get("minimap") or {}).get("enabled"):
            if not all(w in text for w in full["credits"]["map_words"]):
                errs.append("credits: falta la atribución de OpenStreetMap / Natural Earth")
        if (edl.get("music_plan") or inp["credits"]) and not any(w in text for w in full["credits"]["music_words"]):
            errs.append("credits: falta el crédito de la música")
    titles = [i for i, s in enumerate(flat) if s.get("role") == "title"]
    if titles and titles[-1] != len(flat) - 2:
        errs.append("title: la tarjeta role=title debe ir justo antes de los créditos")
    return errs, warns
