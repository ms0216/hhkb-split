"""ジョイスティック案 R: 秋月のアルプス RKJXV122400R を、プレートをくり抜いて沈める（試作・未コミット）。

フレキもコネクタも無い。足（2.5mm ピッチのスルーホール）に線をじかに付ける。
マイコンの帯は主基板の下の空洞（joystick_trial.py の案 X と同じ置き場所）。

寸法の出どころ: アルプスのデータシート（build/joystick/reference/alps_RKJXV122400R_datasheet.pdf）。
[図面] と書いた値は図面の数字、[読み取り] は図から目で読んだ値（足・爪の細かい位置など）。

  使い方:  .venv/bin/python3 joystick_rkjxv.py [left right]   （export_assembly.py の後）
"""
import json
import math
import os
import sys
from functools import reduce
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))

from build123d import Align, Axis, Box, Compound, Cone, Cylinder, Location, Vector, export_stl, fillet  # noqa: E402

from envelopes import CAP_GAP, PLATE_TO_PCB  # noqa: E402
from gen_case import CAP_LIFT, FLOOR, build_case, build_topcase, cap_height, plate_placement  # noqa: E402
from gen_plate import build_plate, halves  # noqa: E402
from interface import BEZEL_OPENING_GAP as GAP  # noqa: E402
from interface import PLATE_MARGIN_X as MARG  # noqa: E402
from interface import PLATE_T, plate_positions  # noqa: E402

OUT = ROOT / "build" / "assembly"
U = 19.05
CTR = (Align.CENTER, Align.CENTER, Align.MIN)

# ---- RKJXV122400R（軸を原点、取付面を z=0。A=18.2 の向き、B=21.7 の向き）----
CORE = 13.15                    # 枠（正方形）[図面]
H_FRAME, H_TIP = 11.2, 18.95    # 取付面 → 枠の上／軸の先 [図面]
A_EXT = (-7.3, 10.9)            # A 方向の外形（計 18.2 [図面]。+側が VR1 の張り出し。振り分けは [読み取り]）
B_EXT = (-10.8, 10.9)           # B 方向の外形（計 21.7 [図面]。+側が VR2、−側がスイッチ。振り分けは [読み取り]）
H_VR = 10.8                     # 可変抵抗の箱の高さ [図面]
PIN_LEN = 2.9                   # 足が取付面の下へ出る長さ [図面]
SHAFT_D = 4.0                   # 軸の径 [図面]
TILT_MAX = 23.0                 # 倒れ角（各方向・最大）[図面]
TILT = float(os.environ.get("TILT", TILT_MAX))   # 検査に使う倒れ角（受けの穴で制限するなら小さくする）
PIVOT = float(os.environ.get("PIVOT", 5.6))   # 取付面 → 倒れの中心 [読み取り]（側面図の軸の中心線。±1mm は見ておく）
# 足の位置（軸から）[図面: 取付穴寸法図。足 3 本は 2.5 ピッチ、列は軸から 8.73]
PINS = [(a, 8.73) for a in (-2.5, 0, 2.5)] + [(8.73, b) for b in (-2.5, 0, 2.5)]          # VR2・VR1
# 取付穴寸法図（400dpi で読み直した・2026-10-06）: 爪は 12.65×10 の四隅、位置決めの突起は 8.6 離れて中心線上、
# スイッチ端子は 6.5 幅で、軸から 8 の点をはさんで 4.5 離れた 2 列
PINS_SW = [(-3.25, -5.75), (3.25, -5.75), (-3.25, -10.25), (3.25, -10.25)]                  # スイッチ（φ1.2 の穴）[図面]
LUGS = [(-6.325, 5.0), (6.325, 5.0), (-6.325, -5.0), (6.325, -5.0)]                         # 爪（φ1.5 の穴）[図面]
BOSS = [(-4.3, 0.0), (4.3, 0.0)]                                                            # 位置決めの突起（φ1.6 の穴・高さ 0.75）[図面]

# ---- 取り付け ----
PIN_CLR = 0.3                   # 足の先と主基板の隙間
FLOOR_T = 1.5                   # 受け皿の床の厚み（＝プレートの厚み。足は床の下へ 1.4 出る）
FLANGE_T, TRAY_FLANGE, RING_W = 1.0, 1.5, 1.5   # つばの厚み・くり抜きより外へ出る量・輪の内側の幅
WIRE_NOTCH = 6.0                # 線を出す切り欠きの幅
MIN_WALL = 1.2                  # 穴と床の縁の間に残す最小の幅。これ未満なら縁まで開く
PIN_SLOT = 2.6                  # 足の長穴の幅（足＋線＋はんだが通る）
PIN_POCKET = 1.5                # 輪を足のまわりで空ける半幅（はんだと、爪を曲げる余地）
TRAY_CLR = 0.3                  # 受け皿とプレートのくり抜きの隙間
CUT_CLR = 0.4                   # 本体とくり抜きの隙間
PUSH_SINK = float(os.environ.get("PUSH_SINK", 0.9))   # 押し込みの沈み [図面] 0.4 +0.5/−0.3 の最大
CAP_D = float(os.environ.get("CAP_D", 10.0))      # 刷るキャップの径（小さいほど倒したときに隣へ届かない）
CAP_D_BOT = float(os.environ.get("CAP_D_BOT", 7.0))   # キャップの下面の径。下の縁を斜めに落とす（倒したとき隣へ届くのは下の縁）
CAP_SLEEVE = (3.4, 5.0)          # キャップの筒の半径と長さ
CAP_T = float(os.environ.get("CAP_T", 2.0))       # 厚み
CAP_OVER = float(os.environ.get("CAP_OVER", 1.0)) # 軸の先を覆う量
# 左右の取り付け方（2026-10-06 に倒れを数えて決めた。数えた表は会話の記録）:
#   右: **沈めない**（プレートの上面に載せる）。沈めると、倒したキャップが H・右スペースのキーキャップに当たる。壁へ 1.0 寄せる。
#   左: 沈める（プレートをくり抜く）。軸を奥へ寄せる向き（FLIP_A=-1）。
# ⚠️ 向きは **fa × fb = −1** の組だけが実物（＋1 だと鏡像になり、プレートの穴が裏返る。v1 の右手がそうだった）。
CFG = {"right": dict(lift=1.8, dt=1.0, fa=1, fb=-1), "left": dict(lift=0.0, dt=0.0, fa=-1, fb=1)}
ZM_ADD = os.environ.get("ZM_ADD")              # 試すときだけ上書き
T_INNER = 0.1                   # 開口の縁 → 底側の部品の内壁（STL で測った）
UB_T, BUMP, POD_STACK = 1.0, 1.0, 2.5
MCU_L, MCU_S, MCU_T = 26.0, 10.0, 1.6
WW5, WH = 4.5, 0.9              # 線 5 本を並べた幅・線の太さ
LEFT_STRIP_AT = (float(os.environ.get("LSX", 38.0)), float(os.environ.get("LSY", 37.8)))   # 左の帯の中心（机の座標。find_strip.py）
STRIP_AT = {"left": (33.6, 40.8),   # ← 左は使っていない（左の帯は LEFT_STRIP_AT）
             "right": (-46.9, 37.9)}      # 帯の中心（机の座標。find_strip.py）
