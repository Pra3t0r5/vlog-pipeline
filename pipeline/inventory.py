import json, re, subprocess, sys, math, pathlib
from fractions import Fraction
if len(sys.argv) != 3 or sys.argv[1] in ("-h", "--help"):
    sys.exit("uso: inventory.py carpeta_del_dron salida.json")
root, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
num = lambda k, s: [float(x) for x in re.findall(rf"\[{k}\s*:\s*(-?[\d.]+)", s)]
def hav(a, b):
    R = 6371000; p1, p2 = map(math.radians, (a[0], b[0])); dl = math.radians(b[1] - a[1]); dp = p2 - p1
    return 2 * R * math.asin(math.sqrt(math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2))
rows = []
for v in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".mp4" and not p.name.startswith("._")):
    p = json.loads(subprocess.run(["ffprobe","-v","error","-select_streams","v:0","-show_entries","format=duration,size:stream=width,height,r_frame_rate","-of","json",str(v)],capture_output=True,text=True).stdout)
    r = {"kind":"video","path":str(v),"dur":round(float(p["format"]["duration"]),1),"gb":round(int(p["format"]["size"])/1e9,2),
         "res":f'{p["streams"][0]["width"]}x{p["streams"][0]["height"]}',"fps":round(float(Fraction(p["streams"][0]["r_frame_rate"])),2)}
    srt = next((c for c in (v.with_suffix(".SRT"), v.with_suffix(".srt")) if c.exists()), None)
    if srt:
        t = srt.read_text(errors="ignore")
        ts = re.findall(r"\n(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", t)
        la, lo, alt = num("latitude", t), num("longitude", t), num("rel_alt", t)
        pts = [(a, b) for a, b in zip(la, lo) if a or b]
        r |= {"start": ts[0] if ts else None, "lat": pts[0][0] if pts else None, "lon": pts[0][1] if pts else None,
              "max_alt": max(alt) if alt else None,
              "travel_m": round(sum(hav(pts[i], pts[i+1]) for i in range(0, len(pts)-30, 30)) if len(pts) > 30 else 0)}
    rows.append(r)
ex = json.loads(subprocess.run(["exiftool","-j","-n","-r","-ext","JPG","-DateTimeOriginal","-GPSLatitude","-GPSLongitude","-RelativeAltitude","-ImageSize",str(root)],capture_output=True,text=True).stdout or "[]")
for e in ex:
    rows.append({"kind":"photo","path":e["SourceFile"],"start":e.get("DateTimeOriginal","").replace(":","-",2),"lat":e.get("GPSLatitude"),"lon":e.get("GPSLongitude"),"max_alt":e.get("RelativeAltitude"),"res":e.get("ImageSize")})
rows.sort(key=lambda r: r.get("start") or "")
out.write_text(json.dumps(rows, indent=1))
print(len(rows), "items")
