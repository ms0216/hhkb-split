import trimesh, numpy as np, glob, os, sys
A=sys.argv[1]; half=sys.argv[2]
mine=["joystick","joystick_cap","joystick_tilt","joystick_seat","joystick_collar","joystick_wire","pod_mcu","pod_board"]
mine=[m for m in mine if os.path.exists(A+half+"_"+m+".stl")]
others={os.path.basename(f)[len(half)+1:-4]:trimesh.load(f) for f in glob.glob(A+half+"_*.stl")}
env={n:m for n,m in others.items() if n not in mine and n not in ("switches_real","pcb_real","db_real")}
real={n:others[n] for n in ("pcb_real","switches_real") if n in others}
for m in (sys.argv[3:] or mine):
    a=others[m]; pts=np.vstack([a.vertices,a.sample(4000)]); lo,hi=a.bounds
    hits=[]
    for n,b in env.items():
        if (b.bounds[0]>hi).any() or (b.bounds[1]<lo).any(): continue
        h=0
        for part in b.split(only_watertight=True):
            if (part.bounds[0]>hi).any() or (part.bounds[1]<lo).any(): continue
            h+=int(part.contains(pts).sum())
        if h: hits.append(f"{n}:{h}")
    P,fi=trimesh.sample.sample_surface(a,3000); N=a.face_normals[fi]; out=[]
    for ax,sign,label in ((2,1,"上"),(2,-1,"下"),(0,-1,"壁側"),(0,1,"内側"),(1,1,"奥"),(1,-1,"手前")):
        sel=N[:,ax]*sign>0.9
        if not sel.any(): continue
        dv=np.zeros(3); dv[ax]=sign; o=P[sel]+dv*0.01; d=np.tile(dv,(len(o),1))
        best=(9e9,None)
        for n,b in {**env,**real}.items():
            try: loc,ri,_=b.ray.intersects_location(o,d,multiple_hits=False)
            except Exception: continue
            if len(loc):
                g=np.abs(loc[:,ax]-o[ri][:,ax]).min()
                if g<best[0]: best=(g,n)
        out.append(f"{label} {best[0]:.2f}({best[1]})")
    print(f"{m:14s} 食い込み: {hits or 'なし'} ／ 空き mm: "+" ".join(out))
