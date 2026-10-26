import io
import json
import pathlib
import subprocess
import sys
import time
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont, ImageOps

import config
import prefilter

BG = (24, 24, 24)
CELL_BG = (0, 0, 0)
_SH = config.base_section("sheets")
QUALITY = _SH["quality"]
TOKEN_DIV = _SH["token_div"]
PRESETS = _SH["presets"]
DEFAULT_PRESET = "standard"


class Layout:
    def __init__(self, name):
        presets = config.get("sheets.presets") or PRESETS
        if name not in presets:
            raise ValueError(f"preset de hojas desconocido '{name}' (válidos: {', '.join(presets)})")
        self.name = name
        p = presets[name]
        self.__dict__.update(p)
        self.token_div = config.get("sheets.token_div", TOKEN_DIV)
        self.width = self.cols * self.pw
        self.label_w = self.width - self.frames * self.vw
        self.max_h = min(self.max_px, int(self.max_tokens * self.token_div / self.width))
        self.f_tag = ImageFont.truetype(config.font("ui"), self.tag_font)
        self.f_row = ImageFont.truetype(config.font("ui"), self.row_font)
        self.f_row2 = ImageFont.truetype(config.font("ui"), self.row_font2)

    def row_height(self, kind):
        return self.vh if kind == "video" else self.ph


def tokens_of(width, height):
    return round(width * height / config.get("sheets.token_div", TOKEN_DIV))


def load_records(proj, cfg, use_prefilter=True):
    recs = json.loads((pathlib.Path(proj) / cfg.get("media", "inv/media.json")).read_text())
    alive = prefilter.survivors(proj) if use_prefilter else None
    if alive is not None:
        keep = [r for r in recs if r["id"] in alive]
    else:
        keep = [r for r in recs if not r.get("exclude_reason") and r.get("keep_in_burst") is not False]
    keep.sort(key=lambda r: (r["time_art"] or "", r["id"]))
    p = v = 0
    for r in keep:
        if r["kind"] == "video":
            v += 1
            r["code"] = f"V{v}"
        else:
            p += 1
            r["code"] = f"P{p}"
        r["day"] = r.get("day") or "sin-fecha"
    return keep


def hhmm(r):
    return (r["time_art"] or "")[11:16]


def fit(img, w, h):
    img = img.copy()
    img.thumbnail((w, h), Image.LANCZOS)
    cell = Image.new("RGB", (w, h), CELL_BG)
    cell.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    return cell


def tag(cell, text, font):
    d = ImageDraw.Draw(cell, "RGBA")
    box = d.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0] + 6, box[3] - box[1] + 4
    d.rectangle((0, 0, w, h), fill=(0, 0, 0, 170))
    d.text((3, 1 - box[1] + 1), text, font=font, fill=(255, 235, 120))


def photo_cell(L, r):
    try:
        with Image.open(r["path"]) as im:
            im.draft("RGB", (L.pw * 2, L.ph * 2))
            im = ImageOps.exif_transpose(im).convert("RGB")
            cell = fit(im, L.pw, L.ph)
    except OSError:
        cell = Image.new("RGB", (L.pw, L.ph), (60, 0, 0))
    tag(cell, f"{r['code']} {hhmm(r)}", L.f_tag)
    return cell


def video_source(proj, r):
    stem = pathlib.Path(r["path"]).stem
    proxy = pathlib.Path(proj) / "proxy" / f"{stem}.mp4"
    return str(proxy) if proxy.exists() else r["path"]


