import json
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import config
import ffx
import guion
from PIL import Image, ImageDraw, ImageFont


def main(argv):
    if len(argv) != 3 or argv[0] in ("-h", "--help"):
        sys.exit("uso: review.py guion.json video.mp4 carpeta_de_salida")
    path = pathlib.Path(argv[0])
    video = pathlib.Path(argv[1])
    outdir = pathlib.Path(argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    G = guion.Guion(str(path), "preview")
    G.resolve(ffx.Report())
    rv = config.section("review")
    TW, TH, COLS, MAXH = rv["tile_w"], rv["tile_h"], rv["cols"], rv["max_h"]
    acts = [s.get("act", "") for s in json.loads(path.read_text())["shots"]]
    font = ImageFont.truetype(config.font("ui"), 13)
    per = COLS * (MAXH // TH)
    tiles = []
    with tempfile.TemporaryDirectory() as td:
        for s in G.shots:
            t = (s.start + s.n // 2) / G.fps
            f = pathlib.Path(td) / f"{s.idx}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{float(t):.3f}", "-i", str(video), "-frames:v", "1", "-vf", f"scale={TW}:{TH}", str(f)], check=True)
            im = Image.open(f).convert("RGB")
            d = ImageDraw.Draw(im)
            label = f"{s.idx} {acts[s.idx]}"
            w = d.textlength(label, font=font)
            d.rectangle([0, 0, w + 8, 18], fill=(0, 0, 0))
            d.text((4, 2), label, font=font, fill=(255, 255, 255))
            tiles.append(im)
    outs = []
    for n, a in enumerate(range(0, len(tiles), per), 1):
        chunk = tiles[a:a + per]
        rows = (len(chunk) + COLS - 1) // COLS
        sheet = Image.new("RGB", (COLS * TW, rows * TH), (0, 0, 0))
        for i, im in enumerate(chunk):
            sheet.paste(im, ((i % COLS) * TW, (i // COLS) * TH))
        p = outdir / f"review-{n:02d}.jpg"
        sheet.save(p, quality=85)
        outs.append(p)
    print("\n".join(map(str, outs)))


if __name__ == "__main__":
    main(sys.argv[1:])
