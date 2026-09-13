"""ボトムケースを生成する。

外形はプレートと同じ輪郭。プレートがそのまま天板になるサンドイッチ構造で、
ケースはプレートを載せるトレイになる。上面は打鍵面と同じ 7.3° に傾く。

高さの基準:
  PLATE_TOP_FRONT — 前縁でのプレート上面の高さ。**唯一の調整つまみ**。
  スイッチとキーキャップの実寸が分かったら、ホーム段のキートップが
  31.6mm（実機の値、docs/hardware/dimensions.md §4.5）になるよう
  この 1 つを動かす。ケースは 3Dプリントなので刷り直しの費用はほぼゼロで、
  基板には影響しない。

電池は単3×2 を奥側に寝かせる。実機も同じ配置（背面の電池コブ）。

3Dプリント向け CAD ではまった落とし穴（同じ轍を踏まないこと）:
  - BuildPart のコンテキスト内で Box() 等を作ると、その時点で部品に合体される。
    切削用の立体はコンテキストに入る前に作ること。
  - builder.part への直接代入はビルダーの内部状態を更新しない。
    add(..., mode=Mode.SUBTRACT) を使うこと。
  - 既に空洞の中を削っても何も起きない。仕切りは「壁を立てる」操作。
  - **形状どうしをちょうど接する位置に置かない。** 接線接触や同一平面は
    非多様体メッシュ（印刷不能）になる。1mm 程度めり込ませるか離すこと。
"""

import sys
from math import degrees, radians, tan
from pathlib import Path

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    BuildSketch,
    Cylinder,
    Location,
    Locations,
    Mode,
    add,
    Plane,
    Polygon,
    Rectangle,
    RectangleRounded,
    RegularPolygon,
    extrude,
    loft,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
# 電池ボックスの外形。**出所は envelopes.py の 1 か所だけ。**
# （残りの envelopes からの取り込みは下の方にあるが、BATT_* は定数の定義で
#   使うのでここで先に読む）
from envelopes import BATT_BOX_H, BATT_BOX_L, BATT_BOX_W, XIAO_W  # noqa: E402
from gen_plate import build_plate, halves, plate_positions  # noqa: E402
from interface import (  # noqa: E402
    BEZEL_OPENING_GAP,
    CLEARANCE,
    BEZEL_TOP_FRONT,
    BEZEL_WALL,
    PLATE_MARGIN_X,
    PLATE_MARGIN_Y,
    CORNER_R,
    boss_positions_plan,
    plan_depth,
    M2_BOSS_D,
    M2_CLEAR_D,
    M2_INSERT_D,
    M2_PILOT_D,
    PLATE_T,
    boss_positions,
    battery_x_center,
    daughterboard_x_center,
    inner_sign,
)

# --------------------------------------------------------------------------
# 実機から確定した値（docs/hardware/dimensions.md §4.5）
# --------------------------------------------------------------------------
TILT_DEG = 7.3           # 打鍵面の傾斜。topre_key の実測値

# 前縁でのプレート上面高さ。**定数で置かず、要求から導く。**
#
# 以前は 17.5 と直接書いていた。「実機の手前縁 17mm に合わせた」つもりだったが、
# **その 17mm はベゼル（リム）の高さで、実機のプレート面は 14.00mm**。
# 取り違えた結果、全段のキートップが 3.5mm 高くなっていた。
#
#   ホーム段  実機 31.6mm  →  当時の設計 35.1mm
#
# しかも test_keytop_heights_match_the_real_machine は参照モデルが実機と
# 合っているかを見ているだけで、**私たちの設計は検査していなかった**。
# 最重要要求を守っているように見えて、守っていないテストだった。
#
# 以後は目標から逆算する。キャップの実測が入れば自動でここが動く。
TARGET_KEYTOP_HOME = 31.6    # 実機のホーム段キートップ高さ（dimensions.md §4.5）
CAP_LIFT = 6.2               # [暫定] プレート上面 → キーキャップ底面（MX ＋ キャップ）
# ホーム段のキャップ高さ。**DSA プロファイルの暫定候補。**
#
# 実機（Topre）は 6.7mm（reference_hhkb.ROWS）。MX で選べる主なプロファイルを
# 入れて組み立て検査を回したところ、**入るのは DSA だけだった**:
#
#   6.7 実機   → PLATE_TOP_FRONT 11.78  OK
#   7.6 DSA    → PLATE_TOP_FRONT 10.88  OK
#   9.1 XDA    → PLATE_TOP_FRONT  9.38  NG 基板と 230mm^3 食い込み
#   9.4 Cherry → PLATE_TOP_FRONT  9.08  NG 基板と 368mm^3 食い込み
#
# 背の高いキャップほどプレートが下がり、ケースが基板を噛む。
# **私たちが履かせるキーキャップの、段ごとの高さ。**手前から奥へ。
#
# 参照モデル（reference_hhkb.ROWS）は**実機 Topre** の値で、これとは別物。
# 一緒にすると「実機のキャップを履かせたら」という計算になり、
# 実際に買うキャップとのズレが見えない（実際そうなっていた）。
#
# いまの選択は **DSA（均一 7.6mm）**。MX で選べるプロファイルのうち、
# ケースが基板を噛まずに収まるのは DSA だけだった（open-gaps #21）。
#
# **段ごとに違うキャップを混ぜるなら、ここを段ごとに変える。**
# そうすれば実機とのズレが検査に出る。
#
# **2026-08-11・利用者の決定: 下 3 段は DSA、上 2 段は背の高いものを混ぜる。**
# ケースの高さを決めるのはホーム段だけなので、**ケースは変わらない**
# （下の PLATE_TOP_FRONT は home しか読まない）。
#
# 上 2 段の 2 つは「実機のキートップ高さに一致する高さ」から逆算した
# **要求値**で、まだ実在の品番に紐づいていない（open-gaps #21）。
CAP_H_QWERTY = 9.16    # [暫定] QWERTY 段のキャップ高さ。実機 35.6mm に要る値
CAP_H_NUMBER = 11.12   # [暫定] 数字段のキャップ高さ。実機 40.0mm に要る値
OUR_CAPS = {
    "bottom": 7.6,      # DSA
    "ZXCV": 7.6,        # DSA
    "home": 7.6,        # DSA
    "QWERTY": CAP_H_QWERTY,
    "number": CAP_H_NUMBER,
}
CAP_H_HOME = OUR_CAPS["home"]   # [暫定] ケースの高さはホーム段だけで決まる

# layout の y は**下向きが正**（原点は配列の左上）なので、y の小さい順＝奥から。
_ROWS_FROM_REAR = ["number", "QWERTY", "home", "ZXCV", "bottom"]


def cap_height(key):
    """そのキーに履かせるキャップの高さ。

    **段ごとに違うキャップを混ぜられるようにするための唯一の出所。**
    以前は組み立て検査が 61 個すべてを `OUR_CAPS["home"]` で建てており、
    上 2 段を高くしても**検査の中では高くならなかった**
    （検証の作法 4「検査対象に入っていない部品は、検査していないのと同じ」）。
    """
    return OUR_CAPS[_ROWS_FROM_REAR[int(round(key.y_mm / 19.05 - 0.5))]]
_Y_HOME = 6.375 + 2.5 * 19.05          # ホーム段のキー中心（手前から）
PLATE_TOP_FRONT = round(
    TARGET_KEYTOP_HOME - CAP_LIFT - CAP_H_HOME - _Y_HOME * tan(radians(TILT_DEG)), 2)

# --------------------------------------------------------------------------
# 3Dプリント（K1 Max / PLA / ノズル 0.4mm）に合わせた値
# --------------------------------------------------------------------------
WALL = 2.4               # 側壁。0.4mm の 6 倍
from interface import CASE_WALL as _IF_CASE_WALL  # noqa: E402
from interface import FRONT_BOSS_W, PCB_FRONT_EDGE_PLAN  # noqa: E402
from envelopes import M2_INSERT_L  # noqa: E402
assert WALL == _IF_CASE_WALL, (
    f"interface.CASE_WALL({_IF_CASE_WALL}) が gen_case.WALL({WALL}) とずれている")
FLOOR = 2.4              # 底板。0.4mm の 6 倍。
                         # 当初 2.0mm にしていたが、蓋(1.6mm)をレールに落とし込むと
                         # 床の内面より上に出て電池に食い込んだため厚くした。
# CLEARANCE（嵌合の逃げ 0.2）は interface.py から読む。プレートも同じ値で
# 上ケースの座ぐりに落とし込むので、出所を 2 つ持たない。
USB_HOLE_R = 1.2         # USB-C 穴の角の丸み。実物のメスの角 r≈1.0 に逃げを足した。
                         # 両端を半円にするとメスの箱の四隅が穴の外に出る（箱モードで
                         # 1.4mm³・2026-09-06）
PORT_CLEAR = 0.4         # 抜き差しする穴の逃げ。**0.6 → 0.4**（2026-09-06・利用者
                         # 「USB-C の穴が大きすぎる」。メスは外面から出ているので
                         # 穴が通すのはメス自体。印刷公差 0.2 ＋ 0.1）

# --------------------------------------------------------------------------
# 内部に収めるもの
# --------------------------------------------------------------------------
# 単3電池は**左右方向に 2 本直列**で寝かせる。
#
# 当初は前後方向に 2 本並べ（奥行 30mm 必要）、基板の真下に置いた。しかし
# 打鍵面が 7.3° 傾いているので基板も傾いて入り、手前側で 4,000mm^3 衝突した。
# 実機はこれを本体後ろの 12mm のコブで逃がしている。
#
# 占有空間から先に組み直したところ、左右方向に並べれば奥行は 15.5mm で済み、
# 傾いた基板の下の「奥側の背の高い領域」に収まることが分かった。
# コブを足す必要がなく、分割版として小さく収まる。
AA_D, AA_L = 14.5, 50.5
# **電池ボックス BH-325-1A150 を使う**（open-gaps #22・2026-08-11 の決定）。
# 出所は envelopes.py の 1 か所だけ。ここで足し引きしない。
# **箱は横倒し**（2026-09-05・案 A。envelopes.battery_envelope の注記）。
# 開口（箱の上面）を奥へ向けるので、箱の「高さ」が奥行に、「幅」が高さになる。
# **2026-09-06（器の案）: 箱は開口を下にして立てる。**電池は底板の蓋から出し入れ。
# 高さは箱の高さ、奥行は箱の幅。床の穴（2 個）は上を向き、天井から垂らした
# ボスへ箱の中からネジ。
BATT_H = BATT_BOX_H              # 占有高さ（z）＝箱の高さ 16.8
BATT_W = BATT_BOX_W              # 占有奥行（y）＝箱の幅 16.6
BATT_STAND = 0.2                 # 箱の下端と底板の上面の隙（蓋が閉じる側）
BATT_BOX_WALL = 1.0              # [暫定] 箱の壁厚（開口＝内側の寸法に使う。実測で確認）
BATT_BOSS_D = 6.4                # 天井から垂らす箱のボスの径（肉 1.6）
BATT_X = BATT_BOX_L              # 占有幅（長辺。裸の電池 2 本＋電極と同じ 109mm）
# interface.py は build123d を読めないので envelopes から取れず、同じ値を
# 持っている。**黙ってずれないよう、ここで突き合わせる。**
from interface import BATT_X as _IF_BATT_X  # noqa: E402
assert BATT_X == _IF_BATT_X, (
    f"interface.BATT_X({_IF_BATT_X}) が envelopes.BATT_BOX_L({BATT_X}) とずれている")
