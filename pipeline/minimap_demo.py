import argparse
import json
import pathlib
import subprocess
import sys

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import config
import ffx
import minimap as M


def main(argv):
    ap = argparse.ArgumentParser(prog="minimap_demo", description="Compone el minimapa sobre un cuadro de un video del proyecto para revisar su diseño sin renderizar el guion")
    ap.add_argument("project")
    ap.add_argument("--pick", action="append", required=True, metavar="ID@SEGUNDO", help="id de media.json y segundo del cuadro, por ejemplo drone.DJI_0001@3.0")
    ap.add_argument("--theme", choices=sorted(config.base_section("minimap")["themes"]))
    ap.add_argument("--suffix", default="")
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--out-dir")
    a = ap.parse_args(argv)
    proj = pathlib.Path(a.project)
    cfg = config.activate_project(proj)
    W, H = (int(x) for x in a.size.lower().split("x"))
    route = proj / "route/route.json"
    media = {m["id"]: m for m in json.loads((proj / "inv/media.json").read_text())}
    labels = json.loads((proj / "route/labels.json").read_text())
    captions_path = proj / "captions.json"
    captions = json.loads(captions_path.read_text()) if captions_path.exists() else {}
    theme = a.theme or cfg["minimap"]["theme"]
    out_dir = pathlib.Path(a.out_dir) if a.out_dir else proj / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
    mm_cfg = M.cfg_with(cfg.get("minimap"))
    for pick in a.pick:
        mid, _, ss = pick.partition("@")
        rec = media[mid]
        src = proj / "proxy" / (pathlib.Path(rec["path"]).stem + ".mp4")
        if not src.exists():
            src = proj / "proxy" / "phone" / src.name
        if not src.exists():
            src = pathlib.Path(rec["path"])
        frame = out_dir / f"minimap-demo-{mid}.png"
        subprocess.run(ffx.nice() + ["ffmpeg", "-v", "error", "-y", "-ss", ss or "0", "-i", str(src), "-frames:v", "1",
                                     "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}", str(frame)], check=True)
        place = M.place_for(mid, rec, captions, labels)
        ov = M.render_overlay(rec["time_art"], rec["lat"], rec["lon"], place, (W, H), theme, route_path=route, labels=labels, cfg=mm_cfg)
        im = Image.open(frame).convert("RGBA")
        im.alpha_composite(ov)
        outp = out_dir / f"minimap-demo-{mid}{a.suffix}.jpg"
        im.convert("RGB").save(outp, quality=92)
        frame.unlink()
        print(outp)


if __name__ == "__main__":
    main(sys.argv[1:])
