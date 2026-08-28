import pcbnew, json
mm=lambda v: v/1e6
out={}
for b in ("left","right","daughterboard"):
    bd=pcbnew.LoadBoard(f"pcb/hhkb_split_{b}.kicad_pcb"); fps=[]
    for f in bd.GetFootprints():
        pads=[{"n":p.GetNumber(),"x":mm(p.GetPosition().x),"y":mm(p.GetPosition().y),"sx":mm(p.GetSize().x),"sy":mm(p.GetSize().y),"rot":p.GetOrientationDegrees(),"net":p.GetNetname(),"layer":p.GetLayerName() if p.GetAttribute()!=pcbnew.PAD_ATTRIB_PTH else "PTH"} for p in f.Pads()]
        bb=f.GetBoundingBox()
        fps.append({"ref":f.GetReference(),"val":f.GetValue(),"layer":f.GetLayerName(),"x":mm(f.GetPosition().x),"y":mm(f.GetPosition().y),"rot":f.GetOrientationDegrees(),"bbox":[mm(bb.GetLeft()),mm(bb.GetTop()),mm(bb.GetRight()),mm(bb.GetBottom())],"pads":pads})
    out[b]=fps
json.dump(out,open("build/fab_check/pads.json","w"),ensure_ascii=False)
print({k:len(v) for k,v in out.items()})
