import json
import pathlib
import re

import config
import costmode
import prompts

_TR = config.base_section("triage")
KINDS = tuple(_TR["kinds"])
MOODS = tuple(_TR["moods"])
REJECT_WHY = tuple(_TR["reject_why"])
GRID = 6
P1_DIR = "triage/pass1"
P2_DIR = "triage/pass2"
MERGED = "triage/merged.json"
P2_SHEETS = "sheets-p2"


class TriageError(Exception):
    pass


def kinds():
    return tuple(config.get("triage.kinds", KINDS))


def moods():
    return tuple(config.get("triage.moods", MOODS))


def reject_why():
    return tuple(config.get("triage.reject_why", REJECT_WHY))


def load_json(path):
    return json.loads(pathlib.Path(path).read_text())


def sheet_groups(proj, sheets_dir="sheets"):
    d = pathlib.Path(proj) / sheets_dir
    if not (d / "manifest.json").exists():
        raise TriageError(f"falta {d / 'manifest.json'}: corré `vlog sheets`")
    man = load_json(d / "manifest.json")
    if "sheets" not in man:
        man = {"sheets": {k: v for k, v in man.items() if isinstance(v, dict) and "day" in v}}
    man.setdefault("frames", 6)
    for s in man["sheets"].values():
        s.setdefault("tokens_est", s.get("tokens", 0))
    idx_raw = load_json(d / "index.json")
    idx = idx_raw.get("sheets") or {k: v for k, v in idx_raw.items() if isinstance(v, list)}
    groups = {}
    for name in sorted(man["sheets"]):
        g = groups.setdefault(man["sheets"][name]["day"], {"sheets": [], "codes": []})
        g["sheets"].append(name)
        g["codes"] += idx[name]
    return groups, man


def pass_file(proj, n, day):
    return pathlib.Path(proj) / (P1_DIR if n == 1 else P2_DIR) / f"{day}.json"


def problems_p1(rows, codes):
    probs = []
    seen = set()
    for r in rows:
        c = r.get("code")
        if c not in codes:
            probs.append(f"código ajeno {c}")
            continue
        if c in seen:
            probs.append(f"código repetido {c}")
        seen.add(c)
        if not isinstance(r.get("reject"), bool):
            probs.append(f"{c}: reject debe ser true/false")
        if r.get("kind") not in kinds():
            probs.append(f"{c}: kind '{r.get('kind')}' fuera de {kinds()}")
        if r.get("reject") and r.get("why") not in reject_why():
            probs.append(f"{c}: why '{r.get('why')}' fuera de {reject_why()}")
    missing = [c for c in codes if c not in seen]
    if missing:
        probs.append(f"faltan {len(missing)} códigos: {', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}")
    return probs


def problems_p2(rows, survivors, frames):
    probs = []
    seen = set()
    for r in rows:
        c = r.get("code")
        if c not in survivors:
            probs.append(f"código ajeno o rechazado en pasada 1: {c}")
            continue
        if c in seen:
            probs.append(f"código repetido {c}")
        seen.add(c)
        if r.get("keep") not in (0, 1, 2, 3):
            probs.append(f"{c}: keep debe ser 0-3")
        if r.get("kind") not in kinds():
            probs.append(f"{c}: kind fuera de la lista")
        if r.get("mood") not in moods():
            probs.append(f"{c}: mood fuera de la lista")
        if not isinstance(r.get("who"), list):
            probs.append(f"{c}: who debe ser lista")
        b = r.get("best")
        if b is not None and not (isinstance(b, list) and len(b) == 2 and 1 <= b[0] <= b[1] <= frames):
            probs.append(f"{c}: best debe ser null o [a,b] con 1<=a<=b<={frames}")
    missing = [c for c in survivors if c not in seen]
    if missing:
        probs.append(f"faltan {len(missing)} códigos: {', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}")
    return probs


def check_day(proj, n, day, groups, frames):
    p = pass_file(proj, n, day)
    if n == 2 and pass_file(proj, 1, day).exists() and not survivors_of(proj, day):
        return []
    if not p.exists():
        return ["no existe"]
    try:
        rows = load_json(p)
    except ValueError as e:
        return [f"JSON inválido: {e}"]
    if not isinstance(rows, list):
        return ["debe ser una lista"]
    if n == 1:
        return problems_p1(rows, groups[day]["codes"])
    return problems_p2(rows, survivors_of(proj, day), frames)


def survivors_of(proj, day):
    p = pass_file(proj, 1, day)
    return [r["code"] for r in load_json(p) if not r["reject"]] if p.exists() else []


def pass_status(proj, cfg, n):
    groups, man = sheet_groups(proj)
    frames = man["frames"]
    out = {}
    for day in groups:
        if n == 2 and not pass_file(proj, 1, day).exists():
            out[day] = ["falta la pasada 1"]
            continue
        out[day] = check_day(proj, n, day, groups, frames)
    return out


