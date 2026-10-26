import datetime as D
import hashlib
import json
import os
import pathlib
import plistlib
import re
import subprocess

import config

MANIFEST = "sources.json"
KINDS = ("drone_sd", "album", "phone_export", "notes", "doc", "music")
MEDIA_EXT = {".jpg", ".jpeg", ".png", ".heic", ".gif", ".mp4", ".mov", ".dng", ".srt"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
MTIME_TOL = 2
CHUNK = 1 << 20


class SourcesError(Exception):
    pass


def now():
    return D.datetime.now().astimezone().isoformat(timespec="seconds")


def mount_of(path):
    p = pathlib.Path(path).resolve()
    while not p.exists():
        p = p.parent
    while not os.path.ismount(p):
        p = p.parent
    return p


def volume_info(path):
    try:
        mp = mount_of(path)
        out = subprocess.run(["diskutil", "info", "-plist", str(mp)], capture_output=True)
        d = plistlib.loads(out.stdout) if out.returncode == 0 else {}
        return {"mount": str(mp), "uuid": d.get("VolumeUUID"), "name": d.get("VolumeName")}
    except Exception:
        return {"mount": None, "uuid": None, "name": None}


def quick_hash(path):
    size = os.path.getsize(path)
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read(CHUNK))
        if size > 2 * CHUNK:
            f.seek(size - CHUNK)
            h.update(f.read(CHUNK))
        elif size > CHUNK:
            h.update(f.read())
    return h.hexdigest()


def file_facts(path):
    st = os.stat(path)
    return {"size": st.st_size, "mtime": int(st.st_mtime), "quick_hash": quick_hash(path)}


def manifest_path(proj):
    return pathlib.Path(proj) / MANIFEST


def empty():
    return {"version": 1, "roots": {}, "files": []}


def load(proj):
    p = manifest_path(proj)
    return json.loads(p.read_text()) if p.exists() else empty()


def save(proj, m):
    p = manifest_path(proj)
    tmp = p.with_suffix(".json.part")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1))
    tmp.replace(p)


def ensure_root(m, kind, path, rid=None):
    if kind not in KINDS:
        raise SourcesError(f"tipo de raíz inválido '{kind}': {', '.join(KINDS)}")
    path = str(pathlib.Path(path).expanduser().resolve())
    for k, r in m["roots"].items():
        if r["kind"] == kind and path in (r["path"], r["origin"]):
            return k
    rid = rid or kind
    base, n = rid, 1
    while rid in m["roots"]:
        n += 1
        rid = f"{base}{n}"
    vol = volume_info(path)
    m["roots"][rid] = {"kind": kind, "path": path, "origin": path, "volume_uuid": vol["uuid"], "volume_name": vol["name"], "added_at": now()}
    return rid


def root_dir(m, rid):
    if rid not in m["roots"]:
        raise SourcesError(f"no existe la raíz '{rid}' (hay: {', '.join(m['roots']) or 'ninguna'})")
    return pathlib.Path(m["roots"][rid]["path"])


def split(m, abspath):
    ap = str(abspath)
    best = None
    for rid, r in m["roots"].items():
        for base in (r["origin"], r["path"]):
            if ap == base or ap.startswith(base.rstrip("/") + "/"):
                if best is None or len(base) > len(best[1]):
                    best = (rid, base)
    if not best:
        return None
    return best[0], os.path.relpath(ap, best[1])


def index_file(m, abspath, fid=None):
    sp = split(m, abspath)
    if not sp:
        raise SourcesError(f"{abspath} no cuelga de ninguna raíz")
    rid, rel = sp
    real = root_dir(m, rid) / rel
    if not real.exists():
        raise SourcesError(f"no está alcanzable: {real}")
    fid = fid or f"{rid}:{rel}"
    rec = {"id": fid, "root": rid, "relpath": rel, **file_facts(real)}
    idx = {f["id"]: i for i, f in enumerate(m["files"])}
    if fid in idx:
        m["files"][idx[fid]] = rec
    else:
        m["files"].append(rec)
    return rec


class Resolver:
    def __init__(self, m):
        self.m = m

    @classmethod
    def for_project(cls, proj):
        return cls(load(proj))

    @classmethod
    def from_manifest(cls, path):
        p = pathlib.Path(path)
        return cls(json.loads(p.read_text()) if p.exists() else empty())

    def path(self, rec_or_path):
        if isinstance(rec_or_path, dict):
            rec = rec_or_path
            rid, rel = rec.get("root"), rec.get("relpath")
            if rid in self.m["roots"] and rel:
                return str(root_dir(self.m, rid) / rel)
            p = rec["path"]
        else:
            p = str(rec_or_path)
        sp = split(self.m, p)
        if not sp:
            return p
        return str(root_dir(self.m, sp[0]) / sp[1])

    def annotate(self, rec):
        sp = split(self.m, rec["path"])
        if sp:
            rec["root"], rec["relpath"] = sp
            rec["path"] = self.path(rec)
        return rec


