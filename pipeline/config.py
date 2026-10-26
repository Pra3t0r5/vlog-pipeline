import copy
import os
import pathlib
import sys
import time

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULTS_FILE = REPO / "config" / "defaults.yaml"
USER_FILE = pathlib.Path.home() / ".config" / "vlog-pipeline" / "config.yaml"
VERSION = "0.1.0"
NE_FILES = ("ne_10m_roads.geojson", "ne_10m_admin_1_states_provinces.geojson", "ne_10m_populated_places_simple.geojson")

_base = None
_active = None
_warned = set()


class ConfigError(Exception):
    pass


def deep_merge(base, over):
    if not isinstance(base, dict) or not isinstance(over, dict):
        return copy.deepcopy(over)
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_yaml(path):
    p = pathlib.Path(path)
    try:
        data = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        raise ConfigError(f"{p}: YAML inválido: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{p}: la raíz debe ser un mapa")
    return data


def user_file():
    env = os.environ.get("VLOG_CONFIG")
    if env:
        return pathlib.Path(env).expanduser()
    return USER_FILE if USER_FILE.exists() else None


def defaults():
    return copy.deepcopy(_defaults_cached())


_defaults_cache = None


def _defaults_cached():
    global _defaults_cache
    if _defaults_cache is None:
        _defaults_cache = load_yaml(DEFAULTS_FILE)
    return _defaults_cache


def base():
    global _base
    if _base is None:
        cfg = defaults()
        uf = user_file()
        if uf is not None:
            if not uf.exists():
                raise ConfigError(f"VLOG_CONFIG apunta a {uf}, que no existe")
            cfg = deep_merge(cfg, load_yaml(uf))
        _base = cfg
    return copy.deepcopy(_base)


def build(project_cfg=None):
    return deep_merge(base(), project_cfg or {})


def activate(project_cfg=None):
    global _active
    _active = build(project_cfg)
    return _active


def reset():
    global _base, _active, _defaults_cache
    _base = _active = _defaults_cache = None


def active():
    global _active
    if _active is None:
        _active = build(None)
    return _active


def get(path, default=None, cfg=None):
    cur = active() if cfg is None else cfg
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


def section(name, cfg=None):
    src = active() if cfg is None else cfg
    return copy.deepcopy(src.get(name) or {})


def base_section(name):
    return base().get(name) or {}


def load_project(proj):
    p = pathlib.Path(proj) / "project.yaml"
    return load_yaml(p) if p.exists() else {}


def activate_project(proj):
    return activate(load_project(proj))


def repo_path(rel):
    p = pathlib.Path(rel).expanduser()
    return p if p.is_absolute() else REPO / p


def vendor_path(key, sub):
    explicit = get(f"paths.{key}")
    if explicit:
        return repo_path(explicit)
    return repo_path(get("paths.vendor_dir", "vendor")) / sub


def projects_root():
    env = os.environ.get("VLOG_ROOT")
    if env:
        return pathlib.Path(env).expanduser()
    root = get("paths.root")
    return pathlib.Path(root).expanduser() if root else pathlib.Path.home() / "vlogs"


def font(kind="main"):
    cfg = active()
    fonts = cfg.get("fonts") or {}
    chosen = fonts.get(kind) or fonts.get("main")
    if chosen:
        p = pathlib.Path(chosen).expanduser()
        if not p.exists():
            raise ConfigError(f"fonts.{kind}: no existe {p}")
        return str(p)
    for c in fonts.get("candidates") or []:
        if pathlib.Path(c).expanduser().exists():
            return str(pathlib.Path(c).expanduser())
    raise ConfigError("no encuentro ninguna tipografía: definí fonts.main (un .ttf/.ttc) en project.yaml o en la configuración de usuario")


def font_or_none(kind="main"):
    try:
        return font(kind)
    except ConfigError:
        return None


def local_offset():
    off = time.localtime().tm_gmtoff
    sign = "+" if off >= 0 else "-"
    off = abs(off)
    return f"{sign}{off // 3600:02d}:{off % 3600 // 60:02d}"


def timezone_offset(cfg=None):
    tz = get("ingest.tz", None, cfg) or get("timezone", None, cfg)
    return str(tz) if tz else local_offset()


def tzinfo(offset):
    import datetime as D
    s = str(offset)
    if len(s) != 6 or s[0] not in "+-" or s[3] != ":":
        raise ConfigError(f"zona horaria inválida '{offset}': usá +HH:MM o -HH:MM")
    sign = -1 if s[0] == "-" else 1
    return D.timezone(sign * D.timedelta(hours=int(s[1:3]), minutes=int(s[4:6])))


def user_agent():
    ua = f"vlog-pipeline/{VERSION}"
    contact = get("http.contact")
    if contact:
        return f"{ua} ({contact})"
    if "ua" not in _warned:
        _warned.add("ua")
        print("aviso: http.contact no está definido; los servicios públicos (Nominatim, Overpass, OSRM) piden un User-Agent que identifique a quien consulta", file=sys.stderr)
    return ua


def constants(name, cfg=None):
    return {k.upper(): v for k, v in section(name, cfg).items() if not isinstance(v, (dict, list))}
