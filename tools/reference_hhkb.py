"""確定した寸法から HHKB オリジナルの断面を組み立て、図として検証する。

数表のままでは形が正しいか判断できないので、いったん実機を再現する
参照モデルを作る。目的は 2 つ:

  1. 人が実機と見比べて「合っている / ずれている」を判断できるようにする
  2. 数値どうしの矛盾を炙り出す（表では気づけない不整合が図では出る）

すべての寸法は docs/hardware/dimensions.md に出典つきで記録済み。
このスクリプトは値を持たず、下の CONFIRMED / ASSUMED から組み立てる。
"""

import sys
from dataclasses import dataclass
from math import radians, tan
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
UNIT = 19.05

# --------------------------------------------------------------------------
# 出典のある確定値（dimensions.md 参照）
# --------------------------------------------------------------------------
WIDTH = 294.0            # PFU 公称
DEPTH_BODY = 108.0       # Tom's Hardware（電池コブを除く本体部）
DEPTH_FULL = 120.0       # PFU 公称（コブ込み）
H_FRONT = 17.0           # Tom's Hardware 実測
H_REAR = 31.8            # Tom's Hardware 実測
H_TOTAL = 40.0           # PFU 公称（キートップ上面まで）
PLATE_ANGLE = 7.3        # topre_key: "Angle measured on the HHKB"

# 列ごとのキャップ高さと天面角（topre_key の ROW_DIMENSIONS、実機ノギス実測）
# 手前から奥へ: 最下段 → ZXCV → ホーム → QWERTY → 数字段
ROWS = [
    ("bottom", 6.7, -13.0),
    ("ZXCV", 6.7, -13.0),
    ("home", 6.7, -8.0),
    ("QWERTY", 8.2, -2.0),
    ("number", 10.2, +2.0),
]
KEYCAP_BOTTOM_W = 18.0   # topre_key: Bottom base length/width
KEYCAP_TOP_W = 11.5      # topre_key: Top base width

# --------------------------------------------------------------------------
# 出典がなく、図の整合性から決める値（ASSUMED = 要検証）
# --------------------------------------------------------------------------
FRONT_BEZEL = (DEPTH_BODY - 5 * UNIT) / 2   # 前後ベゼルの配分は不明。とりあえず等分

# --------------------------------------------------------------------------
# 実機写真から読み取った形状（PHOTO = 定性的に確認、数値は目測）
#
# 出典: pdweb.jp の HHKB Professional BT レビュー 97_11.jpg（前縁の接写）
# 当初この断面を「垂直な前後面をもつ台形」としていたが、実機は違った:
#   - 前面は垂直でなく、下へ行くほど奥へ傾く（最前点は上端付近）
#   - ベゼル上面から前面への移行は大きな R で丸い
#   - 側面の中ほどに上下シェルの合わせ目が走る
#   - 合わせ目より下は内側にさらに絞られ、底は一回り小さい
#   - キーは窪んだトレイの中にあり、ベゼルのリムがキー面より上に立つ
# 数値は写真からの目測。角度・R とも実測ではない。
# --------------------------------------------------------------------------
FRONT_LEAN_DEG = 12.0     # 前面の傾き（垂直から。下ほど奥へ）
FRONT_TOP_R = 6.0         # ベゼル上面 → 前面 の丸み
SEAM_RATIO = 0.45         # 合わせ目の高さ（前縁高さに対する比）。断面には現れないため図示しない
BOTTOM_INSET = 2.0        # 合わせ目より下の絞り込み量（表面特徴。断面には現れない）
BEZEL_RIM_H = 1.5         # キー面に対してベゼルのリムが立ち上がる高さ


@dataclass
class Geometry:
    plate_z_at_rear_row: float
    cap_lift: float            # プレート上面からキャップ底面までの距離
    rows_y: list
    rows_cap_top_z: list
    clearance_front: float     # 前縁でプレートがベゼル上面よりどれだけ低いか


def row_y(i):
    """列 i（0=最下段）のキー中心の奥行位置。手前を 0 とする。"""
    return FRONT_BEZEL + (i + 0.5) * UNIT


def case_top_z(y):
    """ケース上面（ベゼル）の高さ。前縁 H_FRONT から後縁 H_REAR への直線。"""
    return H_FRONT + (H_REAR - H_FRONT) * (y / DEPTH_BODY)


