import json
import pathlib
import re
from dataclasses import dataclass
from fractions import Fraction

import yaml

import config
import ffx
import minimap
import overlay
import sources

MODE_ALIAS = {"tv": "final"}
FORMAT_OF = {"preview": "tv", "final": "tv", "tv": "tv", "celu": "celu", "chat": "chat", "reel": "reel"}

KINDS = ("video", "photo", "card", "map")


def parse_fps(v):
    if isinstance(v, str):
        return Fraction(v)
    n = round(v)
    return Fraction(n * 1000, 1001) if abs(v - n * 1000 / 1001) < 0.01 else Fraction(v).limit_denominator(1001)


@dataclass
class Shot:
    idx: int
    kind: str
    raw: dict
    label: str
    rec: dict = None
    src: str = None
    w: int = None
    h: int = None
    t_in: float = 0.0
    speed: float = 1.0
    dur: float = 0.0
    avail: float = None
    audio: str = "mute"
    gain_db: float = 0.0
    transition: str = "fade"
    xfade: float = None
    title: dict = None
    caption: dict = None
    minimap: dict = None
    focus_x: float = 0.5
    zoom: str = "in"
    focus: list = None
    direction: str = "right"
    fit: str = "blur"
    card: dict = None
    snap: bool = True
    n: int = 0
    xn: int = 0
    start: int = 0
    gplan: dict = None
    ginfo: dict = None