def common_root(paths, marker=None):
    parts = [pathlib.Path(p).parts for p in paths]
    if not parts:
        return None
    first = pathlib.Path(os.path.commonpath([str(pathlib.Path(p).parent) for p in paths]))
    if marker and marker in first.parts:
        i = first.parts.index(marker)
        return pathlib.Path(*first.parts[:i + 1])
    return first


def walk_files(root, exts):
    for p in sorted(pathlib.Path(root).rglob("*")):
        if p.is_file() and p.suffix.lower() in exts and not p.name.startswith("._") and p.name != ".DS_Store":
            yield p


def build(proj, cfg, log=print):
    proj = pathlib.Path(proj)
    m = load(proj)
    skipped = []
    media_p = proj / cfg.get("media", "inv/media.json")
    if media_p.exists():
        recs = json.loads(media_p.read_text())
        drone = [r["path"] for r in recs if r.get("source") == "drone"]
        if drone:
            ensure_root(m, "drone_sd", common_root(drone, "DCIM"))
        others = [r["path"] for r in recs if r.get("source") != "drone"]
        if others:
            if not any(r["kind"] == "album" for r in m["roots"].values()):
                ensure_root(m, "album", album_dir(proj, cfg, m) or common_root(others))
        for r in recs:
            try:
                index_file(m, r["path"], r.get("id"))
            except SourcesError as e:
                skipped.append(str(e))
    route = proj / "route" / config.get("route.export_file", "Rutas.json")
    if route.exists():
        ensure_root(m, "phone_export", route.parent)
        index_file(m, route)
    nd = proj / "notes"
    if nd.exists() and any(p.is_file() for p in nd.iterdir()):
        ensure_root(m, "notes", nd)
        for p in sorted(nd.iterdir()):
            if p.is_file() and p.name != ".DS_Store" and not p.name.startswith("._") and p.name != "chronology.json":
                index_file(m, p)
    md = proj / "music"
    if md.exists():
        files = list(walk_files(md, AUDIO_EXT))
        if files:
            ensure_root(m, "music", md)
            for p in files:
                index_file(m, p)
    save(proj, m)
    log(f"sources.json: {len(m['roots'])} raíces, {len(m['files'])} archivos")
    for s in skipped[:10]:
        log(f"  omitido: {s}")
    if len(skipped) > 10:
        log(f"  ... y {len(skipped) - 10} más omitidos")
    return m


def album_dir(proj, cfg, m=None):
    m = m if m is not None else load(proj)
    for r in m["roots"].values():
        if r["kind"] == "album":
            return pathlib.Path(r["path"])
    legacy = pathlib.Path(proj) / "album"
    if legacy.is_dir() and any(legacy.iterdir()):
        return legacy
    return None


def originals_base(proj, st):
    if st.get("originals_dir"):
        return pathlib.Path(st["originals_dir"]).expanduser()
    name = config.get("paths.originals_dirname", "originales")
    mount = mount_of(proj)
    if mount == pathlib.Path("/") or mount == pathlib.Path.home():
        return pathlib.Path(proj).resolve().parent / name
    return mount / name


def default_album_target(proj, cfg, zip_path):
    st = cfg.get("storage") or {}
    base = originals_base(proj, st)
    z = pathlib.Path(zip_path)
    ym = D.datetime.fromtimestamp(z.stat().st_mtime).strftime("%Y-%m")
    name = st.get("album_name") or re.sub(r"-\d+-\d+$", "", z.stem)
    return base / f"{ym} {name}"


