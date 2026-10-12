"""線の通り道が実形状の中にあるかを、空間を格子に切って探す（幅優先探索）。

  .venv/bin/python3 route_check.py right|left [格子 mm] [太らせる格子数]
障害物 = 組み立ての STL 全部（自分の線・倒れの影・帯は除く）。**底側のケースは溝を彫っていない素の形**を使う。
障害物を「太らせる格子数」ぶん膨らませてから探すので、通れた道は 線の太さ（0.86mm）＋余裕 を持つ。
"""
import sys, os, glob, numpy as np, trimesh
from scipy import ndimage as ndi
from collections import deque
sys.path.insert(0, "tools")
args = [x for x in sys.argv[1:] if not x.startswith("--")]
half = args[0]; G = float(args[1]) if len(args) > 1 else 0.5; GROW = int(args[2]) if len(args) > 2 else 1
A = "build/assembly/"
SKIP = {"joystick_wire", "joystick_tilt", "joystick_cap", "pod_board", "pod_mcu", "pcb", "db", "switches", "xiao", "keycaps", "case",
        "foot0", "foot1", "rubber", "batt_lid", "usb_plug"}
M = {os.path.basename(f)[len(half) + 1:-4]: trimesh.load(f) for f in glob.glob(f"{A}{half}_*.stl")}
plain = f"build/route_{half}_case_plain.stl"
if not os.path.exists(plain):
    from build123d import export_stl
    from gen_case import build_case
    from gen_plate import halves
    export_stl(build_case(halves()[half], half)[0], plain)
obst = {n: m for n, m in M.items() if n not in SKIP}; obst["case_plain"] = trimesh.load(plain)
j, seat, strip = M["joystick"], M["joystick_seat"], M["pod_board"]
xi = [p for p in M["db_real"].split(only_watertight=False)] if False else None
lo = np.minimum(np.minimum(seat.bounds[0], strip.bounds[0]), M["db_real"].bounds[0]) - 4
hi = np.maximum(np.maximum(seat.bounds[1], strip.bounds[1]), M["db_real"].bounds[1]) + 4
lo[2], hi[2] = 2.0, 26.0
xs, ys, zs = [np.arange(lo[i], hi[i], G) for i in range(3)]
X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
# 占有: (x, y) の柱ごとに +z へ 1 本だけ光線を飛ばし、交点の偶奇で中か外かを決める
# （点ごとの contains は 130 万点で 15 分かけて落ちた）
occ = np.zeros(X.shape, bool)
XX, YY = np.meshgrid(xs, ys, indexing="ij")
for n, m in obst.items():
    sel = (XX >= m.bounds[0][0] - G) & (XX <= m.bounds[1][0] + G) & (YY >= m.bounds[0][1] - G) & (YY <= m.bounds[1][1] + G)
    if not sel.any() or m.bounds[1][2] < zs[0] or m.bounds[0][2] > zs[-1]: continue
    ii, jj = np.where(sel)
    o = np.c_[xs[ii] + 1e-4, ys[jj] + 1.3e-4, np.full(len(ii), m.bounds[0][2] - 1.0)]
    for s in range(0, len(o), 20000):
        loc, ri, _ = m.ray.intersects_location(o[s:s + 20000], np.tile([0, 0, 1.0], (len(o[s:s + 20000]), 1)), multiple_hits=True)
        if not len(loc): continue
        order = np.lexsort((loc[:, 2], ri)); loc, ri = loc[order], ri[order]
        for r in np.unique(ri):
            zz = loc[ri == r][:, 2]
            zz = zz[np.r_[True, np.diff(zz) > 1e-5]]          # 同じ面の二重の交点をまとめる
            for k in range(0, len(zz) - 1, 2):
                k0, k1 = np.searchsorted(zs, zz[k]), np.searchsorted(zs, zz[k + 1])
                occ[ii[s + r], jj[s + r], k0:k1] = True
    # **表面そのものも障害物にする。**偶奇だけだと、閉じていないメッシュ（子基板の実形状のピンソケットなど）の
    # 中が「空間」になる（2026-10-08 の点検で発覚: 線の道がソケットの中を昇っていた）。表面を格子より細かく
    # 点で埋めれば、中が空でも殻が道をふさぐ。
    inb = m
    npts = int(min(4_000_000, max(2000, m.area / (G * G) * 6)))
    sp, _ = trimesh.sample.sample_surface(inb, npts)
    idx = np.floor((sp - np.array([xs[0], ys[0], zs[0]])) / G + 0.5).astype(int)
    ok = (idx >= 0).all(1) & (idx[:, 0] < len(xs)) & (idx[:, 1] < len(ys)) & (idx[:, 2] < len(zs))
    idx = idx[ok]; occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    print(f"   {n}: 済", flush=True)
