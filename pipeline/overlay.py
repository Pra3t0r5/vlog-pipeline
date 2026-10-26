import pathlib

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

FORMATS = ("tv", "celu", "chat", "reel")
FADE_S = config.base_section("caption")["fade_s"]
MM_FADE_S = config.base_section("minimap")["fade_s"]


def fade_s():
    return config.get("caption.fade_s", FADE_S)


def mm_fade_s():
    return config.get("minimap.fade_s", MM_FADE_S)


def cfg_with(*layers):
    out = {}
    for layer in layers:
        for fmt, over in ((layer or {}).get("presets") or {}).items():
            if fmt not in FORMATS:
                raise ValueError(f"caption.presets.{fmt}: formato desconocido (válidos: {FORMATS})")
            out[fmt] = {**out.get(fmt, {}), **(over or {})}
    return {"presets": out}


def params(cfg, fmt, frame):
    W, H = frame
    fd = config.get("caption.format_defaults")
    p = {**fd.get(fmt, fd["tv"]), **((cfg or {}).get("presets") or {}).get(fmt, {})}
    S = min(W, H)
    return dict(
        fp=round(max(p["min_place_px"], S * p["place"])),
        fl=round(max(p["min_line_px"], S * p["line"])),
        maxw=W * p["max_w"],
        mx=round(W * p["margin_x"]),
        my=round(H * p["margin_y"]),
    )


def spacing(fp, fl):
    return max(8, fp // 2), max(2, fl // 5)


def wrap(text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if cur and font.getlength(t) > maxw:
            lines.append(cur)
            cur = w
        else:
            cur = t
    return lines + [cur] if cur else lines


def wrap_balanced(text, font, maxw, max_lines=2):
    lines = wrap(text, font, maxw)
    if len(lines) <= max_lines:
        return lines
    words = text.split()
    cut = min(range(1, len(words)), key=lambda i: max(font.getlength(" ".join(words[:i])), font.getlength(" ".join(words[i:]))))
    return [" ".join(words[:cut]), " ".join(words[cut:])]


def block_image(rows, fp, fl, align="left", min_w=0):
    pad, gap = spacing(fp, fl)
    lw = max(int(max(f.getlength(t) for t, f, _ in rows)) + 2 * pad, min_w + 2 * pad if min_w else 0)
    lh = sum(f.size + gap for _, f, _ in rows) + 2 * pad
    sh = Image.new("L", (lw, lh), 0)
    st = Image.new("L", (lw, lh), 0)
    fg = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    drop = max(2, fp // 25)
    y = pad
    for t, f, a in rows:
        x = pad if align == "left" else lw - pad - f.getlength(t) if align == "right" else (lw - f.getlength(t)) / 2
        ImageDraw.Draw(sh).text((x, y + drop), t, font=f, fill=255)
        ImageDraw.Draw(st).text((x, y), t, font=f, fill=255, stroke_width=1, stroke_fill=255)
        ImageDraw.Draw(fg).text((x, y), t, font=f, fill=(255, 255, 255, a))
        y += f.size + gap
    sh = sh.filter(ImageFilter.GaussianBlur(max(2, fp // 8)))
    im = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    im.paste((0, 0, 0, 255), (0, 0), sh.point(lambda v: min(150, int(v))))
    im.paste((0, 0, 0, 255), (0, 0), st.point(lambda v: int(v * 0.55)))
    im.alpha_composite(fg)
    return im


def caption_layout(place, lines, W, H, font_path, cfg=None, fmt="tv", column=None):
    pr = params(cfg, fmt, (W, H))
    fp, fl = pr["fp"], pr["fl"]
    place_font = ImageFont.truetype(font_path, fp)
    line_font = ImageFont.truetype(font_path, fl)
    pad, gap = spacing(fp, fl)
    maxw = pr["maxw"] if column is None else min(pr["maxw"], column["text_w"])
    place_rows = wrap_balanced(place, place_font, maxw, 2) if place else []
    desc_rows = {ln: wrap(ln, line_font, maxw) for ln in lines}
    lay = {"pr": pr, "pad": pad, "gap": gap, "place_font": place_font, "line_font": line_font, "place_rows": place_rows, "desc_rows": desc_rows}
    if column is not None:
        return {**lay, "place_top": column["label_top"], "desc_top": column["desc_top"], "tx": column["tx"], "align": column["align"]}
    slot_h = max((len(r) for r in desc_rows.values()), default=0) * (fl + gap)
    bottom = H - pr["my"]
    return {**lay, "place_top": bottom - slot_h - len(place_rows) * (fp + gap), "desc_top": bottom - slot_h, "tx": pr["mx"], "align": "left"}


def _x(lay, rows, font):
    if lay["align"] == "right":
        return lay["tx"] + lay["pad"] - (int(max(font.getlength(t) for t in rows)) + 2 * lay["pad"])
    return lay["tx"] - lay["pad"]


def place_xy(lay):
    return _x(lay, lay["place_rows"], lay["place_font"]), lay["place_top"] - lay["pad"]


def desc_xy(lay, line):
    return _x(lay, lay["desc_rows"][line], lay["line_font"]), lay["desc_top"] - lay["pad"]


def place_png(lay, out):
    rows = [(t, lay["place_font"], 255) for t in lay["place_rows"]]
    block_image(rows, lay["pr"]["fp"], lay["pr"]["fl"], align=lay["align"]).save(out, compress_level=1)


def desc_png(lay, line, out):
    rows = [(t, lay["line_font"], 205) for t in lay["desc_rows"][line]]
    block_image(rows, lay["pr"]["fp"], lay["pr"]["fl"], align=lay["align"]).save(out, compress_level=1)
