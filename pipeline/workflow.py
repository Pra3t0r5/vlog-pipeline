import datetime as D
import json
import pathlib
import re

import config
import costmode
import prefilter
import sources
import triage

APPROVALS = "approvals.json"
STATUS_FILE = "STATUS.md"


def nonempty_dir(p):
    return p.is_dir() and any(p.iterdir())


def direction_filled(proj, cfg):
    p = proj / "DIRECTION.md"
    return p.exists() and not re.search(r"^\s*\d+\.\s*$", p.read_text(), re.M)


def approvals(proj):
    p = proj / APPROVALS
    return json.loads(p.read_text()) if p.exists() else {}


def approve(proj, gate):
    a = approvals(proj)
    a[gate] = D.datetime.now().astimezone().isoformat(timespec="seconds")
    (proj / APPROVALS).write_text(json.dumps(a, indent=1))
    return a


def output_done(proj, cfg, preset):
    name = cfg.get("name")
    files = [proj / f"{name}-{preset}.mp4"]
    if preset == "tv":
        files.append(proj / f"{name}-final.mp4")
    return any(f.exists() for f in files)


def stage_defs(proj, cfg):
    p = costmode.profile(cfg)
    m = p["models"]
    tk = config.get("workflow.stage_tokens", cfg=config.build(cfg))
    guion = proj / cfg.get("guion", "guion.json")
    edl = proj / cfg.get("edl", "edl.json")
    ap = approvals(proj)
    music_cmd = {"search": "subagente de música acotado (docs/DIRECTOR.md, paso 12)", "user_or_list": "el dueño trae el tema o se elige de config/music_default.json"}[p["music"]]
    S = [
        ("brief", "Brief y DIRECTION.md", "director", "preguntar al dueño y completar DIRECTION.md", tk["brief"], lambda: direction_filled(proj, cfg), False),
        ("rutas", "Ruta del teléfono", "cli", "vlog rutas --from AAAA-MM-DD --to AAAA-MM-DD", tk["rutas"], lambda: (proj / "route" / "route.json").exists(), False),
        ("album", "Álbum de Google Photos", "cli", "vlog album <zip>", tk["album"], lambda: sources.album_dir(proj, cfg) is not None, False),
        ("ingest", "Inventario y fuentes", "cli", "vlog ingest && vlog sources build", tk["ingest"], lambda: (proj / "inv" / "media.json").exists(), False),
        ("proxies", "Proxies", "cli", "vlog proxies", tk["proxies"], lambda: nonempty_dir(proj / cfg.get("proxy_dir", "proxy")), False),
        ("chronology", "Cronología de las notas", "subagente", f"vlog prompt chronology -> subagente {m['chronology']}", tk["chronology"], lambda: (proj / "notes" / "chronology.json").exists(), False),
        ("prefilter", "Prefiltro sin LLM", "cli", "vlog prefilter", tk["prefilter"], lambda: prefilter.load(proj) is not None, False),
        ("sheets", "Hojas de contacto", "cli", "vlog sheets", tk["sheets"], lambda: (proj / "sheets" / "manifest.json").exists(), False),
        ("triage1", "Triage pasada 1", "subagente", f"vlog triage-plan --pass 1  (subagentes {m['triage_pass1']})", tk["triage1"], lambda: triage.done(proj, cfg, 1), False),
        ("triage2", "Triage pasada 2", "subagente", f"vlog sheets --survivors && vlog triage-plan --pass 2  (subagentes {m['triage_pass2']})", tk["triage2"], lambda: triage.done(proj, cfg, 2), False),
        ("sharpness", "Fusión del triage y nitidez", "cli", "vlog triage-merge && vlog sharpness", tk["sharpness"], lambda: (proj / "inv" / "variants.json").exists() and (proj / triage.MERGED).exists(), False),
        ("editor", f"Editor (EDL, hasta {p['editor_rounds']} ronda/s)", "subagente", f"vlog prompt editor -> subagente {m['editor']}; validar con vlog edl-check", tk["editor"], lambda: edl.exists(), False),
        ("captions", "Captions y lugares", "subagente", f"vlog prompt captions -> subagente {m['captions']}", tk["captions"], lambda: (proj / "captions.json").exists(), False),
        ("music", "Música y créditos", "director", music_cmd, tk["music"], lambda: (proj / "music" / "credits.json").exists(), False),
        ("guion", "Guion desde la EDL", "cli", "python -I pipeline/edl2guion.py <proyecto> --edl edl.json --out guion.json", tk["guion"], lambda: guion.exists(), False),
        ("preview", f"Preview ({p['preview_iterations']} iteración/es)", "cli", "vlog preview", tk["preview"], lambda: (proj / f"{cfg.get('name')}-preview.mp4").exists(), False),
        ("preview_ok", "OK del dueño al preview", "dueño", "mostrar el preview y, con su OK, `vlog approve preview`", tk["preview_ok"], lambda: "preview" in ap, False),
        ("final", "Final y salidas", "cli", "vlog final && vlog render", tk["final"], lambda: output_done(proj, cfg, "tv"), False),
        ("reel", "Reel vertical", "subagente", f"vlog prompt reel -> subagente {m['reel']}; luego vlog render reel", tk["reel"], lambda: output_done(proj, cfg, "reel"), not costmode.reel_wanted(cfg)),
    ]
    mode = p["mode"]
    return [{"id": i, "label": l, "who": w, "how": h, "tokens": t[mode], "done": bool(f()), "optional": o} for i, l, w, h, t, f, o in S]


