import argparse
import pathlib
from fractions import Fraction
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
from PIL import Image, ImageDraw, ImageOps

import ffx
import grade
import guion

HALF = 960
WARM_UP = 0.4


def fit_filter(w):
    return f"scale={w}:{w * 9 // 16}:force_original_aspect_ratio=decrease:flags=lanczos"


def frame(G, s, plan, out, w=1920):
    if s.kind == "photo":
        src = pathlib.Path(out).with_suffix(".src.png")
        ImageOps.exif_transpose(Image.open(s.src)).convert("RGB").save(src, compress_level=1)
        pc = grade.pieces(plan, False)
        vf = grade.join(fit_filter(w), pc["grade"], "format=yuv420p", pc["sharp"])
        ffx.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf, "-frames:v", "1", out])
        src.unlink()
        return
    t = s.t_in + s.dur * s.speed / 2
    t0 = max(t - WARM_UP, 0)
    skip = round((t - t0) * src_fps(s.src))
    pc = grade.pieces(plan, True)
    vf = grade.join(pc["dn"], fit_filter(w), pc["grade"], "format=yuv420p", pc["sharp"], f"select=eq(n\\,{skip})")
    ffx.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-i", s.src, "-vf", vf, "-frames:v", "1", out])


def src_fps(path):
    fps = ffx.probe(path).get("fps") or "30000/1001"
    return float(Fraction(fps))


def load(p):
    return np.asarray(Image.open(p).convert("RGB"))


def row(label, m):
    return f"{label:7s} luma {m['mean']:6.1f}  p5/p50/p95 {m['p5']:5.1f}/{m['p50']:5.1f}/{m['p95']:5.1f}  clip>250 Y {m['clipY']:5.2f}% ch {m['clipC']:5.2f}%  sat {m['sat']:.3f}"


def panel(a, b, plan):
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    W, H = ia.size
    top = Image.new("RGB", (2 * HALF + 4, HALF * 9 // 16), (20, 20, 20))
    for k, im in enumerate((ia, ib)):
        t = im.copy()
        t.thumbnail((HALF, HALF * 9 // 16), Image.LANCZOS)
        top.paste(t, (k * (HALF + 4) + (HALF - t.width) // 2, (HALF * 9 // 16 - t.height) // 2))
    cw, ch = HALF, HALF * 9 // 16
    x0, y0 = max((W - cw) // 2, 0), max((H - ch) // 2, 0)
    bot = Image.new("RGB", top.size, (20, 20, 20))
    for k, im in enumerate((ia, ib)):
        bot.paste(im.crop((x0, y0, x0 + cw, y0 + ch)), (k * (HALF + 4), 0))
    out = Image.new("RGB", (top.width, top.height * 2 + 4), (20, 20, 20))
    out.paste(top, (0, 0))
    out.paste(bot, (0, top.height + 4))
    d = ImageDraw.Draw(out)
    for k, lab in enumerate(("antes", "después " + str(plan))):
        d.rectangle((k * (HALF + 4), 0, k * (HALF + 4) + 8 * len(lab) + 10, 16), fill=(0, 0, 0))
        d.text((k * (HALF + 4) + 5, 2), lab, fill=(255, 255, 255))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("guion")
    ap.add_argument("shots", nargs="+", type=int)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    report = ffx.Report()
    G = guion.Guion(a.guion, "preview")
    G.grading = True
    G.resolve(report)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for i in a.shots:
        s = G.shots[i]
        plan = grade.plan(G, s, report)
        info = getattr(s, "ginfo", None) or {}
        if not plan:
            print(f"[{i}] {s.rec['id']}: sin grading ({info.get('night') or 'perfil none'})")
            continue
        pa, pb = out / f"_a{i}.png", out / f"_b{i}.png"
        frame(G, s, None, pa)
        frame(G, s, plan, pb)
        ma, mb = grade.measure(load(pa)), grade.measure(load(pb))
        name = f"compare-{i:02d}-{s.rec['id'].replace('.', '_')}.jpg"
        panel(pa, pb, {k: v for k, v in plan.items() if v}).save(out / name, quality=92)
        pa.unlink()
        pb.unlink()
        ok = mb["clipY"] - ma["clipY"] <= 0.5 and mb["clipC"] - ma["clipC"] <= 0.5
        print(f"[{i}] {s.rec['id']} -> {name}")
        print("   plan:", {k: v for k, v in plan.items() if v}, "| noche:", info.get("night"), "| zoom:", info.get("zoom"), "| lap %.0f" % (info.get("lap") or 0))
        print("   " + row("antes", ma))
        print("   " + row("después", mb))
        print(f"   delta clip Y {mb['clipY'] - ma['clipY']:+.2f} pp, canal {mb['clipC'] - ma['clipC']:+.2f} pp -> {'OK' if ok else 'EXCEDE'}")


if __name__ == "__main__":
    main(sys.argv[1:])