def solve(cap_lift):
    """キャップ底面がプレートから cap_lift だけ浮くとして全体を解く。

    拘束: 最奥列（数字段）のキートップ上面が公称 40mm になること。
    """
    t = tan(radians(PLATE_ANGLE))
    y_rear = row_y(4)
    plate_z_rear = H_TOTAL - ROWS[4][1] - cap_lift
    ys, tops = [], []
    for i, (_, cap_h, _) in enumerate(ROWS):
        y = row_y(i)
        plate_z = plate_z_rear - (y_rear - y) * t
        ys.append(y)
        tops.append(plate_z + cap_lift + cap_h)
    plate_front = plate_z_rear - (y_rear - FRONT_BEZEL) * t
    return Geometry(
        plate_z_at_rear_row=plate_z_rear,
        cap_lift=cap_lift,
        rows_y=ys,
        rows_cap_top_z=tops,
        clearance_front=case_top_z(FRONT_BEZEL) - plate_front,
    )


def check():
    """cap_lift を変えて、プレートがベゼルより下に収まる条件を調べる。"""
    print("プレートがケース上面より下に収まるか（前縁で判定）")
    print(f"{'cap_lift':>9} {'プレート(奥列)':>14} {'前縁クリアランス':>16}  判定")
    ok_lift = None
    for lift in [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]:
        g = solve(lift)
        ok = g.clearance_front > 0
        if ok and ok_lift is None:
            ok_lift = lift
        print(
            f"{lift:9.1f} {g.plate_z_at_rear_row:14.2f} "
            f"{g.clearance_front:16.2f}  {'OK' if ok else 'NG プレートがベゼルより上'}"
        )
    return ok_lift


def draw_section(g, ax, annotate=True):
    """側面断面を実寸で描く。手前が左、奥が右。"""
    # ケース外形（本体部）。写真から読み取った形状を反映する。
    #
    # 前縁の作り方: ベゼル上面は前縁で高さ H_FRONT を保つ。そこから半径
    # FRONT_TOP_R の円弧で前面へ回り込み、前面は垂直から FRONT_LEAN_DEG だけ
    # 傾いて（下ほど奥へ）底に達する。円弧の接点で前面と滑らかに繋がるよう、
    # 円弧の中心を (FRONT_TOP_R, H_FRONT - FRONT_TOP_R) に置く。
    #
    # 上下シェルの合わせ目は「表面上の線」であって断面の形状ではないため、
    # 断面図には描かない（実機写真では側面にはっきり見える）。
    lean_rad = radians(FRONT_LEAN_DEG)
    cy, cz = FRONT_TOP_R, H_FRONT - FRONT_TOP_R
    arc = []
    for k in range(13):                     # ベゼル上面 → 前面 への 1/4 弱の円弧
        a = radians(90) * k / 12 - lean_rad * (k / 12)
        arc.append((cy - FRONT_TOP_R * __import__("math").sin(a),
                    cz + FRONT_TOP_R * __import__("math").cos(a)))
    y_face_top, z_face_top = arc[-1]
    y_bottom_front = y_face_top + z_face_top * tan(lean_rad)
    case = (
        [(y_bottom_front, 0)]                           # 底の前端
        + arc[::-1]                                     # 前面 → 丸み → ベゼル上面
        + [(DEPTH_BODY, H_REAR), (DEPTH_BODY, 0)]       # 上面 → 後縁 → 底
    )
    ax.add_patch(Polygon(case, closed=True, fill=False, lw=1.6, ec="black"))
    bump = [
        (DEPTH_BODY, 0), (DEPTH_BODY, H_REAR),
        (DEPTH_FULL, H_REAR), (DEPTH_FULL, 0),
    ]
    ax.add_patch(Polygon(bump, closed=True, fill=False, lw=1.0, ec="gray", ls="--"))

    # プレート面
    t = tan(radians(PLATE_ANGLE))
    y0, y1 = FRONT_BEZEL, FRONT_BEZEL + 5 * UNIT
    z_rear = g.plate_z_at_rear_row
    z0 = z_rear - (row_y(4) - y0) * t
    z1 = z_rear - (row_y(4) - y1) * t
    ax.plot([y0, y1], [z0, z1], color="#1f77b4", lw=1.2)

    # 各列のキーキャップ断面（台形）
    for i, (name, cap_h, top_ang) in enumerate(ROWS):
        y = g.rows_y[i]
        plate_z = z_rear - (row_y(4) - y) * t
        bz = plate_z + g.cap_lift
        # 底面（18mm）と天面（11.5mm）。天面は top_ang だけ傾く
        bl, br = y - KEYCAP_BOTTOM_W / 2, y + KEYCAP_BOTTOM_W / 2
        tl, tr = y - KEYCAP_TOP_W / 2, y + KEYCAP_TOP_W / 2
        dz = (KEYCAP_TOP_W / 2) * tan(radians(top_ang))
        # 符号: 負 = 手前が高く奥へ下がる
        zt_front, zt_rear = bz + cap_h - dz, bz + cap_h + dz
        cap = [(bl, bz), (tl, zt_front), (tr, zt_rear), (br, bz)]
        ax.add_patch(Polygon(cap, closed=True, fill=True, fc="#d9e6f2",
                             ec="#1f77b4", lw=1.0))
        if annotate:
            ax.text(y, bz + cap_h + 3, f"{name}\n{cap_h}mm / {top_ang:+.0f}°",
                    ha="center", va="bottom", fontsize=6, color="#1f77b4")

    if annotate:
        ax.annotate("", xy=(0, 0), xytext=(0, H_FRONT),
                    arrowprops=dict(arrowstyle="<->", color="crimson", lw=0.8))
        ax.text(-3, H_FRONT / 2, f"{H_FRONT}", ha="right", va="center",
                fontsize=7, color="crimson")
        ax.annotate("", xy=(DEPTH_BODY, 0), xytext=(DEPTH_BODY, H_REAR),
                    arrowprops=dict(arrowstyle="<->", color="crimson", lw=0.8))
        ax.text(DEPTH_BODY + 2, H_REAR / 2, f"{H_REAR}", ha="left", va="center",
                fontsize=7, color="crimson")
        ax.axhline(H_TOTAL, color="green", lw=0.7, ls=":")
        ax.text(DEPTH_FULL, H_TOTAL + 0.5, f"nominal total height {H_TOTAL}mm",
                ha="right", fontsize=7, color="green")
        ax.plot([0, DEPTH_FULL], [0, 0], color="black", lw=1.0)

    ax.set_aspect("equal")
    ax.set_xlim(-12, DEPTH_FULL + 12)
    ax.set_ylim(-6, H_TOTAL + 14)


