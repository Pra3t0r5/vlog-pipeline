import sys, json, time
import numpy as np, librosa
HOP=256
def analyze(path, sr=22050, beats_per_bar=4):
    t0=time.time()
    y,_=librosa.load(path,sr=sr,mono=True)
    oenv=librosa.onset.onset_strength(y=y,sr=sr,hop_length=HOP)
    tempo,bf=librosa.beat.beat_track(onset_envelope=oenv,sr=sr,hop_length=HOP,units='frames',tightness=100,trim=False)
    bf=np.asarray(bf)
    w=int(0.06*sr/HOP)
    ref=[]
    for f in bf:
        lo,hi=max(0,f-w),min(len(oenv),f+w+1)
        ref.append(lo+int(np.argmax(oenv[lo:hi])))
    bf=np.array(ref)
    bt=librosa.frames_to_time(bf,sr=sr,hop_length=HOP)
    bpm=float(60/np.polyfit(np.arange(len(bt)),bt,1)[0]) if len(bt)>2 else float(np.atleast_1d(tempo)[0])
    downbeats=[]
    if len(bf)>=beats_per_bar:
        rms=librosa.feature.rms(y=y,hop_length=HOP)[0]
        S=np.array([rms[f:f+int(0.05*sr/HOP)+1].max() for f in bf])
        best=max(range(beats_per_bar),key=lambda k:S[k::beats_per_bar].mean())
        downbeats=bt[best::beats_per_bar]
    return {"bpm":round(bpm,2),"beats":[round(float(x),3) for x in bt],
            "downbeats":[round(float(x),3) for x in downbeats],"elapsed_s":round(time.time()-t0,2)}
if __name__=="__main__":
    print(json.dumps(analyze(sys.argv[1])))
