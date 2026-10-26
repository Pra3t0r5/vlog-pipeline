import pathlib
import re

import config
import costmode
import pacing
import prefilter

MARKER = "=== PROMPT ==="
MARKER_LINE = re.compile(r"^=== PROMPT ===[ \t]*$", re.M)
PROMPTS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "prompts"
NAMES = ("chronology", "captions", "editor", "reel")
DRONE_SHARE_MAX = config.base_section("edit")["drone_share_max"]
REEL_MAX_S = config.base_section("presets")["reel"]["max_s"]


class PromptError(Exception):
    pass


def template(name):
    p = PROMPTS / f"{name}.md"
    if not p.exists():
        raise PromptError(f"no existe la plantilla {p}")
    text = p.read_text()
    parts = MARKER_LINE.split(text, maxsplit=1)
    if len(parts) != 2:
        raise PromptError(f"la plantilla {p} no tiene una línea {MARKER}")
    return parts[1].strip()


def fill(text, values):
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def notes_listing(proj):
    d = pathlib.Path(proj) / "notes"
    files = sorted(p for p in d.iterdir() if p.is_file() and p.name != "chronology.json") if d.exists() else []
    return "\n".join(f"- {p} ({p.stat().st_size // 1024} KB)" for p in files) or "(notes/ está vacío)"


def values(proj, cfg):
    proj = pathlib.Path(proj)
    full = config.build(cfg)
    prof = costmode.profile(cfg)
    dur = cfg.get("duration") or {}
    target = float(dur.get("target_min", 7))
    lo, hi = prefilter.trip_range(cfg)
    edl = proj / cfg.get("edl", "edl.json")
    reel = next((e.get("guion") for e in cfg.get("outputs") or [] if isinstance(e, dict) and e.get("preset") == "reel"), None)
    music = costmode.MUSIC_POLICY[prof["music"]]
    if prof["music"] == "user_or_list":
        music += f" ({config.repo_path(config.get('music.default_list', 'config/music_default.json'))})"
    scope = ("solo `place`; `line` va siempre en null y no se investiga nada" if not prof["research_subagents"]
             else "`place` y, cuando lo puedas verificar en la web, `line` con un dato interesante y su fuente; hasta 2 búsquedas por lugar distinto")
    return {
        "captions_scope": scope, "project": proj, "title": cfg.get("title") or cfg.get("name"), "from": lo or "(sin fecha)", "to": hi or "(sin fecha)",
        "target_min": target, "floor_min": dur.get("floor_min", round(target * 0.7, 1)), "ceil_min": dur.get("ceil_min", round(target * 1.4, 1)),
        "target_s": round(target * 60), "rounds": prof["editor_rounds"], "model": prof["models"]["editor"],
        "drone_share_max": (cfg.get("edit") or {}).get("drone_share_max", DRONE_SHARE_MAX), "music_policy": music,
        "credits_act": config.get("edit.credits_act", "Créditos", full), "map_attribution": config.get("credits.map_attribution", "", full),
        "crossfade_s": config.get("edit.crossfade_s", 0.6, full),
        "edl_out": edl, "edl": edl, "brief": proj / "DIRECTION.md", "media": proj / cfg.get("media", "inv/media.json"),
        "index": proj / "sheets" / "index.json", "triage": proj / "triage" / "merged.json",
        "sharpness": proj / "inv" / "sharpness.json", "variants": proj / "inv" / "variants.json",
        "chronology": proj / "notes" / "chronology.json", "captions": proj / "captions.json", "credits": proj / "music" / "credits.json",
        "guion_reel": proj / (reel or "guion-reel.json"), "max_s": config.get("presets.reel.max_s", REEL_MAX_S, full),
        "notes_files": notes_listing(proj), "out_file": proj / "notes" / "chronology.json",
        **pacing.prompt_values(cfg),
    }


def render(name, proj, cfg):
    if name not in NAMES:
        raise PromptError(f"plantilla desconocida '{name}' (válidas: {', '.join(NAMES)})")
    return fill(template(name), values(proj, cfg))