XIAO_FRONT_Y, PCB_REAR_Y = 50.5, 49.0   # 左の XIAO のソケットの手前の面／主基板の奥の縁（机の座標の y）[STL に線を当てて測った]
# 右: 子基板（XIAO のピンの裏側）は机の座標で x -85.7〜-64.7・y 36.8〜68.8・下面 z 6.4。帯のすぐ隣
DB_PADS_RIGHT = (float(os.environ.get("DBX", -66.5)), float(os.environ.get("DBY", 46.0)), 6.4)
RUN_ORDER = {"left": "xy", "right": "xy"}
GROOVE_DY = {"left": -17.0, "right": 0.0}     # 左は軸の真横にネジの柱があるので、溝を手前へ 17mm ずらす
# スティックの向き: B（21.7）を左右（壁↔キー）に向ける。FLIP_A で VR1 を奥／手前、FLIP_B で VR2 を壁側／キー側
ORIENT = {h: (int(os.environ.get("FA_" + h[0].upper(), CFG[h]["fa"])), int(os.environ.get("FB_" + h[0].upper(), CFG[h]["fb"]))) for h in CFG}


def tray_solid(box, rect, slots, pins, flange=None, notch="b1", rounds=None):
    """受け皿（刷る）。**プレートと主基板の間に挟まって、上にも下にも動かない。**押さえは要らない。

    box(寸法1, 寸法2, 高さ, 位置1, 位置2, z) は呼ぶ側の座標（z=0 が取付面＝プレートの上面）。rect はくり抜きの (a0, a1, b0, b1)。
      床   : くり抜きの中（厚み FLOOR_T）。部品を載せ、足と爪を通す
      つば : プレートの下面のすぐ下で、くり抜きより外へ出る輪。**プレートが上から押さえる**
             flange = (a0 側, a1 側, b0 側, b1 側) の出る量。壁ぎわは 0 にする
      脚   : 輪の四隅から主基板の上面まで
    部品は、爪を床の下で曲げて留める。**線は先に足へはんだ付けしておき、長穴に通す**（BUILD.md 2-3）。
    線は輪の切り欠き（notch の側）か、輪の下（脚の間・高さ 2.4mm）から平らに並べて出す。
    pins は足・爪の位置。**輪は足のまわり PIN_POCKET を空ける**（くり抜きの内側だけ。足はくり抜きの縁から
    1mm 以内に来るので、空けないと輪が足を塞いで部品が座らない。2026-10-06 に粗探しで発覚）。
    """
    a0, a1, b0, b1 = rect
    f = flange or (TRAY_FLANGE,) * 4
    ca, cb = (a0 + a1) / 2, (b0 + b1) / 2
    wa, wb = a1 - a0, b1 - b0
    zr = -FLOOR_T - FLANGE_T
    oa0, oa1, ob0, ob1 = a0 - f[0], a1 + f[1], b0 - f[2], b1 + f[3]
    # 穴は (a0, a1, b0, b1) の四角で受け取る。**床の縁までの残りが MIN_WALL 未満の穴は、縁まで開いて
    # 切り欠きにする**: 0.2〜0.9mm の壁や梁は刷れないか、すぐ折れる（2026-10-07 の粗探しで STL の断面から発覚）
    fa0, fa1, fb0, fb1 = a0 + TRAY_CLR, a1 - TRAY_CLR, b0 + TRAY_CLR, b1 - TRAY_CLR
    holes = rounds
    for s0, s1, t0, t1 in slots:
        if s0 - fa0 < MIN_WALL: s0 = fa0 - 1.0
        if fa1 - s1 < MIN_WALL: s1 = fa1 + 1.0
        if t0 - fb0 < MIN_WALL: t0 = fb0 - 1.0
        if fb1 - t1 < MIN_WALL: t1 = fb1 + 1.0
        h_ = box(s1 - s0, t1 - t0, 6.0, (s0 + s1) / 2, (t0 + t1) / 2, -5.0)
        holes = h_ if holes is None else holes + h_
    floor = box(wa - 2 * TRAY_CLR, wb - 2 * TRAY_CLR, FLOOR_T, ca, cb, -FLOOR_T) - holes
    ring = box(oa1 - oa0, ob1 - ob0, FLANGE_T, (oa0 + oa1) / 2, (ob0 + ob1) / 2, zr) \
        - box(wa - 2 * RING_W, wb - 2 * RING_W, FLANGE_T + 0.2, ca, cb, zr - 0.1)
    # 壁ぎわ（つばを内へ引いた辺）は輪そのものを作らない: 幅 0.9mm しか残らず、足のくぼみで切れて
    # 厚さ 0.5mm の切れ端になる（thin_check.py が 1 か所検出）。床は残り 3 辺の輪と四隅の脚で支える
    for k, (c1_, c2_, d1_, d2_) in enumerate(((oa0 - 1, a0 + RING_W + 0.1, ob0 + 2.6, ob1 - 2.6), (a1 - RING_W - 0.1, oa1 + 1, ob0 + 2.6, ob1 - 2.6),
                                               (oa0 + 2.6, oa1 - 2.6, ob0 - 1, b0 + RING_W + 0.1), (oa0 + 2.6, oa1 - 2.6, b1 - RING_W - 0.1, ob1 + 1))):
        if f[k] < 0:
            ring -= box(c2_ - c1_, d2_ - d1_, FLANGE_T + 0.2, (c1_ + c2_) / 2, (d1_ + d2_) / 2, zr - 0.1)
    for pa, pb in pins:
        qa0, qa1 = max(pa - PIN_POCKET, a0), min(pa + PIN_POCKET, a1)
        qb0, qb1 = max(pb - PIN_POCKET, b0), min(pb + PIN_POCKET, b1)
        ring -= box(qa1 - qa0, qb1 - qb0, FLANGE_T + 0.2, (qa0 + qa1) / 2, (qb0 + qb1) / 2, zr - 0.1)
    if notch == "b1":
        ring -= box(WIRE_NOTCH, f[3] + RING_W + 0.4, FLANGE_T + 0.2, ca, b1 + (f[3] - RING_W) / 2, zr - 0.1)
    else:                                          # "a1"
        ring -= box(f[1] + RING_W + 0.4, WIRE_NOTCH, FLANGE_T + 0.2, a1 + (f[1] - RING_W) / 2, cb, zr - 0.1)
    foot_h = PLATE_T + zr - (-PLATE_TO_PCB + 0.1)
    feet = [box(2.6, 2.6, foot_h, a, b, zr - foot_h)
            for a in (oa0 + 1.3, oa1 - 1.3) for b in (ob0 + 1.3, ob1 - 1.3)]
    return reduce(lambda p_, q: p_ + q, [floor, ring] + feet), foot_h