# 電池箱の開口面（奥）と奥板の内面の間隔。
BATT_MARGIN_REAR = 1.0
# 箱の床の取付穴（データシート: 2×φ2.4、内側から φ3.8×0.8 の座ぐり）。
# 横倒しなので床は手前（−y）を向き、穴の軸は y。
# 床（箱が接する面）から穴の中心までの高さ。**利用者が現物で実測**（2026-09-06）:
# 左 5.0 / 右 11.5（足すと 16.5 ≈ 箱の幅。左右で箱の上下が逆＝穴は箱の中心から
# 外れている）。図面の「4.1」を一律に使っていたのが間違いだった。
BATT_HOLE_Z_LEFT = 5.0           # [暫定] 利用者の実測
BATT_HOLE_Z_RIGHT = 11.5         # [暫定] 同
BATT_HOLE_X1_FROM_END = 75.9     # [暫定] 穴 1。黒線側の端から。図面 75.9±0.5
BATT_HOLE_X2_FROM_END = 82.8     # [暫定] 穴 2。同 75.9 に隣の 6.9±0.2 を足した
BATT_WIRE_NOTCH = 4.0            # 仕切り壁の両端に開ける、リード線の逃げ（幅・高さ）
# 箱の裏面（横倒しでは仕切り壁を向く面）のケーブル受けの突起。**利用者が現物を
# 実測**（2026-09-06）: 黒線側の端から 14 / 53.5 / 93、幅 4、高さ 5.5。仕切り壁を
# そこだけ切り下げる（利用者「他は下げなくてよい」）
# （箱の裏面のケーブル受けの突起 14 / 53.5 / 93・幅 4・高さ 5.5 は、器の案では
#   天井を向く面に来る。ボスの位置 75.9 / 82.8 と重ならないことを確認済み。
#   突起の高さ 5.5 < ボスの長さ 10.5 なので天井には届かない）
# 電池室の仕切り壁の高さ（床から）。
#
# ⚠️ **2026-08-29 に 16.8（＝BATT_H）→ 6.0 へ下げた。利用者が刷って触った指摘。**
# 以前は「電池箱の高さ」をそのまま仕切りの高さにしていた。根拠は無く、
# 箱と同じ値を入れただけだった。傾いた基板の下面で切られて実高 11.98mm。
# **これが 2 つの実害を出していた**（どちらも体積の干渉検査では出ない）:
#   * 電池箱は**奥面の口から挿す**設計なので、11.98mm の壁が挿入経路の
#     真横に立ち、入れにくい
#   * 箱の裏面のケーブルガイド（データシート側面図の 2.0/8.0/12.3 の
#     突起）に当たる
#
# **2026-09-05（案 A）: 仕切り壁が箱の締結面になる。**箱は横倒しで床（取付穴
# 2 個）が仕切り壁を向くので、壁に横向きのボスを立てて M2 で締める。
# ボスの上端（穴の高さ 6.5 ＋ 2.8）まで要るので 6.0 では足りず、**9.5**。
# 一度 12.0 にしたが、利用者「壁を低くしたはずでは」で見直し、要る高さに
# 戻した。8/29 の理由のうち「挿入経路の真横に壁」は、今は箱を奥から
# 真っ直ぐ差し込んで仕切りに突き当てるので当てはまらない。
# ⚠️ **もう 1 つの理由「裏面のケーブルガイドの突起」は当てはまる。**横倒し
# では突起のある面が仕切り壁（締結面）を向く。突起の高さは図面に無く、
# 締めたとき箱が壁から浮くか・突起が壁に当たるかは**現物で確認**
# （provisional-values.md の BATT_HOLE_* の行）。
# **2026-09-06: 仕切り壁をリム面まで伸ばしてプレートの奥端の受けにする**（利用者の
# 提案）。上シェルの棚は裏返して刷ると空中の庇になり、印刷が壊れた。仕切り壁は
# y=48.8〜51.2 で基板の奥縁（48.3）の後ろにあり、プレートの奥縁（52.3）の 1.1〜
# 3.5 内側を受ける。ここは「上限」で、実際の上面はリム面（cutter）で切る。
# 仕切り壁の厚み。リム面まで上げたら基板の奥縁（平面図で 48.95。傾きで奥へ
# 0.65 ずれる）と 0.19 重なったので、**手前側を 0.4 削って 2.0**（5 周）。
# 奥面（箱の床が当たる面）は動かさない（2026-09-06）
BATT_DIVIDER_T = 2.0
# プレートの奥端の受けは**下シェルの仕切り壁**（BATT_DIVIDER_H の注記）。
# 2026-08-29 に天井から垂らした棚で受け、9/5 に上シェルへ移し、9/6 に仕切り壁へ
# （上シェルの棚は裏返して刷ると庇になり印刷が壊れた）。棚の定数は消した。
# **コブは要る。実機と同じ理由で。**
#
# 一度「コブは不要になった」として 0 にしていた。だが実際には、
# プレートを 3.5mm 高くすることで無理に押し込んでいただけだった。
# ホーム段のキートップを実機どおり 31.6mm に戻した瞬間、電池が基板に
# 3,648mm^3 食い込むと組み立て検査が報告した。
#
# MX ＋ ホットスワップソケットは、プレート上面からソケット下端まで 9.8mm ある。
# Topre は基板の下に出っ張りが無いのでここが 5mm 以上薄い。**実機が単3×2 を
# 収めるためにコブを持っているのと、まったく同じ事情**が分割版にも当てはまる。
#
# 実機は本体 108mm ＋ コブ 12mm ＝ 奥行 120mm（PFU 公称）。同じ 12mm を採る。
_BUMP_BASE = 18.0                # 実機は 12mm。MX ＋ ソケットが Topre より
                                 # 5mm 厚いぶん、6mm 深くなる。12/14/16 では
                                 # 電池が基板に食い込むことを検査で確認した
#
# ⚠️ **ここを USB のために動かしてはいけない。**一度 18.555 にしたが撤回した
# （下の USB_RECESS の注記）。奥行は open-gaps #2 で既に実機 +5.1mm あり、
# CLAUDE.md「寸法は実機に合わせる。交渉可能なのは打鍵感だけ」に反する。
BUMP_DEPTH = _BUMP_BASE

# --------------------------------------------------------------------------
# 子基板（XIAO を載せる小さな別基板）
#
# 経緯は docs/hardware/decisions/2026-08-07-daughterboard.md。
# HHKB のキー配列は本体基板をほぼ埋め尽くすので、XIAO (21x17.8mm) の
# 置き場所が無い。別基板に載せてケース奥に置き、USB-C を実機と同じ奥面へ出す。
#
# **寝かせる。立てない。** XIAO は子基板に平らに載るので、子基板を立てると
# USB-C コネクタが横を向いてしまい、奥の壁に届かない。
# --------------------------------------------------------------------------
# DB_W の出所は interface.py（基板の生成が読むため）。ここは再輸出。
# 子基板の幅（左右）。XIAO は 17.8mm 幅。
# 20.0 では FFC コネクタと取付穴が入らなかった。
# 22.0 でも電池からは 10.2mm 離れ、条件を満たす
from interface import DB_W  # noqa: E402,F401
# **2.4GHz のアンテナから金属を遠ざける距離。**
#
# XIAO のアンテナは USB と反対の端にある。単3 電池は金属の塊で、至近距離に
# あるとアンテナを大きく狂わせる。左右間の BLE 接続はこのキーボードの
# 中核要件なので、その通信距離を自分で潰してはいけない。
#
# 一度 1.0mm まで寄せていた（電池を外へ寄せて子基板の場所を作った副作用）。
# 幾何の干渉だけを見て電波を見ていなかった。
#
# **5.0 の根拠は実測**（2026-08-24・利用者）。手 0 の構成で電池を
# アンテナの横に置いて RSSI を測った:
#   D  : 17mm   → 差 1dB（A のふらつき 7dB の中）
#   D' : 8.5mm  → 変化なし
#   D'' : 5mm   → 変化なし
# 5mm まで近づけても効かないので、下限を実測点 5.0 に置く。
# （初版の 10.0 はチップアンテナの一般指針「5〜10mm」の上限を丸めた
# 経験則で、測っていなかった。#51 の幅詰めで設計距離が 8.16mm になる
# 必要が生じ、D'/D'' で根拠を実測に置き換えた。）
DB_ANTENNA_KEEPOUT = 5.0
# 奥行 30mm。**XIAO とネジを同時に載せるには、この深さが要る。**
#
# 22mm では取付穴の置ける場所が 0 箇所だった。XIAO は 17.8x21mm で、
# ネジの逃げ（φ2.4＋ランド → 半径 2.2mm）が入る余地が残らない。
#   ネジを XIAO の脇に置く  → 幅 26.6mm 必要（使える幅は 22.2mm。不可）
#   ネジを XIAO の前後に置く → 奥行 29.8mm 必要
# コブの奥の内面 y=69.16 から 30mm 前は y=39.16。そこでの本体基板の
# 下端は 13.97mm（**保守平面 pcb_bottom_at の値。**「入る」と言う向きに
# だけ使ってよい）で、子基板スタック 12.5mm に対して余裕がある。
DB_D = 32.0
DB_T = 1.6
DB_BOSS_H = 4.0          # 床からの高さ。これが USB-C の高さを決める
DB_BOSS_D = 5.6          # ボス径。M2_BOSS_D を 6.4 にしたとき（2026-09-06）ここだけ 5.6 の
                         # まま: 6.4 だと右の子基板の裏面の部品に 0.32mm³ 当たる。高さ 4 で
                         # 荷重も小さいので据え置き（肉 1.2）
# **ネジは手前の 2 本だけ。奥は壁のポケットが受ける**（open-gaps #28）。
#
# 以前は対角（-8,-13.5）と（8,+13.5）だった。XIAO を奥へ寄せた（#28）ので、
# 奥のネジは XIAO の真下に入ってしまう。奥端は、壁に掘ったポケットへ
# XIAO の端を差し込む形で受ける。**組み立ては「奥を斜めに差してから手前を下ろす」。**
DB_BOSS_POS = [(-8.0, -13.5), (8.0, -13.5)]
# 奥の壁の内側と子基板の隙間。**1.0 → 0.4mm**（open-gaps #28）。
# メスを壁へ近づけるため。**ここは公差が食い合う場所**で、印刷 ±0.2mm と
# 基板外形 ±0.2mm が重なる。きつすぎれば入らない。クーポンで確かめること。
DB_FROM_REAR = 0.4

# --------------------------------------------------------------------------
# LED の窓（open-gaps #43・2026-08-24 利用者決定）
#
# **実機の LED 位置（右端から 61mm・上端から 6mm・実測）は再現しない**
# （利用者「左右に分かれている時点で位置まで一緒にする理由はない」）。
# 代わりに **XIAO の真上、コブの天井に薄肉の窓**を開ける。左右対称・
# 部品追加なし・基板に影響しない。PLA の 0.6mm ならインジケーターの
# 点灯が透ける。
#
# 位置の出所は Seeed 公式 STEP モデル（pcb_parts.json の立体一覧）:
#   RGB LED（4 パッド）… 子基板中心から (+5.72, +14.76)
#   充電 LED          … 同 (+5.70, +16.90)
# 窓は両方を覆う中間 (+5.71, +15.83)・φ5.0。モデルの読み取りなので、
# **実物を点灯させて窓から見えることを確認してから確定**
# （向きの取り違えは 2026-08-16 に踏んだ型）。
XIAO_LED_DX = 5.71       # [暫定] 子基板中心 → LED 群の中心（x）
XIAO_LED_DY = 15.83      # [暫定] 同（y・奥が正）
LED_WIN_D = 5.0          # 窓の直径（RGB と充電の両 LED を覆う）
LED_WIN_SKIN = 0.6       # 残す肉。0.4mm ノズルの 3 層で光が透ける

# --------------------------------------------------------------------------
# ★未解決★ USB-C のメスがケースの外へ 0.26mm はみ出す（open-gaps #23 と一体）
#
# XIAO のメスは子基板の奥端より 3.055mm 出ている（`pcb_parts.usb_receptacle`。
# **Seeed 公式の 3D モデル。**利用者のノギス実測とも一致していて、
# **モデルの誤りではない**）。壁の外面までは WALL + DB_FROM_REAR = 2.8mm
# しかないので、実物が 0.26mm 顔を出す。抜き差しの外力を直に受ける。
#
# **一度これをコブを 0.56mm 深くして直したが、撤回した。**
# CLAUDE.md「キー配列・寸法…は実機に合わせる。交渉可能なのは打鍵感だけ」に
# 反する。奥行は open-gaps #2 で既に実機 +5.1mm あり、「現状維持を推奨」と
# 書いてある寸法だった。**そこを黙って 0.56mm 動かしたのが誤り。**
#
# **直すには XIAO を前へ動かすしかない**（はみ出し量は
# 3.055 − WALL − DB_FROM_REAR で決まり、コブの深さは効かない）。
# だが XIAO を前へ動かすとアンテナが本体基板の下へ戻る。いまの余裕は
# **0.362mm**（本物の基板外形 y=48.700 に対しアンテナ y=49.062）。
# 面一にするには 0.255mm 要るので、**余裕の 70% を使う。**
#
# → **#23 の解決と一緒に決める。**#23 が解けて XIAO を前へ出せるように
#   なれば、奥行も余裕も削らずに済む。
#   状態は test_the_usb_receptacle_sticks_out_until_23_is_solved が記録する。
USB_RECESS = 0.3         # 解けたときに目指す引っ込め量（印刷公差 ±0.2 を見て）


