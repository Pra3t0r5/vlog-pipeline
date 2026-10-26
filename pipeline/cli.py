import argparse
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

try:
    import yaml
except ImportError:
    import importlib.util
    missing = [pkg for mod, pkg in (("PIL", "Pillow"), ("numpy", "numpy"), ("scipy", "scipy"), ("yaml", "PyYAML"), ("imagehash", "ImageHash"), ("librosa", "librosa"), ("soundfile", "soundfile")) if importlib.util.find_spec(mod) is None]
    sys.exit(f"vlog: faltan dependencias de Python ({', '.join(missing)}) en {sys.executable}.\n"
             "Creá un entorno con `python3 -m venv venv && venv/bin/pip install -r requirements.txt` (bin/vlog lo usa solo) o apuntá VLOG_PYTHON a un intérprete que las tenga.")

import adbui
import config
import costmode
import ffx
import edl_check
import prefilter
import presets
import prompts
import sources
import triage
import workflow

PIPE = pathlib.Path(__file__).resolve().parent
REPO = PIPE.parent
PY = sys.executable
HEAVY = ("proxy", "build")
SKELETON = ("inv", "proxy", "build", "music", "notes", "route", "sheets")
FACTOR = 2


def die(msg, code=1):
    print(f"vlog: {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode:
        die(f"falló: {' '.join(str(c) for c in cmd)[:200]}", r.returncode)
    return r


def free_bytes(path):
    p = pathlib.Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free


def tree_size(path):
    p = pathlib.Path(path)
    if p.is_file():
        return p.stat().st_size
    if not p.exists():
        return 0
    out = subprocess.run(["du", "-sk", str(p)], capture_output=True, text=True).stdout.split()
    return int(out[0]) * 1024 if out else 0


def gb(n):
    return f"{n / 1e9:.1f} GB"


def check_disk(target, source_bytes, factor=FACTOR):
    need = int(source_bytes * factor)
    have = free_bytes(target)
    return have >= need, have, need


def find_project(arg):
    cands = [arg] if arg else [os.environ.get("VLOG_PROJECT"), os.getcwd()]
    for c in cands:
        if not c:
            continue
        p = pathlib.Path(c).expanduser().resolve()
        if (p / "project.yaml").exists():
            return p
        if arg and (config.projects_root() / arg / "project.yaml").exists():
            return config.projects_root() / arg
    die("no encuentro project.yaml: usá --project <carpeta> o corré el comando dentro del proyecto")


def load(proj):
    try:
        cfg = config.load_yaml(proj / "project.yaml")
        config.activate(cfg)
    except config.ConfigError as e:
        die(str(e))
    return cfg


def save(proj, cfg):
    (proj / "project.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))


def ask(prompt, default=None, given=None, yes=False):
    if given is not None:
        return given
    if yes:
        if default is None:
            die(f"falta el dato '{prompt}' y --yes impide preguntar")
        return default
    s = input(f"{prompt}{f' [{default}]' if default is not None else ''}: ").strip()
    return s or default


def direction_text(**kw):
    return (config.REPO / "config" / "DIRECTION.template.md").read_text().format(**kw)


def parse_res(res):
    m = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", res or "")
    if not m or int(m[1]) < 2 or int(m[2]) < 2:
        die(f"resolución inválida '{res}': usá ANCHOxALTO, por ejemplo 3840x2160")
    return int(m[1]), int(m[2])


def cmd_new(a):
    yes = a.yes
    name = a.name
    theme = ask("Tema / brief en una frase", None if not yes else name, a.theme, yes)
    try:
        minutes = float(ask("Duración objetivo (minutos)", "7", a.minutes, yes))
    except (TypeError, ValueError):
        die("la duración debe ser un número de minutos")
    if minutes <= 0:
        die("la duración debe ser mayor que cero")
    audience = ask("Para quién es", "la familia, en un televisor", a.audience, yes)
    base_cfg = config.activate(None)
    pf = base_cfg["presets"]["final"]
    res = ask(f"Resolución de salida ({pf['w']}x{pf['h']} o 1920x1080)", f"{pf['w']}x{pf['h']}", a.res, yes)
    fps = ask("FPS", str(base_cfg["output"]["fps"]), a.fps, yes)
    tz = ask("Zona horaria de las fotos y videos (+HH:MM)", config.timezone_offset(base_cfg), a.tz, yes)
    try:
        config.tzinfo(tz)
    except config.ConfigError as e:
        die(str(e))
    root = pathlib.Path(ask("Carpeta de vlogs", str(config.projects_root()), a.root, yes)).expanduser()
    cost_mode = ask(f"Modo de costo ({'/'.join(costmode.MODES)})", costmode.DEFAULT, a.cost_mode, yes)
    if cost_mode not in costmode.MODES:
        die(f"modo de costo inválido '{cost_mode}' (válidos: {', '.join(costmode.MODES)})")
    drone = ask("Ruta de la tarjeta/carpeta del dron (vacío si no hay)", "", a.drone, yes) or ""
    album = ask("Zip del álbum de Google Photos (vacío si no hay)", "", a.album, yes) or ""
    w, h = parse_res(res)
    src = sum(tree_size(p) for p in (drone, album) if p)
    proj = root / name
    if proj.exists() and (proj / "project.yaml").exists():
        die(f"{proj} ya existe; no lo piso")
    internal = pathlib.Path.home()
    print(f"Fuentes: {gb(src)}. Libre en {internal}: {gb(free_bytes(internal))}; libre en {root}: {gb(free_bytes(root))}")
    if src:
        ok, have, need = check_disk(root, src)
        if not ok:
            die(f"rechazo crear {proj}: los directorios pesados ({', '.join(HEAVY)}) necesitan {FACTOR}x las fuentes = {gb(need)} y el disco tiene {gb(have)} libres")
    for d in SKELETON:
        (proj / d).mkdir(parents=True, exist_ok=True)
    cfg = {
        "name": name,
        "theme": theme,
        "audience": audience,
        "cost_mode": cost_mode,
        "duration": {"target_min": minutes, "floor_min": max(1, round(minutes * 0.7, 1)), "ceil_min": round(minutes * 1.4, 1)},
        "output": {"fps": fps, "final": {"w": w, "h": h}},
        "sources": {"drone": drone, "album_zip": album},
        "rutas": {"from": "", "to": ""},
        "guion": "guion.json",
        "inventory": "inv/inventory.json",
        "ingest": {"start_date": "", "end_date": "", "tz": tz, "owners": [], "clock_offsets": []},
        "proxy_dir": "proxy",
        "source_bytes": src,
    }
    save(proj, cfg)
    t = direction_text(title=name, theme=theme, audience=audience, minutes=minutes, ceil=cfg["duration"]["ceil_min"], floor=cfg["duration"]["floor_min"], w=w, h=h, fps=fps)
    (proj / "DIRECTION.md").write_text(t)
    print(f"Proyecto creado en {proj}")
    print("Siguiente: completar DIRECTION.md con el director y correr `vlog doctor`.")


FILTERS = ("xfade", "overlay", "perspective", "fade", "gblur", "lutyuv", "tpad", "settb", "movie", "concat", "curves", "vibrance", "colorbalance", "hqdn3d", "cas", "select",
           "sidechaincompress", "loudnorm", "ebur128", "amix", "acrossfade", "afade", "adelay", "apad", "atrim", "atempo", "alimiter", "aresample", "aformat", "asplit", "anullsrc")
ENCODERS = ("libx264", "libx265", "aac")
OPTIONAL_ENCODERS = ("h264_videotoolbox", "hevc_videotoolbox")
MODS = (("PIL", "Pillow"), ("numpy", "numpy"), ("scipy", "scipy"), ("yaml", "PyYAML"), ("imagehash", "ImageHash"), ("librosa", "librosa"), ("soundfile", "soundfile"), ("pillow_heif", "pillow-heif"))
MIN_PYTHON = (3, 12)


def tool_version(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else ""


def ffmpeg_names(kind):
    out = subprocess.run(["ffmpeg", "-hide_banner", f"-{kind}"], capture_output=True, text=True).stdout
    return {ln.split()[1] for ln in out.splitlines() if len(ln.split()) > 2 and ln.startswith(" ")}


def cmd_doctor(a):
    bad = 0
    opt = 0

    def line(ok, label, extra="", required=True):
        nonlocal bad, opt
        if ok:
            tag = "ok"
        elif required:
            tag, bad = "FALTA", bad + 1
        else:
            tag, opt = "opcional", opt + 1
        print(f"[{tag}] {label}{(' — ' + extra) if extra else ''}")

    line(sys.version_info >= MIN_PYTHON, f"python {sys.version.split()[0]}", f"se necesita {'.'.join(map(str, MIN_PYTHON))} o más")
    line(sys.prefix != sys.base_prefix, "entorno virtual activo", sys.prefix, required=False)
    line(sys.platform == "darwin", f"sistema {sys.platform}", "pensado para macOS (encoders videotoolbox, diskutil); en otros sistemas cae a libx264/libx265 y a la biblioteca zipfile", required=False)
    for b in ("ffmpeg", "ffprobe", "exiftool"):
        p = shutil.which(b)
        line(bool(p), b, p or "")
    for b, why in (("adb", "solo para exportar la ruta del teléfono por cable (`vlog rutas`); sin adb se usa --file"),
                   ("ditto", "solo macOS: descomprime el zip del álbum (`vlog album`); sin él se usa la biblioteca zipfile"),
                   ("zipinfo", "cuenta los archivos del zip (`vlog album`); sin él se usa la biblioteca zipfile"),
                   ("nice", "baja la prioridad de los ffmpeg largos"),
                   ("diskutil", "solo macOS: UUID de volúmenes en sources.json"),
                   ("claude", "Claude Code: lo usa quien dirige el flujo (docs/DIRECTOR.md), no el CLI")):
        p = shutil.which(b)
        line(bool(p), b, p or why, required=False)
    for m, pkg in MODS:
        try:
            __import__(m)
            line(True, f"python:{pkg}")
        except ImportError:
            line(False, f"python:{pkg}", "pip install -r requirements.txt", required=m != "pillow_heif")
    try:
        from PIL import features
        line(features.check("freetype2"), "Pillow con FreeType", "los textos del video salen de Pillow")
    except ImportError:
        pass
    if shutil.which("ffmpeg"):
        print(f"[info] {tool_version(['ffmpeg', '-version'])}")
        names = ffmpeg_names("filters")
        for f in FILTERS:
            line(f in names, f"filtro:{f}")
        encs = ffmpeg_names("encoders")
        for e in ENCODERS:
            line(e in encs, f"encoder:{e}")
        for e in OPTIONAL_ENCODERS:
            line(e in encs, f"encoder:{e}", "sin él se usa libx264/libx265" if e not in encs else "", required=False)
        if "drawtext" in names:
            print("[aviso] drawtext existe pero el pipeline NO lo usa: los textos salen de Pillow")
    if shutil.which("exiftool"):
        print(f"[info] exiftool {tool_version(['exiftool', '-ver'])}")
    try:
        font = config.font("main")
        line(True, "tipografía", font)
    except config.ConfigError as e:
        line(False, "tipografía", str(e))
    ne = config.vendor_path("naturalearth_dir", "naturalearth")
    have = [f for f in config.NE_FILES if (ne / f).exists()]
    line(len(have) == len(config.NE_FILES), "datos de Natural Earth", str(ne) if len(have) == len(config.NE_FILES) else f"{len(have)}/{len(config.NE_FILES)} archivos; `vlog fetch-data` los baja (solo hacen falta para el minimapa)", required=False)
    if shutil.which("adb"):
        out = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout
        n = len([l for l in out.splitlines()[1:] if l.strip().endswith("device")])
        print(f"[info] teléfonos adb autorizados: {n}")
    uf = config.user_file()
    print(f"[info] configuración de usuario: {uf if uf else 'ninguna'}")
    print("Todo en orden." if not bad else f"{bad} problema(s) obligatorio(s).")
    if opt:
        print(f"{opt} componente(s) opcional(es) ausente(s); limitan solo la función que se indica.")
    return 1 if bad else 0


def cmd_config(a):
    if a.defaults:
        sys.stdout.write(config.DEFAULTS_FILE.read_text())
        return 0
    cfg = config.build(None)
    if a.project or os.environ.get("VLOG_PROJECT") or (pathlib.Path.cwd() / "project.yaml").exists():
        cfg = config.build(load(find_project(a.project)))
    if a.key:
        val = config.get(a.key, None, cfg)
        if val is None:
            die(f"no existe la clave '{a.key}'")
        cfg = val
    if isinstance(cfg, (dict, list)):
        sys.stdout.write(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    else:
        print(cfg)
    return 0


DATA_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"


def cmd_fetch_data(a):
    import urllib.request
    dest = config.vendor_path("naturalearth_dir", "naturalearth")
    dest.mkdir(parents=True, exist_ok=True)
    for fn in config.NE_FILES:
        out = dest / fn
        if out.exists() and not a.force:
            print(f"{fn} ya existe")
            continue
        print(f"bajando {fn} (Natural Earth, dominio público)...")
        part = out.with_suffix(".part")
        req = urllib.request.Request(DATA_URL + fn, headers={"User-Agent": config.user_agent()})
        try:
            with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as f:
                shutil.copyfileobj(r, f)
        except OSError as e:
            part.unlink(missing_ok=True)
            die(f"no pude bajar {fn}: {e}")
        part.rename(out)
    print(f"datos en {dest}. Crédito obligatorio en el video: Natural Earth (dominio público) y © OpenStreetMap contributors si usás calles OSM.")
    return 0


def cmd_osm(a):
    proj = find_project(a.project)
    argv = ["--project", str(proj)] + (["--force"] if a.force else [])
    for t in a.only or []:
        argv += ["--only", t]
    run([PY, PIPE / "osm_fetch.py"] + argv)


def cmd_rutas(a):
    proj = find_project(a.project)
    cfg = load(proj)
    lo, hi = a.date_from, a.date_to
    for d in (lo, hi):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            die(f"fecha inválida '{d}': usá YYYY-MM-DD")
    if lo > hi:
        die("--from es posterior a --to")
    out = proj / "route"
    out.mkdir(exist_ok=True)
    dst = out / config.get("route.export_file", "Rutas.json")
    if a.file:
        if pathlib.Path(a.file).resolve() != dst.resolve():
            shutil.copy(a.file, dst)
    elif dst.exists() and not a.force:
        print(f"{dst} ya existe; sigo con ese (usá --force para volver a exportar)")
    else:
        try:
            adb = adbui.Adb()
            serial = adbui.device_ready(adb("devices"))
            adb = adbui.Adb(serial)
            print(f"Teléfono {serial}. No toques la pantalla hasta que termine.")
            name = adbui.export_timeline(adb)
            adb("pull", f"{config.get('route.device_dir', '/sdcard/Download')}/{name}", str(dst), timeout=300)
        except adbui.Abort as e:
            die(f"aborto sin cambios en el teléfono: {e}", 2)
    run([PY, PIPE / "route.py", dst, lo, hi, out])
    cfg["rutas"] = {"from": lo, "to": hi}
    save(proj, cfg)


def zip_names(z):
    if shutil.which("zipinfo"):
        return subprocess.run(["zipinfo", "-1", str(z)], capture_output=True).stdout.decode("utf-8", "replace").split("\n")
    with zipfile.ZipFile(z) as f:
        return f.namelist()


def zip_uncompressed(z):
    if shutil.which("zipinfo"):
        tot = subprocess.run(["zipinfo", "-t", str(z)], capture_output=True, text=True).stdout
        mt = re.search(r"([\d]+) bytes uncompressed", tot)
        if mt:
            return int(mt.group(1))
    with zipfile.ZipFile(z) as f:
        return sum(i.file_size for i in f.infolist())


def extract_zip(z, dest):
    if shutil.which("ditto"):
        run(["ditto", "-x", "-k", "--norsrc", "--noextattr", z, dest])
        return
    with zipfile.ZipFile(z) as f:
        for info in f.infolist():
            parts = pathlib.PurePosixPath(info.filename).parts
            if not parts or parts[0] == "__MACOSX" or any(p.startswith("._") for p in parts):
                continue
            f.extract(info, dest)


def cmd_album(a):
    proj = find_project(a.project)
    cfg = load(proj)
    z = pathlib.Path(a.zip).expanduser().resolve()
    if not z.exists():
        die(f"no existe {z}")
    m = sources.load(proj)
    known = sources.album_dir(proj, cfg, m)
    dest = known or sources.default_album_target(proj, cfg, z)
    names = zip_names(z)
    files = [n for n in names if n and not n.endswith("/") and not n.startswith("__MACOSX/") and pathlib.PurePosixPath(n).name != ".DS_Store" and not pathlib.PurePosixPath(n).name.startswith("._")]

    def extracted():
        if not dest.exists():
            return []
        return [p for p in dest.rglob("*") if p.is_file() and p.name != ".DS_Store" and not p.name.startswith("._")]

    got = extracted()
    if got and len(got) == len(files) and not a.force:
        print(f"álbum ya extraído en {dest} ({len(got)} archivos, coincide con el zip); nada que hacer")
    else:
        unc = zip_uncompressed(z)
        ok, have, need = check_disk(dest, unc)
        if not ok:
            die(f"extraer necesita {FACTOR}x = {gb(need)} y hay {gb(have)} libres en {sources.mount_of(dest)}")
        dest.mkdir(parents=True, exist_ok=True)
        extract_zip(z, dest)
        got = extracted()
        if len(got) != len(files):
            die(f"verificación fallida: el zip trae {len(files)} archivos y extraje {len(got)}", 3)
        print(f"{len(files)} archivos extraídos en {dest} y verificados contra la lista del zip")
    m = sources.load(proj)
    rid = sources.ensure_root(m, "album", dest)
    m["roots"][rid]["extracted_from"] = z.name
    m["roots"][rid]["file_count"] = len(files)
    sources.save(proj, m)
    cfg.setdefault("storage", {})["album_dir"] = str(dest)
    if (proj / "project.yaml").exists():
        save(proj, cfg)
    print(f"El álbum es la raíz de fuentes '{rid}' (fuera de la carpeta del proyecto: nada se copia dentro).")
    print(f"El zip NO se borró. Cuando `vlog sources build` y `vlog sources check` pasen y la cuenta coincida ({len(files)} archivos), se puede borrar a mano:")
    print(f"  rm {shlex.quote(str(z))}")


def cmd_ingest(a):
    proj = find_project(a.project)
    cfg = load(proj)
    drone = a.src or cfg.get("sources", {}).get("drone")
    inv = proj / "inv" / "inventory.json"
    ses = proj / "inv" / "sessions.json"
    media = proj / "inv" / "media.json"
    if drone:
        if not pathlib.Path(drone).exists():
            die(f"no está montado {drone}: revisá la tarjeta SD")
        if inv.exists() and not a.force:
            print(f"{inv} ya existe; sigo (usá --force para rehacer)")
        else:
            run([PY, PIPE / "inventory.py", drone, inv])
        if ses.exists() and not a.force:
            print(f"{ses} ya existe; sigo")
        else:
            run([PY, PIPE / "cluster.py", inv, ses, proj])
    ing = cfg.get("ingest", {})
    rr = cfg.get("rutas", {})
    lo, hi = ing.get("start_date") or rr.get("from"), ing.get("end_date") or rr.get("to")
    m = sources.load(proj)
    album = sources.album_dir(proj, cfg, m)
    if media.exists() and not a.force:
        print(f"{media} ya existe; sigo (usá --force para rehacer)")
    elif not lo or not hi:
        print("Falta ingest.start_date / ingest.end_date en project.yaml (o correr `vlog rutas` antes) para unificar el material del álbum.")
    elif not inv.exists():
        print("Falta el inventario del dron; pasá --src o completá sources.drone.")
    elif album is None:
        print("Falta el álbum: corré `vlog album <zip>` o registrá la carpeta con `vlog sources add album <carpeta>`.")
    else:
        sources.ensure_root(m, "album", album)
        if drone:
            sources.ensure_root(m, "drone_sd", sources.common_root([r["path"] for r in json.loads(inv.read_text())], "DCIM"))
        sources.save(proj, m)
        cmd = [PY, PIPE / "ingest.py", "--project", proj, "--sources", sources.manifest_path(proj), "--drone-inv", inv, "--album", album, "--route", proj / "route" / "route.json", "--out", media,
               "--geocache", proj / "inv" / "geocache.json", "--start-date", lo, "--end-date", hi]
        if ing.get("tz"):
            cmd += ["--tz", ing["tz"]]
        for o in ing.get("owners", []):
            cmd += ["--owner", o]
        for o in ing.get("clock_offsets", []):
            cmd += ["--clock-offset", o]
        cmd += a.extra
        run(cmd)
        sources.build(proj, cfg)
    print("Falta (lo hace el director): cruzar con las notas, triage y guion.")


def cmd_proxies(a):
    proj = find_project(a.project)
    cfg = load(proj)
    inv = json.loads((proj / cfg.get("inventory", "inv/inventory.json")).read_text())
    pdir = proj / cfg.get("proxy_dir", "proxy")
    pdir.mkdir(exist_ok=True)
    vids = [r for r in inv if r["kind"] == "video"]
    src = sum(r["gb"] for r in vids) * 1e9
    ok, have, need = check_disk(pdir, src / 20, 2)
    if not ok:
        die(f"poco espacio para proxies: {gb(have)} libres")
    made = skipped = 0
    for r in vids:
        stem = pathlib.Path(r["path"]).stem
        out = pdir / f"{stem}.mp4"
        if out.exists():
            skipped += 1
            continue
        part = pdir / f".{stem}.part.mp4"
        px = config.get("proxies.drone")
        run(["ffmpeg", "-v", "error", "-y"] + ffx.hwaccel_args() + ["-i", r["path"], "-vf", f"scale={px['w']}:{px['h']}", "-c:v", ffx.pick_codec("h264_videotoolbox"), "-b:v", px["bitrate"], "-an", part])
        part.rename(out)
        made += 1
        print(f"proxy {stem}")
    print(f"proxies: {made} nuevos, {skipped} ya estaban")


def load_checked(proj):
    cfg = load(proj)
    try:
        costmode.mode_of(cfg)
    except costmode.CostModeError as e:
        die(str(e))
    return cfg


def cmd_prefilter(a):
    proj = find_project(a.project)
    cfg = load_checked(proj)
    if (proj / "sheets" / "manifest.json").exists() and not a.force:
        die("las hojas ya existen y los códigos P/V dependen del prefiltro: usá --force si vas a rehacer hojas y triage")
    out = prefilter.run(proj, cfg)
    print(prefilter.report(out))
    print(f"escrito {prefilter.path_of(proj)}")


def cmd_sheets(a):
    import sheets
    proj = find_project(a.project)
    cfg = load_checked(proj)
    preset = a.preset or costmode.profile(cfg)["sheet_preset"]
    out, only = (pathlib.Path(a.out).expanduser() if a.out else None), None
    if a.survivors:
        try:
            if not triage.done(proj, cfg, 1):
                die("faltan resultados válidos de la pasada 1: `vlog triage-plan --pass 1`")
            groups, _ = triage.sheet_groups(proj)
        except triage.TriageError as e:
            die(str(e))
        only = {r["code"] for d in groups for r in triage.load_json(triage.pass_file(proj, 1, d)) if not r["reject"]}
        out = out or proj / triage.P2_SHEETS
    log = print if a.verbose else (lambda *x, **k: None)
    res = sheets.build(proj, cfg, preset, out, a.force, not a.no_prefilter, only, log)
    print(f"hojas {res['preset']}: {res['n_sheets']} hojas, {res['n_items']} tomas, ~{res['total_tokens_est']} tokens (máx. {res['max_sheet_tokens_est']} por hoja) en {out or proj / 'sheets'}")


def cmd_triage_plan(a):
    proj = find_project(a.project)
    cfg = load_checked(proj)
    n = a.pass_no
    try:
        items = triage.plan(proj, cfg, n, a.day, not a.all)
    except (triage.TriageError, FileNotFoundError) as e:
        die(f"{e}" + (" (corré `vlog sheets --survivors`)" if n == 2 else ""))
    if not items:
        print(f"pasada {n}: nada pendiente.")
        return 0
    print(f"pasada {n}: {len(items)} grupo(s), modelo {items[0]['model']}, ~{sum(i['tokens_est'] for i in items)} tokens de imagen")
    for it in items:
        print(f"\n===== {it['day']}  {it['n_items']} tomas, {len(it['sheets'])} hoja(s), ~{it['tokens_est']} tokens de imagen -> {it['out_file']}")
        for pr in it["problems"]:
            print(f"  pendiente: {pr}")
        if not a.no_prompt:
            print("----- prompt -----")
            print(it["prompt"])


def cmd_triage_merge(a):
    proj = find_project(a.project)
    cfg = load_checked(proj)
    try:
        merged = triage.merge(proj, cfg)
    except triage.TriageError as e:
        die(f"triage incompleto o inválido:\n{e}")
    keep = {}
    for r in merged:
        keep[r["keep"]] = keep.get(r["keep"], 0) + 1
    print(f"{len(merged)} tomas en {proj / triage.MERGED}; keep: {dict(sorted(keep.items()))}")


def cmd_sharpness(a):
    proj = find_project(a.project)
    if not (proj / triage.MERGED).exists():
        die("falta triage/merged.json: `vlog triage-merge`")
    run([PY, PIPE / "sharpness.py", proj])


def cmd_prompt(a):
    proj = find_project(a.project)
    cfg = load_checked(proj)
    try:
        print(prompts.render(a.name, proj, cfg))
    except prompts.PromptError as e:
        die(str(e))


def cmd_edl_check(a):
    proj = find_project(a.project)
    cfg = load_checked(proj)
    path = proj / (a.edl or cfg.get("edl", "edl.json"))
    if not path.exists():
        die(f"no existe {path}")
    errs, warns = edl_check.check(json.loads(path.read_text()), edl_check.load_inputs(proj, cfg), cfg)
    for w in warns:
        print(f"aviso: {w}")
    for e in errs:
        print(f"ERROR: {e}")
    print(f"{len(errs)} error(es), {len(warns)} aviso(s)")
    return 1 if errs else 0


def cmd_approve(a):
    proj = find_project(a.project)
    ap = workflow.approve(proj, a.gate)
    print(f"{a.gate}: aprobado {ap[a.gate]}")


def cmd_profile(a):
    proj = find_project(a.project)
    cfg = load_checked(proj)
    p = costmode.profile(cfg)
    print(f"cost_mode: {p['mode']}")
    for k, v in p["models"].items():
        print(f"  modelo {k:13} {v or 'no se usa'}")
    for k in ("sheet_preset", "editor_rounds", "preview_iterations", "music", "reel", "research_subagents", "window_budget"):
        print(f"  {k:19} {p[k]}")
    print(f"  música: {costmode.MUSIC_POLICY[p['music']]}")


def render(mode, a):
    proj = find_project(a.project)
    cfg = load(proj)
    g = proj / cfg.get("guion", "guion.json")
    if not g.exists():
        print(f"Falta {g}: el director debe escribir la lista de cortes (guion.json) a partir de DIRECTION.md, el triage y los beats. Este paso lo decide Claude, no un script.")
        return 4
    run([PY, PIPE / "render.py", g, mode])


def cmd_preview(a):
    return render("preview", a)


def cmd_final(a):
    return render("final", a)


def output_entries(cfg):
    out = []
    for e in cfg.get("outputs") or []:
        if isinstance(e, dict):
            out.append((e["preset"], e.get("guion")))
        elif isinstance(e, str) and e in presets.ALL:
            out.append((e, None))
    return out


def cmd_render(a):
    proj = find_project(a.project)
    cfg = load(proj)
    entries = [(p, None) for p in a.presets] if a.presets else output_entries(cfg)
    if not entries:
        die("sin presets: pasalos como argumento o listalos en outputs: de project.yaml")
    for preset, guion_rel in entries:
        if preset not in presets.ALL:
            die(f"preset desconocido '{preset}' (válidos: {', '.join(presets.ALL)})")
        g = proj / (guion_rel or cfg.get("guion", "guion.json"))
        if not g.exists():
            die(f"falta {g} para el preset {preset}")
        run([PY, PIPE / "render.py", g, preset])


def cmd_status(a):
    proj = find_project(a.project)
    cfg = load_checked(proj)
    st = workflow.compute(proj, cfg)
    print(workflow.format_text(proj, cfg, st))
    workflow.write_status(proj, cfg, st)
    print(f"escrito {proj / workflow.STATUS_FILE}")


CLEAN_CLASSES = {
    "segcache": "segmentos cacheados (build/final, build/preview, build/test, build/celu, build/chat, build/reel)",
    "proxies": "proxies",
    "sheets": "hojas de contacto",
    "review": "tiras de review (build/review-*.jpg)",
    "previews": "videos de preview (no listados en outputs)",
}


def preset_files(proj, cfg, preset, guion_rel):
    g = proj / (guion_rel or cfg.get("guion", "guion.json"))
    name, out_dir = cfg.get("name"), proj
    if g.exists():
        raw = json.loads(g.read_text())
        name = raw.get("name", name)
        out_dir = (g.parent / raw["out_dir"]).resolve() if "out_dir" in raw else proj
    files = {(out_dir / f"{name}-{preset}.mp4").resolve()}
    if preset == "tv":
        files.add((out_dir / f"{name}-final.mp4").resolve())
    return files


def declared_outputs(proj, cfg):
    outs = {(proj / o).resolve() for o in cfg.get("outputs", []) if isinstance(o, str) and o.endswith(".mp4")}
    for preset, guion_rel in output_entries(cfg):
        outs |= preset_files(proj, cfg, preset, guion_rel)
    if outs:
        return outs
    name = cfg.get("name")
    g = proj / cfg.get("guion", "guion.json")
    out_dir = proj
    if g.exists():
        raw = json.loads(g.read_text())
        name = raw.get("name", name)
        out_dir = (g.parent / raw.get("out_dir", ".")).resolve() if "out_dir" in raw else proj
    return {(out_dir / f"{name}-final.mp4").resolve()} if name else set()


def clean_targets(proj, cfg):
    build = proj / "build"
    exports = declared_outputs(proj, cfg)
    t = {
        "segcache": [build / d for d in ("final", "preview", "test", "celu", "chat", "reel")],
        "proxies": [proj / cfg.get("proxy_dir", "proxy")],
        "sheets": [proj / "sheets"],
        "review": sorted(build.glob("review-*.jpg")) if build.exists() else [],
        "previews": [p for p in sorted(list(proj.glob("*-preview.mp4")) + list(build.glob("*-preview.mp4"))) if p.resolve() not in exports],
    }
    return {k: [p for p in v if p.exists()] for k, v in t.items()}, exports


def protected_roots(proj):
    m = sources.load(proj)
    return [pathlib.Path(r["path"]).resolve() for r in m["roots"].values()]


def cmd_clean(a):
    proj = find_project(a.project)
    cfg = load(proj)
    targets, exports = clean_targets(proj, cfg)
    drop = set(x for v in (a.drop or []) for x in v.split(",") if x)
    keep = set(x for v in (a.keep or []) for x in v.split(",") if x)
    bad = (drop | keep) - set(CLEAN_CLASSES)
    if bad:
        die(f"clase desconocida: {', '.join(sorted(bad))}. Válidas: {', '.join(CLEAN_CLASSES)}")
    drop -= keep
    guards = protected_roots(proj)
    rows, total = [], 0
    for cls, paths in targets.items():
        n = sum(tree_size(p) for p in paths)
        total += n
        rows.append((cls, n, paths))
    print(f"{'clase':10} {'tamaño':>9}  qué")
    for cls, n, paths in rows:
        verb = ("se borra" if a.apply else "se borraría") if cls in drop else "se conserva"
        print(f"{cls:10} {gb(n):>9}  {CLEAN_CLASSES[cls]} [{verb}]")
    for e in sorted(exports):
        print(f"{'export':10} {gb(tree_size(e)) if e.exists() else '(no existe)':>9}  {e.relative_to(proj) if e.is_relative_to(proj) else e} [se conserva siempre]")
    print(f"Derivados regenerables: {gb(total)}. Raíces de fuentes (intocables): {len(guards)}")
    if not a.apply:
        print("Dry-run: no se borró nada. Para borrar: `vlog clean --apply --drop segcache,proxies` (--keep excluye clases).")
        return 0
    if not drop:
        die("--apply exige --drop con al menos una clase")
    freed = 0
    for cls, n, paths in rows:
        if cls not in drop:
            continue
        for p in paths:
            rp = p.resolve()
            if not rp.is_relative_to(proj.resolve()) or rp in exports or any(rp == g or g in rp.parents or rp in g.parents for g in guards):
                print(f"salteo {p}: toca una fuente, un export o sale del proyecto")
                continue
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            freed += 1
    print(f"Borrados {freed} elemento(s) derivados; fuentes y exports intactos.")
    return 0


def cmd_sources(a):
    proj = find_project(a.project)
    return sources.dispatch(a, proj, load(proj))


def parser():
    p = argparse.ArgumentParser(prog="vlog", description="vlog-pipeline: videos de viaje desde material en bruto. Cada subcomando es una etapa idempotente; `vlog status` dice cuál sigue.")
    p.add_argument("--project", "-p")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="crea un proyecto (carpeta, project.yaml, DIRECTION.md) y chequea el espacio en disco")
    n.add_argument("name")
    new_help = {"theme": "tema o brief en una frase", "minutes": "duración objetivo en minutos", "audience": "para quién es", "res": "resolución del master, ANCHOxALTO",
                "fps": "cuadros por segundo (fracción o número)", "tz": "zona horaria de las fotos y videos, +HH:MM", "root": "carpeta que contiene los proyectos",
                "drone": "carpeta o tarjeta del dron (solo lectura)", "album": "zip del álbum de Google Photos", "cost_mode": "standard o low"}
    for k, h in new_help.items():
        n.add_argument(f"--{k.replace('_', '-')}", dest=k, help=h)
    n.add_argument("--yes", action="store_true", help="no preguntar: usar los valores dados o los de fábrica")
    n.set_defaults(f=cmd_new)
    sub.add_parser("doctor", help="revisa las herramientas, dependencias y datos que necesita el pipeline").set_defaults(f=cmd_doctor)
    cf = sub.add_parser("config", help="imprime la configuración fusionada (defaults + usuario + proyecto)")
    cf.add_argument("key", nargs="?")
    cf.add_argument("--defaults", action="store_true")
    cf.set_defaults(f=cmd_config)
    fd = sub.add_parser("fetch-data", help="baja los GeoJSON de Natural Earth para el minimapa")
    fd.add_argument("--force", action="store_true")
    fd.set_defaults(f=cmd_fetch_data)
    om = sub.add_parser("osm", help="baja calles de los pueblos listados en osm.towns (Overpass)")
    om.add_argument("--force", action="store_true")
    om.add_argument("--only", action="append")
    om.set_defaults(f=cmd_osm)
    r = sub.add_parser("rutas", help="exporta del teléfono (adb) o importa con --file la ruta de Google Maps y la procesa")
    r.add_argument("--from", dest="date_from", required=True)
    r.add_argument("--to", dest="date_to", required=True)
    r.add_argument("--file")
    r.add_argument("--force", action="store_true")
    r.set_defaults(f=cmd_rutas)
    al = sub.add_parser("album", help="descomprime el zip del álbum fuera del proyecto y verifica la cuenta")
    al.add_argument("zip")
    al.add_argument("--force", action="store_true")
    al.set_defaults(f=cmd_album)
    i = sub.add_parser("ingest", help="inventario del dron y unificación con el álbum en inv/media.json")
    i.add_argument("--src")
    i.add_argument("--force", action="store_true")
    i.add_argument("extra", nargs=argparse.REMAINDER)
    i.set_defaults(f=cmd_ingest)
    sub.add_parser("proxies", help="proxies livianos de los videos del dron").set_defaults(f=cmd_proxies)
    pf = sub.add_parser("prefilter", help="descarta sin LLM lo borroso, ráfagas, duplicados, capturas y lo fuera de fechas")
    pf.add_argument("--force", action="store_true")
    pf.set_defaults(f=cmd_prefilter)
    s = sub.add_parser("sheets", help="hojas de contacto para el triage")
    s.add_argument("--preset", choices=("standard", "low"))
    s.add_argument("--survivors", action="store_true")
    s.add_argument("--out")
    s.add_argument("--no-prefilter", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument("--verbose", "-v", action="store_true")
    s.set_defaults(f=cmd_sheets)
    tp = sub.add_parser("triage-plan", help="imprime un prompt por grupo y lista lo que falta del triage")
    tp.add_argument("--pass", dest="pass_no", type=int, choices=(1, 2), required=True)
    tp.add_argument("--day")
    tp.add_argument("--all", action="store_true")
    tp.add_argument("--no-prompt", action="store_true")
    tp.set_defaults(f=cmd_triage_plan)
    sub.add_parser("triage-merge", help="junta las dos pasadas del triage en triage/merged.json").set_defaults(f=cmd_triage_merge)
    sub.add_parser("sharpness", help="mide nitidez y agrupa variantes").set_defaults(f=cmd_sharpness)
    ap = sub.add_parser("approve", help="registra el OK del dueño a una etapa")
    ap.add_argument("gate", choices=("preview",))
    ap.set_defaults(f=cmd_approve)
    sub.add_parser("profile", help="muestra el perfil del modo de costo vigente").set_defaults(f=cmd_profile)
    ec = sub.add_parser("edl-check", help="valida la EDL contra el brief y el triage")
    ec.add_argument("--edl")
    ec.set_defaults(f=cmd_edl_check)
    pr = sub.add_parser("prompt", help="imprime una plantilla de prompt rellena con los datos del proyecto")
    pr.add_argument("name", choices=prompts.NAMES)
    pr.set_defaults(f=cmd_prompt)
    sub.add_parser("preview", help="renderiza el preview de baja resolución").set_defaults(f=cmd_preview)
    sub.add_parser("final", help="renderiza el master en la resolución final").set_defaults(f=cmd_final)
    rd = sub.add_parser("render", help="renderiza las salidas declaradas en outputs (tv, celu, chat, reel)")
    rd.add_argument("presets", nargs="*")
    rd.set_defaults(f=cmd_render)
    sub.add_parser("status", help="etapa actual, siguiente paso y tokens estimados; escribe STATUS.md").set_defaults(f=cmd_status)
    sp = sub.add_parser("sources", help="manifiesto de fuentes: build, list, check, relink, add")
    sources.add_args(sp)
    sp.set_defaults(f=cmd_sources)
    c = sub.add_parser("clean", help="lista y borra derivados regenerables (simulacro por defecto)")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--apply", action="store_true")
    c.add_argument("--drop", action="append")
    c.add_argument("--keep", action="append")
    c.set_defaults(f=cmd_clean)
    return p


def main():
    a = parser().parse_args()
    sys.exit(a.f(a) or 0)


if __name__ == "__main__":
    main()