def cap_boxes(positions, keys):
    """キーキャップの箱（プレート座標）。envelopes.key_stack_envelopes と同じ寸法。"""
    out = []
    for (kx, ky), k in zip(positions, keys):
        w, d = k.w_u * U - CAP_GAP, U - CAP_GAP
        z0 = PLATE_T + CAP_LIFT
        out.append((k.label.split("\n")[0] or "?", np.array([kx - w / 2, ky - d / 2, z0]), np.array([kx + w / 2, ky + d / 2, z0 + cap_height(k)])))
    return out


def tilt_report(half, sx, sy, zm, boxes, cap_d):
    """軸を全方位に最大まで倒したときの、キャップ・軸と各キーキャップの隙間（mm）。負は食い込み。"""
    piv = np.array([sx, sy, zm + PIVOT - PUSH_SINK])   # 倒したまま押し込んだ姿で見る（軸ごと沈む）
    # キャップ（円柱）の表面の点: 軸に沿った高さ h（倒れの中心から）と半径 r
    h0, h1 = H_TIP - PIVOT + CAP_OVER - CAP_T, H_TIP - PIVOT + CAP_OVER
    rad = lambda h: (CAP_D_BOT + (cap_d - CAP_D_BOT) * (h - h0) / (h1 - h0)) / 2   # noqa: E731  円すい台
    pts = [(h, rad(h) * math.cos(a), rad(h) * math.sin(a)) for h in np.linspace(h0, h1, 5) for a in np.linspace(0, 2 * math.pi, 48, endpoint=False)]
    pts += [(h, SHAFT_D / 2 * math.cos(a), SHAFT_D / 2 * math.sin(a)) for h in np.linspace(H_FRAME - PIVOT, h0, 6) for a in np.linspace(0, 2 * math.pi, 16, endpoint=False)]
    # 刷るキャップの筒（軸にかぶせる部分。export_print.py と同じ r 3.4 × 5）
    pts += [(h, CAP_SLEEVE[0] * math.cos(a), CAP_SLEEVE[0] * math.sin(a)) for h in np.linspace(h0 - CAP_SLEEVE[1], h0, 6) for a in np.linspace(0, 2 * math.pi, 32, endpoint=False)]
    P = np.array(pts)
    worst = {}
    for th in (0.0, TILT):
        for az in np.linspace(0, 2 * math.pi, 72, endpoint=False):
            t = math.radians(th)
            d = np.array([math.cos(az), math.sin(az), 0.0])            # 倒す向き
            ax = np.array([0, 0, 1.0]) * math.cos(t) + d * math.sin(t)  # 倒れた軸
            u = d * math.cos(t) - np.array([0, 0, 1.0]) * math.sin(t)   # 軸に直交（倒す側）
            v = np.cross(ax, u)
            W = piv + np.outer(P[:, 0], ax) + np.outer(P[:, 1], u) + np.outer(P[:, 2], v)
            for name, lo, hi in boxes:
                dd = np.maximum(np.maximum(lo - W, W - hi), 0)
                dist = np.linalg.norm(dd, axis=1)
                inside = ((W >= lo) & (W <= hi)).all(axis=1)
                g = -1.0 if inside.any() else float(dist.min())
                key = (name, th)
                if key not in worst or g < worst[key][0]:
                    worst[key] = (g, math.degrees(az))
    near = sorted(((g, n, th, az) for (n, th), (g, az) in worst.items() if g < 6.0))
    print(f"   倒れの検査（キャップ φ{cap_d:.0f}・全方位 72 通り・{TILT}°）: 近い順")
    for g, n, th, az in near[:8]:
        print(f"      {n:8s} {'直立' if th == 0 else '最大に倒す'}: {'食い込む' if g < 0 else f'{g:.2f} mm'}（向き {az:.0f}°）")
    return min((g for g, n, th, az in near if th > 0), default=9.9)