def done(proj, cfg, n):
    try:
        st = pass_status(proj, cfg, n)
    except TriageError:
        return False
    return bool(st) and all(not p for p in st.values())


def section(md, *titles):
    out = []
    for t in titles:
        m = re.search(rf"^##\s+{re.escape(t)}.*?$(.*?)(?=^##\s|\Z)", md, re.S | re.M | re.I)
        if m:
            out.append(f"## {t}\n{m.group(1).strip()}")
    return "\n\n".join(out)


def brief_excerpt(proj):
    p = pathlib.Path(proj) / "DIRECTION.md"
    return section(p.read_text(), "Qué se ve", "Prohibido") if p.exists() else "(sin DIRECTION.md)"


def day_context(proj, day):
    p = pathlib.Path(proj) / "notes" / "chronology.json"
    if not p.exists():
        return "(sin cronología)"
    for d in load_json(p).get("days", []):
        if d.get("date") == day:
            keys = ("base", "places", "milestones", "family_moments_happy", "avoid")
            return "\n".join(f"- {k}: {json.dumps(d[k], ensure_ascii=False)}" for k in keys if d.get(k))
    return "(el día no está en la cronología)"


def people(cfg):
    p = cfg.get("people") or [o.rsplit("=", 1)[-1] if isinstance(o, str) else str(o) for o in (cfg.get("ingest") or {}).get("owners", [])]
    return ", ".join(str(x).lower() for x in p) if p else "los integrantes que nombra DIRECTION.md, en minúscula"


def plan(proj, cfg, n, day=None, only_pending=True):
    proj = pathlib.Path(proj)
    sheets_dir = "sheets" if n == 1 else P2_SHEETS
    groups, man = sheet_groups(proj, sheets_dir)
    role = "triage_pass1" if n == 1 else "triage_pass2"
    model = costmode.model_for(cfg, role)
    status = pass_status(proj, cfg, n)
    tpl = prompts.template(f"triage-pass{n}")
    items = []
    for d, g in groups.items():
        if day and d != day:
            continue
        probs = status.get(d, [])
        if only_pending and not probs:
            continue
        codes = g["codes"]
        vals = {
            "project": proj, "day": d, "model": model, "frames": man["frames"], "n_items": len(codes),
            "sheet_files": "\n".join(f"- {proj / sheets_dir / s}" for s in g["sheets"]),
            "codes": ", ".join(codes), "out_file": pass_file(proj, n, d), "people": people(cfg),
            "brief_excerpt": brief_excerpt(proj), "day_context": day_context(proj, d),
            "survivors": ", ".join(codes), "kinds": ", ".join(kinds()), "moods": ", ".join(moods()), "reject_why": ", ".join(reject_why()),
        }
        tokens = sum(man["sheets"][s]["tokens_est"] for s in g["sheets"])
        items.append({"day": d, "sheets": g["sheets"], "n_items": len(codes), "tokens_est": tokens, "model": model,
                      "out_file": str(vals["out_file"]), "problems": probs, "prompt": prompts.fill(tpl, vals)})
    return items


def normalize_best(best, frames):
    if best is None:
        return None
    a, b = (max(1, min(GRID, round(((k - 0.5) / frames) * GRID + 0.5))) for k in best)
    return [min(a, b), max(a, b)]


def merge(proj, cfg):
    proj = pathlib.Path(proj)
    groups, man = sheet_groups(proj)
    frames = man["frames"]
    p2man = proj / P2_SHEETS / "manifest.json"
    frames2 = load_json(p2man)["frames"] if p2man.exists() else frames
    errs, rows = [], {}
    for day in groups:
        e1 = check_day(proj, 1, day, groups, frames)
        if e1:
            errs += [f"{day} pasada 1: {x}" for x in e1]
            continue
        for r in load_json(pass_file(proj, 1, day)):
            if r["reject"]:
                rows[r["code"]] = {"code": r["code"], "keep": 0, "kind": r["kind"], "who": [], "mood": "neutro",
                                   "desc": f"descartada en pasada 1: {r['why']}", "avoid": r["why"], "best": None, "sim": r.get("sim")}
        e2 = check_day(proj, 2, day, groups, frames2)
        if e2:
            errs += [f"{day} pasada 2: {x}" for x in e2]
            continue
        p2 = pass_file(proj, 2, day)
        for r in (load_json(p2) if p2.exists() else []):
            r = dict(r)
            r["best"] = normalize_best(r.get("best"), frames2)
            r.setdefault("avoid", None)
            r.setdefault("sim", None)
            rows[r["code"]] = r
    if errs:
        raise TriageError("\n".join(errs))
    order = [c for g in groups.values() for c in g["codes"]]
    merged = [rows[c] for c in order]
    out = proj / MERGED
    out.write_text(json.dumps(merged, indent=1, ensure_ascii=False))
    return merged