def frame(L, path, t):
    cmd = ["nice", "-n", "10", "ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", path,
           "-frames:v", "1", "-vf", f"scale={L.vw}:{L.vh}:force_original_aspect_ratio=decrease",
           "-f", "image2pipe", "-c:v", "png", "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0 or not p.stdout:
        return Image.new("RGB", (L.vw, L.vh), (60, 0, 0))
    return Image.open(io.BytesIO(p.stdout)).convert("RGB")


def video_row(L, proj, r):
    row = Image.new("RGB", (L.width, L.vh), CELL_BG)
    d = ImageDraw.Draw(row)
    dur = r["dur"] or 0
    snd = "snd" if r.get("has_audio") else "-"
    gap = L.vh // 3
    d.text((6, 2), r["code"], font=L.f_row, fill=(255, 235, 120))
    d.text((6, gap + 2), f"{hhmm(r)} {dur:.0f}s", font=L.f_row2, fill=(235, 235, 235))
    d.text((6, 2 * gap), f"audio {snd}", font=L.f_row2, fill=(150, 220, 150) if snd != "-" else (150, 150, 150))
    src = video_source(proj, r)
    for i in range(L.frames):
        t = max(0.0, dur * (i + 0.5) / L.frames)
        fr = frame(L, src, t)
        row.paste(fr, (L.label_w + i * L.vw + (L.vw - fr.width) // 2, (L.vh - fr.height) // 2))
    return row


def build_rows(L, items):
    rows, run = [], []

    def flush():
        nonlocal run
        for i in range(0, len(run), L.cols):
            rows.append(("photo", run[i:i + L.cols]))
        run = []

    for r in items:
        if r["kind"] == "video":
            flush()
            rows.append(("video", [r]))
        else:
            run.append(r)
    flush()
    return rows


def render_row(L, proj, kind, chunk):
    if kind == "video":
        return video_row(L, proj, chunk[0])
    row = Image.new("RGB", (L.width, L.ph), BG)
    for i, r in enumerate(chunk):
        row.paste(photo_cell(L, r), (i * L.pw, 0))
    return row


def paginate(L, rows):
    pages, cur, h = [], [], 0
    for kind, chunk in rows:
        rh = L.row_height(kind)
        if cur and h + rh > L.max_h:
            pages.append(cur)
            cur, h = [], 0
        cur.append((kind, chunk))
        h += rh
    if cur:
        pages.append(cur)
    return pages


def plan(L, recs):
    by_day = defaultdict(list)
    for r in recs:
        by_day[r["day"]].append(r)
    out = []
    for day in sorted(by_day):
        for n, page in enumerate(paginate(L, build_rows(L, by_day[day])), 1):
            h = sum(L.row_height(k) for k, _ in page)
            out.append({"name": f"{day}-{n:02d}.jpg", "day": day, "page": page, "height": h,
                        "codes": [r["code"] for _, c in page for r in c]})
    return out


def estimate(L, recs):
    sheets = plan(L, recs)
    return {"sheets": len(sheets), "tokens_est": sum(tokens_of(L.width, s["height"]) for s in sheets)}


def build(proj, cfg, preset=None, out=None, force=False, use_prefilter=True, only=None, log=print):
    t0 = time.time()
    proj = pathlib.Path(proj)
    preset = preset or (cfg.get("sheets") or {}).get("preset") or DEFAULT_PRESET
    L = Layout(preset)
    out = pathlib.Path(out) if out else proj / "sheets"
    out.mkdir(parents=True, exist_ok=True)
    recs = load_records(proj, cfg, use_prefilter)
    if only is not None:
        recs = [r for r in recs if r["code"] in only]
    sheets = plan(L, recs)
    old_path = out / "manifest.json"
    old = json.loads(old_path.read_text()) if old_path.exists() else {}
    flag = bool(use_prefilter and prefilter.survivors(proj) is not None)
    if (old.get("preset"), old.get("prefilter"), old.get("n_items")) != (preset, flag, len(recs)):
        force = True
    names = {s["name"] for s in sheets}
    for stale in set(old.get("sheets", {})) - names:
        (out / stale).unlink(missing_ok=True)
    index = {"codes": {r["code"]: r["id"] for r in recs}, "sheets": {}}
    manifest = {}
    total = 0
    for s in sheets:
        dst = out / s["name"]
        if force or not dst.exists():
            rendered = [render_row(L, proj, k, c) for k, c in s["page"]]
            sheet = Image.new("RGB", (L.width, s["height"]), BG)
            y = 0
            for im in rendered:
                sheet.paste(im, (0, y))
                y += im.height
            sheet.save(dst, "JPEG", quality=config.get("sheets.quality", QUALITY), optimize=True)
        tokens = tokens_of(L.width, s["height"])
        total += tokens
        index["sheets"][s["name"]] = s["codes"]
        manifest[s["name"]] = {"day": s["day"], "n_items": len(s["codes"]), "width": L.width, "height": s["height"], "tokens_est": tokens}
        log(s["name"], len(s["codes"]), (L.width, s["height"]), tokens, flush=True)
    summary = {
        "preset": preset,
        "frames": L.frames,
        "prefilter": flag,
        "n_items": len(recs),
        "n_sheets": len(manifest),
        "total_tokens_est": total,
        "max_sheet_tokens_est": max((m["tokens_est"] for m in manifest.values()), default=0),
        "sheets": manifest,
    }
    (out / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False))
    (out / "manifest.json").write_text(json.dumps(summary, indent=1))
    log(f"sheets={len(manifest)} items={len(recs)} tokens={total} secs={time.time() - t0:.0f}")
    return summary