def _usb_receptacle_size():
    """XIAO の USB-C メスの (幅, 高さ, 子基板の奥端からの張り出し, 板上面からの中心高さ)。

    **KiCad の STEP から数えた実寸**（`pcb_parts.usb_receptacle`）。
    ここを定数で持つと、XIAO の向きや型番を変えたときに穴だけ取り残される。
    """
    import pcb_parts

    x0, y0, z0, x1, y1, z1 = pcb_parts.usb_receptacle()
    rec = pcb_parts.load()["db"]
    t = rec["board_step_thickness"]              # STEP の板厚（1.51）
    return (x1 - x0, z1 - z0, y1 - rec["board_bbox"][4], (z0 + z1) / 2 - t)


_RECEPT = _usb_receptacle_size()

# 奥の壁の切り欠き。**2 段になる**（open-gaps #28）。
#
#   外側 … 利用者のケーブルの**樹脂の胴体**が入るぶん。実測 12x7mm ＋ 逃げ
#   内側 … **XIAO の端**が入るポケット。外からは見えない
#
# 以前は 10x6mm の 1 段で、しかも「XIAO のコネクタを囲めているか」しか
# 検査していなかった。**利用者が挿すケーブルは検査の対象外だった。**
# 値は envelopes.USB_PLUG_W / USB_PLUG_H（実測）から導く。下の import のあと。
# 子基板の上面から切り欠きの中心まで。**XIAO の積み上げの真ん中に合わせる。**
#
# 以前は 1.6 と直書きしていた。それだと切り欠きの上端と XIAO の上面の
# 隙間が **0.10mm** しかなかった。実測値は「4.5 ぐらい」と概数で渡された
# ものなので、0.1mm は余裕とは呼べない。真ん中に合わせると上下 0.75mm ずつ。
# test_the_usb_opening_clears_the_connector が余裕を見張る。
# 値は usb_center_z() で DB_STACK_H から導く（envelopes の import は下）。

# 電源スイッチ（**SS12D01G4-G**・秋月 112723。2026-08-12 確定）。
# **基板には載らない。**（前提だった C&K OS102011MA1QN1・右アングルから
# 差し替わったが、基板に載せない設計なので方式は変わらない）
# 奥の壁のポケットへ落とし込み、操作部だけ外へ出す。
# 経緯は docs/hardware/decisions/2026-08-08-power-switch.md。
#
# 寸法は envelopes.py の SW_PWR_W/D/H（暫定値。買う製品を変えたらそこを直す）。
# アクチュエータは長さ 4.00mm・ストローク 2.00mm。壁 2.4mm を貫いて
# 1.6mm 出る。スロットはストロークぶん長くする。
SW_SLOT_W = 2.6          # 操作部が通るスロットの幅（アクチュエータ + 逃げ）
# スロットの長さ = ストローク 2.0 + アクチュエータの断面 約2.5 + 逃げ。
# **本体の高さではない。**本体ぶん開けると穴が無駄に大きくなる。
SW_SLOT_LEN = 5.0
SW_RIB = 1.2             # スイッチを受ける箱の壁厚。0.4mm ノズル 3 周
                         # （ベゼル壁と同じ理屈）。**2026-08-24 に 1.6 → 1.2**
                         # ——#51 の幅詰めで左のスイッチ帯が 0.8mm 不足し、
                         # 受け箱の壁から 0.4×2 を返した（利用者の案）。
                         # 中身は 30 円のスライドスイッチで荷重は微小
# 受け（レールと奥のリブ）の高さ。**本体より低くする。**
#
# ⚠️ **本体と同じ高さにすると、スイッチを入れられない**（2026-08-12 に
# 実形状で発見）。入れ方は「上から落とし込む」だが、**ツマミは壁を貫いて
# 外に出ている**ので、降ろすあいだツマミはスロットの中を滑る必要がある。
# 受けが本体と同じ高さだと、ツマミがスロットに入る高さまで持ち上げた
# ときに**スロットの上端に当たる**（実測 12.6mm³）。
# 受けを低くすると、ツマミをスロットへ入れる高さが下がり、
# **スロットを短くできる。**受けは本体の下半分を掴む。
SW_HOLD_H = 5.6          # 受けの高さ（本体 8.8 の下側 5.6mm を掴む）

# 電源スイッチの**指の逃げ**（窪み・open-gaps #18・2026-08-12）。
#
# **壁 2.4mm を貫いて外へ 1mm 出すには、アクチュエータが 3.4mm 以上
# 突き出ている部品しか使えない。**市場の超小型スライドの実勢は
# **1.4〜3.0mm**（8 品番を当たった調査）で、3.4mm 以上は稀だった。
#
# **決まった部品（SS12D01G4-G）は 4.0mm なので、窪みが無くても足りる。**
# それでも窪みは残す——**部品を買い直すときの自由度**がここで決まるから
# （窪みがあれば 1.4mm で足りる）。この窪みは指の掛かりも兼ねる。
#
# → **スロットの周りを窪ませ、操作面をツライチにする。**必要な突出量は
# 「窪みの底までの壁厚」= 2.4 − SW_DISH_D になり、**1.4mm あれば足りる。**
#
# **つまみを被せる案も同じ効果**があり、操作感はそちらが上（指の腹で
# 動かせる）。**それでも窪みを採る**——ケースは刷り直せるが、部品の購入は
# 戻しにくい。**戻せない側（部品選択）を最大限ゆるくしておき、操作感が
# 足りなければ後からつまみを刷る**（利用者の判断・2026-08-12）。
#
# 壁は薄くなるが、**スライドの力を受けるのは受け箱のリブ**（壁の内面に
# 付いている周囲の帯）で、窪みはその内側。内面は削らないのでスイッチの
# 座りも変わらない。
SW_DISH_D = 1.0          # 窪みの深さ（壁 2.4 → 底で 1.4mm）
SW_DISH_W = 10.0         # 窪みの幅の**上限**（実際は空きから決まる。
                         # power_switch_dish_w を見ること）
SW_DISH_EDGE = 0.5       # 窪みの縁と、隣の造作とのあいだに残す壁
SW_DISH_H = 8.0          # 同・高さ
# RESET のボタンは**載せられない。**
# XIAO nRF52840 の裏面に出ているパッドは VUSB/GND/3V3/10/9/8/7・0〜6（側面ピンの
# 複製）と BAT +/−、NFC だけで、**RST は出ていない**（実機の写真で確認）。
# 復旧はキー操作（Fn+Ctrl+Esc）で行う。それも効かないほど壊れたときは
# 上ケースの 3 本のネジを外す。キーキャップを外す必要は無い。

# 上ケースを奥で留める方法は**未解決**（docs/hardware/open-gaps.md #12）。
#
# 舌と溝を試したが噛まなかった。**ケースは上が開いたトレイなので、
# コブの上に材料が無い。**溝を空中に切っていた。
# 「当たらない」ことしか見ない干渉検査では気づけず、噛み合いを直接見る
# test_the_rear_hook_is_actually_captured が検出した。
#
# **2026-08-12 に「庇」を試して、また外した。**コブの天井は上ケースの
# 後端の真後ろ（z 28.82..31.25）まで来ているので、そこを手前へ 3mm
# 伸ばして庇にし、上ケースの天面を欠き取って潜らせた。**噛みはした**
# （0.3mm 持ち上げると当たる）。**が、組み立てられなかった**——
# 上へ・奥へ・傾けて、**どの向きにも動かせない**（上ケースは外形が
# ケースと同一の「落とし込み蓋」で、平面方向の逃げが 0）。
#
# → **水平方向に噛む機構は原理的に入らない。**入るのは
#   **垂直に押し込んで噛むもの**（ナットやチルト脚と同じ返し／溝）だけ。
#   次はその形で設計する。**「噛むか」と「組めるか」は別の検査**。

from envelopes import (PCB_T, PLATE_TO_PCB, SOCKET_DROP,  # noqa: E402
                       DB_STACK_H, DB_XIAO_LIFT, SCREW_HEAD_D, SCREW_HEAD_H,
                       SW_PWR_BODY_D, SW_PWR_D, SW_PWR_H, SW_PWR_PIN_W,
                       SW_PWR_W,
                       USB_PLUG_H, USB_PLUG_W, USB_SHELL_EXPOSED,
                       USB_SHELL_H, USB_SHELL_W)
from interface import XIAO_OUTLINE_W, XIAO_OVERHANG  # noqa: E402

# 奥の壁の切り欠き。**外から見えるのは「金属が通る穴」だけ。**実機と同じ姿。
#
# 一度ここを「樹脂が通る大きさ（12.4x7.4mm）」にしていたが、**誤りだった。**
# 実機の写真では樹脂は完全に外にあり、金属が 1mm ほど見えたまま挿さっている。
# 穴を樹脂の大きさにすると、壁に不要な大きな口が開く。
#
# ⚠️ **穴を通るのはプラグだけではない。メスも通る。**（2026-08-10 に判明）
# XIAO の USB-C メスは子基板の奥端より **3.055mm** 出ていて、壁（2.4mm ＋
# 板の逃げ 0.4mm）を貫いて外へ 0.25mm 顔を出す。メスの断面は 8.94x4.20 で、
# プラグの金属（8.34x2.56）より**大きい**。プラグ基準で穴を開けていたので、
# メスの頭が穴の上縁に 0.24mm 食い込んでいた（実形状の総当たりで発覚）。
#
# だから穴は「プラグとメスの**両方**が通る大きさ」から導く。
USB_W = max(USB_SHELL_W, _RECEPT[0]) + PORT_CLEAR * 2
USB_H = max(USB_SHELL_H, _RECEPT[1]) + PORT_CLEAR * 2
# 内側のポケット（XIAO の**基板**の端を受ける）の前に残る壁の厚み。
# ここを USB_W x USB_H で貫く。**メスはこの中に収まり、外面より
# USB_RECESS だけ引っ込む**（上の DB_FROM_REAR の注記）。
USB_PLUG_ENTRY = WALL - (XIAO_OVERHANG - DB_FROM_REAR)
# 樹脂用の座ぐり（USB_COUNTERBORE）は **2026-09-06 に廃止**。メスの面は外面より
# 0.26 外に出ている（#30）ので樹脂は壁に入らない。穴はメスの小判形だけ
# （test_a_real_cable_can_reach_the_socket の 2 が根拠を見張る）。
# 内側のポケット（XIAO の端を受ける）の深さ。
XIAO_POCKET_D = XIAO_OVERHANG - DB_FROM_REAR


# --------------------------------------------------------------------------
# 器の案（2026-09-06・利用者「底面以外にネジと継ぎ目を見せたくない」）
#
# 上シェル＝ベゼル面＋四方の壁（机まで）。下シェル＝壁の下端の内側に嵌まる底板。
# 壁の下端 FLOOR は外皮 BOTTOM_SKIN だけを残し、内側を 45° に落とす。底板の上の
# 外周も 45° に落とし、斜面どうしで載る（打鍵の力は底板 → 斜面 → 壁へ。ネジは
# 底板を斜面へ引き付けるだけ）。裏返して刷る上シェルでは斜面は 45° の張り出し、
# 底板では上向きの斜面なので、どちらも支え無しで刷れる。継ぎ目は底面の外皮の
# 下端の線だけ。
# 案 A（二枚貝＋奥板・相欠き）は 2026-09-06 に廃止。経緯は
# docs/hardware/decisions/2026-09-06-cup-case.md
BOTTOM_SKIN = 1.2        # 壁の下端に残す外皮（0.4 の 3 倍）。手前と左右の壁はプレートより
                         # 下がこの厚み（BEZEL_WALL）で、底板のリブが内側を埋める
BOTTOM_FIT = 0.1         # 底板の縁と外皮の内面の隙（片側）
BOTTOM_CHAMFER = WALL - BOTTOM_SKIN   # 斜面の高さ＝横幅（45°）。1.2。**斜面は底板の上**
                         # （z = FLOOR〜FLOOR + 1.2）。底板は平板のまま入り、上の外周の角が
                         # 斜面に当たって止まる（BOTTOM_FIT ぶん上がった所）。底板側にも
                         # 斜面を付けると、手前のネジの頭（縁から 0.05）が斜面と重なった