class Guion:
    def __init__(self, path, mode):
        self.path = pathlib.Path(path).resolve()
        self.label = mode
        mode = MODE_ALIAS.get(mode, mode)
        self.mode = mode
        self.raw = json.loads(self.path.read_text())
        self.base = self.path.parent
        self.project = (self.base / self.raw.get("project", ".")).resolve()
        self.name = self.raw.get("name") or (config.load_project(self.project).get("name")) or self.project.name
        self.cache = (self.base / self.raw["cache_dir"]).resolve() if "cache_dir" in self.raw else self.project / "build" / mode
        self.out_dir = (self.base / self.raw["out_dir"]).resolve() if "out_dir" in self.raw else self.project
        self.grading = bool(self.raw.get("grading", True))
        self.project_cfg = {}
        yp = self.project / "project.yaml"
        if yp.exists():
            self.project_cfg = yaml.safe_load(yp.read_text()) or {}
        self.cfg = config.activate(self.project_cfg)
        mm = {"enabled": False}
        for layer in (self.project_cfg.get("minimap"), self.raw.get("minimap")):
            if isinstance(layer, dict):
                mm.update(layer)
        self.minimap = minimap.cfg_with(mm)
        self.minimap["enabled"] = bool(mm["enabled"])
        self.caption_cfg = overlay.cfg_with(self.project_cfg.get("caption"), self.raw.get("caption"))
        self.fmt = FORMAT_OF[self.label]
        self.cache.mkdir(parents=True, exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        out = config.deep_merge(self.cfg.get("output") or {}, self.raw.get("output", {}))
        self.style = {**self.cfg["style"], **self.raw.get("style", {})}
        if not self.style.get("font"):
            self.style["font"] = config.font("main")
        self.preset = {**self.cfg["presets"][mode], **out.get(mode, {})}
        self.preset["codec"] = ffx.pick_codec(self.preset["codec"])
        self.fps = parse_fps(out.get("fps", "30000/1001"))
        if not 1 <= self.fps <= 120:
            raise ffx.RenderError(f"fps fuera de rango: {self.fps}")
        self.fps_s = f"{self.fps.numerator}/{self.fps.denominator}"
        self.W, self.H = self.preset["w"], self.preset["h"]
        self.vertical = self.H > self.W
        self.xn_default = max(1, round(self.style["xfade"] * self.fps))
        self.media_by_id, self.media_by_stem = {}, {}
        inv = self.project / self.raw.get("inventory", "inv/media.json")
        if not inv.exists():
            raise ffx.RenderError(f"no existe el inventario {inv}: corré `vlog ingest`")
        if not self.raw.get("shots"):
            raise ffx.RenderError(f"el guion {self.path.name} no tiene shots")
        resolver = sources.Resolver.for_project(self.project)
        for r in json.loads(inv.read_text()):
            r["path"] = resolver.path(r)
            stem = pathlib.Path(r["path"]).stem
            rid = r.setdefault("id", stem)
            m = re.match(r"(\d+)\D+(\d+)", r.get("res") or "")
            if "w" not in r and m:
                r["w"], r["h"] = int(m[1]), int(m[2])
            self.media_by_id[rid] = r
            self.media_by_stem[stem] = None if stem in self.media_by_stem else r
        self.proxy_dir = self.project / self.raw.get("proxy_dir", "proxy")
        self.shots = []

    def music_entries(self):
        m = self.raw.get("music", [])
        return [m] if isinstance(m, dict) else m

    def lookup(self, ref):
        if ref in self.media_by_id:
            return self.media_by_id[ref]
        r = self.media_by_stem.get(ref)
        if r is None and ref in self.media_by_stem:
            raise ffx.RenderError(f"'{ref}' es ambiguo (varios medios con ese nombre): usá el id completo de media.json")
        if r is None:
            raise ffx.RenderError(f"no existe el medio '{ref}' en el inventario")
        return r

    def path_of(self, p):
        p = pathlib.Path(p)
        if p.is_absolute():
            return p
        for root in (self.base, self.project):
            if (root / p).exists():
                return (root / p).resolve()
        raise ffx.RenderError(f"no existe {p}")

    def proxy_for(self, rec):
        stem = pathlib.Path(rec["path"]).stem
        for c in (self.proxy_dir / f"{stem}.mp4", self.proxy_dir / "phone" / f"{stem}.mp4", self.proxy_dir / "phone" / f"{rec['id']}.mp4"):
            if c.exists():
                pr = ffx.probe(c)
                if rec.get("w") and abs(pr["w"] / pr["h"] / (rec["w"] / rec["h"]) - 1) < 0.02:
                    return str(c)
        return None

    def source_of(self, s, report):
        if self.mode == "preview" and s.kind == "video":
            p = self.proxy_for(s.rec)
            if p:
                return p
            report.warn(f"preview: sin proxy utilizable para {s.rec['id']}, se usa el original")
        return s.src

    def resolve(self, report):
        for i, raw in enumerate(self.raw["shots"]):
            self.shots.append(self.resolve_shot(i, raw, report))
        self.layout()
        if self.mode in ("final", "celu", "chat"):
            miss = sorted({s.src for s in self.shots if s.src and not pathlib.Path(s.src).exists()})
            if miss:
                raise ffx.RenderError("faltan originales para el render final (¿tarjeta SD sin montar?):\n" + "\n".join(miss[:10]))
        return self.shots

    def resolve_shot(self, i, raw, report):
        st = self.style
        if "card" in raw:
            kind = "card"
        elif "map" in raw:
            kind = "map"
        else:
            ref = raw.get("id") or raw.get("src")
            if not ref:
                raise ffx.RenderError(f"shot {i}: falta id, card o map")
            rec = self.lookup(ref)
            kind = "photo" if rec["kind"] == "photo" else "video"
        s = Shot(idx=i, kind=kind, raw=raw, label=kind)
        s.transition = raw.get("transition", st["transition"])
        s.xfade = raw.get("xfade")
        s.title = raw.get("title")
        cap = raw.get("caption")
        if cap and (cap.get("place") or cap.get("line")):
            s.caption = {"place": cap.get("place"), "line": cap.get("line")}
        mmr = raw.get("minimap")
        s.minimap = mmr if isinstance(mmr, dict) else ({} if mmr is not False else None)
        s.focus_x = float(raw.get("focus_x", 0.5))
        if not 0 <= s.focus_x <= 1:
            raise ffx.RenderError(f"shot {i}: focus_x debe estar entre 0 y 1")
        s.snap = raw.get("snap", kind != "card")
        s.audio = raw.get("audio", "mute")
        s.gain_db = float(raw.get("gain_db", 0))
        if s.audio not in ("keep", "mute"):
            raise ffx.RenderError(f"shot {i}: audio debe ser 'keep' o 'mute'")
        if s.transition not in ("fade", "cut"):
            raise ffx.RenderError(f"shot {i}: transition debe ser 'fade' o 'cut'")
        if kind in ("video", "photo"):
            s.rec = rec
            s.src = rec["path"]
            s.w, s.h = rec["w"], rec["h"]
            s.label = rec["id"].replace(".", "_")
        if kind == "video":
            self.resolve_video(s, raw, report)
        elif kind == "photo":
            s.dur = float(raw["dur"]) if "dur" in raw else (raw["out"] - raw.get("in", 0) if "out" in raw else st["photo_dur"])
            s.zoom = raw.get("zoom", "in")
            if s.zoom not in ("in", "out", "pan", "none"):
                raise ffx.RenderError(f"shot {i}: zoom debe ser in|out|pan|none")
            s.focus = raw.get("focus")
            s.direction = raw.get("dir", "right")
            s.fit = raw.get("fit", self.fit_default(s))
            if s.audio == "keep":
                report.warn(f"shot {i}: una foto no tiene audio, se ignora audio:keep")
                s.audio = "mute"
        elif kind == "card":
            s.card = raw["card"]
            s.dur = float(raw.get("dur", st["card_dur"]))
            s.label = "card"
            s.audio = "mute"
        elif kind == "map":
            p = self.path_of(raw["map"])
            pr = ffx.probe(p)
            s.src, s.w, s.h = str(p), pr["w"], pr["h"]
            s.t_in = float(raw.get("in", 0))
            out = float(raw.get("out", pr["dur"]))
            s.dur = float(raw["dur"]) if "dur" in raw else out - s.t_in
            s.avail = pr["dur"] - s.t_in - 0.1
            s.fit = raw.get("fit", "blur")
            s.label = "map-" + p.stem
            s.audio = "mute"
        return s

    def fit_default(self, s):
        return "fill" if self.vertical and s.w and s.h and s.w > s.h else "blur"

    def resolve_video(self, s, raw, report):
        rec = s.rec
        s.speed = float(raw.get("speed") or 1)
        s.t_in = float(raw.get("in", 0))
        total = rec.get("dur") or ffx.probe(rec["path"])["dur"]
        if "out" in raw:
            span = raw["out"] - s.t_in
        elif "dur" in raw:
            span = raw["dur"] * s.speed
        else:
            span = total - s.t_in
        limit = total - s.t_in - 0.1
        if span > limit:
            report.warn(f"shot {s.idx} ({rec['id']}): pide {span:.2f}s y el video sólo tiene {limit:.2f}s desde in={s.t_in}; se recorta")
            span = limit
        s.dur = span / s.speed
        s.avail = limit / s.speed
        s.fit = raw.get("fit", self.fit_default(s))
        if s.audio == "keep" and not rec.get("has_audio"):
            report.warn(f"shot {s.idx} ({rec['id']}): no tiene audio, se ignora audio:keep")
            s.audio = "mute"

    def layout(self):
        fps = self.fps
        sh = self.shots
        for i, s in enumerate(sh):
            s.n = max(1, round(s.dur * fps))
            if i == 0 or s.transition == "cut":
                s.xn = 0
            else:
                s.xn = max(1, round(s.xfade * fps)) if s.xfade else self.xn_default
        for i, s in enumerate(sh):
            nxt = sh[i + 1].xn if i + 1 < len(sh) else 0
            if s.n < s.xn + nxt + 2:
                raise ffx.RenderError(f"shot {i} ({s.label}) dura {s.n} frames y las transiciones piden {s.xn + nxt + 2}: alargalo o acortá el fundido")
            s.start = 0 if i == 0 else sh[i - 1].start + sh[i - 1].n - s.xn
        last = sh[-1]
        self.total_frames = last.start + last.n
        self.total = float(self.total_frames / fps)
        cap = self.preset.get("max_s")
        if cap and self.total > cap + 1e-6:
            raise ffx.RenderError(f"el preset {self.label} admite {cap}s y el guion dura {self.total:.1f}s")