def check(proj, deep=False, log=print):
    m = load(proj)
    if not m["files"]:
        log("sources.json vacío o inexistente: corré `vlog sources build`")
        return 2
    by_root = {}
    for f in m["files"]:
        by_root.setdefault(f["root"], []).append(f)
    problems = 0
    for rid, files in by_root.items():
        r = m["roots"][rid]
        base = pathlib.Path(r["path"])
        head = f"[{rid}] {r['kind']} {base} ({len(files)} archivos)"
        if not base.exists():
            vol = f"volumen '{r.get('volume_name')}'" if r.get("volume_name") else "el volumen"
            log(f"[FALTA] {head}: raíz no alcanzable, ¿{vol} sin montar?")
            problems += len(files)
            continue
        vol = volume_info(base)
        if r.get("volume_uuid") and vol["uuid"] and vol["uuid"] != r["volume_uuid"]:
            log(f"[aviso] {head}: el volumen es otro (UUID {vol['uuid']} ≠ {r['volume_uuid']}); revisá que sea el mismo disco o tarjeta")
        missing, changed = [], []
        for f in files:
            p = base / f["relpath"]
            try:
                st = p.stat()
            except OSError:
                missing.append(f["relpath"])
                continue
            if st.st_size != f["size"] or abs(int(st.st_mtime) - f["mtime"]) > MTIME_TOL:
                changed.append(f["relpath"])
            elif deep and quick_hash(p) != f["quick_hash"]:
                changed.append(f["relpath"])
        problems += len(missing) + len(changed)
        ok = len(files) - len(missing) - len(changed)
        log(f"[{'ok' if ok == len(files) else 'FALTA'}] {head}: {ok} ok, {len(missing)} faltan, {len(changed)} cambiados")
        for tag, lst in (("falta", missing), ("cambió", changed)):
            for x in lst[:5]:
                log(f"    {tag}: {x}")
            if len(lst) > 5:
                log(f"    ... {len(lst) - 5} más")
    log("Todo alcanzable y sin cambios." if not problems else f"{problems} problema(s).")
    return 1 if problems else 0


def relink(proj, rid, new_path, force=False, log=print):
    m = load(proj)
    if rid not in m["roots"]:
        raise SourcesError(f"no existe la raíz '{rid}' (hay: {', '.join(m['roots']) or 'ninguna'})")
    new = pathlib.Path(new_path).expanduser().resolve()
    if not new.exists():
        raise SourcesError(f"no existe {new}")
    files = [f for f in m["files"] if f["root"] == rid]
    hit = sum(1 for f in files if (new / f["relpath"]).exists())
    if files and hit < len(files) and not force:
        raise SourcesError(f"en {new} están {hit} de {len(files)} archivos de la raíz '{rid}'; no re-apunto (usá --force para hacerlo igual)")
    vol = volume_info(new)
    r = m["roots"][rid]
    log(f"raíz '{rid}': {r['path']} -> {new} ({hit}/{len(files)} archivos presentes)")
    r["path"] = str(new)
    r["volume_uuid"], r["volume_name"] = vol["uuid"], vol["name"]
    r["relinked_at"] = now()
    save(proj, m)
    return m


def show(proj, log=print):
    m = load(proj)
    cnt = {}
    for f in m["files"]:
        cnt[f["root"]] = cnt.get(f["root"], 0) + 1
    for rid, r in m["roots"].items():
        up = "montada" if pathlib.Path(r["path"]).exists() else "NO alcanzable"
        log(f"{rid:14} {r['kind']:13} {cnt.get(rid, 0):5} archivos  {up}  {r['path']}")


def add_args(sp):
    sub = sp.add_subparsers(dest="scmd", required=True)
    sub.add_parser("build")
    sub.add_parser("list")
    c = sub.add_parser("check")
    c.add_argument("--deep", action="store_true")
    r = sub.add_parser("relink")
    r.add_argument("root")
    r.add_argument("path")
    r.add_argument("--force", action="store_true")
    a = sub.add_parser("add")
    a.add_argument("kind", choices=KINDS)
    a.add_argument("path")
    a.add_argument("--root-id")


def dispatch(a, proj, cfg):
    try:
        if a.scmd == "build":
            build(proj, cfg)
        elif a.scmd == "list":
            show(proj)
        elif a.scmd == "check":
            return check(proj, a.deep)
        elif a.scmd == "relink":
            relink(proj, a.root, a.path, a.force)
        elif a.scmd == "add":
            m = load(proj)
            p = pathlib.Path(a.path).expanduser().resolve()
            if p.is_dir():
                rid = ensure_root(m, a.kind, p, a.root_id)
                exts = AUDIO_EXT if a.kind == "music" else MEDIA_EXT | {".md", ".pdf", ".json", ".gpx"}
                for f in walk_files(p, exts):
                    index_file(m, f)
            else:
                rid = ensure_root(m, a.kind, p.parent, a.root_id)
                index_file(m, p)
            save(proj, m)
            print(f"raíz '{rid}' actualizada; {len(m['files'])} archivos indexados en total")
    except SourcesError as e:
        print(f"vlog: {e}")
        return 1
    return 0
