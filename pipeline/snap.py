import bisect
def snap_shots(shots, beats, downbeats=(), tol=0.6, prefer_downbeat=True):
    out=[]; cursor=beats[0]; db=set(round(d,3) for d in downbeats)
    for s in shots:
        target=cursor+s['dur']; lo=cursor+s.get('min',s['dur']*0.7); hi=cursor+s.get('max',s['dur']*1.3)
        cand=[b for b in beats if lo<=b<=hi and b>cursor]
        if not cand: cand=[min((b for b in beats if b>cursor), key=lambda b:abs(b-target))]
        def cost(b): return abs(b-target)-(tol*0.5 if prefer_downbeat and round(b,3) in db else 0)
        end=min(cand,key=cost); out.append({**s,'start':cursor,'end':end,'dur_snapped':end-cursor}); cursor=end
    return out
if __name__=="__main__":
    p=60/96; beats=[i*p+0.014 for i in range(48)]
    for r in snap_shots([{'dur':3},{'dur':2.2},{'dur':4}],beats,downbeats=beats[::4]): print({k:round(v,3) for k,v in r.items()})