# ---- 左手: ロータリーエンコーダ EC12PL（秋月 g105770 ほか・2 色 LED 付スイッチ付・つまみ付セット）----
# 出どころ: TOP-UP の図面と規格書（build/joystick/reference/akizuki_g105771_EC12PL_*.pdf）。[図面] / [推定]
# RE111F（g114936）は最小電流 1mA の指定に合わないので外した（2026-10-06）。
ENC_W, ENC_D, ENC_H = 12.4, 13.2, 7.0   # 本体（左右×前後×高さ）[図面]
ENC_LUG_W = 14.0                # 爪の先から先 [図面]
ENC_BUSH = (6.8, 5.0)           # 軸受けの径・高さ [図面]
ENC_SHAFT_D, ENC_SHAFT_TOP = 6.0, 25.0   # 軸の径・軸の先（取付面から）[図面]
ENC_PIN_LEN = 2.9               # 足が取付面の下へ出る長さ [図面]
ENC_PINS_ABC = [(-2.5, -7.5), (0.0, -7.5), (2.5, -7.5)]          # A・C・B（φ1.1 の穴）[図面]
ENC_PINS_SW = [(-3.0, 7.0), (-1.0, 7.0), (1.0, 7.0), (3.0, 7.0)]  # 4・3・2・1（スイッチは 4 と 1。2・3 は LED。φ1.0）[図面]
ENC_LUGS = [(-6.6, 0.0), (6.6, 0.0)]                              # 爪（2.0×2.1 の角穴）[図面]
KNOB_D, KNOB_H = 15.0, 13.0     # 付属のつまみ（P-15X13）[秋月の型番]
KNOB_TOP = ENC_SHAFT_TOP + 1.0  # つまみの上面 [推定]（内側の深さが図面に無い）
LEFT_ENCODER = os.environ.get("LEFT", "encoder") == "encoder"


