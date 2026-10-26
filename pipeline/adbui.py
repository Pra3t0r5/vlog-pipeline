import re
import subprocess
import time
import xml.etree.ElementTree as ET

import config

_ADB = config.base_section("adb")
EXPORT_LABEL = _ADB["export_label"]
ENTRY_LABEL = _ADB["entry_label"]
FORBIDDEN = tuple(_ADB["forbidden_words"])
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
FILE_PATTERNS = (re.compile(_ADB["file_pattern"], re.I),)


class Abort(Exception):
    pass


def parse_dump(xml_text):
    nodes = []
    for el in ET.fromstring(xml_text).iter("node"):
        m = BOUNDS.fullmatch(el.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        nodes.append({
            "text": el.get("text", ""),
            "desc": el.get("content-desc", ""),
            "bounds": (x1, y1, x2, y2),
            "clickable": el.get("clickable") == "true",
        })
    return nodes


def forbidden_words():
    return tuple(w.lower() for w in config.get("adb.forbidden_words", FORBIDDEN))


def is_forbidden(s):
    low = s.lower()
    return any(w in low for w in forbidden_words())


def find_exact(nodes, label):
    return [n for n in nodes if n["text"].strip() == label]


def center(node):
    x1, y1, x2, y2 = node["bounds"]
    return (x1 + x2) // 2, (y1 + y2) // 2


def covering(nodes, x, y):
    return [n for n in nodes if n["bounds"][0] <= x <= n["bounds"][2] and n["bounds"][1] <= y <= n["bounds"][3]]


def safe_tap_point(nodes, label):
    hits = find_exact(nodes, label)
    if not hits:
        raise Abort(f"no encontré el elemento exacto '{label}'")
    if len(hits) > 1:
        raise Abort(f"'{label}' aparece {len(hits)} veces; no sé cuál tocar")
    target = hits[0]
    if is_forbidden(target["text"]) or is_forbidden(target["desc"]):
        raise Abort(f"el objetivo '{target['text']}' contiene un texto prohibido")
    x, y = center(target)
    for n in covering(nodes, x, y):
        if is_forbidden(n["text"]) or is_forbidden(n["desc"]):
            raise Abort(f"el punto ({x},{y}) cae sobre '{n['text'] or n['desc']}': aborto sin tocar")
    return x, y


class Adb:
    def __init__(self, serial=None, runner=None):
        self.base = ["adb"] + (["-s", serial] if serial else [])
        self.runner = runner or self._run

    def _run(self, args, timeout=60):
        r = subprocess.run(self.base + args, capture_output=True, text=True, timeout=timeout)
        if r.returncode:
            raise Abort(f"adb {' '.join(args)}: {r.stderr.strip()[-300:]}")
        return r.stdout

    def __call__(self, *args, timeout=60):
        return self.runner(list(args), timeout)

    def dump(self):
        self("shell", "uiautomator", "dump", "/sdcard/vlog_ui.xml")
        return parse_dump(self("exec-out", "cat", "/sdcard/vlog_ui.xml"))

    def tap_label(self, label):
        x, y = safe_tap_point(self.dump(), label)
        self("shell", "input", "tap", str(x), str(y))
        return x, y


def list_downloads(adb):
    out = adb("shell", "ls", config.get("route.device_dir", "/sdcard/Download"))
    return {l.strip() for l in out.splitlines() if l.strip()}


def matching(names):
    pats = (re.compile(config.get("adb.file_pattern"), re.I),) if config.get("adb.file_pattern") else FILE_PATTERNS
    return {n for n in names if any(p.match(n) for p in pats)}


def device_ready(devices_output):
    lines = [l.split() for l in devices_output.splitlines()[1:] if l.strip()]
    ok = [l[0] for l in lines if len(l) > 1 and l[1] == "device"]
    if len(ok) != 1:
        raise Abort(f"se necesita exactamente un teléfono autorizado por adb; hay {len(ok)}")
    return ok[0]


def export_timeline(adb, timeout=None, poll=3, sleep=time.sleep, now=time.monotonic):
    timeout = timeout if timeout is not None else config.get("adb.timeout_s", 180)
    before = matching(list_downloads(adb))
    adb("shell", "am", "start", "-a", config.get("adb.settings_action", "android.settings.LOCATION_SOURCE_SETTINGS"))
    sleep(2)
    adb.tap_label(config.get("adb.entry_label", ENTRY_LABEL))
    sleep(2)
    adb.tap_label(config.get("adb.export_label", EXPORT_LABEL))
    end = now() + timeout
    while now() < end:
        fresh = matching(list_downloads(adb)) - before
        if fresh:
            return sorted(fresh)[-1]
        sleep(poll)
    raise Abort(f"no apareció un archivo nuevo en {config.get('route.device_dir', '/sdcard/Download')}; si el teléfono pide confirmar el guardado, hacelo a mano y repetí")
