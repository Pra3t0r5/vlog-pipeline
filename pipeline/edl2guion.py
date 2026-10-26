import argparse
import json
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import config

CREDITS_TEXT = config.base_section("credits")["fallback_title"]
REAL = ("video", "photo")


def add_music_file(out, project, slot, f):
    if not f or not slot:
        return
    rel = pathlib.Path(f)
    if not rel.is_absolute() and rel.parts[0] != "music":
        rel = pathlib.Path("music") / rel
    full = rel if rel.is_absolute() else project / rel
    if full.exists():
        out[slot] = str(rel)


def music_files(project, edl=None):
    p = project / "music" / "credits.json"
    out = {}
    if p.exists():
        for e in json.loads(p.read_text()):
            add_music_file(out, project, e.get("slot"), e.get("file"))
    for e in (edl or {}).get("music_plan", []):
        add_music_file(out, project, e.get("slot"), e.get("file"))
    return out


def bg_for(shot):
    if shot is None:
        return None
    if shot["kind"] == "video":
        return {"id": shot["id"], "at": round((shot["in"] + shot["out"]) / 2, 2)}
    return {"id": shot["id"]}


def real_shots(edl):
    return [s for a in edl["acts"] for s in a["shots"] if s["kind"] in REAL]


def convert(edl, project, map_clip):
    reals = real_shots(edl)
    order = {id(s): i for i, s in enumerate(reals)}
    shots, music, spans = [], [], []
    credit_done = False
    seen_real = 0
    for a in edl["acts"]:
        first_idx = len(shots)
        title_pending = a.get("card") is None
        for j, s in enumerate(a["shots"]):
            k = s["kind"]
            audio = s.get("audio", "mute")
            if k == "map":
                g = {"map": map_clip, "in": 0, "dur": s["dur"]}
            elif k == "card":
                t = s.get("title") or {}
                is_credit = a["name"] == config.get("edit.credits_act", "Créditos") and s.get("role") != "title"
                if s.get("role") == "title":
                    card = {"title": t.get("text", a["name"])}
                    if t.get("sub"):
                        card["sub"] = t["sub"]
                    bg = bg_for(reals[seen_real - 1] if seen_real else None)
                elif is_credit:
                    if credit_done:
                        continue
                    credit_done = True
                    prev = reals[seen_real - 1] if seen_real else None
                    card = {"title": t.get("text") or config.get("credits.fallback_title", CREDITS_TEXT)}
                    if s.get("lines"):
                        card["lines"] = list(s["lines"])
                    else:
                        card["music_credits"] = True
                    bg = bg_for(prev)
                else:
                    card = {"title": t.get("text", a["name"])}
                    if t.get("sub"):
                        card["sub"] = t["sub"]
                    nxt = reals[seen_real] if seen_real < len(reals) else None
                    bg = bg_for(nxt)
                if bg:
                    card["bg"] = bg
                g = {"card": card, "dur": s["dur"]}
            else:
                g = {"id": s["id"]}
                if k == "video":
                    g.update({"in": s["in"], "out": s["out"], "audio": "keep" if audio == "keep" else "mute"})
                else:
                    g["dur"] = s["dur"]
                title = s.get("title")
                if title_pending:
                    title = title or {"text": a["name"]}
                    title_pending = False
                if title:
                    g["title"] = {"text": title["text"], **({"sub": title["sub"]} if title.get("sub") else {})}
                cap = s.get("caption")
                if cap and (cap.get("place") or cap.get("line")):
                    g["caption"] = {"place": cap.get("place"), "line": cap.get("line")}
                seen_real += 1
            g["transition"] = "fade" if len(shots) == first_idx else "cut"
            g["act"] = a["name"]
            shots.append(g)
        spans.append((a.get("music"), first_idx, len(shots) - 1))
    files = music_files(project, edl)
    merged = []
    for slot, a0, a1 in spans:
        if merged and merged[-1][0] == slot:
            merged[-1][2] = a1
        else:
            merged.append([slot, a0, a1])
    for slot, a0, a1 in merged:
        if slot in files:
            music.append({"file": files[slot], "from_shot": a0, "to_shot": a1})
    return shots, music


def main(argv):
    ap = argparse.ArgumentParser(prog="edl2guion")
    ap.add_argument("project")
    ap.add_argument("map", nargs="?")
    ap.add_argument("--edl", default="edl.json")
    ap.add_argument("--out", default="guion.json")
    ap.add_argument("--map", dest="map_opt")
    a = ap.parse_args(argv)
    project = pathlib.Path(a.project)
    cfg_path = project / "project.yaml"
    pcfg = (yaml.safe_load(cfg_path.read_text()) or {}) if cfg_path.exists() else {}
    cfg = config.activate(pcfg)
    edl_path = pathlib.Path(a.edl)
    edl = json.loads((edl_path if edl_path.is_absolute() else project / edl_path).read_text())
    map_clip = str(pathlib.Path(a.map_opt or a.map) if (a.map_opt or a.map) else project / cfg["edit"]["map_clip"])
    shots, music = convert(edl, project, map_clip)
    name = pcfg.get("name")
    guion = {
        "name": name or project.resolve().name,
        "project": ".",
        "inventory": "inv/media.json",
        "proxy_dir": "proxy",
        "out_dir": "build",
        "snap_to_beats": False,
        "output": {"fps": cfg["output"]["fps"]},
        "style": {"xfade": edl.get("crossfade_s", cfg["edit"]["crossfade_s"])},
        "music": music,
        "shots": shots,
    }
    out_path = pathlib.Path(a.out)
    out = out_path if out_path.is_absolute() else project / out_path
    out.write_text(json.dumps(guion, ensure_ascii=False, indent=1))
    total = sum(s.get("dur") or (s["out"] - s["in"]) for s in shots)
    print(out, len(shots), "shots", f"{total:.1f}s sin fundidos", len(music), "temas")


if __name__ == "__main__":
    main(sys.argv[1:])
