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
    Locations, Mode, Plane, Rectangle, RectangleRounded, extrude

from interface import (CORNER_R, M2_CLEAR_D, PCB_INSET, PLATE_T, TILT_DEG,
                       boss_positions)

# --------------------------------------------------------------------------
# 基板とその実装部品
# --------------------------------------------------------------------------
PCB_T = 1.6              # [確定] FR4 の標準厚
# PCB_INSET は interface.py（凍結境界）から読む。基板生成と共有するため。
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
# **裸の電池 2 本**の両端に付く電極バネと配線に要る余裕。
#
# **電池ボックスの寸法ではない。**いまの設計は箱を使わず、ケース自身が
# 電池室になる（gen_case の「電池は 手前=仕切り壁 / 左右と奥=側壁 /
# 下=蓋 / 上=基板 で保持される」）。
#
# 文書側が「電池ボックスが届いたら測る」と書いていたため取り違えが起き、
# 設計に入らない横並び型（58 x 32mm）を買うことになった（open-gaps #22）。
AA_TERMINAL = 8.0        # [暫定] 電極バネと配線に要る長手方向の余裕（合計）

# --------------------------------------------------------------------------
# MCU
# --------------------------------------------------------------------------
# XIAO 単体の外形。**2026-08-08 に現物をノギスで実測**（USB コネクタを除く）。
# 届いたのは無印（USB と反対側の空きランドで確認。ブートローダは Sense 版と
# 共通で、ボリューム名は両方 XIAO-SENSE になるため当てにならない）。
# 技適 211-220207 は無印と Sense の両方を対象とする。
# XIAO 単体の外形。**2026-08-08 に現物をノギスで実測。**
#   21 x 18 x 3mm（基板と実装部品のみ）
#   厚みは **USB コネクタを含めると 4.5mm**、ピンヘッダは含まない
#
# 届いたのは無印。USB と反対側の空きランドで確認した。**ブートローダの
# 表記は当てにならない**（無印にも Sense 用が載って出荷され、ボリューム名は
# 両方 XIAO-SENSE、Board-ID も Seeed_XIAO_nRF52840_Sense になる）。
# 技適 211-220207 は無印と Sense の両方を対象とするので、どちらでも合法。
#
# **この 3 つはどこからも使われていない**（記録のためだけ）。ケースに効くのは
# 下の DB_STACK_H。
XIAO_L, XIAO_W, XIAO_H = 21.0, 18.0, 3.0        # [確定] 実測。USB とヘッダを除く
XIAO_H_WITH_USB = 4.5                            # [確定] 実測。USB コネクタ込み


# ホットスワップソケットが基板の裏へ張り出す範囲（キー中心から mm）。
# 実際のフットプリント pcb/lib/keyswitch.pretty の実測値に、はんだ付けの
# 余裕を少し足したもの。KiCad は Y 下向きなので符号を反転済み。
#
# 当初は「キー領域全体を覆う一枚の板」として粗く見積もっていたが、
# 取付ネジをキーの隙間へ移したところ、その粗さがボスとの干渉として出た。
# ソケットは各キーの下にしか無いので、実物どおりキーごとに置く。
# **出所は bands.py。**ここにも同じ数字を書いていて、変異検査でどちらも
# 生き残った（＝片方だけ直しても誰も気づかない状態だった）。
from bands import (SOCK_HI as SOCKET_Y1, SOCK_LO as SOCKET_Y0,  # noqa: E402
                   SOCK_X_HI as SOCKET_X1, SOCK_X_LO as SOCKET_X0)


def pcb_envelope(w, h_plate, half, keys):
    """基板とソケットが占有する空間（プレート座標系、原点は板の中心）。

    基板はプレートと平行に、その下へ入る。取付ネジの位置には穴が要る
    （ケースのボスが貫くため）。ソケットはキーごとに置く。
    """
    from gen_plate import plate_positions

    positions, _ = plate_positions(keys)
    with BuildPart() as env:
        # 基板そのもの
        with BuildSketch():
            RectangleRounded(w - PCB_INSET * 2, h_plate - PCB_INSET * 2, CORNER_R)
            with Locations(*boss_positions(half)):
                Circle(M2_CLEAR_D / 2, mode=Mode.SUBTRACT)
        extrude(amount=-PCB_T)
        # ソケットはキーの下だけ。まとめて 1 つのスケッチにして一度に押し出す。
        with BuildSketch(Plane.XY.offset(-PCB_T)):
            for kx, ky in positions:
                with Locations((kx + (SOCKET_X0 + SOCKET_X1) / 2,
                                ky + (SOCKET_Y0 + SOCKET_Y1) / 2)):
                    Rectangle(SOCKET_X1 - SOCKET_X0, SOCKET_Y1 - SOCKET_Y0)
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


