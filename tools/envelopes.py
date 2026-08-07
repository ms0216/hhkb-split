"""まだ設計していない部品が占有する空間を、先に確保しておく。

部品を単体で作ってから組み合わせると、統合の段階で破綻が出る。実際、
電池室を基板の真下に置いてしまい、傾いた基板と 4,000mm^3 衝突した。
先に「ここは誰かが使う」と宣言しておけば、ケースを作る時点で当たる。

ここに置くのは**空間の予約**であって部品ではない。実物の設計が済んだら
その部品に置き換える。それまでは保守的（大きめ）に見積もる。

確度の表記:
  [確定]  実測または規格から確定した寸法
  [暫定]  実測待ち。値は保守的に大きめ。実測が入ったら差し替える
"""

from math import radians, tan

from build123d import Align, Box, BuildPart, BuildSketch, Circle, Location, \
    Locations, Mode, Plane, RectangleRounded, extrude

from interface import CORNER_R, M2_CLEAR_D, PLATE_T, TILT_DEG, boss_positions

# --------------------------------------------------------------------------
# 基板とその実装部品
# --------------------------------------------------------------------------
PCB_T = 1.6              # [確定] FR4 の標準厚
PCB_INSET = 3.0          # [確定] プレート外形より内側へ引く量。
                         #        ケースの側壁 2.4mm の内側に収める必要がある。
                         #        1.0mm にしていて壁と 17,000mm^3 衝突した
SOCKET_DROP = 3.2        # [暫定] Kailh ホットスワップソケットが基板下へ出る量
SOCKET_INSET = 7.0       # [確定] ソケットが存在する範囲。基板の全面ではなく
                         #        キーの下だけ。全面に広げるとネジボスと衝突する
PLATE_TO_PCB = 3.5       # [暫定] プレート下面から基板上面までの距離。
                         #        MX 軸のピン長で決まる。実測待ち

# --------------------------------------------------------------------------
# 電池
# --------------------------------------------------------------------------
AA_D, AA_L = 14.5, 50.5  # [確定] 単3
AA_TERMINAL = 8.0        # [暫定] 電極バネと配線に要る長手方向の余裕（合計）

# --------------------------------------------------------------------------
# MCU
# --------------------------------------------------------------------------
XIAO_L, XIAO_W, XIAO_H = 21.0, 17.5, 5.0   # [暫定] ピンソケット込みの概略


def pcb_envelope(w, h_plate):
    """基板とソケットが占有する空間（プレート座標系、原点は板の中心）。

    基板はプレートと平行に、その下へ入る。取付ネジの位置には穴が要る
    （ケースのボスが貫くため）。
    """
    with BuildPart() as env:
        # 基板そのもの
        with BuildSketch():
            RectangleRounded(w - PCB_INSET * 2, h_plate - PCB_INSET * 2, CORNER_R)
            with Locations(*boss_positions(w, h_plate)):
                Circle(M2_CLEAR_D / 2, mode=Mode.SUBTRACT)
        extrude(amount=-PCB_T)
        # ソケットが下へ出る範囲はキーの下だけ。基板の縁まで広げると
        # 外周のネジボスと衝突する（9,300mm^3 の食い込みとして検出された）。
        with BuildSketch(Plane.XY.offset(-PCB_T)):
            RectangleRounded(w - SOCKET_INSET * 2, h_plate - SOCKET_INSET * 2,
                             CORNER_R)
        extrude(amount=-SOCKET_DROP)
    return env.part


def place_pcb(env, h_plate, rim_front):
    """基板の占有空間を、傾いたプレートの下へ置く。"""
    mid_z = rim_front + (h_plate / 2) * tan(radians(TILT_DEG))
    return (Location((0, 0, mid_z), (TILT_DEG, 0, 0))
            * Location((0, 0, -PLATE_TO_PCB)) * env)


def battery_envelope(center):
    """単3×2 と電極が占有する空間。

    左右方向に 2 本直列で寝かせる。前後に並べると奥行 30mm を要し、
    傾いた基板の下に入らない。
    """
    with BuildPart() as env:
        with Locations(center):
            Box(AA_L * 2 + AA_TERMINAL, AA_D + 1.0, AA_D,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
    return env.part


def pcb_bottom_at(y, h_plate, rim_front):
    """奥行位置 y における基板下端の高さ。

    傾いているので位置によって変わる。電池やボスの高さを決めるときは
    必ずこの関数で確認する（一定と思い込んで衝突させた）。
    """
    rim = rim_front + (y + h_plate / 2) * tan(radians(TILT_DEG))
    return rim - PLATE_TO_PCB - PCB_T - SOCKET_DROP
