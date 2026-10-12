"""キャップの断面（軸に沿った高さ h・半径 r の折れ線）を、全方位に倒して押し込んだ姿で、右手のキーキャップとの最小の隙間を数える。
joystick_rkjxv.tilt_report と同じ姿勢の式（軸の位置・倒れの中心・押し込みの沈み）を使う。

器の筐体の tools（main）が要る: main の作業ツリーにこのファイルと joystick_rkjxv.py を置き、PYTHONPATH=.:tools で回す。
2026-10-12 の結果と較正:
  真四角の箱で数えると、いまの φ10 は 1.27mm（tilt_report は 1.30）。**利用者の実測は約 4mm。**
  キーキャップの上面のすぼまりを片側 2.85（DSA の公称）にすると 3.45mm（倒すだけなら 4.08）で、実測と合う → CAP_TAPER=2.85 で数える。
  その条件で、print/gen_heads.py の頭（φ14・側面 3.2）は 1.33mm（相手は右スペース）。箱のままだと食い込む。
  山の頭（φ14）の実測は「右スペースへいっぱいに倒して押して 3〜4mm」「上面はキーの上面から 8mm 強」（利用者・2026-10-12）。
  高さは計算（8.6）と合う。隙間は計算（1.33）より大きい → 倒れ角かキーキャップの形が実物と違う。
  決め手が無いので 2 通りで見る: 較正A（倒れ 20°・すぼまり 4.0）と 較正B（倒れ 17°・すぼまり 2.85）。
  **低く広い頭の相手は、キーキャップではなくスティック自身の本体の上面**（BODY=True。上面はキーの上面より 2.6 低い）。
  print/gen_heads.py の低い皿（low_profile）: 公称 0.86・較正A 1.52・較正B 1.94。いまの皿（concave）: 1.33・1.95・2.38。
  使い方: CAP_TAPER=2.85 PYTHONPATH=.:tools python3 -c "import cap_clear as C, gen_heads as G; ..."（gen_heads.stick_profile を渡す）
"""
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

TAPER = float(os.environ.get("CAP_TAPER", 0))   # キーキャップの上面のすぼまり（片側 mm）。0 なら真四角の箱（joystick_rkjxv と同じ）。DSA は 18.4 → 12.7 で 2.85


def tapered(boxes, taper, n=8):
    """箱を n 枚に輪切りにして、上へ行くほど片側 taper までまっすぐすぼめる。"""
    out = []
    for name, lo, hi in boxes:
        for i in range(n):
            t = (i + 1) / n * taper; z0 = lo[2] + (hi[2] - lo[2]) * i / n; z1 = lo[2] + (hi[2] - lo[2]) * (i + 1) / n
            out.append((name, np.array([lo[0] + t, lo[1] + t, z0]), np.array([hi[0] - t, hi[1] - t, z1])))
    return out


def body_boxes():
    """スティック自身の本体（動かない部分）。つばのように低く広い頭は、倒すと自分の本体の上面に当たりうる。
    寸法は joystick_rkjxv.build と同じ（外形の振り分けは図からの読み取り）。"""
    sx, sy, zm, _ = axis_right(); fa, fb = J.ORIENT["right"]; h = J.CORE / 2
    def box(a0, a1, b0, b1, z0, z1, name):
        xs = sorted((sx + fb * b0, sx + fb * b1)); ys = sorted((sy + fa * a0, sy + fa * a1))
        return (name, np.array([xs[0], ys[0], zm + z0]), np.array([xs[1], ys[1], zm + z1]))
    return [box(-h, h, -h, h, 0, J.H_FRAME, "本体の枠"), box(h, J.A_EXT[1], -5, 5, 0.4, 0.4 + J.H_VR, "本体の VR1"),
            box(-5, 5, h, J.B_EXT[1], 0.4, 0.4 + J.H_VR, "本体の VR2"), box(-4, 4, J.B_EXT[0], -h, 0.4, 6.4, "本体のスイッチ")]


BODY = False                                    # True にすると本体も相手に入れる


def clearance(profile, tilt=J.TILT, sink=J.PUSH_SINK, pivot=J.PIVOT):
    """profile: [(取付面からの高さ z, 半径 r), ...] の折れ線。戻り値: (最小の隙間, 相手, 向き)"""
    sx, sy, zm, boxes = axis_right()
    if TAPER:
        boxes = tapered(boxes, TAPER)
    if BODY:
        boxes = boxes + body_boxes()
    piv = np.array([sx, sy, zm + pivot - sink])
    pts = []
    for (z0, r0), (z1, r1) in zip(profile, profile[1:]):
        for t in np.linspace(0, 1, 8):
            h, r = z0 + (z1 - z0) * t - pivot, r0 + (r1 - r0) * t
            pts += [(h, r * math.cos(a), r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 60, endpoint=False)]
    P = np.array(pts); best = (9.9, "", 0)
    OUTER = np.hypot(P[:, 1], P[:, 2]) >= 4.6
    for az in np.linspace(0, 2 * math.pi, 72, endpoint=False):
        t = math.radians(tilt); d = np.array([math.cos(az), math.sin(az), 0.0])
        ax = np.array([0, 0, 1.0]) * math.cos(t) + d * math.sin(t); u = d * math.cos(t) - np.array([0, 0, 1.0]) * math.sin(t); v = np.cross(ax, u)
        W = piv + np.outer(P[:, 0], ax) + np.outer(P[:, 1], u) + np.outer(P[:, 2], v)
        for name, lo, hi in boxes:
            # 本体の上面には軸の根元が動く穴（半径 4.4 の丸み）がある。箱はそこも塞いだ形なので、
            # 軸のすぐまわり（半径 4.6 未満）の点は本体とは比べない（前の頭の筒 r3.4 は実物で当たっていない）
            Wn = W[OUTER] if name.startswith("本体") else W
            inside = ((Wn >= lo) & (Wn <= hi)).all(axis=1)
            g = -1.0 if inside.any() else float(np.linalg.norm(np.maximum(np.maximum(lo - Wn, Wn - hi), 0), axis=1).min())
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
