"""キャップの断面（軸に沿った高さ h・半径 r の折れ線）を、全方位に倒して押し込んだ姿で、右手のキーキャップとの最小の隙間を数える。
joystick_rkjxv.tilt_report と同じ姿勢の式（軸の位置・倒れの中心・押し込みの沈み）を使う。

器の筐体の tools（main）が要る: main の作業ツリーにこのファイルと joystick_rkjxv.py を置き、PYTHONPATH=.:tools で回す。
2026-10-12 の結果: いまの φ10 は 1.27mm（tilt_report は 1.30）。φ16・覆い 2.0・下面の円すい 2.0 で 1.14mm（相手は右スペース）。"""
import sys, math, os
sys.argv = ["x", "--dry"]
import numpy as np
import joystick_rkjxv as J
from gen_plate import halves
from interface import plate_positions, PLATE_T
from gen_case import plate_placement
from envelopes import PLATE_TO_PCB
from interface import BEZEL_OPENING_GAP as GAP, PLATE_MARGIN_X as MARG

def axis_right():
    keys = halves()["right"]; positions, (w, h) = plate_positions(keys)
    key_w = w - 2 * MARG; s = -1; x_open = s * (key_w / 2 + GAP)
    by = {k.label.split("\n")[0]: (p, k) for p, k in zip(positions, keys)}
    (nx, ny), nk = by["N"]; bx0, bx1 = x_open, nx - J.U / 2; by0, by1 = ny - J.U / 2, ny + J.U / 2
    c = J.CFG["right"]; zm = -PLATE_TO_PCB + J.PIN_CLR + J.PIN_LEN + c["lift"]; fa, fb = J.ORIENT["right"]
    ax0, ax1 = sorted((fa * J.A_EXT[0], fa * J.A_EXT[1])); b0, b1 = sorted((fb * J.B_EXT[0], fb * J.B_EXT[1]))
    sx = (bx0 + bx1) / 2 - (b0 + b1) / 2 + s * c["dt"]; sy = (by0 + by1) / 2 - (ax0 + ax1) / 2
    return sx, sy, zm, J.cap_boxes(positions, keys)

def clearance(profile, tilt=J.TILT, sink=J.PUSH_SINK, pivot=J.PIVOT):
    """profile: [(取付面からの高さ z, 半径 r), ...] の折れ線。戻り値: (最小の隙間, 相手, 向き)"""
    sx, sy, zm, boxes = axis_right()
    piv = np.array([sx, sy, zm + pivot - sink])
    pts = []
    for (z0, r0), (z1, r1) in zip(profile, profile[1:]):
        for t in np.linspace(0, 1, 8):
            h, r = z0 + (z1 - z0) * t - pivot, r0 + (r1 - r0) * t
            pts += [(h, r * math.cos(a), r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 60, endpoint=False)]
    P = np.array(pts); best = (9.9, "", 0)
    for az in np.linspace(0, 2 * math.pi, 72, endpoint=False):
        t = math.radians(tilt); d = np.array([math.cos(az), math.sin(az), 0.0])
        ax = np.array([0, 0, 1.0]) * math.cos(t) + d * math.sin(t); u = d * math.cos(t) - np.array([0, 0, 1.0]) * math.sin(t); v = np.cross(ax, u)
        W = piv + np.outer(P[:, 0], ax) + np.outer(P[:, 1], u) + np.outer(P[:, 2], v)
        for name, lo, hi in boxes:
            inside = ((W >= lo) & (W <= hi)).all(axis=1)
            g = -1.0 if inside.any() else float(np.linalg.norm(np.maximum(np.maximum(lo - W, W - hi), 0), axis=1).min())
            if g < best[0]: best = (g, name, math.degrees(az))
    return best

if __name__ == "__main__":
    tip = J.H_TIP
    old = [(tip + 1 - 2 - 5, 3.4), (tip - 1, 3.4), (tip - 1, 3.5), (tip + 1, 5.0)]
    print("いまのキャップ（φ10）:", "%.2f mm %s" % clearance(old)[:2], " ← tilt_report は 1.30")
    sx, sy, zm, boxes = axis_right()
    near = sorted((max(lo[0]-sx,0,sx-hi[0])**2 + max(lo[1]-sy,0,sy-hi[1])**2, n, hi[2]) for n, lo, hi in boxes)[:5]
    print("軸のまわりのキーキャップ（平面の距離・上面の高さ）:", [(n, round(math.sqrt(d), 2), round(float(z), 2)) for d, n, z in near], " 軸の先 z=%.2f 枠の上 z=%.2f" % (zm + tip, zm + J.H_FRAME))
    for D in (12, 14, 16, 18, 20):
        for rise in (2.0, 3.0, 4.0):          # 下の縁（半径 3.5）から外周までの円すいの高さ
            top = tip + 1.0
            prof = [(top - 0.8 - rise - 3.0, 3.4), (top - 0.8 - rise, 3.4), (top - 0.8, D / 2), (top, D / 2)]
            g, n, az = clearance(prof)
            print(f"φ{D} 円すいの高さ {rise}: 最小の隙間 {g:5.2f} mm（{n}・向き {az:.0f}°）  直立 {clearance(prof, tilt=0)[0]:.2f}")
