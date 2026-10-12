"""受け皿の床を水平に切り、幅が W 未満の細い所（壁・梁）を探す。格子 0.1mm の点サンプル＋収縮/膨張。"""
import sys, numpy as np, trimesh
from scipy import ndimage as ndi
W = float(sys.argv[2]) if len(sys.argv) > 2 else 0.9
for f in sys.argv[1].split(","):
    m = trimesh.load(f); lo, hi = m.bounds
    for zname, z in (("床の中", hi[2] - 0.75), ("輪の中", hi[2] - 2.0)):
        g = 0.1
        xs = np.arange(lo[0] - 0.5, hi[0] + 0.5, g); ys = np.arange(lo[1] - 0.5, hi[1] + 0.5, g)
        X, Y = np.meshgrid(xs, ys); P = np.c_[X.ravel(), Y.ravel(), np.full(X.size, z)]
        A = m.contains(P).reshape(X.shape)
        r = int(round(W / 2 / g))
        st = ndi.generate_binary_structure(2, 1)
        opened = ndi.binary_dilation(ndi.binary_erosion(A, st, iterations=r), st, iterations=r)
        thin = A & ~opened
        lab, n = ndi.label(thin)
        big = [(int((lab == i).sum()), i) for i in range(1, n + 1) if (lab == i).sum() * g * g > 0.3]
        print(f"{f.split('/')[-1]} {zname}: 面積 {A.sum()*g*g:.0f}mm²  幅 {W}mm 未満の所 {len(big)} か所", [f"{a*g*g:.1f}mm² @({xs[int(np.mean(np.where(lab==i)[1]))]-(lo[0]+hi[0])/2:+.1f},{ys[int(np.mean(np.where(lab==i)[0]))]-(lo[1]+hi[1])/2:+.1f})" for a, i in sorted(big, reverse=True)[:8]])
