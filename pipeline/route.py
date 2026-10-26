import json, re, sys
src, lo, hi, outdir = sys.argv[1:5]
ll = lambda s: tuple(float(x) for x in re.findall(r"-?\d+\.\d+", s)[:2])
d = json.load(open(src)); segs = d["semanticSegments"] if isinstance(d, dict) else d
segs = [s for s in segs if lo <= s.get("startTime", "")[:10] <= hi]
pts, visits, acts = [], [], []
for s in segs:
    for p in s.get("timelinePath", []): pts.append((p["time"], *ll(p["point"])))
    if "visit" in s:
        c = s["visit"]["topCandidate"]
        visits.append({"start": s["startTime"], "end": s["endTime"], "type": c.get("semanticType"), "place_id": c.get("placeId"), "lat": ll(c["placeLocation"]["latLng"])[0], "lon": ll(c["placeLocation"]["latLng"])[1]})
    if "activity" in s:
        a = s["activity"]; acts.append({"start": s["startTime"], "type": a.get("topCandidate", {}).get("type"), "km": round(a.get("distanceMeters", 0) / 1000, 1)})
pts.sort()
json.dump({"points": pts, "visits": visits, "activities": acts}, open(f"{outdir}/route.json", "w"), indent=1)
gpx = "".join(f'<trkpt lat="{a}" lon="{b}"><time>{t}</time></trkpt>' for t, a, b in pts)
open(f"{outdir}/route.gpx", "w").write(f'<?xml version="1.0"?><gpx version="1.1" creator="pipeline"><trk><trkseg>{gpx}</trkseg></trk></gpx>')
print(len(pts), "puntos", len(visits), "visitas", len(acts), "traslados")
from collections import Counter
print(Counter(a["type"] for a in acts).most_common())
for day in sorted({v["start"][:10] for v in visits}):
    print(day, sum(1 for v in visits if v["start"][:10] == day), "visitas;", round(sum(a["km"] for a in acts if a["start"][:10] == day)), "km")