def build_encoder(half):
    """左手の空き地（5 の右）にエンコーダを置く。マイコンは無い。抵抗 2 本とダイオードの小さな帯（LEFT_STRIP_AT）を主基板の下に置く（B 案だけなら帯も要らない）。

    右手のスティックと同じ「くり抜き＋受け皿」: エンコーダ・線・受け皿を先に組み、上から落とし込む。
    """
    keys = halves()[half]
    positions, (w, h_plate) = plate_positions(keys)
    pl = plate_placement(w, h_plate)
    key_w = w - 2 * MARG
    s = 1
    e = -s
    x_open = s * (key_w / 2 + GAP)
    by = {k.label.split("\n")[0]: (p, k) for p, k in zip(positions, keys)}
    (fx, fy), fk = by["5"]
    bx0, bx1 = fx + U / 2, x_open
    by0, by1 = fy - U / 2, fy + U / 2 + GAP
    ex, ey = (bx0 + bx1) / 2 + float(os.environ.get("ENC_DX", 0)), (by0 + by1) / 2 + float(os.environ.get("ENC_DY", 0))
    zp = -PLATE_TO_PCB
    z0 = PLATE_T                                   # 取付面＝プレートの上面の高さ（受け皿の床の上）
    X = lambda t: x_open + e * t                   # noqa: E731

    def Bx(dx, dy, dz, x, y, z):
        return Location((ex + x, ey + y, z0 + z)) * Box(dx, dy, dz, align=CTR)

    def Cy(r, h, x, y, z):
        return Location((ex + x, ey + y, z0 + z)) * Cylinder(r, h, align=CTR)

    body = fillet(Bx(ENC_W, ENC_D, ENC_H, 0, 0, 0).edges().filter_by(Axis.Z), 0.6)
    body += Bx(ENC_LUG_W, 2.0, 3.0, 0, 0, 0)
    body += Cy(ENC_BUSH[0] / 2, ENC_BUSH[1], 0, 0, ENC_H)
    body += Cy(ENC_SHAFT_D / 2, ENC_SHAFT_TOP - ENC_H - ENC_BUSH[1], 0, 0, ENC_H + ENC_BUSH[1])
    pins = [Bx(0.9, 0.3, ENC_PIN_LEN + 2.0, x, y, -ENC_PIN_LEN) for x, y in ENC_PINS_ABC + ENC_PINS_SW]
    pins += [Bx(0.3, 2.0, ENC_PIN_LEN, x, y, -ENC_PIN_LEN) for x, y in ENC_LUGS]
    enc = Compound(children=[body] + pins)
    k1, k0 = KNOB_TOP, KNOB_TOP - KNOB_H
    knob = fillet(Cy(KNOB_D / 2, KNOB_H, 0, 0, k0).edges().sort_by(Axis.Z)[-1], 1.5)
    # くり抜きと受け皿（床はプレートの上面の高さ・脚は主基板の上に立つ）
    # 幅はつまみ（φ15）が通る大きさにする: 図面の赤字「本体とつまみは一度固定すると外れない」。
    # 爪の幅 14.0 に合わせた 14.8 では、つまみを挿したあと受け皿ごと下へ抜けず、分解できなくなる
    cw, cd = max(ENC_LUG_W + 2 * CUT_CLR, KNOB_D + 0.4), 15.6 + 2 * CUT_CLR
    cut = Bx(cw, cd, PLATE_T + 0.4, 0, -0.25, -PLATE_T - 0.2)
    # 足の穴は**長穴**にする: 線を足にはんだ付けしてから差し込めるように（刷った床のそばでこてを使わない。
    # 足は床の下に 1.4mm しか出ず、PLA は溶ける）。**位置は爪の穴 2 つで決まる**ので、爪の穴は詰める
    # （爪は 0.3×2.0。穴は 0.7×2.2 ＝ 遊び 左右 ±0.2・前後 ±0.1。最初の 1.0×2.4 は回転 ±1.7° のがたが出た）
    hs = PIN_SLOT / 2
    slots = [(-2.5 - hs, 2.5 + hs, ENC_PINS_ABC[0][1] - hs, ENC_PINS_ABC[0][1] + hs),
             (-3.0 - hs, 3.0 + hs, ENC_PINS_SW[0][1] - hs, ENC_PINS_SW[0][1] + hs)]
    slots += [(x - 0.35, x + 0.35, y - 1.1, y + 1.1) for x, y in ENC_LUGS]
    tray, foot_h = tray_solid(Bx, (-cw / 2, cw / 2, -0.25 - cd / 2, -0.25 + cd / 2), slots, ENC_PINS_ABC + ENC_PINS_SW + ENC_LUGS, notch="b1")   # 線は奥（XIAO の側）へ出す
    # 線: **XIAO はエンコーダのすぐ奥・主基板の上面とほぼ同じ高さにある**（STL に線を当てて確かめた。間に壁は無い）。
    # 5 本（A・B・GND・3.3V・行）は受け皿の下から奥へ約 13mm、主基板の上をそのまま XIAO のピンソケットへ。
    # 1 本（列）だけ、主基板の奥の縁を回り込んで裏へ入り、5 のキーのソケットへ。**縁の溝も、底板の上の線も要らない。**
    zw = zp + 0.1
    cos_t = math.cos(math.radians(7.3))
    yw0 = (pl * Location((ex, ey, 0))).position.Y
    y_x = ey + (XIAO_FRONT_Y - yw0) / cos_t         # XIAO のソケットの手前（プレート座標の y）
    y_e = ey + (PCB_REAR_Y + 0.3 - yw0) / cos_t     # 主基板の奥の縁のすぐ外
    W5 = 5 * WH
    w5 = Location((ex, (ey + y_x) / 2, zw)) * Box(W5, y_x - ey, WH, align=CTR)
    zu = zp - 1.6 - 1.2                             # 主基板の裏から 0.3 下を走る線の底面
    x1 = ex + W5 / 2 + 1.0
    y_u = y_e - 2.0                                 # 裏へ入ったら、奥の縁に沿って 5 のキーの桁まで走る
    w1 = [Location((x1, y_e, zu)) * Box(WH, WH, zw + WH - zu, align=CTR),          # 縁を回り込む
          Location((x1, (y_e + y_u) / 2, zu)) * Box(WH, abs(y_e - y_u) + WH, WH, align=CTR),
          Location(((x1 + fx) / 2, y_u, zu)) * Box(abs(x1 - fx) + WH, WH, WH, align=CTR),
          Location((fx, (y_u + fy) / 2, zu)) * Box(WH, abs(y_u - fy) + WH, WH, align=CTR)]
    wires = [pl * w5] + [pl * q for q in w1]
    plate = pl * (build_plate(keys, half)[0] - cut)
    case = build_case(keys, half)[0]                # 溝は彫らない（前の版の溝を消すため、素の形で書き直す）

    print(f"== {half}: 左手エンコーダ（EC12PL・くり抜き＋受け皿・付属のつまみ・軸は切らない）")
    print(f"   空き地 {abs(bx1 - bx0):.2f} × {by1 - by0:.2f}  くり抜き {cw:.1f} × {cd:.1f}  受け皿の脚 {foot_h:.2f}  足の先 → 主基板 {z0 - ENC_PIN_LEN - zp - PLATE_T + PLATE_T:.2f} mm")
    row_top = CAP_LIFT + cap_height(fk)
    print(f"   高さ（プレート上面から）: 本体 {ENC_H}  軸の先 {ENC_SHAFT_TOP}  つまみ {k0:.1f}〜{k1:.1f}[推定]  ／ 数字段のキートップ {row_top:.2f} → 上に出る量 {k1 - row_top:+.2f}・キーの横に並ぶ量 {max(0, row_top - k0):.2f}")
    near = []
    for name, lo, hi in cap_boxes(positions, keys):
        if hi[2] < z0 + k0 or lo[2] > z0 + k1:
            continue
        dx = max(lo[0] - ex, 0, ex - hi[0]); dy = max(lo[1] - ey, 0, ey - hi[1])
        near.append((math.hypot(dx, dy) - KNOB_D / 2, name, hi[2] - z0))
    for g, n, top in sorted(near)[:3]:
        print(f"      つまみ φ{KNOB_D:.0f} ↔ {n} のキーキャップ: {g:.2f} mm（そのキートップ +{top:.2f}）")
    return {
        "joystick": pl * enc, "joystick_cap": pl * knob, "joystick_seat": pl * tray,
        "joystick_wire": Compound(children=wires),
        # 左の帯（6×4 穴・100kΩ×2 とダイオード。build/joystick/pod_layout/left_layout.py）: 主基板の下・底板の上（エンコーダの左 約 20mm）。部品は高さ 6.0 の箱 [推定]
        "pod_board": Compound(children=[Location((LEFT_STRIP_AT[0], LEFT_STRIP_AT[1], FLOOR + BUMP)) * Box(6 * 2.54, 4 * 2.54, UB_T, align=CTR),
                                        Location((LEFT_STRIP_AT[0], LEFT_STRIP_AT[1], FLOOR + BUMP + UB_T)) * Box(6 * 2.54, 4 * 2.54, 6.0, align=CTR)]),
        "plate": plate, "topcase": build_topcase(keys, half)[0], "case": case,
    }