def main():
    BUILD.mkdir(exist_ok=True)
    print(f"前後ベゼル（仮に等分）: {FRONT_BEZEL:.2f}mm ずつ")
    print(f"ケース上面の傾斜: {DEPTH_BODY}mm で {H_REAR - H_FRONT}mm 上がる = "
          f"{__import__('math').degrees(__import__('math').atan((H_REAR - H_FRONT) / DEPTH_BODY)):.2f}°")
    print(f"プレート面の傾斜: {PLATE_ANGLE}° (実測)\n")

    lift = check()
    if lift is None:
        print("\nどの cap_lift でも成立しない。前提のどれかが誤っている。")
        return 1
    print(f"\n成立する最小の cap_lift = {lift:.1f}mm 。これを採用する。")

    g = solve(lift)
    print("\n各列のキートップ上面の高さ（机上面から）:")
    for (name, cap_h, ang), y, top in zip(ROWS, g.rows_y, g.rows_cap_top_z):
        print(f"  {name:8s} 奥行 {y:6.1f}mm  キートップ {top:5.1f}mm")

    fig, ax = plt.subplots(figsize=(13, 5), dpi=150)
    draw_section(g, ax)
    ax.set_xlabel("depth [mm]  (front <- -> rear)", fontsize=8)
    ax.set_ylabel("height [mm]", fontsize=8)
    ax.set_title("HHKB Professional HYBRID Type-S : reference section "
                 "(reconstructed from sourced dimensions)", fontsize=10)
    ax.grid(True, lw=0.3, alpha=0.4)
    fig.savefig(BUILD / "hhkb_reference_section.png", bbox_inches="tight")
    plt.close(fig)
    print(f"\n断面図: {BUILD / 'hhkb_reference_section.png'}")

    # 1:1 の実寸 PDF（A4 横に側面断面を原寸で置き、実機に当てて比較する）
    mm = 1 / 25.4
    with PdfPages(BUILD / "hhkb_reference_1to1.pdf") as pdf:
        fig = plt.figure(figsize=(297 * mm, 210 * mm))
        ax = fig.add_axes([0.06, 0.30, 0.88, 0.45])
        draw_section(g, ax, annotate=False)
        ax.set_axis_off()
        # 100mm の基準スケール（印刷倍率の確認用）
        ax.plot([0, 100], [-4, -4], color="red", lw=1.0)
        for x in (0, 100):
            ax.plot([x, x], [-6, -2], color="red", lw=1.0)
        ax.text(50, -9, "100 mm reference (check print scale)", ha="center", color="red", fontsize=7)
        fig.text(0.06, 0.90, "HHKB reference side section — print at 100% scale",
                 fontsize=11)
        fig.text(0.06, 0.86,
                 "Place the real keyboard facing right; align its front-bottom corner with the lower-left corner of this drawing.",
                 fontsize=8)
        pdf.savefig(fig)
        plt.close(fig)
    print(f"1:1 PDF: {BUILD / 'hhkb_reference_1to1.pdf'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