HEAD_RECESS_CLR = 0.1    # 底のネジ頭の座ぐりの逃げ（片側）。手前は底板の縁まで 0.05
FRONT_RIB_T = 2.0        # 底板から立てる手前のリブ（プレートの手前縁を受ける）の厚み
REAR_COL_D = 5.6         # 奥の柱（天井から垂らす・底からネジ）の径。左の空き 6.76 に入る
REAR_COL_Y = 55.3        # 同・y。柱の手前 52.5 はプレートの奥縁 52.3 ＋ 逃げの奥（切り欠き不要）、
                         # 奥面 58.1 は電源スイッチを外す動き（手前へ 4.4: ツマミ 4.0 が壁の内面を
                         # 抜ける）で端子（切って 2.0）の先端が来る 58.26 の手前。端子が 5.0 の
                         # ままだと 52.3 まで前に置くしかなく、プレート・受けの壁に切り欠きが要り、
                         # 電池蓋が L 字になった（2026-09-13 に利用者の提案で端子を切ることに）
SW_STOP_T = 2.4          # 電源スイッチの手前の止めブロック（底板から）の厚み
SW_STOP_H = 7.8          # 同・高さ。**いちばん下の端子（中心 − 2.5、厚み 0.3 → 下端 8.05）の
                         # 手前まで**。本体の下 1.5mm を受ければ手前へは滑らない。2026-09-13 まで
                         # 10.7 で端子のスリットを入れていたが、幅 1.5 × 高さ 8.3 の細い板 2 枚に
                         # なっていた（利用者「細くて狭い板は必要？」）。端子の下で止めれば
                         # スリットも要らない
LID_OPEN_CLR = 0.3       # 電池蓋の開口の逃げ（箱の内側から片側）
LID_LAP = 0.8            # 蓋の縁が底板の段に掛かる幅
LID_FIT = 0.1            # 蓋と開口・段の隙（片側）
LID_TAB = 2.0            # 蓋の外端の爪が段の下へ入る長さ
OPENING_CHAMFER = 0.8    # 開口（キーの窪み）の上縁の面取り（2026-09-06・利用者
                         # 「角が丸くなっておらず当たると痛い」）。丸めは
                         # カーネルが不安定だが、直線の辺の面取りは通る。
                         # 最下段の覆いの縁も同じ
BOTTOM_EDGE_R = 1.0      # 上シェルの底縁（外皮 1.2）の丸め。2026-09-06 に 1.5 → 1.0（実機の「合わせ目より下は
                         # 一回り小さい」の代用。dimensions.md §5「R1〜2 から試作」）

# ゴム足（市販品）
RUBBER_D = 10.0
RUBBER_T = 2.0           # [暫定] 厚み。**傾斜角に直接効く。**買う製品で確定させる
RUBBER_RECESS = 0.6      # 座ぐりの深さ
RUBBER_INSET = 12.0      # 縁からの距離

# --------------------------------------------------------------------------
# チルト脚
#
# 実機はヒンジ式の折りたたみ脚が 2 組。3Dプリントでヒンジを作ると壊れやすいので、
# 高さの違う差し込み脚を 2 組用意して 0° / 3° / 6° を作る。機能は同じ。
# 脚は前縁を支点に後縁を持ち上げるので、必要な高さは支点からの距離で決まる。
# --------------------------------------------------------------------------
FOOT_D = 12.0            # 脚の直径
FOOT_PEG_D = 4.0         # 差し込みピンの径
# ピンの長さ。**4.0 → 2.4（open-gaps #29 の発見で短縮）。**
#
# 子基板側の脚は、**子基板の裏に 2.1mm 出る FFC コネクタ J_MAIN
# （床上 4.31mm まで下がる）の真下**にある。ピン 4.0mm のときの盲穴ボス
# （床から 5.6mm）は左右とも 49.3mm^3 食い込んでいた。子基板の裏面部品を
# モデルに入れて初めて見えた。脚の位置は動かせない（_foot_positions の注記）
# ので、ピンを床厚 2.4mm と同じにし、キャップ 1.2mm（0.4mm×3 層）を足して
# ボス頂 3.6mm に抑える。コネクタとの余裕 0.71mm。
#
# **φ4×2.4mm のピンで脚が保持できるかは暫定扱い。印刷して確かめること**
# （provisional-values.md に登録済み）。
FOOT_PEG_H = 2.4         # [暫定] 保持力は印刷して確かめる（上の注記）
FOOT_BOSS_CAP = 1.2      # 盲穴ボスのキャップ厚。1.6 だとボス頂がコネクタに近づく
# **抜け止めの返し**（2026-08-12・利用者の「固定が弱いところ」から）。
#
# ピンを伸ばして掛かりを稼ぐ道は塞がっている（上の注記。真上に J_MAIN が
# 4.31mm まで下がる）。**摩擦だけでは、裏返すたびに脚が抜ける。**
# → **ピンの先に返しを付け、穴の奥に溝を掘って噛ませる。**
# 押し込むとき返し（φ4.4）が穴（φ4.2）を 0.1mm/片側 押し広げて通り、
# 溝（φ4.7）で開いて戻らなくなる。**定位置では重なりが無い**ので、
# 干渉検査から除外する必要が無い（ナットで学んだ形）。
# 噛みは test_the_tilt_foot_is_captured が寸法で見る。
FOOT_BARB_D = 4.4        # 返しの外径（ピン φ4.0 ＋ 0.4）
FOOT_BARB_H = 0.6        # 返しの高さ（層 0.2mm × 3）
FOOT_GROOVE_D = 4.7      # 穴の奥の溝の径（返し ＋ 0.3 の逃げ）
# 脚は**後ろの隅**に差し、そこが設置点になる。実機の折りたたみ脚と同じ役割。
# 0° 用の短い脚も作るので、脚は常に 2 個使う（外すのではなく差し替える）。
# 当初は脚を内側に置き、電池室と蓋の中にボスが立っていた。
TILT_STEPS = [0.0, 3.0, 6.0]
# 0° の脚の高さ。**前側のゴム足の「接地までの高さ」と揃える。**
#
# ゴム足は 0.6mm の座ぐりに沈むので、接地までは（厚み − 座ぐり）。
# チルト脚は差し込み穴だけで沈まないので、全高がそのまま接地までになる。
# **ここを 2.0（＝ゴム足の厚みそのもの）にしていたため、「0°」でも
# 後ろが 0.6mm 高く、打鍵面が 7.3° ではなく 7.71° になっていた**
# （2026-08-08 に発見）。傾斜は動かしてはならない値なので導出にする。
FOOT_BASE_H = RUBBER_T - RUBBER_RECESS

# --------------------------------------------------------------------------
# 三脚ネジ穴（テンティング用。普段は使わない）
# 1/4-20 の六角ナットを埋め込む。二面幅 11.1mm / 厚み 5.5mm
# --------------------------------------------------------------------------
NUT_AF = 11.1 + 0.3      # 二面幅＋逃げ
NUT_T = 5.5 + 0.2 + 0.6   # 厚み＋逃げ＋唇の高さ（ナットは唇の上に座る）
NUT_BOSS_D = 18.0
NUT_BOSS_H = 9.0
NUT_THRU_D = 7.0
# **抜け止め。**入口（底面側）の帯だけ二面幅を狭め、押し込んだナットが
# 自重で落ちないようにする。**PLA が 0.2mm 変形すれば入る**程度に留める
# （大きくすると入らないか、押し込みで割れる）。
NUT_LIP_H = 0.6          # 狭める帯の高さ（層 0.2mm × 3）
NUT_LIP_UNDER = 0.4      # 二面幅をどれだけ狭めるか（片側 0.2mm の食い込み）


def case_heights(depth):
    """前縁・後縁でのプレート上面高さを返す。"""
    rise = depth * tan(radians(TILT_DEG))
    return PLATE_TOP_FRONT, PLATE_TOP_FRONT + rise