def build(half):
    if half == "left" and LEFT_ENCODER:
        return build_encoder(half)
    keys = halves()[half]
    positions, (w, h_plate) = plate_positions(keys)
    pl = plate_placement(w, h_plate)
    key_w = w - 2 * MARG
    s = -1 if half == "right" else 1
    e = -s                                         # キーボードの内向き
    x_open = s * (key_w / 2 + GAP)
    x_wall = s * (key_w / 2 + MARG)
    by = {k.label.split("\n")[0]: (p, k) for p, k in zip(positions, keys)}
    if half == "right":
        (nx, ny), nk = by["N"]
        bx0, bx1 = x_open, nx - U / 2              # 空き地（左右）
        by0, by1 = ny - U / 2, ny + U / 2          # 空き地（前後）
    else:
        (fx, fy), nk = by["5"]
        bx0, bx1 = fx + U / 2, x_open
        by0, by1 = fy - U / 2, fy + U / 2 + GAP
    X = lambda t: x_open + e * t                   # noqa: E731
    zp = -PLATE_TO_PCB                             # 主基板の上面
    lift = float(ZM_ADD) if ZM_ADD is not None else CFG[half]["lift"]
    on_plate = lift >= PLATE_T - (zp + PIN_CLR + PIN_LEN) - 0.01     # プレートの上面に載せる（くり抜かない）
    zm = zp + PIN_CLR + PIN_LEN + lift             # 取付面（lift=0 で足の先が主基板の 0.3 上）
    fa, fb = ORIENT[half]                          # A→前後（y）、B→左右（x）
    assert fa * fb == -1, "鏡像の向き（fa*fb=+1）は実物に無い"
    ax0, ax1 = sorted((fa * A_EXT[0], fa * A_EXT[1]))
    bx_0, bx_1 = sorted((fb * B_EXT[0], fb * B_EXT[1]))
    # 本体の外形を空き地の中央に置く → 軸の位置
    sx = (bx0 + bx1) / 2 - (bx_0 + bx_1) / 2 + s * float(os.environ.get("DT", CFG[half]["dt"]))   # 壁へ寄せる量
    sy = (by0 + by1) / 2 - (ax0 + ax1) / 2 + float(os.environ.get("DY_" + half.upper(), 0))

    if os.environ.get("TILT_ONLY"):
        row_top = CAP_LIFT + cap_height(nk)
        w_ = tilt_report(half, sx, sy, zm, cap_boxes(positions, keys), CAP_D)
        print(f"@@ {half} FA={fa} 倒れ {TILT:.0f}° キャップ φ{CAP_D:.0f}×{CAP_T:.0f} 覆い {CAP_OVER:.0f} 壁寄せ {os.environ.get('DT', CFG[half]['dt'])} 持ち上げ {lift} DY={sy - ((by0 + by1) / 2 - (ax0 + ax1) / 2):+.1f}: 最小の隙間 {w_:.2f}  キャップ上面−隣の段のキートップ {zm + H_TIP + CAP_OVER - PLATE_T - row_top:+.2f}")
        return {}

    def P(a, b, z):                                # スティック座標 (A, B, 高さ) → プレート座標
        return (sx + fb * b, sy + fa * a, zm + z)

    def Bx(da, db, dz, a, b, z):
        return Location(P(a, b, z)) * Box(db, da, dz, align=CTR)

    def Cy(r, h, a, b, z):
        return Location(P(a, b, z)) * Cylinder(r, h, align=CTR)

    core = fillet(Bx(CORE, CORE, H_FRAME, 0, 0, 0).edges().filter_by(Axis.Z), 0.8)
    body = core
    body += Bx(A_EXT[1] - CORE / 2, 10.0, H_VR, (A_EXT[1] + CORE / 2) / 2, 0, 0.4)            # VR1
    body += Bx(10.0, B_EXT[1] - CORE / 2, H_VR, 0, (B_EXT[1] + CORE / 2) / 2, 0.4)            # VR2
    body += Bx(8.0, -B_EXT[0] - CORE / 2, 6.0, 0, (B_EXT[0] - CORE / 2) / 2, 0.4)             # スイッチ
    body += Bx(-A_EXT[0] - CORE / 2, 6.0, 4.0, (A_EXT[0] - CORE / 2) / 2, 0, 1.0)             # 反対側の小さな出っ張り
    body += Cy(4.4, 1.3, 0, 0, H_FRAME)                                                        # 根元の丸み
    body += Cy(SHAFT_D / 2, H_TIP - H_FRAME, 0, 0, H_FRAME)
    pins = [Bx(0.3, 0.8, PIN_LEN, a, b, -PIN_LEN) for a, b in PINS[:3]] + [Bx(0.8, 0.3, PIN_LEN, a, b, -PIN_LEN) for a, b in PINS[3:]]
    pins += [Bx(0.8, 0.3, PIN_LEN - 0.3, a, b, -PIN_LEN + 0.3) for a, b in PINS_SW]
    pins += [Bx(0.3, 1.0, PIN_LEN - 0.3, a, b, -PIN_LEN + 0.3) for a, b in LUGS]
    stick = Compound(children=[body] + pins)
    cap = Location(P(0, 0, H_TIP + CAP_OVER - CAP_T)) * Cone(CAP_D_BOT / 2, CAP_D / 2, CAP_T, align=CTR)

    ca0, ca1, cb0, cb1 = A_EXT[0] - CUT_CLR, A_EXT[1] + CUT_CLR, B_EXT[0] - CUT_CLR, B_EXT[1] + CUT_CLR
    # 足の穴は長穴（左と同じ理由）。位置は爪 4 本（0.3×1.0 → 穴 0.8×1.5）と突起 2 つ（φ1.6 → 穴 φ1.8）で決まる。
    hs = PIN_SLOT / 2
    slots = [(-2.5 - hs, 2.5 + hs, PINS[0][1] - hs, PINS[0][1] + hs), (PINS[3][0] - hs, PINS[3][0] + hs, -2.5 - hs, 2.5 + hs)]
    slots += [(a - hs, a + hs, -10.25 - hs, -5.75 + hs) for a in (-3.25, 3.25)]
    slots += [(a - 0.4, a + 0.4, b - 0.75, b + 0.75) for a, b in LUGS]
    rounds = reduce(lambda p_, q: p_ + q, [Cy(0.9, 6.0, a, b, -5.0) for a, b in BOSS])
    # くり抜き: 本体の外形＋隙間。受け皿はプレートと主基板に挟まれて動かない（押さえは無い）。
    # **押さえを上ケースと一体にする案はやめた**（2026-10-06 夜）: 上ケースの枠の面より 8mm 上に出て、
    # 枠の面をベッドに付けて刷れなくなる（STL で測った: 押さえ上面 z 29.2・まわりの枠 21.0）。
    assert on_plate, "受け皿は取付面＝プレートの上面の高さだけに対応（沈める形は joystick_rkjxv_v5.py）"
    cut = Bx(ca1 - ca0, cb1 - cb0, PLATE_T + 0.4, (ca0 + ca1) / 2, (cb0 + cb1) / 2, -PLATE_T - 0.2)
    plate = pl * (build_plate(keys, half)[0] - cut)
    # 壁ぎわ（スティックを壁へ寄せた側）はつばを出さない。出すと底側の部品の縁に 1.4mm 食い込む
    wall_b1 = fb * s > 0
    WALL_IN = -0.6                                 # 壁ぎわは輪をくり抜きより 0.6 内へ引く（プレートの下は底側の部品の縁）
    fl = (TRAY_FLANGE, TRAY_FLANGE, WALL_IN if not wall_b1 else TRAY_FLANGE, WALL_IN if wall_b1 else TRAY_FLANGE)
    tray, foot_h = tray_solid(Bx, (ca0, ca1, cb0, cb1), slots, PINS + PINS_SW + LUGS + BOSS, flange=fl, notch="b1" if wall_b1 else "b1", rounds=rounds)

    # 帯（穴 13×7）とマイコンの基板。穴ごとの配置は build/joystick/pod_layout/pod_layout.py（キットは列 1〜10・行 0 と 3）: 主基板の下の空洞・机の座標（案 X と同じ）
    c0 = Vector(*STRIP_AT[half], 0)
    zb = FLOOR + BUMP
    zs = zb + UB_T
    Pi = 2.54

    def Bs(du, dv, dz, u, v, z):
        return Location((c0.X + u, c0.Y + v, z)) * Box(du, dv, dz, align=CTR)
    Uc = lambda i: (i - 6) * Pi                    # noqa: E731
    Vc = lambda j: (j - 3) * Pi                  # noqa: E731
    board = Bs(13 * Pi, 7 * Pi, UB_T, 0, 0, zb)
    board -= reduce(lambda a_, b_: a_ + b_, [Bs(1.0, 1.0, UB_T + 0.2, Uc(i), Vc(j), zb - 0.1) for i in range(13) for j in range(7)])

    # 両端に立てる部品（抵抗を折って立てる・コンデンサ）の占める空間。高さ 6.0 は「立てた 1/4W 小型抵抗」の見込み [推定]
    smalls = [Bs(Pi, 7 * Pi, 6.0, Uc(0), 0, zs), Bs(2 * Pi, 7 * Pi, 6.0, Uc(11.5), 0, zs), Bs(13 * Pi, 3 * Pi, 6.0, 0, Vc(5), zs)]
    zk = zs + POD_STACK
    mcu = [Bs(MCU_L, MCU_S, MCU_T, Uc(5.5), Vc(1.5), zk), Bs(3.0, 3.0, 0.8, Uc(5.5), Vc(1.5), zk + MCU_T)]
    for j in (0, 3):
        for i in range(1, 11):
            mcu += [Bs(Pi, Pi, POD_STACK, Uc(i), Vc(j), zs), Bs(0.64, 0.64, BUMP + UB_T + POD_STACK + MCU_T + 0.8, Uc(i), Vc(j), zb - BUMP)]

    # 線 5 本: 受け皿の下（主基板の上）→ 壁へ → 縁の溝 → 底板の上 → 帯。4 本: 帯 → 露出ビア
    zw = zp + 0.1
    t_s = (sx - x_open) * e                        # 軸の位置（開口の縁から内へ）
    yg = sy + float(os.environ.get("GDY_" + half.upper(), GROOVE_DY[half]))   # 溝の位置（前後）
    def seg_t(t0, t1, y):                          # 主基板の上を左右に走る線
        return Location((X((t0 + t1) / 2), y, zw)) * Box(abs(t1 - t0), WW5, WH, align=CTR)
    if abs(yg - sy) > 0.1:                         # 軸の下 → 壁ぎわを前後に → 溝
        t_w = T_INNER + 1.8
        w_top = seg_t(t_w, t_s, sy) + seg_t(T_INNER - 0.9, t_w + WW5, yg)
        w_top += Location((X(t_w + WW5 / 2), (sy + yg) / 2, zw)) * Box(WW5, abs(yg - sy) + WW5, WH, align=CTR)
    else:
        w_top = seg_t(T_INNER - 0.9, t_s, sy)
    g_top = (pl * Location((X(T_INNER - 0.5), yg, zw))).position
    gx = g_top.X
    ZW = FLOOR + 0.05
    groove_w = Location((gx, g_top.Y, ZW)) * Box(1.0, WW5, g_top.Z + WH - ZW, align=CTR)

    def run(p, q, n, xfirst):
        ww = n * WH
        mid = (q[0], p[1]) if xfirst else (p[0], q[1])
        segs = []
        for a_, b_ in ((p, mid), (mid, q)):
            dx, dy = abs(b_[0] - a_[0]), abs(b_[1] - a_[1])
            if dx + dy > 0.1:
                segs.append(Location(((a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2, ZW)) * Box(dx + ww, dy + ww, WH, align=CTR))
        return segs
    o5, o4 = [v == "x" for v in os.environ.get("ORDER_" + half.upper(), RUN_ORDER[half])]
    # 4 本（電源・GND・I2C）は、露出ビア（φ0.6 で細かすぎる）ではなく、子基板の裏の XIAO のピンへ
    via = Vector(*DB_PADS_RIGHT)
    floor5 = run((gx + e * 3.0, g_top.Y), (c0.X, c0.Y), 5, o5)
    floor4 = run((c0.X, c0.Y), (via.X, via.Y), 4, o4) + [Location((via.X, via.Y, ZW)) * Box(1.8, 1.8, via.Z - ZW - 0.05, align=CTR)]
    wire = Compound(children=[pl * w_top, groove_w] + floor5 + floor4)
    gw = (pl * Location((X(T_INNER - 0.6), yg, 0))).position
    # **底側のケースは彫らない**（2026-10-08）。前はここで壁に溝を彫っていたが、ケースは印刷済みで、
    # 主基板の縁と壁の隙間は 0.5mm しか無く線は通らない。線は主基板の上を奥へ走り、XIAO の脇で下へ降りる
    # （route_check.py が実形状の空間を探して確かめた道。絵の線は route_check.py が書き直す）。
    case = build_case(keys, half)[0]

    # 倒した姿（前後左右の 4 通り）を半透明で出す
    tilts = []
    for az in (0, 90, 180, 270):
        d = (math.cos(math.radians(az)), math.sin(math.radians(az)))
        rot_axis = Axis((sx, sy, zm + PIVOT), (-d[1], d[0], 0))
        lever = Compound(children=[Cy(SHAFT_D / 2, H_TIP - H_FRAME, 0, 0, H_FRAME), cap])
        tilts.append(lever.rotate(rot_axis, TILT))

    # ---- 数字 ----
    z_tip = zm + H_TIP - PLATE_T
    row_top = CAP_LIFT + cap_height(nk)
    print(f"== {half}: 案 R（RKJXV122400R・プレートをくり抜いて沈める）  向き FLIP_A={fa} FLIP_B={fb}")
    print(f"   空き地 {abs(bx1 - bx0):.2f} × {by1 - by0:.2f}  本体 {B_EXT[1] - B_EXT[0]:.1f} × {A_EXT[1] - A_EXT[0]:.1f}  "
          f"")
    print(f"   取付面: プレート上面の {PLATE_T - zm:+.2f} mm 下  くり抜き {cb1 - cb0:.1f}×{ca1 - ca0:.1f}  受け皿の脚 {foot_h:.2f}  足の先 → 主基板 {zm - PIN_LEN - zp:.2f} mm")
    print(f"   高さ（プレート上面から）: 枠の上 {zm + H_FRAME - PLATE_T:.2f}  軸の先 {z_tip:.2f}  キャップの上 {z_tip + CAP_OVER:.2f}"
          f"  ／ 隣の段のキートップ {row_top:.2f} → 差 {z_tip + CAP_OVER - row_top:+.2f}")
    worst = tilt_report(half, sx, sy, zm, cap_boxes(positions, keys), CAP_D)
    print(f"   → 倒したときの最小の隙間 {worst:.2f} mm")
    return {
        "joystick": pl * stick, "joystick_cap": pl * cap, "joystick_tilt": pl * Compound(children=tilts),
        "joystick_wire": wire, "joystick_seat": pl * tray,
        "plate": plate, "topcase": build_topcase(keys, half)[0], "case": case,
        "pod_board": Compound(children=[board] + smalls), "pod_mcu": Compound(children=mcu),
    }


STYLE_ADD = {
    "joystick":      ("#202020", 1.00),
    "joystick_cap":  ("#f5f5f5", 1.00),
    "joystick_tilt": ("#ff5050", 0.35),
    "joystick_seat": ("#e0b030", 1.00),
    "joystick_wire": ("#d03030", 1.00),
    "pod_mcu":       ("#2e9e4f", 1.00),
    "pod_board":     ("#c8a060", 1.00),
}

if __name__ == "__main__":
    dry = "--dry" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not dry:
        style_path = OUT / "style.json"
        style = json.loads(style_path.read_text())
        style.update({k: list(v) for k, v in STYLE_ADD.items()})
        style_path.write_text(json.dumps(style, indent=2))
    for half in args or ["left", "right"]:
        parts = build(half)
        if dry:
            continue
        for old in list(OUT.glob(f"{half}_pod_*.stl")) + list(OUT.glob(f"{half}_joystick_*.stl")):   # 置き換えたら古い方を消す
            if old.stem[len(half) + 1:] not in parts:
                old.unlink()
        for name, part in parts.items():
            export_stl(part, str(OUT / f"{half}_{name}.stl"))
    print("完了" if not dry else "（--dry: 何も書いていない）")