# --------------------------------------------------------------------------
# 子基板（XIAO を載せる小さな別基板）
# --------------------------------------------------------------------------
# **XIAO_H と名づけてはいけない。**45 行目の XIAO_H（XIAO 単体の高さ 5.0mm）を
# 上書きしてしまう。実際に一度上書きし、定数の重複定義を検査する
# test_constants.py が見つけた。
# 子基板の上面から XIAO の頭まで。**USB コネクタを含む。**
#
# XIAO を直付けするなら実測の 4.5mm（XIAO_H_WITH_USB）でよいが、
# 仕様は「**ピンソケット実装で交換可能にする**」としている。ソケットの
# 高さぶんこれより高くなる。**ソケットの品種が未定なので暫定のまま。**
# 4.0 は直付けの実測 4.5mm すら下回っていた（2026-08-08 に 4.5 へ）。
DB_STACK_H = 4.5         # [暫定] 子基板の上面から XIAO の頭まで（USB 込み・ソケット未定）

# 電源スイッチ。**基板には載らない。**ケース背面のパネルに付けて
# リード線で基板のランド（SW_PWR_1 / SW_PWR_2）へ繋ぐ（open-gaps #17）。
#
# C&K OS102011MA1QN1（SPDT・非ショーティング・0.1A @ 12VDC）。
# データシート I-42 ページの外形図から読んだ値。
#   本体 8.60 x 4.40mm、奥行 約 4.70mm、ストローク 2.00mm、ピン間 8.20mm
#
# **図面を読んだ値であって、現物を測った値ではない。**届いたらノギスで
# 確かめて入れ直すこと。
#
# **縦向きに取り付ける。**本体 8.60 x 4.40 のうち長いほうを上下にする。
# 横向き（長いほうを左右）にすると受けの箱が 12.0mm になり、左半分の
# 枠 10.6mm に入らず、電池と子基板の両方に食い込んだ（組み立て検査が
# 42.6mm^3 と 34.6mm^3 で検出）。縦向きなら箱は 7.8mm で収まる。
#
# 右アングルなので、回しても操作部は背面を向いたまま。スライド方向が
# 左右から上下に変わるだけで、操作に不都合は無い。
#
# 向き: 幅 = 背面パネルに沿った左右、奥行 = パネルの裏、高さ = 上下。
# 奥行にはスルーホール端子とリード線のぶんを足してある。
SW_PWR_W = 4.4           # [暫定] 電源スイッチ本体の幅（左右）＝ 本体の短辺
SW_PWR_D = 8.0           # [暫定] 同・奥行（パネル裏。端子と配線を含む）
SW_PWR_H = 8.6           # [暫定] 同・高さ（上下）＝ 本体の長辺

# M2 熱圧入インサートの長さ。**外径だけでなく長さにも制約がある。**
#
# 子基板の取付ボスは高さ 4.0mm（gen_case.DB_BOSS_H）で、下穴は
# +1.0mm の 5.0mm しか掘っていない。**市販の M2 インサートには
# 5.7mm・6.0mm もあり、それを買うと入らない。**
# 外径は interface.M2_INSERT_D = 3.2mm で規定済みだが、長さは
# どこにも書かれていなかった（open-gaps #24）。
M2_INSERT_L = 4.0        # [暫定] 買う予定のインサートの長さ

# 本体基板（J_DB）と子基板（J_MAIN）を結ぶ FFC ケーブル。
#
# **まだ買っていない。**0.5mm ピッチ 12 芯の既製品から選ぶ前提で、
# 手に入りやすい 100mm を置いている。
FFC_LENGTH = 100.0       # [暫定] FFC ケーブルの長さ

# 直線距離に足す余裕。垂直の落差・両端の曲げ半径・抜け止めの遊び。
# **実測ではなく見積もり。**ケーブルを張った状態で使ってはいけないので、
# 直線距離ぴったりでは足りない。
FFC_SLACK = 25.0         # [暫定] FFC に要る直線距離以外の余裕


def daughterboard_envelope(center, w, d, t):
    """子基板と、その上に載る XIAO が占める空間。

    **基板だけでなく XIAO の高さを含める。** 基板の板厚だけで検査すると、
    その上に立つ部品が本体基板とぶつかるのを見逃す。
    """
    from build123d import Box, BuildPart, Locations, Align

    with BuildPart() as env:
        with Locations(center):
            Box(w, d, t + DB_STACK_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return env.part
