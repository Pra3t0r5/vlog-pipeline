import pathlib

import ffx

NATIVE = ("preview", "final", "tv", "celu", "chat", "reel")
ALL = NATIVE


def out_path(G, preset):
    return G.out_dir / f"{G.name}-{preset}.mp4"


def fit_size(G, out, report):
    limit = G.preset.get("max_mb")
    if not limit:
        return out
    limit *= 1e6
    if out.stat().st_size <= limit:
        return out
    dur = ffx.probe(out)["dur"]
    abr = int(G.preset["audio_bitrate"].rstrip("k")) * 1000
    vbits = min((limit * 8 * 0.93) / dur - abr, G.preset["vmax"])
    src = out.with_suffix(".full.mp4")
    out.rename(src)
    part = out.with_suffix(".part.mp4")
    try:
        with report.stage(f"ajuste a {G.preset['max_mb']} MB"):
            for _ in range(4):
                cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "medium", "-profile:v", "high",
                       "-b:v", f"{int(vbits)}", "-maxrate", f"{int(vbits * 1.3)}", "-bufsize", f"{int(vbits * 2)}", "-pix_fmt", "yuv420p",
                       "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-c:a", "copy", "-movflags", "+faststart", str(part)]
                ffx.run(cmd)
                if part.stat().st_size <= limit:
                    part.rename(out)
                    return out
                vbits *= 0.85
            part.unlink()
            raise ffx.RenderError(f"{G.label} no entra en {G.preset['max_mb']} MB")
    finally:
        if not out.exists():
            src.rename(out)
        elif src.exists():
            src.unlink()
