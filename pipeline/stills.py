from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

import overlay

BG = (480, 270)


def load(path):
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


RGB_TO_YUV709 = "scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=bicubic"


def fill_crop(im, w, h, resample=Image.LANCZOS, focus_x=0.5):
    s = max(w / im.width, h / im.height)
    r = im.resize((max(w, round(im.width * s)), max(h, round(im.height * s))), resample, reducing_gap=2.0)
    x = min(max(round(focus_x * r.width - w / 2), 0), r.width - w)
    y = (r.height - h) // 2
    return r.crop((x, y, x + w, y + h))


def blur_bg(im, w, h, style, dim=None):
    small = fill_crop(im, *BG, resample=Image.BILINEAR).filter(ImageFilter.GaussianBlur(style["bg_sigma"]))
    small = ImageEnhance.Brightness(small).enhance(style["bg_dim"] if dim is None else dim)
    small = ImageEnhance.Color(small).enhance(0.9)
    return small.resize((w, h), Image.BICUBIC)


def is_wide(w, h, W, H, tol):
    return abs((w / h) / (W / H) - 1) <= tol


def rect_for(w, h, cw, ch, style, fit="blur"):
    if fit == "fill" or is_wide(w, h, cw, ch, style["aspect_tol"]):
        return (0.0, 0.0, 1.0, 1.0)
    s = min(cw / w, ch / h)
    fw, fh = round(w * s) // 2 * 2, round(h * s) // 2 * 2
    return ((cw - fw) // 2 / cw, (ch - fh) // 2 / ch, fw / cw, fh / ch)


def compose(im, cw, ch, style, fit="blur", focus_x=0.5):
    rect = rect_for(im.width, im.height, cw, ch, style, fit)
    if rect == (0.0, 0.0, 1.0, 1.0):
        return fill_crop(im, cw, ch, focus_x=focus_x)
    canvas = blur_bg(im, cw, ch, style)
    fw, fh = round(rect[2] * cw), round(rect[3] * ch)
    fg = im.resize((fw, fh), Image.LANCZOS, reducing_gap=2.0)
    canvas.paste(fg, ((cw - fw) // 2, (ch - fh) // 2))
    return canvas


def zoom_filter(n, mode, style, focus=None, direction="right", rect=(0.0, 0.0, 1.0, 1.0)):
    p = f"(in/{n})"
    if mode == "pan":
        z = repr(1 + style["pan_zoom"])
        sgn = {"right": 1, "down": 1, "left": -1, "up": -1}[direction]
        horizontal = direction in ("left", "right")
        span = f"(W/2-W/(2*{z}))" if horizontal else f"(H/2-H/(2*{z}))"
        cx = f"(W/2+{sgn}*{span}*(2*{p}-1))" if horizontal else "(W/2)"
        cy = "(H/2)" if horizontal else f"(H/2+{sgn}*{span}*(2*{p}-1))"
    else:
        amt = style["focus_zoom"] if focus else style["zoom_amt"]
        q = p if mode == "in" else f"(1-{p})"
        z = f"(1+{amt}*{q})"
        fx, fy = (0.5, 0.5)
        if focus:
            fx = rect[0] + focus[0] * rect[2]
            fy = rect[1] + focus[1] * rect[3]
        cx = f"(W/2+W*{fx - 0.5:.6f}*{q})"
        cy = f"(H/2+H*{fy - 0.5:.6f}*{q})"
    cx = f"min(max({cx},W/(2*{z})),W-W/(2*{z}))"
    cy = f"min(max({cy},H/(2*{z})),H-H/(2*{z}))"
    hw, hh = f"W/(2*{z})", f"H/(2*{z})"
    corners = [(f"{cx}-{hw}", f"{cy}-{hh}"), (f"{cx}+{hw}", f"{cy}-{hh}"), (f"{cx}-{hw}", f"{cy}+{hh}"), (f"{cx}+{hw}", f"{cy}+{hh}")]
    pts = [f"x{k}='{x}':y{k}='{y}'" for k, (x, y) in enumerate(corners)]
    return "perspective=" + ":".join(pts) + ":sense=source:eval=frame:interpolation=cubic"


def font(style, size):
    return ImageFont.truetype(style["font"], int(size))


def wrap_font(style, text, size, max_w):
    f = font(style, size)
    lines = overlay.wrap(text, f, max_w)
    widest = max(lines, key=f.getlength, default="")
    if widest and f.getlength(widest) > max_w:
        f = fit_font(style, widest, size, max_w)
    return f, lines


def title_png(t, W, H, style, out):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if H > W:
        x, y = int(W * 0.06), int(H * 0.60)
        big, big_lines = wrap_font(style, t["text"], W * 0.085, W * 0.88)
        small, small_lines = wrap_font(style, t.get("sub") or " ", W * 0.05, W * 0.88)
        gap = int(big.size * 1.35)
        sgap = int(small.size * 1.4)
        sub_y = y + gap * len(big_lines)
        bottom = sub_y + (sgap * len(small_lines) if t.get("sub") else 0)
        d.rectangle([0, y - int(H * 0.02), W, bottom + int(H * 0.012)], fill=(0, 0, 0, 90))
        for i, ln in enumerate(big_lines):
            d.text((x, y + gap * i), ln, font=big, fill="white")
        if t.get("sub"):
            for i, ln in enumerate(small_lines):
                d.text((x, sub_y + sgap * i), ln, font=small, fill=(230, 230, 230))
        im.save(out)
        return
    big, big_lines = wrap_font(style, t["text"], H * 0.065, W * 0.9)
    small, small_lines = wrap_font(style, t.get("sub") or " ", H * 0.035, W * 0.9)
    step = int(H * 0.08)
    x, y = int(W * 0.05), int(H * 0.78) - step * (len(big_lines) - 1) - (int(H * 0.045) * (len(small_lines) - 1) if t.get("sub") else 0)
    d.rectangle([0, y - int(H * 0.03), W, H], fill=(0, 0, 0, 90))
    for i, ln in enumerate(big_lines):
        d.text((x, y + step * i), ln, font=big, fill="white")
    if t.get("sub"):
        for i, ln in enumerate(small_lines):
            d.text((x, y + step * len(big_lines) + int(H * 0.045) * i), ln, font=small, fill=(230, 230, 230))
    im.save(out)


def fit_font(style, text, size, max_w):
    f = font(style, size)
    while f.getlength(text) > max_w and size > 8:
        size *= 0.94
        f = font(style, size)
    return f


def card_png(card, W, H, style, bg_im, lines, out):
    if bg_im is not None:
        img = blur_bg(bg_im, W, H, style, dim=style["card_dim"])
    else:
        img = Image.new("RGB", (W, H), card.get("bg", {}).get("color", style["card_color"]))
    blocks = []
    for text, size, col, gap in ([(card["title"], H * 0.085, (255, 255, 255), H * 0.02)] if card.get("title") else []) + (
        [(card["sub"], H * 0.045, (236, 226, 208), H * 0.03)] if card.get("sub") else []
    ) + [(ln, H * 0.036, (225, 215, 198), H * 0.012) for ln in lines]:
        f, parts = wrap_font(style, text, size, W * 0.86)
        for i, part in enumerate(parts):
            blocks.append((f, part, col, gap if i == len(parts) - 1 else H * 0.008))
    heights = [b[0].getbbox(b[1])[3] + b[3] for b in blocks]
    y = (H - sum(heights)) / 2
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    yy = y
    for (f, text, col, gap), h in zip(blocks, heights):
        x = (W - f.getlength(text)) / 2
        sd.text((x + H * 0.003, yy + H * 0.004), text, font=f, fill=(0, 0, 0, 160))
        ld.text((x, yy), text, font=f, fill=col + (255,))
        yy += h
    img = Image.alpha_composite(img.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(H * 0.004)))
    img = Image.alpha_composite(img, layer).convert("RGB")
    img.save(out, compress_level=1)