grown = ndi.binary_dilation(occ, ndi.generate_binary_structure(3, 1), iterations=GROW) if GROW else occ
free = ~grown
def region(c, r):
    c = np.array(c); d2 = (X - c[0]) ** 2 + (Y - c[1]) ** 2 + (Z - c[2]) ** 2
    return (d2 <= r * r) & free
# 出発: 受け皿の床の下（足の先のまわり）
pins = j.vertices[j.vertices[:, 2] <= np.percentile(j.vertices[:, 2], 3)]
start = np.zeros_like(free)
for p in pins[:: max(1, len(pins) // 40)]: start |= region(p, 2.5)
# 行き先: 帯の上／XIAO のピンの頭（左右の列）
sb = strip.bounds
goal_strip = free & (X >= sb[0][0]) & (X <= sb[1][0]) & (Y >= sb[0][1]) & (Y <= sb[1][1]) & (Z >= sb[0][2]) & (Z <= sb[1][2] + 1)
dbb = M["db_real"].bounds
xpcb_top = dbb[1][2] - 3.2          # XIAO の基板の上面あたり（USB の頭 4.5 − 基板 1.2 ほど下）
goal_xiao = np.zeros_like(free)
cx = (dbb[0][0] + dbb[1][0]) / 2
for sx_ in (-7.62, 7.62):
    for k in range(7):
        goal_xiao |= region((cx + sx_, 52.2 + 2.54 * k, xpcb_top + 1.0), 1.6)
def bfs(src, dst, label):
    dist = np.full(free.shape, -1, np.int32); q = deque()
    for idx in zip(*np.where(src)): dist[idx] = 0; q.append(idx)
    if not q: print(f"  {label}: 出発点が空（障害物に埋まっている）"); return None
    prev = {}
    hit = None
    while q:
        c = q.popleft()
        if dst[c]: hit = c; break
        for d in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
            n = (c[0]+d[0], c[1]+d[1], c[2]+d[2])
            if 0 <= n[0] < free.shape[0] and 0 <= n[1] < free.shape[1] and 0 <= n[2] < free.shape[2] and free[n] and dist[n] < 0:
                dist[n] = dist[c] + 1; prev[n] = c; q.append(n)
    if hit is None:
        print(f"  {label}: **道が無い**（届いた空間 {int((dist>=0).sum())} 格子）"); return None
    path = [hit]
    while path[-1] in prev: path.append(prev[path[-1]])
    path = path[::-1]; pts = np.array([[xs[a], ys[b], zs[c_]] for a, b, c_ in path])
    print(f"  {label}: 道あり 長さ 約 {dist[hit]*G:.0f}mm")
    step = max(1, len(pts) // 9)
    print("     通る点:", " → ".join(f"({p[0]:.0f},{p[1]:.0f},{p[2]:.0f})" for p in pts[::step]))
    return pts
print(f"== {half}: 格子 {G}mm・障害物を {GROW} 格子（{GROW*G}mm）太らせた ／ 空間 {free.shape} ／ 出発 {int(start.sum())}・帯 {int(goal_strip.sum())}・XIAO {int(goal_xiao.sum())} 格子")
a = bfs(start, goal_strip, "受け皿 → 帯")
b = bfs(goal_strip, goal_xiao, "帯 → XIAO のピンの頭")
c = bfs(start, goal_xiao, "受け皿 → XIAO のピンの頭（帯を通らない）")
# 見つけた道を、絵の線（{half}_joystick_wire.stl）として書く。太さは線の束の目安（直径 1.8mm）
if a is not None and b is not None and "--write" in sys.argv:
    segs = []
    for pts in (a, b):
        q = pts[:: 3] if len(pts) > 6 else pts
        q = np.vstack([q, pts[-1]])
        for p0, p1 in zip(q, q[1:]):
            if np.linalg.norm(p1 - p0) < 1e-6: continue
            segs.append(trimesh.creation.cylinder(radius=0.9, segment=[p0, p1], sections=10))
            segs.append(trimesh.creation.icosphere(subdivisions=1, radius=0.9).apply_translation(p1))
    trimesh.util.concatenate(segs).export(f"{A}{half}_joystick_wire.stl")
    print("  線の絵を書いた:", f"{A}{half}_joystick_wire.stl")