def build_case(keys, half):
    """**底板**（下シェル。2026-09-06・器の案）。

    上シェルが四方の壁を持つ器になったので、下シェルは壁の下端の内側に嵌まる
    平板。継ぎ目とネジは底面だけ。**床面をベッドに付けて刷る。**底板から立つ物:
      * 手前のリブ（プレートの手前縁を受ける。ネジ受けの角柱の間）
      * プレート受けの壁（基板の奥縁と電池箱の間。旧・仕切り壁と同じ場所）
      * 子基板の柱 2 本（今までどおり）
      * 電源スイッチの台と止めブロック（受け箱は上シェル。口が下と手前に開く）
      * チルト脚のボス・三脚ナットのボス
    穴: 手前 3 本・奥の柱のネジ（頭は座ぐり）、電池蓋の開口（半掛かりの段付き）、
    ゴム足の座ぐり。
    縁: 外形から BOTTOM_SKIN + BOTTOM_FIT 内側。上の外周は 45° に落とし、
    上シェルの壁の下端の斜面に載る（BOTTOM_CHAMFER の注記）。
    """
    from build123d import Solid
    _positions, (w, h_plate) = plate_positions(keys)
    h_body = plan_depth(h_plate)
    h = h_body + BUMP_DEPTH
    y_off = BUMP_DEPTH / 2
    y_out = h_body / 2 + BUMP_DEPTH
    z_front, z_rear = case_heights(h)
    rim_front = z_front - PLATE_T
    z_max = BEZEL_TOP_FRONT + h * tan(radians(TILT_DEG)) + 5.0
    inset = BOTTOM_SKIN + BOTTOM_FIT
    s = inner_sign(half)
    cutter = tilted_cutter(w, h_body, rim_front)                 # リム面より上

    # 板そのもの（平板。上シェルの外皮の内側に入り、上の外周の角が斜面に当たる）
    with BuildPart() as _pl:
        with BuildSketch():
            with Locations((0, y_off)):
                RectangleRounded(w - inset * 2, h - inset * 2, max(CORNER_R - inset, 0.5))
        extrude(amount=FLOOR)
    plate = _pl.part

    # 立てる物（板の上面 FLOOR から）。上シェルの斜面（壁の内面から BOTTOM_CHAMFER・
    # z = FLOOR〜FLOOR + 1.2）に掛からないよう、壁の内面から BOTTOM_CHAMFER + 逃げ 内側
    bx = battery_x_center(half, w)
    by = battery_center(h_body)
    db_x = daughterboard_x_center(half, w)
    db_y = y_out - WALL - DB_FROM_REAR - DB_D / 2
    _edge = w / 2 - WALL - BOTTOM_CHAMFER - CLEARANCE
    x_in_edge = s * _edge
    x_out_edge = -s * _edge
    with BuildPart() as _up:
        # 手前のリブ。ネジ受けの角柱（上シェル、幅 FRONT_BOSS_W）の間だけ
        # 内面は基板の手前縁 + 逃げ（上シェルの角柱と同じ）。ネジ中心（−50.75）に揃えると
        # 壁に 0.6 食い込み、壁の内面基準にすると基板に 0.1 掛かった
        _ry = (-PCB_FRONT_EDGE_PLAN + CLEARANCE) - FRONT_RIB_T / 2
        _gaps = []
        _xs = sorted(bx_ for bx_, _ in _boss_positions(half))
        _lo = -_edge
        for bx_ in _xs:
            _gaps.append((_lo, bx_ - FRONT_BOSS_W / 2 - CLEARANCE))
            _lo = bx_ + FRONT_BOSS_W / 2 + CLEARANCE
        _gaps.append((_lo, _edge))
        for g0, g1 in _gaps:
            if g1 - g0 < 2.0:
                continue
            with Locations(((g0 + g1) / 2, _ry, FLOOR - 0.01)):
                Box(g1 - g0, FRONT_RIB_T, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 左右のリブ（上シェルの薄い壁 1.2 の内側を埋め、プレートの左右の縁を受ける）。
        # 手前の縁からコブの手前（壁が 2.4 に戻る所）まで。内縁側は子基板の手前で止める
        _rib_x = w / 2 - inset - BOTTOM_SKIN / 2          # 外皮の内面から 1.2
        _y_front = -h_body / 2 + inset + CORNER_R          # 手前の角の丸みを避ける
        for sx_ in (-1, 1):
            _y_end = h_body / 2 - CLEARANCE * 2
            if sx_ == s:                                   # 内縁側: 子基板の手前
                _y_end = min(_y_end, db_y - DB_D / 2 - CLEARANCE)
            with Locations((sx_ * _rib_x, (_y_front + _y_end) / 2, FLOOR - 0.01)):
                Box(BOTTOM_SKIN, _y_end - _y_front, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # プレート受けの壁（基板の奥縁 + 0.2 と電池箱 − 0.2 の間。旧・仕切り壁）
        y_div = by - BATT_W / 2 - CLEARANCE - BATT_DIVIDER_T / 2
        _x_inner = db_x - s * (DB_W / 2 + CLEARANCE)
        with Locations(((x_out_edge + _x_inner) / 2, y_div, FLOOR - 0.01)):
            Box(abs(_x_inner - x_out_edge), BATT_DIVIDER_T, z_max,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # （奥の柱は y 55.3 で壁（〜51.2）より奥、蓋の張り出しも柱の周りだけなので、壁に
        #   切り欠きは要らない。2026-09-13）
        # 子基板の柱（今までどおり床から 4）
        for dx, dy in DB_BOSS_POS:
            with Locations((db_x + dx, db_y + dy, FLOOR - 0.01)):
                Cylinder(DB_BOSS_D / 2, DB_BOSS_H + 0.01, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 電源スイッチの台（受け箱の中に入る）と、手前の止めブロック
        sw_x = power_switch_x_center(half, w)
        sw_bot = power_switch_center_z() - SW_PWR_H / 2 - CLEARANCE / 2
        y_in = y_out - WALL
        holder_d = SW_PWR_BODY_D + CLEARANCE + SW_RIB
        # 台: 受け箱の中（本体の真下）。上面は本体の下面 − 0.1
        with Locations((sw_x, y_in - (SW_PWR_BODY_D + CLEARANCE) / 2, FLOOR - 0.01)):
            Box(SW_PWR_W - CLEARANCE, SW_PWR_BODY_D - CLEARANCE, (sw_bot - 0.1) - (FLOOR - 0.01),
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 止めブロック: 本体の手前面 + 逃げ から SW_STOP_T。受け箱の壁の内側に収まる幅。
        # 高さは端子の下まで（SW_STOP_H の注記）。端子はブロックの上を通る
        _y_stop1 = y_in - (SW_PWR_BODY_D + CLEARANCE) - CLEARANCE
        with Locations((sw_x, _y_stop1 - SW_STOP_T / 2, FLOOR - 0.01)):
            Box(SW_PWR_W, SW_STOP_T, SW_STOP_H - (FLOOR - 0.01),
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # チルト脚の盲穴ボス
        for fx, fy in _foot_positions(w, h_body):
            with Locations((fx, fy, FLOOR - 0.01)):
                Cylinder(FOOT_PEG_D / 2 + 2.0, (FOOT_PEG_H + FOOT_BOSS_CAP) - (FLOOR - 0.01),
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
    from envelopes import under_pcb_base
    cutter_under_pcb = tilted_cutter(w, h_body, under_pcb_base(
        h_plate, rim_front, PLATE_TO_PCB + PCB_T + SOCKET_DROP))
    ups = _up.part - cutter          # リブ・壁の頭はリム面（プレートの下面）
    # ナットのボスは基板の下面（ソケットの先端）で切る（以前と同じ）
    with BuildPart() as _n:
        with Locations((0, 0, FLOOR - 0.01)):
            Cylinder(NUT_BOSS_D / 2, NUT_BOSS_H + 0.01, align=(Align.CENTER, Align.CENTER, Align.MIN))
    nut_boss = _n.part - cutter_under_pcb
    # リード線の逃げ（受けの壁の両端・箱の端の真下）
    with BuildPart() as _wn:
        for nx in (bx - BATT_X / 2 + BATT_WIRE_NOTCH / 2, bx + BATT_X / 2 - BATT_WIRE_NOTCH / 2):
            with Locations((nx, y_div, FLOOR)):
                Box(BATT_WIRE_NOTCH, WALL * 2, BATT_WIRE_NOTCH, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ups = ups - _wn.part

    part = plate + ups + nut_boss
    if len(part.solids()) != 1:
        raise ValueError(f"底板に立てた物が板に付いていない（{len(part.solids())} 個）")

    # 穴（下から）
    with BuildPart() as _holes:
        # 手前 3 本＋奥の柱: バカ穴と頭の座ぐり
        for hx, hy in list(_boss_positions(half)) + list(rear_column_positions(half, w, h_body)):
            with Locations((hx, hy, -1.0)):
                Cylinder(M2_CLEAR_D / 2, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
            with Locations((hx, hy, -1.0)):
                Cylinder(SCREW_HEAD_D / 2 + HEAD_RECESS_CLR, 1.0 + SCREW_HEAD_H + 0.2,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 電池蓋の開口（貫通。本体＋内端の張り出し）と、蓋の縁が掛かる段（下から FLOOR/2）
        ox0, oy0, ox1, oy1 = battery_opening(half, w, h_body)
        for x0, y0, x1, y1 in (battery_opening(half, w, h_body), battery_opening_ext(half, w, h_body)):
            with Locations(((x0 + x1) / 2, (y0 + y1) / 2, -1.0)):
                Box(x1 - x0, y1 - y0, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
            with Locations(((x0 + x1) / 2, (y0 + y1) / 2, -1.0)):
                Box((x1 - x0) + (LID_LAP + LID_FIT) * 2, (y1 - y0) + (LID_LAP + LID_FIT) * 2,
                    1.0 + FLOOR / 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 蓋の外端の爪が入るポケット（段を外へ LID_TAB 延ばす。蓋の爪の幅と同じ y 範囲）
        _s = inner_sign(half)
        _x_tab_edge = (ox0 if _s > 0 else ox1) - _s * (LID_LAP + LID_FIT)
        with Locations((_x_tab_edge - _s * (LID_TAB + LID_FIT) / 2, (oy0 + oy1) / 2, -1.0)):
            Box(LID_TAB + LID_FIT, (oy1 - oy0) * 0.5 + LID_FIT * 2, 1.0 + FLOOR / 2,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 三脚ナット
        with Locations((0, 0, -1.0)):
            Cylinder(NUT_THRU_D / 2, NUT_BOSS_H + FLOOR * 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
        _hex_r = NUT_AF / 2 / __import__("math").cos(radians(30))
        with BuildSketch(Plane.XY.offset(NUT_LIP_H)):
            RegularPolygon(_hex_r, 6)
        extrude(amount=NUT_T - NUT_LIP_H)
        with BuildSketch(Plane.XY.offset(-1.0)):
            RegularPolygon((NUT_AF - NUT_LIP_UNDER) / 2 / __import__("math").cos(radians(30)), 6)
        extrude(amount=1.0 + NUT_LIP_H)
        # ゴム足の座ぐり
        for fx, fy in _rubber_positions(w, h_body):
            with Locations((fx, fy, -1.0)):
                Cylinder(RUBBER_D / 2, 1.0 + RUBBER_RECESS, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # チルト脚: 穴の奥の溝、差し込み穴
        for fx, fy in _foot_positions(w, h_body):
            with Locations((fx, fy, FOOT_PEG_H - FOOT_BARB_H)):
                Cylinder(FOOT_GROOVE_D / 2, FOOT_BARB_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
            with Locations((fx, fy, -1.0)):
                Cylinder(FOOT_PEG_D / 2 + CLEARANCE / 2, 1.0 + FOOT_PEG_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 子基板の柱のインサート下穴
        for dx, dy in DB_BOSS_POS:
            with Locations((db_x + dx, db_y + dy, FLOOR + DB_BOSS_H - (M2_INSERT_L + 1.0))):
                Cylinder(M2_INSERT_D / 2, M2_INSERT_L + 2.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = part - _holes.part
    if len(part.solids()) != 1:
        raise ValueError(f"底板が穴で分かれた（{len(part.solids())} 個）")
    return part, (w, h_body), (z_front, z_rear)


def battery_opening(half, w, h_body):
    """底板の電池蓋の開口の本体 (x0, y0, x1, y1)。箱の内側（電池が通る所）＋逃げ。
    **底板・蓋・検査がこの 1 つから取る。**内端の張り出しは battery_opening_ext。"""
    bx = battery_x_center(half, w)
    by = battery_center(h_body)
    x0 = bx - (BATT_X / 2 - BATT_BOX_WALL) - LID_OPEN_CLR
    x1 = bx + (BATT_X / 2 - BATT_BOX_WALL) + LID_OPEN_CLR
    y0 = by - (BATT_W / 2 - BATT_BOX_WALL) - LID_OPEN_CLR
    y1 = by + (BATT_W / 2 - BATT_BOX_WALL) + LID_OPEN_CLR
    return (x0, y0, x1, y1)


def battery_opening_ext(half, w, h_body):
    """開口の内端の張り出し (x0, y0, x1, y1)。**奥の柱の 1 本目の真下まで**広げ、柱の
    ネジが蓋を貫いて底板と共締めになるようにする。x は開口の内端から柱の向こう側
    まで、y は柱の周り（受けの壁とは y で重ならない）。"""
    s = inner_sign(half)
    ox0, _oy0, ox1, _oy1 = battery_opening(half, w, h_body)
    cx, cy = rear_column_positions(half, w, h_body)[0]
    x_in_open = ox1 if s > 0 else ox0
    x_col = cx + s * (REAR_COL_D / 2 + LID_OPEN_CLR)
    return (min(x_in_open, x_col), cy - REAR_COL_D / 2 - LID_OPEN_CLR,
            max(x_in_open, x_col), cy + REAR_COL_D / 2 + LID_OPEN_CLR)


def rear_column_positions(half, w, h_body):
    """奥の柱（天井から垂らす・底からネジ）の (x, y)。電池箱と子基板の間。
    左は幅 6.76 に 1 本、右は 40 に 2 本。**1 本目は電池箱に近い側**（電池蓋の
    内端のネジを兼ねる）。プレートの奥縁より奥（y ≥ 52.5）・スイッチの受け箱の手前。"""
    s = inner_sign(half)
    bx = battery_x_center(half, w)
    db_x = daughterboard_x_center(half, w)
    x_batt = bx + s * BATT_X / 2            # 電池箱の内縁側の端
    x_db = db_x - s * DB_W / 2              # 子基板の電池側の端
    y = REAR_COL_Y
    gap = abs(x_db - x_batt)
    if gap < REAR_COL_D + CLEARANCE * 2:
        raise ValueError(f"{half}: 電池箱と子基板の間 {gap:.2f} に柱 φ{REAR_COL_D} が入らない")
    first = x_batt + s * (CLEARANCE + REAR_COL_D / 2)
    if gap < REAR_COL_D * 2 + CLEARANCE * 3 + 4.0:
        return [(first, y)]
    return [(first, y), (x_db - s * (CLEARANCE + REAR_COL_D / 2 + 2.0), y)]


def build_battery_lid(half, keys):
    """底板の電池蓋。開口を塞ぐ板（厚み FLOOR）で、外周に幅 LID_LAP・厚み FLOOR/2 の
    縁が付き、底板の段に半掛かりで嵌まって面一になる。内端は奥の柱の下まで伸び、
    柱のネジ（底板と共締め）が貫く。外端は爪（LID_TAB）が底板の段の下へ入る。
    **床面（外面）をベッドに付けて刷る。**"""
    _positions, (w, h_plate) = plate_positions(keys)
    h_body = plan_depth(h_plate)
    s = inner_sign(half)
    ox0, oy0, ox1, oy1 = battery_opening(half, w, h_body)
    cx, cy = rear_column_positions(half, w, h_body)[0]
    with BuildPart() as p:
        for x0, y0, x1, y1 in (battery_opening(half, w, h_body), battery_opening_ext(half, w, h_body)):
            # 本体（開口に入る部分。逃げ LID_FIT）
            with Locations(((x0 + x1) / 2, (y0 + y1) / 2, 0)):
                Box((x1 - x0) - LID_FIT * 2, (y1 - y0) - LID_FIT * 2, FLOOR,
                    align=(Align.CENTER, Align.CENTER, Align.MIN))
            # 縁（段に掛かる）
            with Locations(((x0 + x1) / 2, (y0 + y1) / 2, 0)):
                Box((x1 - x0) + LID_LAP * 2, (y1 - y0) + LID_LAP * 2, FLOOR / 2,
                    align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 外端の爪: 縁の外側へ LID_TAB 伸ばす（底板の段の下へ差し込む）
        x_tab = (ox0 if s > 0 else ox1) - s * LID_LAP
        with Locations((x_tab, (oy0 + oy1) / 2, 0)):
            Box(LID_TAB * 2, (oy1 - oy0) * 0.5, FLOOR / 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 柱のネジ: バカ穴と頭の座ぐり（下から）
        with Locations((cx, cy, -1.0)):
            Cylinder(M2_CLEAR_D / 2, FLOOR + 2.0, mode=Mode.SUBTRACT,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((cx, cy, -1.0)):
            Cylinder(SCREW_HEAD_D / 2 + HEAD_RECESS_CLR, 1.0 + SCREW_HEAD_H + 0.2, mode=Mode.SUBTRACT,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
    if len(p.part.solids()) != 1:
        raise ValueError("電池蓋が分かれている")
    return p.part, ((ox1 - ox0) + LID_LAP * 2, (oy1 - oy0) + LID_LAP * 2)


def battery_center(h_body):
    """電池室の中心（本体中心を原点とする Y 座標）。

    ケース・蓋の開口・組み立て検査がすべてこの 1 つの関数を使う。
    同じ式を複数箇所に書いたせいで 14mm ずれた前科があるため。

    奥へ寄せるほど傾いた基板との余裕が増えるので、後壁ぎわに置く。
    """
    # **コブの中に置く。** コブぶんを足さずに書いていた時期があり、
    # 電池が本体側へ 12mm 前へずれていた。
    y_rear_inner = h_body / 2 + BUMP_DEPTH - WALL
    return y_rear_inner - BATT_MARGIN_REAR - BATT_W / 2


# inner_sign / battery_x_center / daughterboard_x_center は **interface.py が出所**。
# 本体基板の FFC コネクタ（J_DB）が子基板と X を揃えるために読むので、
# KiCad の Python から読める側へ移した（2026-08-15）。ここは再輸出だけ。


def power_switch_x_center(half, w):
    """電源スイッチの中心 X。**電池と子基板の隙間に置く。**

    奥の壁ぎわは電池（幅 BATT_X）と子基板が占めていて、置けるのは
    その左右の隙間だけ。左半分は 10.6mm しか無いので、**いちばん広い
    隙間の中央**を選ぶ。手で決め打ちにすると、電池や子基板を動かした
    ときに黙って重なる。
    """
    from envelopes import SW_PWR_W
    s_ = inner_sign(half)
    bx, dx = battery_x_center(half, w), daughterboard_x_center(half, w)
    obstacles = sorted([(bx - BATT_X / 2, bx + BATT_X / 2),
                        (dx - DB_W / 2, dx + DB_W / 2)])
    gaps, cur = [], -w / 2 + WALL
    for a, b in obstacles:
        if a > cur:
            gaps.append((cur, a))
        cur = max(cur, b)
    if w / 2 - WALL > cur:
        gaps.append((cur, w / 2 - WALL))
    lo, hi = max(gaps, key=lambda g: g[1] - g[0])
    if hi - lo < SW_PWR_W + CLEARANCE * 2:
        raise RuntimeError(
            f"{half}: 電源スイッチの場所が {hi - lo:.1f}mm しかない "
            f"（{SW_PWR_W + CLEARANCE * 2:.1f}mm 必要）")
    del s_
    # **蓋の座ぐりと子基板ポケットに挟まれた空きの中央**を基本にする。
    # 外面の造作（窪み・スロット）はここを基準に置く。隙間の中央ではない。
    a, b = power_switch_free_span(half, w)
    c = (a + b) / 2
    # ⚠️ **受け箱（内側）の制約にも収める**（2026-08-24・#51）。
    # 幅を詰めて帯が狭くなると、窪みの中央に置いた受け箱が子基板の
    # ポケットへ食い込む（実形状検査で 0.855mm³）。受け箱が電池と
    # 子基板の間に収まる中心の範囲を出し、窪みの中央をそこへ丸める。
    # 成立しない（範囲が空）なら例外で止める——黙って重ねない。
    hw = (SW_PWR_W + CLEARANCE + SW_RIB * 2) / 2   # 受け箱の半幅
    # 両脇の逃げは CLEARANCE/2（2026-09-06）。電池箱をリード線の逃げ 2.0 だけ
    # 内へ寄せた（BATT_WIRE_ROOM）ので左の帯は 6.76 で、0.2 では受け箱 6.5 が
    # 0.14 入らない。⚠️ 箱の長辺は図面で 109±1.0——**現物の実測待ち**（BATT_X）。
    # 現物が長ければここは成立しない（電源スイッチの移設が要る）
    _sc = CLEARANCE / 2
    h_lo, h_hi = lo + _sc + hw, hi - _sc - hw
    if h_lo > h_hi:
        raise RuntimeError(
            f"{half}: スイッチの受け箱が電池と子基板の間に収まらない "
            f"（中心の許容幅 {h_hi - h_lo:.2f}mm）")
    return min(max(c, h_lo), h_hi)


def power_switch_slot_z(half, w):
    """操作部のスロットの z 範囲 (下端, 上端)。**ケースと検査がここから取る。**

    ⚠️ **上端は「溝の口」まで伸ばす**（2026-08-12）。スイッチは上から
    落とし込むが、**ツマミは壁を貫いて外へ出ている。**スロットが操作部の
    ストロークぶんしか無いと、降ろす途中でツマミが壁に当たって
    **入らない**（実形状で 12.6mm³ 検出）。ツマミがスロットの中を
    滑り降りられるように、上を溝の口まで開ける。
    """
    del w
    from envelopes import SW_PWR_H, SW_PWR_KNOB_W, SW_PWR_TRAVEL
    sz = power_switch_center_z()
    bot = sz - SW_PWR_H / 2 - CLEARANCE / 2       # 座った位置での本体の下端
    # 受けの上まで持ち上げた状態でツマミが要る高さ（そこでスロットへ入れる）
    top = (bot + SW_HOLD_H) + SW_PWR_H / 2 + (SW_PWR_KNOB_W + SW_PWR_TRAVEL) / 2
    return sz - SW_SLOT_LEN / 2, top + 0.3


def power_switch_free_span(half, w):
    """電源スイッチの**外面の造作（指の窪み）が使える x の範囲**。

    ⚠️ **窪みは 2 つの造作に挟まれている**（2026-08-12 に順番に踏んだ）:

      1. 左は**電池蓋の座ぐり。**蓋をコブの奥面へ移して座ぐりを広げたら、
         窪み（幅 10mm）が 2.22mm 食い込んだ。どちらも外面の造作なので、
         重なった分は**蓋に覆われて指が入らない**
      2. 右は**子基板のポケット。**1 を避けて右へ寄せたら、今度は
         ポケットと重なって**壁が消えた**（外から中が見えた）

    **空きは 8.06mm しかなく、幅 10mm の窪みはどこにも置けない。**
    だから窪みの幅は定数ではなく、**ここで決まる。**
    """
    bx, dx = battery_x_center(half, w), daughterboard_x_center(half, w)
    # 2026-09-06（器の案）: 奥板と座ぐりは無くなった。空きは電池箱の端と
    # 子基板のポケットの間
    lo = bx + BATT_X / 2                    # 電池箱の右端
    hi = dx - DB_W / 2                      # 子基板のポケットの左端
    if half == "right":                     # 左右で並びが反転する
        lo, hi = dx + DB_W / 2, bx - BATT_X / 2
    return (lo, hi) if lo < hi else (hi, lo)


def power_switch_dish_w(half, w):
    """指の窪みの幅。**空きから決める**（power_switch_free_span を見ること）。"""
    lo, hi = power_switch_free_span(half, w)
    return min(SW_DISH_W, (hi - lo) - SW_DISH_EDGE * 2)


def power_switch_dish_x(half, w):
    """指の窪みの中心 x。スイッチの中心に揃えつつ、**空き（奥板の座ぐりと
    子基板のポケットの間）からはみ出さない**位置へ寄せる（2026-09-06）。
    スロット（ツマミ）が窪みの中に入ることは test が見る。"""
    lo, hi = power_switch_free_span(half, w)
    half_w = power_switch_dish_w(half, w) / 2
    c = power_switch_x_center(half, w)
    return min(max(c, lo + SW_DISH_EDGE + half_w), hi - SW_DISH_EDGE - half_w)


def battery_center_z():
    """電池（ボックス）の中心高さ。**底は床に載る。**

    **出所を 1 つにするために関数にした。**以前は `FLOOR + AA_D / 2` が
    ここと gen_assembly の 2 か所に書かれており、裸の電池から電池ボックス
    （高さ 16.8mm）へ変えたとき、**箱が床を 1.15mm 突き抜けて蓋に
    1759mm³ 食い込んだ**（2026-08-11。組み立て検査が捕まえた）。
    """
    return FLOOR + BATT_H / 2


def power_switch_center_z():
    """電源スイッチの中心高さ。電池の中心に合わせる。

    コブの中で電池と同じ高さ帯に置けば、上下に余裕が残る。
    """
    return battery_center_z()


def usb_center_z():
    """奥の壁に開ける USB-C 切り欠きの中心高さ。

    子基板の載る高さから導く。数値を直接書くと、ボスの高さを変えたときに
    穴だけ取り残される。

    **メスの実物の中心に合わせる。**以前は「XIAO の積み上げ（DB_STACK_H）の
    真ん中」にしていたが、メスは積み上げの真ん中に居ない（板の上面から
    0.26〜4.46mm で、中心は 2.36。積み上げの半分 2.25 とは 0.11 ずれる）。
    そのうえ穴がメスより低かったので、メスの頭が上縁に食い込んでいた。

    さらに前は「子基板の上面から 1.6mm」と直書きで、切り欠きの上端と
    XIAO の上面の隙間が 0.10mm しか無かった。**直書き → 概数 → 実測**と
    2 度上げてきた値なので、もう推測に戻さないこと。

    **ソケットの浮き（DB_XIAO_LIFT）を必ず足す**（2026-08-12・#27）。
    メスは XIAO の上に載っているので、XIAO が浮けば穴も同じだけ上がる。
    ここを足し忘れると、穴だけ 10.5mm 低い位置に開き、**組み上げてから
    ケーブルが挿さらない**（#28 の再来）。実形状側（gen_assembly）も
    同じ関数を使ってメスの空洞を彫るので、片方だけ直すことはできない。
    """
    return FLOOR + DB_BOSS_H + DB_T + DB_XIAO_LIFT + _RECEPT[3]


def _rubber_positions(w, h_body):
    """ゴム足は**前の 2 箇所**だけ。後ろはチルト脚が接地点を兼ねる。"""
    ix = w / 2 - RUBBER_INSET
    iy = h_body / 2 - RUBBER_INSET
    return [(-ix, -iy), (ix, -iy)]


def _foot_positions(w, h_body):
    """チルト脚の位置。**後ろの隅**。ここが接地点になる。

    内側に寄せると電池室と電池蓋の中にボスが立つ。実際にそうなっており、
    断面図で「電池室の中に 2 本の柱」として見えて発覚した。
    隅なら電池（幅 109mm）にも蓋の開口にも当たらない。

    **位置はここから動かせない**（open-gaps #29 で全部並べた）:
      奥へ寄せる → 電池側の脚のボスが電池の占有空間に入る（左右とも）
      内へ寄せる → 支持多角形が狭まり、隅のキーを打つと傾く
      左右で y を変える → 脚の高さが左右で別になり、部品が倍・取り違えも起きる
    子基板側の脚のボスは J_MAIN コネクタの真下に来るが、それは
    **ボスを低くして**逃がす（FOOT_PEG_H の注記）。
    """
    y = h_body / 2 - RUBBER_INSET
    x = w / 2 - RUBBER_INSET
    return [(-x, y), (x, y)]


def foot_height(h, add_deg):
    """後ろを add_deg だけ持ち上げるのに要る脚の高さ。

    支点は前側のゴム足。脚は後ろの隅にあるので、支点からの距離は
    前後のゴム足／脚の間隔になる。0° の脚はゴム足と同じ高さ。
    """
    lever = h - RUBBER_INSET * 2
    return FOOT_BASE_H + lever * tan(radians(add_deg))


def plate_placement(w, h_plate):
    """プレートをリム面に載せる位置（gen_assembly から移した・2026-09-05）。

    プレートは XY 平面上に平らに作られている。X 軸まわりに TILT_DEG 回すと
    底面が z = y·tan(TILT) の平面になるので、リム面の中央高さだけ持ち上げる。
    **上シェルの開口と最下段の覆いも同じ姿勢で切る**（キャップと同じ傾き）。
    """
    del w
    rim_front = PLATE_TOP_FRONT - PLATE_T
    mid_z = rim_front + (h_plate / 2) * tan(radians(TILT_DEG))
    return Location((0, 0, mid_z), (TILT_DEG, 0, 0))


def _bottom_blank_covers(positions, keys, key_w, key_h, w, h_body, z_max, pose):
    """最下段のキーが無い帯を覆う蓋（ベゼルの枠と同じ断面の板）。

    実機は最下段の左右の余白を筐体の面で覆っている（利用者の指摘・
    実機写真で確認）。帯はキーの並びから機械的に出す——手で座標を
    書くと配列を変えたとき黙ってずれる。
    """
    from build123d import Box, Location

    # 最下段のキーが占める x 区間（セル境界）
    bottom = [(p, k) for p, k in zip(positions, keys)
              if abs(p[1] - min(q[1] for q in positions)) < 1.0]
    b0 = min(p[0] - k.w_u * 19.05 / 2 for p, k in bottom)
    b1 = max(p[0] + k.w_u * 19.05 / 2 for p, k in bottom)
    row_top = max(p[1] for p, _ in bottom) + 19.05 / 2   # 帯の上端（セル）

    g = BEZEL_OPENING_GAP
    ext = 10.0                                   # 枠へ食い込ませて融合する量
    zones = []
    if b0 - (-key_w / 2) > 2.0:                  # 左端の帯
        zones.append((-key_w / 2 - ext, b0 - g))
    if key_w / 2 - b1 > 2.0:                     # 右端の帯
        zones.append((b1 + g, key_w / 2 + ext))

    # **外形でクリップする。**枠へ食い込ませる延長（ext）をそのままに
    # すると、前面から 3.6mm・側面から 7mm はみ出す（前縁高さの検査が
    # 捕まえた——前縁の帯に覆いの斜め上面が混ざり 17.04mm に見えた）。
    with BuildPart() as _ol:
        with BuildSketch():
            RectangleRounded(w, h_body, CORNER_R)
        extrude(amount=z_max * 2)
    outline = _ol.part

    parts = []
    y0 = -key_h / 2 - ext                        # 下は枠へ食い込ませる
    y1 = row_top - g                             # 上はキーとの隙間を空ける
    for x0, x1 in zones:
        with BuildPart() as _p:
            with Locations(((x0 + x1) / 2, (y0 + y1) / 2, 0)):
                Box(x1 - x0, y1 - y0, z_max * 2,
                    align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # **プレートと同じ姿勢に傾ける**（2026-09-05）。垂直のままだと、覆いの
        # 奥の面（次の段のキャップに向く）が 7.3° ずれる。開口と同じ理由
        _p_part = pose * _p.part
        # ⚠️ intersect / 減算は ShapeList を返すことがあるので、
        # 演算のたびに 1 つの立体へ融合し直す。
        def _one(x):
            if hasattr(x, "intersect"):
                return x
            ps = list(x)
            out = ps[0]
            for q in ps[1:]:
                out += q
            return out
        slab = _one(_p_part.intersect(outline))
        slab = _one(slab - tilted_cutter(w, h_body, BEZEL_TOP_FRONT))
        slab = _one(slab.intersect(
            tilted_cutter(w, h_body, PLATE_TOP_FRONT + 0.1)))
        parts.append(slab)
    out = parts[0]
    for p in parts[1:]:
        out += p
    return out


def build_topcase(keys, half):
    """上シェル＝**ベゼル面＋四方の壁の器**（2026-09-06・器の案）。

    壁は机まで下り、下端の 2.4 は外皮 BOTTOM_SKIN だけを残して内側を 45° に
    落とす。底板はその内側に嵌まり、斜面に載る。継ぎ目は底面だけ。
    **ベゼル面をベッドに付けて裏返して刷る**ので、天井から垂らす物（手前の
    ネジ受け・奥の柱・電池箱のボス・電源スイッチの受け箱）はベッドから立つ。
    奥壁に USB-C・XIAO のポケット・スイッチのスロットと窪み、天井に LED 窓。
    プレートは壁（WALL）の内側にリム面で入り、ベゼルの縁が押さえる。
    """
    positions, (w, h_plate) = plate_positions(keys)
    h_body = plan_depth(h_plate)
    h = h_body + BUMP_DEPTH
    y_off = BUMP_DEPTH / 2
    y_out = h_body / 2 + BUMP_DEPTH
    key_w = w - PLATE_MARGIN_X * 2
    key_h = h_body - PLATE_MARGIN_Y * 2
    rim = PLATE_TOP_FRONT - PLATE_T
    z_max = BEZEL_TOP_FRONT + h * tan(radians(TILT_DEG)) + 5.0
    z_hang = FLOOR + BOTTOM_FIT                 # 垂らす物の下端（底板の上面 + 逃げ）

    cut_above_top = tilted_cutter(w, h_body, BEZEL_TOP_FRONT)
    above_rim = tilted_cutter(w, h_body, rim)
    under_ceiling = tilted_cutter(w, h_body, BEZEL_TOP_FRONT - WALL)

    def _inset(d):
        with BuildPart() as _c:
            with BuildSketch():
                with Locations((0, y_off)):
                    RectangleRounded(w - d * 2, h - d * 2, max(CORNER_R - d, 0.5))
            extrude(amount=z_max)
        return _c.part
    # 空洞: 壁 WALL の内側。本体はリム面まで、コブは天井の下面まで
    cav_below_rim = _inset(WALL) - above_rim
    # ⚠️ intersect は ShapeList を返すことがあり、その後の引き算が効かない（天井が
    # 丸ごと消えた）。**引き算だけで作る**: 本体側（y < h_body/2）を引いてから天井を引く
    with BuildPart() as _front_zone:
        with Locations((0, h_body / 2 - 100, 0)):
            Box(w * 3, 200, z_max * 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
    cav_bump = (_inset(WALL) - _front_zone.part) - under_ceiling
    def _front_zone_inv():                       # コブ側（y > h_body/2 − CLEARANCE）を引く箱
        with BuildPart() as _bz:
            with Locations((0, h_body / 2 - CLEARANCE + 100, 0)):
                Box(w * 3, 200, z_max * 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
        return _bz.part
    # 壁の下端: 外皮 BOTTOM_SKIN だけ残し、内側を 45° に落とす（底板の斜面が載る）。
    # 外皮の内側の空洞（z < BOTTOM_CHAMFER）＋斜面のロフト（BOTTOM_CHAMFER〜FLOOR）
    with BuildPart() as _sk:
        with BuildSketch(Plane.XY.offset(-1.0)):
            with Locations((0, y_off)):
                RectangleRounded(w - BOTTOM_SKIN * 2, h - BOTTOM_SKIN * 2, max(CORNER_R - BOTTOM_SKIN, 0.5))
        extrude(amount=1.0 + FLOOR)
    with BuildPart() as _ch:
        with BuildSketch(Plane.XY.offset(FLOOR)):
            with Locations((0, y_off)):
                RectangleRounded(w - BOTTOM_SKIN * 2, h - BOTTOM_SKIN * 2, max(CORNER_R - BOTTOM_SKIN, 0.5))
        with BuildSketch(Plane.XY.offset(FLOOR + BOTTOM_CHAMFER)):
            with Locations((0, y_off)):
                RectangleRounded(w - WALL * 2, h - WALL * 2, max(CORNER_R - WALL, 0.5))
        loft()
    bottom_recess = _sk.part + _ch.part
    # プレートの通り道（手前と左右の壁を BEZEL_WALL 1.2 に）: 本体側（y < h_body/2）の
    # 壁の内側 1.2 を、底からプレート上面 + 0.1 まで抜く。ベゼルの縁（その上）と
    # コブの壁は WALL のまま。内側の 1.2 は底板のリブが埋める（BEZEL_WALL の注記）。
    # 裏返して刷ると壁はベッドから離れるほど薄くなるだけで、張り出しは無い
    thin_cav = ((_inset(BEZEL_WALL) - _front_zone_inv()) - tilted_cutter(w, h_body, PLATE_TOP_FRONT + 0.1))
    # プレートの座ぐり（リム面より上・プレート上面 + 0.1 より下）。thin_cav と重なるが、
    # 上の定義を残す（ベゼルの縁の下端をここで決めている）
    # **プレートのある y の範囲だけ**（奥縁 + 逃げまで）。コブの中まで切ると、天井から
    # 垂らした柱・ボスがリム面〜プレート上面の帯で輪切りになる（最初そうなった）
    with BuildPart() as _pz:                     # プレートより奥（引く側）
        with Locations((0, (h_body / 2 - BEZEL_WALL + CLEARANCE) + 100, 0)):
            Box(w * 3, 200, z_max * 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
    rebate = ((_inset(BEZEL_WALL) - tilted_cutter(w, h_body, PLATE_TOP_FRONT + 0.1) - _pz.part)
              .intersect(above_rim))

    # 天井から垂らす物（すべて z_hang から上へ。ベゼル上面で切る）
    with BuildPart() as _hang:
        # 手前のネジ受け（壁と一体の角柱。プレートの切り欠きを通り、底板の上まで）
        for bx, by in _boss_positions(half):
            _y_in = -PCB_FRONT_EDGE_PLAN + CLEARANCE
            _y_out_ = -h_body / 2 - 1.0
            with Locations((bx, (_y_in + _y_out_) / 2, z_hang)):
                Box(FRONT_BOSS_W, _y_in - _y_out_, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 奥の柱（電池箱と子基板の間）
        for cx, cy in rear_column_positions(half, w, h_body):
            with Locations((cx, cy, z_hang)):
                Cylinder(REAR_COL_D / 2, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 電池箱のボス（箱の床の穴の真上。箱の上面 + 逃げから天井まで）
        _bz_top = FLOOR + BATT_STAND + BATT_H + CLEARANCE / 2
        _by_hole = battery_center(h_body) - BATT_W / 2 + battery_hole_z(half)
        for hx in battery_hole_xs(half, w):
            with Locations((hx, _by_hole, _bz_top)):
                Cylinder(BATT_BOSS_D / 2, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 電源スイッチの受け箱（左右の壁＋天井。奥は壁の内面、手前と下は開く。
        # 本体は壁の内面に当たり、手前は底板の止めブロック、下は底板の台）
        sw_x = power_switch_x_center(half, w)
        sw_bot = power_switch_center_z() - SW_PWR_H / 2 - CLEARANCE / 2
        y_in = y_out - WALL
        holder_d = SW_PWR_BODY_D + CLEARANCE + SW_RIB
        with Locations((sw_x, y_in - holder_d / 2, sw_bot)):
            Box(SW_PWR_W + CLEARANCE + SW_RIB * 2, holder_d, z_max,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    hang = _hang.part - cut_above_top
    # 受け箱の中身: 本体の空所。壁の内面から手前へ開く（**壁は切らない**）
    # 手前へは受け箱の口を開けるだけ（20 まで伸ばしたら奥の柱を輪切りにした）
    with BuildPart() as _sv:
        with Locations((sw_x, y_in + 0.05, sw_bot - 1.0)):      # 壁の内面に 0.05 食い込ませる
            Box(SW_PWR_W + CLEARANCE, holder_d + 0.55, 1.0 + SW_PWR_H + CLEARANCE,
                align=(Align.CENTER, Align.MAX, Align.MIN))
    sw_void = _sv.part

    # LED の窓（#43）。XIAO の真上の天井を外面から LED_WIN_SKIN だけ残して薄くする
    _led_x = daughterboard_x_center(half, w) + XIAO_LED_DX
    _led_y = (y_out - WALL - DB_FROM_REAR - DB_D / 2 + XIAO_LED_DY)
    with BuildPart() as _lw:
        with Locations((_led_x, _led_y, FLOOR)):
            Cylinder(LED_WIN_D / 2, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((0, y_out - WALL + 50, 0)):
            Box(w * 2, 100, z_max * 3, mode=Mode.SUBTRACT, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    led_window_void = _lw.part - tilted_cutter(w, h_body, BEZEL_TOP_FRONT - LED_WIN_SKIN)
    pose = plate_placement(w, h_plate)
    blank_covers = _bottom_blank_covers(positions, keys, key_w, key_h, w, h_body, z_max, pose)
    with BuildPart() as _op:
        with BuildSketch():
            RectangleRounded(key_w + BEZEL_OPENING_GAP * 2, key_h + BEZEL_OPENING_GAP * 2, 1.5)
        extrude(amount=100.0, both=True)
    opening_cut = pose * _op.part

    db_x = daughterboard_x_center(half, w)
    with BuildPart() as top:
        with BuildSketch():
            with Locations((0, y_off)):
                RectangleRounded(w, h, CORNER_R)
        extrude(amount=z_max)
        add(cav_below_rim, mode=Mode.SUBTRACT)
        add(cav_bump, mode=Mode.SUBTRACT)
        add(bottom_recess, mode=Mode.SUBTRACT)
        add(thin_cav, mode=Mode.SUBTRACT)
        add(hang, mode=Mode.ADD)
        add(sw_void, mode=Mode.SUBTRACT)
        add(cut_above_top, mode=Mode.SUBTRACT)
        add(rebate, mode=Mode.SUBTRACT)
        add(led_window_void, mode=Mode.SUBTRACT)
        add(opening_cut, mode=Mode.SUBTRACT)
        add(blank_covers, mode=Mode.ADD)
        # 奥壁: USB-C の小判穴と XIAO のポケット
        with BuildSketch(Plane.XZ.offset(-(y_out + 1.0))):
            with Locations((db_x, usb_center_z())):
                RectangleRounded(USB_W, USB_H, USB_HOLE_R)
        extrude(amount=USB_PLUG_ENTRY + 1.0, mode=Mode.SUBTRACT)
        with Locations((db_x, y_out - WALL + XIAO_POCKET_D / 2, FLOOR + DB_BOSS_H + DB_T + DB_STACK_H / 2)):
            Box(XIAO_OUTLINE_W + CLEARANCE * 2, XIAO_POCKET_D, DB_STACK_H + CLEARANCE * 2,
                mode=Mode.SUBTRACT, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # 奥壁: 電源スイッチの窪みとスロット
        sw_z = power_switch_center_z()
        with Locations((power_switch_dish_x(half, w), y_out - SW_DISH_D / 2, sw_z)):
            Box(power_switch_dish_w(half, w), SW_DISH_D, SW_DISH_H, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
        _sl0, _sl1 = power_switch_slot_z(half, w)
        with Locations((sw_x, y_out, _sl0)):
            Box(SW_SLOT_W, WALL * 4, _sl1 - _sl0, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 手前のネジの頭の座ぐりは底板の縁（外面から 1.3）を 0.39 越える（ネジ中心は
        # 基板の縁で決まり動かせない）。**外皮の下端にも同じ座ぐりを切る**（外皮 1.2 の
        # うち内側 0.3 を頭の高さぶんだけ。外からは見えない）
        for hx, hy in _boss_positions(half):
            with Locations((hx, hy, -1.0)):
                Cylinder(SCREW_HEAD_D / 2 + HEAD_RECESS_CLR, 1.0 + SCREW_HEAD_H + 0.2, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 垂らした物の下端のインサート下穴（底からのネジ）: 手前 3・奥の柱
        # 下穴はインサート + 1.5（M2×6 の先端: 底板 0.6 ＋ 逃げ 0.1 ＋ 5.3 → 1.3 余る）
        for hx, hy in list(_boss_positions(half)) + list(rear_column_positions(half, w, h_body)):
            with Locations((hx, hy, z_hang - 0.5)):
                Cylinder(M2_INSERT_D / 2, 0.5 + M2_INSERT_L + 1.5, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 電池箱のボスの下穴（箱の中から上へ）
        for hx in battery_hole_xs(half, w):
            with Locations((hx, _by_hole, _bz_top - 0.5)):
                Cylinder(M2_INSERT_D / 2, 0.5 + M2_INSERT_L + 1.5, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 最後に外形で切り落とす（角柱は外形をわずかに越える）
        with BuildSketch():
            with Locations((0, y_off)):
                RectangleRounded(w, h, CORNER_R)
        extrude(amount=z_max, mode=Mode.INTERSECT)
    part = top.part
    if len(part.solids()) != 1:
        raise ValueError(f"上シェルが {len(part.solids())} 個に分かれている")
    # 開口と覆いの上縁の面取り（OPENING_CHAMFER。体積の門つき）
    if OPENING_CHAMFER > 0:
        _inv = pose.inverse()
        _z_top_local = BEZEL_TOP_FRONT - PLATE_TOP_FRONT + PLATE_T
        _edges = [e for e in part.edges()
                  if abs((_inv * e).center().Z - _z_top_local) < 0.3
                  and abs((_inv * e).center().X) < key_w / 2 + 3.0
                  and abs((_inv * e).center().Y) < key_h / 2 + 1.5
                  and e.length > 1.0]
        _v0, _b0 = part.volume, part.bounding_box()
        part = part.chamfer(OPENING_CHAMFER, None, _edges)
        _b1 = part.bounding_box()
        _len = sum(e.length for e in _edges)
        _est = _len * OPENING_CHAMFER ** 2 / 2
        _got = _v0 - part.volume
        if (abs(_got - _est) > 0.3 * _est or len(part.solids()) != 1
                or abs(_b1.max.Z - _b0.max.Z) > 1e-3 or abs(_b1.max.Y - _b0.max.Y) > 1e-3):
            raise ValueError(f"開口の面取りで {_got:.0f}mm³ 減った（見積り {_est:.0f}）。"
                             "**カーネルが別の面を失った**")
    # 底の外周の丸め（外皮 BOTTOM_SKIN の外側の辺だけ。体積の門つき）
    if BOTTOM_EDGE_R > 0:
        bb = part.bounding_box()
        _edges = [e for e in part.edges()
                  if e.center().Z < 0.01 and e.length > 5.0
                  and (abs(abs(e.center().X) - bb.max.X) < 0.5
                       or abs(e.center().Y - bb.min.Y) < 0.5 or abs(e.center().Y - bb.max.Y) < 0.5)]
        _v0 = part.volume
        part = part.fillet(BOTTOM_EDGE_R, _edges)
        _per = 2 * ((bb.max.X - bb.min.X) + (bb.max.Y - bb.min.Y))
        _est = _per * (1 - 3.14159265 / 4) * BOTTOM_EDGE_R ** 2
        _got = _v0 - part.volume
        if abs(_got - _est) > 0.3 * _est or len(part.solids()) != 1:
            raise ValueError(f"底縁の丸めで {_got:.0f}mm³ 減った（見積り {_est:.0f}）")
    return part, (w, h_body)


def battery_hole_z(half):
    """電池箱の取付穴の、床（箱が接する面）からの高さ。左右で違う（実測）。"""
    return BATT_HOLE_Z_LEFT if half == "left" else BATT_HOLE_Z_RIGHT


def battery_hole_xs(half, w):
    """電池箱の取付穴 2 個の x。黒線側の端を外壁側と仮定（現物で確認。
    値の出所は BATT_HOLE_X1/X2_FROM_END）。"""
    bx = battery_x_center(half, w)
    sign = 1 if half == "left" else -1
    x_end = bx - sign * BATT_X / 2
    return [x_end + sign * d for d in (BATT_HOLE_X1_FROM_END, BATT_HOLE_X2_FROM_END)]


def build_tilt_foot(add_deg, h):
    """差し込み式のチルト脚。add_deg だけ後縁を持ち上げる。"""
    z = foot_height(h, add_deg)
    with BuildPart() as foot:
        with BuildSketch():
            RectangleRounded(FOOT_D, FOOT_D, 3.0)
        extrude(amount=z)
        with Locations((0, 0, z)):
            Cylinder(FOOT_PEG_D / 2, FOOT_PEG_H,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 先端の返し。押し込むと穴を押し広げて通り、奥の溝で開いて戻らない。
        with Locations((0, 0, z + FOOT_PEG_H - FOOT_BARB_H)):
            Cylinder(FOOT_BARB_D / 2, FOOT_BARB_H,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
    return foot.part, z


def tilted_cutter(w, h, rim_front, y_offset=0.0):
    """z = rim_front + (y + h/2)·tan(TILT) の平面より上を占める立体。

    y_offset は、傾斜の基準（本体部分の中心）が外形の中心とずれている場合に
    与える。後部にコブを足すと外形の中心が後ろへ寄るため。

    BuildPart の中で add(..., mode=Mode.SUBTRACT) して使う。
    builder.part への直接代入はビルダーの内部状態を更新せず、
    切削用の立体がそのまま残る不具合を起こしたので使わない。
    """
    mid_z = rim_front + (h / 2 + y_offset) * tan(radians(TILT_DEG))
    box = Box(w * 3, h * 6, 200, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return Location((0, 0, mid_z), (TILT_DEG, 0, 0)) * box


def _boss_positions(half):
    """ネジボスの位置。**必ず** tools/interface.py の共有定義から導く。

    ここに独自の実装を持っていたせいで、プレートの穴（共有定義）と
    ケースのボス（独自実装）が食い違い、しかもボスが電池室の中に
    立っていた。テストが「プレートの穴 vs 共有定義」しか見ておらず、
    ケースの実物と照合していなかったため長く気づけなかった。
    """
    return boss_positions_plan(half)


def main():
    import json

    from verify import BUILD, assert_watertight, render_outline_2d, to_mesh

    BUILD.mkdir(exist_ok=True)
    # **前に出したが、今は出さない物を消す。**
    #
    # ⚠️ 2026-08-12。底面の電池蓋を廃止したのに `build/battery_lid_*.stl`
    # が残り、**slice_check.py は build/*.stl を全部拾う**ので「刷れます」と
    # 報告し続けた。**存在しない部品を刷らせるところだった。**
    # export_assembly.py で同じ穴を塞いだのに、**こちらに入れていなかった。**
    manifest = BUILD / "gen_case_manifest.json"
    written = []
    for name, keys in halves().items():
        part, (w, h), (z_front, z_rear) = build_case(keys, name)
        mesh, stl = to_mesh(part, f"case_{name}")
        written.append(stl.name)
        assert_watertight(mesh, stl.name)

        for deg in TILT_STEPS:
            foot, fz = build_tilt_foot(deg, h)
            fmesh, fstl = to_mesh(foot, f"tilt_foot_{int(deg)}deg_{name}")
            written.append(fstl.name)
            assert_watertight(fmesh, fstl.name)
            print(f"      チルト脚 +{deg:.0f}° 高さ {fz:.2f}mm -> {fstl.name}")
        # 上ケース（ベゼル）
        topc, (tw, th) = build_topcase(keys, name)
        tmesh, tstl = to_mesh(topc, f"topcase_{name}")
        written.append(tstl.name)
        assert_watertight(tmesh, tstl.name)
        print(f"      上ケース {tw:.2f} x {th:.2f} x "
              f"{topc.bounding_box().size.Z:.2f}mm -> {tstl.name}")
        lid, (lw_, lh_) = build_battery_lid(name, keys)
        lmesh, lstl = to_mesh(lid, f"battery_lid_{name}")
        written.append(lstl.name)
        assert_watertight(lmesh, lstl.name)
        print(f"      電池蓋 {lw_:.2f} x {lh_:.2f}mm -> {lstl.name}")
        render_outline_2d(part, BUILD / f"case_{name}_section.png", axis="X",
                          title=f"case {name} - side section", annotate_count=False)
        bb = part.bounding_box()
        print(f"{name:5s} 設計値 {w:6.2f} x {h:6.2f}mm  "
              f"プレート上面 前 {z_front:.1f} / 奥 {z_rear:.1f}mm  傾斜 {TILT_DEG}°")
        print(f"      実測値 {bb.size.X:6.2f} x {bb.size.Y:6.2f} x {bb.size.Z:6.2f}mm  "
              f"水密={mesh.is_watertight}")
        # 底板は外形から BOTTOM_SKIN + BOTTOM_FIT 内側（器の案・2026-09-06）
        _in = (BOTTOM_SKIN + BOTTOM_FIT) * 2
        assert abs(bb.size.X - (w - _in)) < 0.01, f"底板の幅が設計値と違う（{bb.size.X:.2f} vs {w - _in:.2f}）"
        assert abs(bb.size.Y - (h + BUMP_DEPTH - _in)) < 0.01, "底板の奥行が設計値と違う"
        assert abs(bb.min.Z) < 1e-6, "底板の下面が z=0 でない"
        # 上シェル: 外形は w × (h + コブ)、机（z=0）からベゼル上面まで
        tb = topc.bounding_box()
        assert abs(tb.size.X - w) < 0.01, "上シェルの幅が設計値と違う"
        assert abs(tb.size.Y - (h + BUMP_DEPTH)) < 0.01, "上シェルの奥行が設計値と違う"
        assert abs(tb.min.Z) < 1e-6, f"上シェルの下端が机（0）でない（{tb.min.Z:.2f}）"
        _z_top = BEZEL_TOP_FRONT + (h + BUMP_DEPTH) * tan(radians(TILT_DEG))
        assert abs(tb.max.Z - _z_top) < 0.05, f"上シェルの高さが設計値と違う（{tb.max.Z:.2f} vs {_z_top:.2f}）"

    # 前回の控えとの差を消す（消えた部品の STL と、その絵）。
    old = set(json.loads(manifest.read_text())) if manifest.exists() else set()
    for gone in sorted(old - set(written)):
        for q in (BUILD / gone, BUILD / f"view_{Path(gone).stem}.png"):
            if q.exists():
                q.unlink()
                print(f"      もう作らない物を消した: {q.name}")
    manifest.write_text(json.dumps(sorted(written), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
