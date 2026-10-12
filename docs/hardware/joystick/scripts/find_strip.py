"""帯（27.94×20.32・高さ 2.4〜7.2）を底板の上に置ける場所を探す。
格子の各点で、(1) 高さ 3.0 と 6.8 の点がどの部品の中にも無い (2) 7.2 から上へ最初に当たる物までの空き、を見る。"""
import trimesh, numpy as np, glob, os, sys
A=sys.argv[1]
SK={"joystick_wire","joystick_tilt","joystick","joystick_cap","joystick_flex","joystick_seat","pod_fpc","pod_mcu","pod_board","pod_box","keycaps","switches","pcb","db"}
import os
W,D,ZT=float(os.environ.get('SW',27.94)),float(os.environ.get('SD',20.32)),float(os.environ.get('SZ',7.2))
for half in sys.argv[2:]:
    M={os.path.basename(f)[len(half)+1:-4]:trimesh.load(f) for f in glob.glob(A+half+"_*.stl")}
    M={n:m for n,m in M.items() if n not in SK}
    parts={n:[p for p in m.split(only_watertight=True)] for n,m in M.items() if n not in ("pcb_real","switches_real","db_real")}
    j=trimesh.load(A+f"{half}_joystick.stl"); c=j.bounds.mean(0)
    xs=np.arange(c[0]-45,c[0]+20,1.0) if half=='left' else np.arange(c[0]-20,c[0]+45,1.0); ys=np.arange(c[1]-30,c[1]+85,1.0) if half=="right" else np.arange(c[1]-55,c[1]+30,1.0)
    X,Y=np.meshgrid(xs,ys); P=np.c_[X.ravel(),Y.ravel()]
    blocked=np.zeros(len(P),bool); who=np.full(len(P),"",dtype=object)
    for z in (3.0,5.0,6.8,ZT-0.2):
        pts=np.c_[P,np.full(len(P),z)]
        for n,ps in parts.items():
            for p in ps:
                if p.bounds[0][2]>z or p.bounds[1][2]<z: continue
                if n=="case" and z<2.45: continue
                ins=p.contains(pts); who[ins&~blocked]=n; blocked|=ins
    up=np.full(len(P),99.0); upw=np.full(len(P),"",dtype=object)
    o=np.c_[P,np.full(len(P),ZT)]; d=np.tile([0,0,1.0],(len(P),1))
    for n,m in M.items():
        try: loc,ri,_=m.ray.intersects_location(o,d,multiple_hits=False)
        except Exception: continue
        if not len(loc): continue
        g=loc[:,2]-ZT; better=g<up[ri]; up[ri[better]]=g[better]; upw[ri[better]]=n
    ok=(~blocked)&(up<90)                      # 上に何か（基板）がある＝筐体の中
    G=ok.reshape(X.shape); U=np.where(ok,up,-1).reshape(X.shape)
    UW=upw.reshape(X.shape)
    # 帯の外形ぶんの窓で最小の空きを取る
    nx,ny=int(round(W)),int(round(D)); best=[]
    for iy in range(G.shape[0]-ny):
        for ix in range(G.shape[1]-nx):
            if G[iy:iy+ny+1,ix:ix+nx+1].all():
                w=U[iy:iy+ny+1,ix:ix+nx+1]; k=np.unravel_index(w.argmin(),w.shape); best.append((w.min(), xs[ix]+W/2, ys[iy]+D/2, UW[iy+k[0],ix+k[1]]))
    print("==",half,"スティック",c[:2].round(1).tolist(),"置ける場所",len(best))
    best.sort(reverse=True)
    for g,x,y,u in best[:5]: print(f"   空き {g:.1f}({u})  中心 ({x:.1f},{y:.1f})  スティックから ({x-c[0]:+.1f},{y-c[1]:+.1f})")
    near=sorted(best,key=lambda b:(b[1]-c[0])**2+(b[2]-c[1])**2)
    for g,x,y,u in [b for b in near if b[0]>=2.0][:6]: print(f"   空き 2.0 以上で近い順: 空き {g:.1f}({u})  中心 ({x:.1f},{y:.1f})  スティックから ({x-c[0]:+.1f},{y-c[1]:+.1f})")
    bl=[(n,int((who==n).sum())) for n in set(who) if n]; print("   塞いでいる物:",sorted(bl,key=lambda t:-t[1])[:8])
