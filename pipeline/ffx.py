import json
import pathlib
import subprocess
import time
from contextlib import contextmanager

import config

CODEC_FALLBACK = {"h264_videotoolbox": "libx264", "hevc_videotoolbox": "libx265"}


def nice():
    n = config.get("render.nice", 10)
    return ["nice", "-n", str(n)] if n else []


class RenderError(Exception):
    pass


class Report:
    def __init__(self):
        self.stages = {}
        self.warnings = []
        self.hits = 0
        self.part_hits = 0
        self.audio_hit = False
        self.audio_info = None
        self.snap = None
        self.builds = 0
        self.t0 = time.time()

    @contextmanager
    def stage(self, name):
        t = time.time()
        try:
            yield
        finally:
            self.stages[name] = self.stages.get(name, 0) + time.time() - t

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)


def run(cmd):
    r = subprocess.run(nice() + [str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode:
        raise RenderError(f"{cmd[0]} falló ({r.returncode}): {' '.join(str(c) for c in cmd)[:300]}\n{r.stderr[-1500:]}")
    return r


_probes = {}
_encoders = None


def encoders():
    global _encoders
    if _encoders is None:
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        except OSError:
            out = ""
        _encoders = {ln.split()[1] for ln in out.splitlines() if ln.startswith(" ") and len(ln.split()) > 2}
    return _encoders


def pick_codec(name):
    have = encoders()
    if not have or name in have:
        return name
    fb = CODEC_FALLBACK.get(name)
    return fb if fb in have else name


def hwaccel_args():
    if config.get("render.hwaccel", "auto") == "none":
        return []
    return ["-hwaccel", "videotoolbox"] if "h264_videotoolbox" in encoders() else []


def probe(path):
    path = str(path)
    if path in _probes:
        return _probes[path]
    r = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    j = json.loads(r.stdout)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    out = {"has_audio": a is not None, "dur": float(j["format"].get("duration") or 0)}
    if v:
        w, h = v["width"], v["height"]
        rot = 0
        for sd in v.get("side_data_list", []):
            if "rotation" in sd:
                rot = int(sd["rotation"])
        if abs(rot) % 180 == 90:
            w, h = h, w
        out.update(w=w, h=h, fps=v.get("r_frame_rate"))
    _probes[path] = out
    return out


def count_frames(path):
    r = run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)])
    return int(r.stdout.strip().rstrip(","))


def sig(path):
    st = pathlib.Path(path).stat()
    return [str(path), st.st_size, st.st_mtime_ns]
