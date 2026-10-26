import math

import config

MODES = ("relaxed", "standard")
KINDS = ("drone", "photo", "hero", "phone")


def half_up(x):
    return math.floor(x * 2 + 0.5) / 2


def settings(cfg=None):
    full = config.build(cfg or {})
    p = full["pacing"]
    mode = p["mode"]
    if mode not in MODES:
        raise config.ConfigError(f"pacing: '{mode}' no es válido (válidos: {', '.join(MODES)})")
    mult = float(p["multiplier"][mode])
    ranges = {k: [half_up(float(v) * mult) for v in p["targets"][k]] for k in KINDS}
    override = p.get("min_shot_s")
    return {
        "mode": mode,
        "multiplier": mult,
        "ranges": ranges,
        "min_shot_s": float(override) if override is not None else None,
        "max_cuts_per_min": round(float(p["max_cuts_per_min"]) / mult, 1),
    }


def min_for(st, kind):
    return st["min_shot_s"] if st["min_shot_s"] is not None else st["ranges"][kind][0]


def kind_of(shot, media, triage_keep=None):
    if triage_keep is not None and triage_keep >= 3:
        return "hero"
    if shot["kind"] == "photo":
        return "photo"
    return "drone" if media.get("source") == "drone" else "phone"


def prompt_values(cfg=None):
    st = settings(cfg)
    fmt = lambda k: f"{st['ranges'][k][0]:g} a {st['ranges'][k][1]:g}".replace(".", ",")
    return {
        "pacing_mode": st["mode"],
        "pacing_multiplier": f"{st['multiplier']:g}".replace(".", ","),
        "drone_range": fmt("drone"),
        "photo_range": fmt("photo"),
        "hero_range": fmt("hero"),
        "phone_range": fmt("phone"),
        "min_shot": f"{st['min_shot_s']:g}".replace(".", ",") if st["min_shot_s"] is not None else "el mínimo de cada rango",
        "max_cuts_per_min": f"{st['max_cuts_per_min']:g}".replace(".", ","),
    }
