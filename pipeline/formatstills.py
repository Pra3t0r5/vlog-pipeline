import argparse
import json
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import config
import ffx
import guion
import render

FORMATS = ("tv", "celu", "chat", "reel")


def mini_guion(src, indices, out_dir, fmt):
    raw = json.loads(pathlib.Path(src).read_text())
    shots = [dict(raw["shots"][i]) for i in indices]
    shots[0]["transition"] = "fade"
    raw.update(shots=shots, music=[], project=str(pathlib.Path(src).resolve().parent), out_dir=str(out_dir), cache_dir=str(out_dir / f"cache-{fmt}"), snap_to_beats=False)
    path = out_dir / f"guion-{fmt}.json"
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=1))
    return path


def still(src, shot, fmt, out_dir, offset):
    indices = [shot - 1, shot, shot + 1]
    path = mini_guion(src, indices, out_dir, fmt)
    rep = ffx.Report()
    G, video = render.render_one(path, fmt, rep)
    s = G.shots[1]
    t = (s.start + s.n / 2) / float(G.fps) + offset
    png = out_dir / f"example-{fmt}.png"
    ffx.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(png)])
    return png, G


def compare(pngs, out, height=720):
    ims = [Image.open(p).convert("RGB") for p in pngs]
    ims = [im.resize((round(im.width * height / im.height), height), Image.LANCZOS) for im in ims]
    gap, top = 24, 40
    W = sum(im.width for im in ims) + gap * (len(ims) + 1)
    sheet = Image.new("RGB", (W, height + top + gap), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype(config.font("ui"), 22)
    x = gap
    for name, im in zip(FORMATS, ims):
        sheet.paste(im, (x, top))
        d.text((x, 8), name, font=f, fill=(230, 230, 230))
        x += im.width + gap
    sheet.save(out, quality=92)


def main(argv):
    ap = argparse.ArgumentParser(prog="formatstills")
    ap.add_argument("guion")
    ap.add_argument("--shot", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--formats", default=",".join(FORMATS))
    ap.add_argument("--offset", type=float, default=0.0)
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pngs = []
    for fmt in a.formats.split(","):
        png, G = still(a.guion, a.shot, fmt, out, a.offset)
        pngs.append(png)
        print(png, f"{G.W}x{G.H}")
    if len(pngs) == len(FORMATS):
        compare(pngs, out / "compare.jpg")
        print(out / "compare.jpg")


if __name__ == "__main__":
    main(sys.argv[1:])
