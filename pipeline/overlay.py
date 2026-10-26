import pathlib

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

FORMATS = ("tv", "celu", "chat", "reel")
_CAP = config.base_section("caption")
MIN_SHOT_S = _CAP["min_shot_s"]
FADE_IN_AFTER = _CAP["fade_in_after"]
FADE_S = _CAP["fade_s"]
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


def caption_png(cap, W, H, style, out, cfg=None, fmt="tv"):
    pr = params(cfg, fmt, (W, H))
    fp, fl, maxw = pr["fp"], pr["fl"], pr["maxw"]
    place_font = ImageFont.truetype(style["font"], fp)
    line_font = ImageFont.truetype(style["font"], fl)
    rows = []
    if cap.get("place"):
        rows += [(t, place_font, 255) for t in wrap(cap["place"], place_font, maxw)]
    if cap.get("line"):
        rows += [(t, line_font, 205) for t in wrap(cap["line"], line_font, maxw)]
    pad = max(8, fp // 2)
    gap = max(2, fl // 5)
    lw = int(max(f.getlength(t) for t, f, _ in rows)) + 2 * pad
    lh = sum(f.size + gap for _, f, _ in rows) + 2 * pad
    sh = Image.new("L", (lw, lh), 0)
    st = Image.new("L", (lw, lh), 0)
    fg = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    y = pad
    for t, f, a in rows:
        ImageDraw.Draw(sh).text((pad, y + 2), t, font=f, fill=255)
        ImageDraw.Draw(st).text((pad, y), t, font=f, fill=255, stroke_width=1, stroke_fill=255)
        ImageDraw.Draw(fg).text((pad, y), t, font=f, fill=(255, 255, 255, a))
        y += f.size + gap
    sh = sh.filter(ImageFilter.GaussianBlur(max(2, fp // 8)))
    im = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    im.paste((0, 0, 0, 255), (0, 0), sh.point(lambda v: min(150, int(v))))
    im.paste((0, 0, 0, 255), (0, 0), st.point(lambda v: int(v * 0.55)))
    im.alpha_composite(fg)
    mx, my = pr["mx"], pr["my"]
    x = mx - pad
    yy = H - my - lh + pad
    im.save(out, compress_level=1)
    return (x, yy)


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


def caption_window(s, nxt_xn, fps, title_end=None):
    if s.n / fps < config.get("caption.min_shot_s", MIN_SHOT_S):
        return None
    fade = fade_s()
    vis_a = s.xn / fps
    vis_b = (s.n - nxt_xn) / fps
    a = vis_a + config.get("caption.fade_in_after", FADE_IN_AFTER)
    if title_end is not None:
        a = max(a, title_end + 0.1)
    if vis_b - a < 1.5 * fade + 0.5:
        return None
    return {"in": round(a, 3), "out": round(vis_b - fade, 3)}