def cost_table_md():
    dummy = pathlib.Path("/nonexistent-vlog-project")
    std = stage_defs(dummy, {"name": "x", "cost_mode": "standard"})
    low = stage_defs(dummy, {"name": "x", "cost_mode": "low"})
    rows = ["| Etapa | Quién | standard | low |", "|---|---|---|---|"]
    for a, b in zip(std, low):
        opt = " (opcional en low)" if b["optional"] else ""
        rows.append(f"| {a['label'].split(' (')[0]}{opt} | {a['who']} | {k(a['tokens'])} | {k(b['tokens'])} |")
    tot = lambda st: sum(s["tokens"] for s in st if not s["optional"])
    rows.append(f"| **Total** | | **{k(tot(std))}** | **{k(tot(low))}** |")
    return "\n".join(rows)


def windows(stages, budget):
    pending = [s for s in stages if not s["done"] and not s["optional"]]
    if not budget:
        return [pending] if pending else []
    out, cur, used = [], [], 0
    for s in pending:
        if cur and used + s["tokens"] > budget:
            out.append(cur)
            cur, used = [], 0
        cur.append(s)
        used += s["tokens"]
    if cur:
        out.append(cur)
    return out


def compute(proj, cfg):
    p = costmode.profile(cfg)
    stages = stage_defs(proj, cfg)
    pending = [s for s in stages if not s["done"] and not s["optional"]]
    return {
        "mode": p["mode"], "profile": p, "stages": stages,
        "next": pending[0] if pending else None,
        "remaining_tokens": sum(s["tokens"] for s in pending),
        "windows": windows(stages, p["window_budget"]),
    }


def k(n):
    return f"{n / 1000:.0f} k" if n else "0"


def pending_detail(proj, cfg, st):
    nxt = st["next"]
    if not nxt or nxt["id"] not in ("triage1", "triage2"):
        return []
    n = 1 if nxt["id"] == "triage1" else 2
    try:
        status = triage.pass_status(proj, cfg, n)
    except triage.TriageError:
        return []
    todo = [d for d, pr in status.items() if pr]
    return [f"pasada {n}: faltan {len(todo)} de {len(status)} grupos: {', '.join(todo)}"] if todo else []


def format_text(proj, cfg, st):
    lines = [f"Modo: {st['mode']}"]
    for s in st["stages"]:
        mark = "x" if s["done"] else (" " if not s["optional"] else "-")
        lines.append(f"[{mark}] {s['label']:40} {s['who']:10} {k(s['tokens']):>7}{'  (opcional)' if s['optional'] else ''}")
    nxt = st["next"]
    if nxt:
        lines.append(f"Siguiente: {nxt['label']} -> {nxt['how']}")
        lines += pending_detail(proj, cfg, st)
        lines.append(f"Tokens restantes estimados: {k(st['remaining_tokens'])}")
        if st["profile"]["window_budget"]:
            for i, w in enumerate(st["windows"], 1):
                lines.append(f"  ventana {i}: {', '.join(s['id'] for s in w)} (~{k(sum(s['tokens'] for s in w))})")
    else:
        lines.append("Todo listo.")
    return "\n".join(lines)


def format_md(proj, cfg, st):
    now = D.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    L = [f"# Estado de «{cfg.get('name')}»", "", f"Generado {now}. Modo de costo: **{st['mode']}**. Para retomar en una sesión nueva: leer `docs/DIRECTOR.md` del repo, `DIRECTION.md` y este archivo; después correr `vlog status`.", "",
         "| | Etapa | Quién | Tokens est. |", "|---|---|---|---|"]
    for s in st["stages"]:
        mark = "hecho" if s["done"] else ("opcional" if s["optional"] else "pendiente")
        L.append(f"| {mark} | {s['label']} | {s['who']} | {k(s['tokens'])} |")
    nxt = st["next"]
    L += ["", "## Siguiente"]
    if nxt:
        L += [f"**{nxt['label']}**: `{nxt['how']}`"]
        L += [f"- {x}" for x in pending_detail(proj, cfg, st)]
        L += ["", f"Tokens restantes estimados: **{k(st['remaining_tokens'])}** (estimación: la tabla por etapa está en `config/defaults.yaml`, `workflow.stage_tokens`; recalibrarla con el primer video propio)."]
    else:
        L += ["Todo listo."]
    if st["profile"]["window_budget"] and st["windows"]:
        L += ["", f"## Ventanas de 5 horas (presupuesto de referencia {k(st['profile']['window_budget'])} por ventana)"]
        for i, w in enumerate(st["windows"], 1):
            L.append(f"{i}. {', '.join(s['id'] for s in w)} (~{k(sum(s['tokens'] for s in w))})")
        L += ["", "Cada etapa es reanudable: lo hecho se saltea y el triage retoma por grupo."]
    ap = approvals(proj)
    L += ["", "## Aprobaciones del dueño", ", ".join(f"{g}: {t}" for g, t in ap.items()) if ap else "ninguna todavía"]
    return "\n".join(L) + "\n"


def write_status(proj, cfg, st=None):
    st = st or compute(proj, cfg)
    (proj / STATUS_FILE).write_text(format_md(proj, cfg, st))
    return st
