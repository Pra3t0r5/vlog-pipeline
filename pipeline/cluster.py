import json, sys, math, pathlib
from datetime import datetime as D
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config
if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
    sys.exit("uso: cluster.py inventory.json sessions.json [carpeta_del_proyecto]")
rows = json.load(open(sys.argv[1])); out = sys.argv[2]
ING = config.get("ingest") if len(sys.argv) < 4 else config.activate_project(sys.argv[3])["ingest"]
def km(a, b):
    if None in (a.get("lat"), b.get("lat")): return 0
    return math.dist((a["lat"], a["lon"]), (b["lat"], b["lon"])) * 111
cl, cur = [], []
for r in rows:
    if cur and ((D.fromisoformat(r["start"]) - D.fromisoformat(cur[-1]["start"])).total_seconds() > ING["cluster_gap_s"] or km(r, cur[-1]) > ING["cluster_km"]):
        cl.append(cur); cur = []
    cur.append(r)
cl.append(cur)
res = []
for i, c in enumerate(cl):
    v = [r for r in c if r["kind"] == "video"]
    g = [r for r in c if r.get("lat")]
    res.append({"id": f"S{i+1:02d}", "start": c[0]["start"], "end": c[-1]["start"], "videos": len(v), "photos": len(c)-len(v),
                "secs": round(sum(r["dur"] for r in v)), "gb": round(sum(r["gb"] for r in v), 1),
                "lat": round(sum(r["lat"] for r in g)/len(g), 5) if g else None, "lon": round(sum(r["lon"] for r in g)/len(g), 5) if g else None,
                "items": [r["path"].split("/")[-1] for r in c]})
json.dump(res, open(out, "w"), indent=1)
for s in res: print(s["id"], s["start"][:16], "→", s["end"][11:16], f'{s["videos"]:3}v {s["photos"]:2}f {s["secs"]:5}s {s["gb"]:5}GB', s["lat"], s["lon"])
