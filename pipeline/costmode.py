import config

_CM = config.base_section("costmode")
PROFILES = _CM["profiles"]
MODES = tuple(PROFILES)
DEFAULT = _CM["default"]

MUSIC_POLICY = {
    "search": "un subagente Sonnet acotado busca y filtra candidatos (sin Content ID shield); el dueño elige",
    "user_or_list": "el dueño trae el tema; si no, se usa config/music_default.json; sin búsqueda",
}


class CostModeError(ValueError):
    pass


def profiles_of(cfg):
    return config.build(cfg or {}).get("costmode", {}).get("profiles") or PROFILES


def mode_of(cfg):
    m = (cfg or {}).get("cost_mode", config.build(cfg or {}).get("costmode", {}).get("default", DEFAULT))
    modes = tuple(profiles_of(cfg))
    if m not in modes:
        raise CostModeError(f"cost_mode '{m}' inválido en project.yaml (válidos: {', '.join(modes)})")
    return m


def profile(cfg):
    m = mode_of(cfg)
    p = {k: (dict(v) if isinstance(v, dict) else v) for k, v in profiles_of(cfg)[m].items()}
    p["mode"] = m
    sheets = (cfg or {}).get("sheets") or {}
    if sheets.get("preset"):
        p["sheet_preset"] = sheets["preset"]
    return p


def model_for(cfg, role):
    return profile(cfg)["models"].get(role)


def reel_wanted(cfg):
    p = profile(cfg)
    if p["reel"] == "required":
        return True
    for e in (cfg or {}).get("outputs") or []:
        name = e.get("preset") if isinstance(e, dict) else e
        if name == "reel":
            return True
    return False


def table_md():
    s, l = PROFILES["standard"], PROFILES["low"]
    rows = [
        ("Cronología", "chronology"), ("Triage pasada 1", "triage_pass1"), ("Triage pasada 2", "triage_pass2"),
        ("Código y scripts", "code"), ("Editor (EDL)", "editor"), ("Captions", "captions"), ("Reel", "reel"),
        ("Investigación", "research"),
    ]
    out = ["| | standard | low |", "|---|---|---|"]
    for label, k in rows:
        out.append(f"| {label} | {s['models'][k] or 'no'} | {l['models'][k] or 'no'} |")
    out.append(f"| Hojas de contacto | {s['sheet_preset']} | {l['sheet_preset']} |")
    out.append(f"| Rondas del editor | {s['editor_rounds']} | {l['editor_rounds']} |")
    out.append(f"| Iteraciones de preview | {s['preview_iterations']} | {l['preview_iterations']} |")
    out.append(f"| Música | {s['music']} | {l['music']} |")
    out.append(f"| Reel | {s['reel']} | {l['reel']} |")
    out.append(f"| Presupuesto por ventana | sin tope | {l['window_budget']:,} tokens |".replace(",", "."))
    return "\n".join(out)
