import re
import unicodedata

import config

REAL = ("video", "photo")
SPLIT = re.compile(r"\s[·|\-–—]\s|[,:;]")


def norm(text):
    t = unicodedata.normalize("NFKD", str(text or "")).casefold()
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def names_of(texts):
    out = set()
    for t in texts:
        if not t:
            continue
        whole = norm(t)
        if whole:
            out.add(whole)
        for seg in SPLIT.split(str(t)):
            n = norm(seg)
            if n:
                out.add(n)
    return out


def names_place(named, place):
    n = norm(place)
    return bool(n) and n in named


def entries_from_guion(shots):
    out = []
    for s in shots:
        e = {"idx": s.idx, "kind": s.kind, "act": s.raw.get("act"), "texts": [], "caption": s.caption, "has_title": False}
        if s.kind == "card":
            e["texts"] = [(s.card or {}).get("title"), (s.card or {}).get("sub")]
        elif s.title:
            e["texts"] = [s.title.get("text"), s.title.get("sub")]
            e["has_title"] = True
        out.append(e)
    return out


def entries_from_edl(edl):
    out = []
    for a in edl["acts"]:
        for s in a["shots"]:
            t = s.get("title") or {}
            if isinstance(t, str):
                t = {"text": t}
            cap = s.get("caption")
            if cap is not None and not (cap.get("place") or cap.get("line")):
                cap = None
            out.append({"idx": len(out), "kind": s["kind"], "act": a["name"], "texts": [t.get("text"), t.get("sub")], "caption": cap, "has_title": bool(t) and s["kind"] != "card", "ref": s})
    return out


def named_in_effect(entries):
    cur, act, out = set(), object(), []
    for e in entries:
        if e["act"] != act:
            cur, act = set(), e["act"]
        if e["kind"] == "card" or e["has_title"]:
            cur = names_of(e["texts"])
        out.append(cur)
    return out


def place_key(e):
    return norm((e["caption"] or {}).get("place")) or None


def caption_runs(entries):
    runs, cur = [], []
    for e in entries:
        ok = e["kind"] in REAL and e["caption"]
        if cur and (not ok or place_key(e) != place_key(cur[-1]) or e["act"] != cur[-1]["act"] or e["has_title"] or e["idx"] != cur[-1]["idx"] + 1):
            runs.append(cur)
            cur = []
        if ok:
            cur.append(e)
    if cur:
        runs.append(cur)
    return runs


def min_line_s(text, cfg=None):
    return config.get("caption.min_line_s", 1.5, cfg) + config.get("caption.line_s_per_word", 0.3, cfg) * len(str(text).split())


def plan_descriptions(slots, a, b, d, cfg=None):
    persist = config.get("caption.on_short_shot", "persist", cfg) != "skip"
    segs, skipped, cur = [], [], None
    last = len(slots) - 1
    for k, (t, text) in enumerate(slots):
        t = a if k == 0 else max(a, t - d / 2)
        slot_end = slots[k + 1][0] - d / 2 if k < last else b - d
        if (cur is not None and cur["text"] == text) or (cur is None and text is None):
            continue
        t_apply = t if cur is None else max(t, cur["start"] + min_line_s(cur["text"], cfg))
        if t_apply >= slot_end:
            if text is not None:
                skipped.append(text)
            continue
        if text is not None:
            need = min_line_s(text, cfg)
            if b - d - t_apply < need or (not persist and k < last and slot_end - t_apply < need):
                skipped.append(text)
                continue
        if cur is not None:
            cur["end"] = t_apply + d
            segs.append(cur)
        cur = {"text": text, "start": t_apply} if text is not None else None
    if cur is not None:
        cur["end"] = b
        segs.append(cur)
    return segs, skipped


def run_geometry(spans, d, cfg=None):
    first, last = spans[0], spans[-1]
    a = first["vis_a"] + config.get("caption.fade_in_after", 0.5, cfg)
    if first.get("title_end") is not None:
        a = max(a, first["title_end"] + 0.1)
    b = last["vis_b"]
    if b - a < 1.5 * d + 0.5 or b - first["vis_a"] < config.get("caption.min_shot_s", 2.5, cfg):
        return None
    return a, b


def plan_run(spans, d, cfg=None):
    geo = run_geometry(spans, d, cfg)
    if geo is None:
        return None
    a, b = geo
    slots = [(s["anchor"], (s["caption"] or {}).get("line") or None) for s in spans]
    segs, skipped = plan_descriptions(slots, a, b, d, cfg)
    return {"a": a, "b": b, "segments": segs, "skipped": skipped}
