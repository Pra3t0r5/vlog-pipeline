import argparse
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import config


def query(lat, lon, r):
    bb = f"{lat - r},{lon - r},{lat + r},{lon + r}"
    return (f'[out:json][timeout:60];(way["highway"]({bb});way["leisure"~"park|garden"]({bb});way["landuse"~"grass|recreation_ground"]({bb});'
            f'way["natural"="water"]({bb});way["waterway"~"river|stream|canal"]({bb}););out geom;')


def fetch(name, town, out_dir):
    lat, lon, r = town
    req = urllib.request.Request(config.get("http.overpass_url"), data=urllib.parse.urlencode({"data": query(lat, lon, r)}).encode(), headers={"User-Agent": config.user_agent()})
    els = json.load(urllib.request.urlopen(req, timeout=90))["elements"]
    res = {"roads": [], "parks": [], "water": [], "center": [lat, lon], "r": r}
    for e in els:
        g = [[p["lon"], p["lat"]] for p in e.get("geometry", [])]
        t = e.get("tags", {})
        if len(g) < 2:
            continue
        if "highway" in t:
            res["roads"].append([t["highway"], g])
        elif "waterway" in t or t.get("natural") == "water":
            res["water"].append(g)
        else:
            res["parks"].append(g)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(res, separators=(",", ":")))
    return {k: len(v) for k, v in res.items() if isinstance(v, list)}


def main(argv):
    ap = argparse.ArgumentParser(prog="osm_fetch", description="Baja las calles, parques y agua de los pueblos listados en osm.towns de project.yaml, desde Overpass")
    ap.add_argument("--project", required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", action="append", default=[])
    a = ap.parse_args(argv)
    cfg = config.activate_project(a.project)
    towns = cfg["osm"]["towns"]
    if not towns:
        sys.exit("osm.towns está vacío en project.yaml: definí {nombre: [lat, lon, radio_en_grados]} (ver docs/CONFIG.md)")
    out_dir = config.vendor_path("osm_dir", "osm")
    for name, town in towns.items():
        if a.only and name not in a.only:
            continue
        if (out_dir / f"{name}.json").exists() and not a.force:
            print(name, "ya existe")
            continue
        for attempt in range(3):
            try:
                print(name, fetch(name, town, out_dir))
                break
            except Exception as ex:
                print(name, "error", ex)
                time.sleep(30)
        time.sleep(3)


if __name__ == "__main__":
    main(sys.argv[1:])
