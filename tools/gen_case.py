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
    RectangleRounded,
    RegularPolygon,
    extrude,
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
assert WALL == _IF_CASE_WALL, (
    f"interface.CASE_WALL({_IF_CASE_WALL}) が gen_case.WALL({WALL}) とずれている")
FLOOR = 2.4              # 底板。0.4mm の 6 倍。
                         # 当初 2.0mm にしていたが、蓋(1.6mm)をレールに落とし込むと
                         # 床の内面より上に出て電池に食い込んだため厚くした。
# CLEARANCE（嵌合の逃げ 0.2）は interface.py から読む。プレートも同じ値で
# 上ケースの座ぐりに落とし込むので、出所を 2 つ持たない。
PORT_CLEAR = 0.6         # 抜き差しする穴の逃げ。嵌合より広くとる（印刷の公差＋挿しやすさ）

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
BATT_H = BATT_BOX_W              # 占有高さ（z）＝箱の幅 16.6
BATT_W = BATT_BOX_H              # 占有奥行（y）＝箱の高さ 16.8
BATT_X = BATT_BOX_L              # 占有幅（長辺。裸の電池 2 本＋電極と同じ 109mm）
# interface.py は build123d を読めないので envelopes から取れず、同じ値を
# 持っている。**黙ってずれないよう、ここで突き合わせる。**
from interface import BATT_X as _IF_BATT_X  # noqa: E402
assert BATT_X == _IF_BATT_X, (
    f"interface.BATT_X({_IF_BATT_X}) が envelopes.BATT_BOX_L({BATT_X}) とずれている")
# 電池箱の開口面（奥）と奥板の内面の間隔。奥板の舌の足（REAR_TONGUE）が
# 内側へ 1.2 出るので、それより広く。
BATT_MARGIN_REAR = 1.0
# 箱の床の取付穴（データシート: 2×φ2.4、内側から φ3.8×0.8 の座ぐり）。
# 横倒しなので床は手前（−y）を向き、穴の軸は y。
BATT_HOLE_Z_FROM_EDGE = 4.1      # [暫定] 図面「4.1±0.2」を箱の長辺の縁から
                                 # の距離と読んだ。どちらの縁かは現物で確認
BATT_HOLE_X1_FROM_END = 75.9     # [暫定] 穴 1。黒線側の端から。図面 75.9±0.5
BATT_HOLE_X2_FROM_END = 82.8     # [暫定] 穴 2。同 75.9 に隣の 6.9±0.2 を足した
BATT_WIRE_NOTCH = 4.0            # 仕切り壁の両端に開ける、リード線の逃げ（幅・高さ）
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
# 穴の高さ（BATT_HOLE_Z_FROM_EDGE）までボスが要るので 6.0 では足りない。
# 「挿入経路の真横に壁が立つ」問題は、箱を奥の窓から真っ直ぐ差し込むだけ
# なので今は起きない（仕切りは箱の手前にある）。
BATT_DIVIDER_H = 12.0
# プレートの奥端を受ける棚（利用者の指摘 2026-08-29: 奥端が宙吊りで撓む）。
#
# プレートはネジ 3 本（手前 y=−51）にしか留まっておらず、奥端（y=+51.7）の
# 下には何も無い（基板は y=48.7 で終わり、その奥は電池と子基板）。床から
# 柱を立てる場所は無い（幅いっぱいが電池箱と子基板）ので、**コブの天井の
# 前縁から垂らした帯（フランジ）の下に棚を出し、リム面で受ける**。
# 棚の下は電池箱の上面（FLOOR+16.8=19.2）。厚み 2.4 で底は 20.1〜20.7。
PLATE_SHELF_D = 4.0      # 棚が本体側へ出る量（プレートとの掛かりは 2.2mm）
PLATE_SHELF_T = 2.4      # 棚の厚み。リム面に平行
# 子基板の上（XIAO_W/2 + 3 の幅）は**棚を切り欠く**（XIAO 一式の予約
# 21.7〜22.9 とリム面 22.6〜23.1 の隙が 1mm 無い）。棚は 2026-09-05 に
# 上シェルの物になった（build_topcase）。
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
# **保険の座ぐり。**手持ちのケーブルは金属が 1.0mm 見えていたが、
# **ケーブルによってはもっと短い。**その場合は樹脂がわずかに壁へ入る必要がある。
# ここを 0 にすると「このケーブルでしか挿さらないキーボード」になる。
#
# **定数で置かず、要求から導く**（2026-08-10）。メスを 0.3mm 引っ込めたら
# 壁が 0.555mm 厚くなり、**実測したケーブル（金属の露出 1.0mm）が
# 0.055mm 届かなくなった。**#28 の検査が捕まえた。0.5 と直書きしていた
# ので、片方を動かしたときに追随しなかった。
#
#   金属だけで届かないぶん ＝ USB_PLUG_ENTRY − USB_SHELL_EXPOSED
#   そこへ印刷の公差（CLEARANCE）を足したぶんを、樹脂に譲る
#
# 壁を貫通してはいけない（外に大きな口が開く）。`test_a_real_cable_can_reach
# _the_socket` の 3 番目がそれを見張っている。
USB_COUNTERBORE = max(0.5, USB_PLUG_ENTRY - USB_SHELL_EXPOSED + CLEARANCE)
# 内側のポケット（XIAO の端を受ける）の深さ。
XIAO_POCKET_D = XIAO_OVERHANG - DB_FROM_REAR


# --------------------------------------------------------------------------
# 上下シェルの合わせ目とスカート（2026-09-05・案 A）
#
# 上シェル（ベゼル＋コブ天井）は**側壁を外側から被るスカート**（厚み SKIRT_T）
# を持つ。下シェルの側壁は合わせ目（SEAM_Z）より上で外側 SKIRT_T + SKIRT_FIT
# を削り、内側の帯（1.2）が**リム面までプレートを受ける**。
#
# ⚠️ 一度「合わせ目より上の側壁は丸ごと上シェルの物」にした（2026-09-05 の
# 最初の版）。すると**プレートを受ける段と押さえるベゼルの縁が同じ部品に
# 入り、プレートが上からも下からも入らなかった**（利用者が .blend を見て
# 指摘。CLAUDE.md の教訓 9 を、検査を足さずに踏んだ）。受けるのは下、押さえる
# のは上——元の分担に戻し、`test_the_plate_can_be_put_into_the_shells` が
# 入れられることを見張る。実機の「側面の中ほどに上下シェルの合わせ目」
# （dimensions.md §4 の 3）を再現し、#12（上ケースの奥の留め）の原因だった
# 「同一外形の落とし込み（平面方向の逃げ 0）」をやめる。
# 経緯は docs/hardware/decisions/2026-09-05-case-redesign-plan-a.md。
# 合わせ目の高さ（底面から）＝**手前のリム面**。実機写真は「側面の中ほど」
# （目測 9mm 前後）で、手前のリム 9.49 はその範囲。手前壁は上下シェルが
# リム面で突き合わせになる（手前のネジボスが外面に接していて、相欠きに
# すると熱圧入インサートが外へ出る）ので、合わせ目をリムに揃えると
# 手前と側面の合わせ目が一直線になる。
SEAM_Z = PLATE_TOP_FRONT - PLATE_T
SKIRT_T = 1.2            # スカートの厚み（0.4 ノズル 3 周）。下シェル側の
                         # 帯は WALL − SKIRT_T − SKIRT_FIT = 1.2（同じく 3 周）
# スカートの内面と帯の外面の隙間。**0 ＝ 接触**（2026-09-05・利用者の判断:
# 「隙間があるとガタつく。合わなければ削る」。電池蓋のビードを大きい側に
# 振ったのと同じ方針）。印刷の公差 CLEARANCE(0.2) をここに入れると帯が
# 1.0（2.5 周）に痩せ、横に ±0.2 の遊びが出る。0 で刷って被さらなければ
# 帯（平らで外から手が届く）をやすりで削る。クーポン（#11）で確定させる。
SKIRT_FIT = 0.0          # [暫定] クーポンで実測してから決める
# プレートの奥端の上の隙間（座ぐりの天井をプレート上面からこれだけ上げる）。
# 奥端は上シェルの棚（下）とベゼルの縁（上）の**溝**に入るので、プレートを
# 少し傾けて奥から差し込む（手前が板厚＋0.5 下がる ≈ 1.1°。奥端の角の
# 持ち上がりは 0.05 程度）。0.1 のままだと傾けた瞬間に溝に当たる。
PLATE_REAR_GAP = 0.5
REAR_CORNER_D = 6.0      # 奥の隅は下シェルが全高で持つ（奥壁と一体の柱）。
                         # スカートはここで止まる
# 奥板（電池窓を塞ぐ板。旧・電池蓋のスライド＋ビードは全廃）
REAR_PLATE_CLR = 0.3     # 窓を電池箱の断面からどれだけ広げるか（片側）
REAR_PLATE_T = 1.6       # 板厚。奥壁の外面に面一で沈む（座ぐりも同じ深さ）
REAR_PLATE_FRAME = 2.0   # 座ぐりを窓から広げる量（左右）＝板の掛かり代。
                         # 2.5 にすると電源スイッチの指の窪みが 4.76mm に
                         # 痩せる（検査 5.0 未満）。旧・蓋の掛かり代と同じ 2.0
REAR_PLATE_LIP = 3.0     # 上縁のリップがコブ天井の奥縁に被る量
REAR_TONGUE_T = 1.2      # 板の下端の足（内側へ L 字に出る）の厚み
REAR_TONGUE_H = 1.0      # 同・床の溝へ入る深さ
REAR_GROOVE_W = 1.4      # 床の溝の幅（足 + 0.2）
REAR_GROOVE_D = 1.2      # 同・深さ（床 2.4 の半分）
REAR_RAIL_H = 6.0        # 上シェルの奥縁の裏に付ける桟（奥板のネジを受ける）
REAR_RAIL_D = 6.0        # 同・奥行
REAR_SCREW_DX = 40.0     # 奥板のネジ 2 本の、電池箱中心からの x
# 奥面 3 本目のネジ（2026-09-05・利用者「見えない所ならネジを増やしてよい」）。
# 奥板のリップは電池窓の幅（109）しか押さえず、子基板側の 35mm は隅の柱で
# 受けるだけだった。奥壁を貫いて上シェルの天井裏のボスへ M2 を横に入れる。
# 位置は子基板の中心から電池側へ REAR_SCREW3_DX（LED 窓と USB を避ける）。
REAR_SCREW3_DX = 8.0
REAR_SCREW3_BOSS_W = 6.0 # 天井裏のボス（角柱）の x 幅
SW_KEEPER = 4.0          # 電源スイッチの上に上シェルから垂らす柱の一辺。
                         # スイッチが溝から浮き上がるのを止める

# 手前面の造作（実機再現・dimensions.md §4 の 1・2。2026-09-05）
#
# 実機は手前面が下へ行くほど奥へ傾き（目測 12°）、ベゼル上面から手前面へ
# 大きな R（目測 R6）で移る。**どちらも丸ごとは再現できない**:
#   * 傾け: 手前の M2 ボス（φ5.6・中心 y=−51.5）は外面から 0.74 はみ出す位置に
#     あり、内側の端は基板の手前縁まで 0.44。面を傾けるとボスが削れて
#     インサートが露出する。基板は発注済みで、ボスを内へ動かせない
#   * R6: ベゼルの手前バーは高さ 6.5 しか無く、R6 だと座ぐりの壁まで消える
# できるのは**ベゼルのバーの範囲だけ**: 上端から FRONT_FACET_H の高さだけ
# 12° で内側へ傾け（上端が最前点。下端で 1.2 内側）、上端の縁を R2 で丸める。
# R は CAD カーネルが左右の縁では拒否した（隅の小さな面）ので手前だけ。
FRONT_FACET_DEG = 12.0   # [目測] 実機写真から
FRONT_FACET_H = 0.0      # 傾ける高さ（上端から）。**0 ＝ 無効。**5.5 で試すと
                         # 下端（z=12）に幅 1.2 の水平な段ができた——その下は
                         # プレートの座ぐりの壁で、面を内側へ入れられない。
                         # 実機に無い線が 1 本増えるので、R2 だけにした
                         # （2026-09-05）。手前のボスを内へ動かせる基板改版が
                         # あれば、下まで通して復活させる
FRONT_EDGE_R = 0.0       # 上端の丸め。**0 ＝ 無効。**R2 は手前の辺だけなら
                         # カーネルが通したが、**通した結果が奥の天井の一部を
                         # 黙って失っていた**（max Z 33.53 → 33.26。x=60, y=71 の
                         # 天井が消えた。2026-09-05 に is_inside で検出）。
                         # OCC のフィレットは失敗を例外で言わないことがある。
                         # 丸めは試作後に手やすり、または別の作り方で
BOTTOM_EDGE_R = 1.5      # 下シェルの底縁の丸め（実機の「合わせ目より下は
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
    """トレイ型ボトムケースを作る。

    奥行はプレートの平面図での長さ（傾けたぶん cos(TILT) 倍に縮む）に合わせる。
    プレートの平らな寸法をそのまま使うと、リムがプレートより 0.84mm 長くなり
    覆いきれない（組み立て検査で検出）。
    """
    positions, (w, h_plate) = plate_positions(keys)
    h_body = plan_depth(h_plate)          # プレートが載る範囲
    h = h_body + BUMP_DEPTH               # 後部のコブを足した全体の奥行
    # 座標の基準は**本体部分の中心**（＝プレートの中心＝原点）に固定する。
    # コブは後ろへ張り出すだけなので、外形の矩形は BUMP/2 だけ後ろへずらす。
    # 外形の中心を原点にするとプレートと基板が前へずれる（実際にずらして
    # 2,680mm^3 の食い込みを出した）。
    y_off = BUMP_DEPTH / 2
    z_front, z_rear = case_heights(h)
    rim_front = z_front - PLATE_T          # プレートを載せるリムの高さ（前縁）
    rim_rear = z_rear - PLATE_T
    # **コブの上面はベゼル面まで上がる**ので、そこまで立ち上げておく。
    # rim_rear + 5.0 のままだと 31.31mm までしか無く、ベゼル面（33.53mm）に
    # 届かず切れない。
    z_max = BEZEL_TOP_FRONT + h * tan(radians(TILT_DEG)) + 5.0

    # 切削用の立体は BuildPart に入る前に作る。
    # コンテキストの中で Box() を作ると、その時点で部品に合体されてしまい、
    # 「原点で合体 → 傾けた位置で減算」という食い違いが起きる。
    # 上面の切り方は**本体とコブで違う**。
    #   本体   … リム（プレートの下面）で切る。上にプレートと上ケースが載る
    #   コブ   … ベゼル上面で切る。ここには上ケースが載らないので、
    #             低く切ると奥に 5.7mm の段ができ、上ケースの舌を受ける
    #             材料も無くなる（噛み合いの検査が「舌の上に材料が無い」と検出）
    with BuildPart() as _body:
        with BuildSketch():
            RectangleRounded(w + 20, h_body, CORNER_R)
        extrude(amount=z_max + 50, both=True)
    cutter = tilted_cutter(w, h_body, rim_front).intersect(_body.part)
    # コブの側壁・奥壁の上端。**天井は上シェルの物**（2026-09-05・案 A）。
    # 天井の下面（ベゼル上面 − WALL）から CLEARANCE 下げて切る。
    cutter_bump = tilted_cutter(w, h_body, BEZEL_TOP_FRONT - WALL - CLEARANCE)
    _y_out = h_body / 2 + BUMP_DEPTH
    # 合わせ目より上の側壁の外側 SKIRT_T + SKIRT_FIT を削る（上シェルの
    # スカートが被る）。内側 1.2 の帯はリム面（コブでは天井の下）まで残り、
    # プレートを受ける。奥の隅（y > 奥面 − REAR_CORNER_D）は柱として全厚で残す。
    with BuildPart() as _sk:
        with BuildSketch(Plane.XY.offset(SEAM_Z)):
            with Locations((0, y_off)):
                RectangleRounded(w + 2.0, h + 2.0, CORNER_R + 1.0)
                RectangleRounded(w - (SKIRT_T + SKIRT_FIT) * 2,
                                 h - (SKIRT_T + SKIRT_FIT) * 2,
                                 max(CORNER_R - SKIRT_T - SKIRT_FIT, 0.5),
                                 mode=Mode.SUBTRACT)
        extrude(amount=z_max)
        with Locations((0, _y_out - REAR_CORNER_D + 100, 0)):
            Box(w * 3, 200, z_max * 3, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 手前壁は触らない（相欠きにするとネジボスのインサートが外へ出る。
        # SEAM_Z の注記）。上シェルの手前はリム面で突き合わせ。
        with Locations((0, -h_body / 2 + WALL - 100, 0)):
            Box(w * 3, 200, z_max * 3, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    skirt_cut = _sk.part
    # ボスの頭を止める面（基板の下面）。これも**必ず**コンテキストの外で作る。
    # 中で作ると即座に部品へ合体され、外形が 538x614mm に膨れる（実際にやった）。
    from envelopes import under_pcb_base
    cutter_pcb = tilted_cutter(w, h_body, under_pcb_base(
        h_plate, rim_front, PLATE_TO_PCB + PCB_T))
    # ボスも外で作って外で切る。**ネジは基板を通らない。**基板に取付穴は
    # 無く（feec08b で廃止）、ボスは基板の外に立っている。切る高さは
    # 20 行ほど下で「プレートの下面（リム）」に決めている。
    with BuildPart() as _b:
        # **角柱**（2026-09-05）。円柱 φ5.6 では中心 51.5 でインサートの外側の
        # 肉が 0.46 だった。角柱にして外面（y=−h_body/2 − 1）から基板の縁 + 0.2
        # まで一体で作り、インサートを内へ寄せる（interface.MOUNT_Y の注記）。
        for bx, by in _boss_positions(half):
            _y_in = -PCB_FRONT_EDGE_PLAN + CLEARANCE          # 基板の縁 + 0.2
            _y_out_ = -h_body / 2 - 1.0                          # 外面より外（外形で切る）
            with Locations((bx, (_y_in + _y_out_) / 2, FLOOR)):
                Box(FRONT_BOSS_W, _y_in - _y_out_, z_max,
                    align=(Align.CENTER, Align.CENTER, Align.MIN))
    # **ボスの頭はプレートの下面（リム）で止める。**
    # 以前は基板の下面で止めていた（基板をボスに載せる設計だったため）。
    # 上ケース方式ではネジは上ケースから入り、プレートはボスの上に載る。
    bosses = _b.part - cutter
    # コブの天井と LED 窓は**上シェル**（build_topcase）へ移した（2026-09-05）。
    # 電池室の仕切り壁。**基板の下面（ソケットの先端）で頭を切る。**
    #
    # 電池を前へ動かしたぶん仕切りも前へ来る。前ほど打鍵面が低いので、
    # 高く立てると傾いた基板を突き上げる（186mm^3 の食い込みとして
    # 組み立て検査が検出）。ボスと同じく、コンテキストの外で作って外で切る。
    # **高さは BATT_DIVIDER_H（6.0）。**箱の高さと同じ 16.8 で立てていたのを
    # 2026-08-29 に下げた（挿入と裏面ガイドの干渉。定数の注記を見ること）。
    # 切り取りは残す——下げても、手前ほど低い打鍵面では効く場所がある。
    cutter_under_pcb = tilted_cutter(w, h_body, under_pcb_base(
        h_plate, rim_front, PLATE_TO_PCB + PCB_T + SOCKET_DROP))
    y_div = (battery_center(h_body) - BATT_W / 2 - WALL / 2 - CLEARANCE)
    with BuildPart() as _d:
        with Locations((battery_x_center(half, w), y_div, FLOOR)):
            Box(BATT_X, WALL, BATT_DIVIDER_H,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    divider = _d.part - cutter_under_pcb
    # プレートの奥端の棚は上シェルの物になった（build_topcase・2026-09-05）。
    with BuildPart() as _n:
        with Locations((0, 0, FLOOR)):
            Cylinder(NUT_BOSS_D / 2, NUT_BOSS_H,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
    nut_boss = _n.part - cutter_under_pcb

    with BuildPart() as case:
        # 1. 外形を最大高さまで立ち上げる（コブぶん後ろへずらす）
        with BuildSketch():
            with Locations((0, y_off)):
                RectangleRounded(w, h, CORNER_R)
        extrude(amount=z_max)

        # 2. 上面を傾いた平面で切り落とす
        add(cutter_bump, mode=Mode.SUBTRACT)      # 全体をベゼル上面で
        add(cutter, mode=Mode.SUBTRACT)           # 本体部分はさらにリムまで

        # 3. 内側をくり抜く
        with BuildSketch(Plane.XY.offset(FLOOR)):
            with Locations((0, y_off)):
                RectangleRounded(w - WALL * 2, h - WALL * 2,
                                 max(CORNER_R - WALL, 0.5))
        extrude(amount=z_max, mode=Mode.SUBTRACT)

        # 3-2. 合わせ目より上の側壁・手前壁を落とす（上シェルのスカートが
        #      代わる）。天井・LED 窓・棚は上シェル側。
        add(skirt_cut, mode=Mode.SUBTRACT)

        # 4. 電池室。後壁ぎわ（コブの中）に置き、仕切り壁と天井を作る。
        #    天井を張らないと、傾いた基板が電池室の上に落ちてきて衝突する。
        # 仕切り壁は電池からわずかに離す。ちょうど接する位置に置くと
        # 干渉として検出される（接触は 0 にならない）。
        #
        # **幅は電池ぶんだけ。** 以前は内寸いっぱいに張っていたが、
        # 内縁側は子基板の場所として空けておく必要がある。
        add(divider, mode=Mode.ADD)
        # 天井は張らない。電池の上には基板が来るので、板を入れると
        # 傾いた基板の下端を突き上げる（2,817mm^3 の食い込みとして検出）。
        # 電池は 手前=仕切り壁 / 左右と奥=側壁 / 下=蓋 / 上=基板 で保持される。

        # 5. ネジボス。ケースに合体する**前に**頭を基板の下面で切る。
        #    ケースに合体してから切ると、平面がケース全体に効いてリムまで
        #    5.1mm 下がる（プレートが沈む）。高さのテストで検出された。
        add(bosses, mode=Mode.ADD)
        for bx, by in _boss_positions(half):
            with Locations((bx, by, FLOOR)):
                Cylinder(M2_INSERT_D / 2, z_max, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))

        # 6. 電池蓋の開口とレール（底面）
        #
        # 順序が肝心。**狭い方を貫通させ、広い方を上側だけ削る**。
        # 逆にすると（広い開口を先に貫通させてから狭い座ぐりを削ると）、
        # 蓋を受ける段が一切できない。当初これを間違えており、組み立て検査で
        # ケースと蓋が食い込むという形で発覚した。
        # 6-0. 子基板の座（取付ボス 2 本）と、奥の壁の USB-C 切り欠き。
        #
        # 蓋の開口より**先に**置く。開口は床を貫通させる操作なので、
        # あとから足すとボスの根元が削られる。
        db_x = daughterboard_x_center(half, w)
        # 子基板もコブの中。USB-C はコブの奥面から出る（実機の USB も同じ面）。
        y_rear_outer = h_body / 2 + BUMP_DEPTH
        db_y = y_rear_outer - WALL - DB_FROM_REAR - DB_D / 2
        for dx, dy in DB_BOSS_POS:
            with Locations((db_x + dx, db_y + dy, FLOOR)):
                Cylinder(M2_BOSS_D / 2, DB_BOSS_H,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
            with Locations((db_x + dx, db_y + dy, FLOOR)):
                Cylinder(M2_INSERT_D / 2, DB_BOSS_H + 1.0, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 奥の壁の USB-C。**2 段に切る**（open-gaps #28）。
        #
        #   外側 USB_PLUG_ENTRY … ケーブルの樹脂の胴体が入るぶん（12.4x7.4mm）
        #   内側 XIAO_POCKET_D  … XIAO の端を受けるポケット（外からは見えない）
        #
        # **1 段で貫くと、樹脂が入る大きさの穴が壁を貫通する。**外から見て
        # 大きな口が開き、ほこりも入る。段にすれば、外に見えるのは
        # 普通の機器と同じ大きさの穴だけで済む。
        with Locations((db_x, y_rear_outer - USB_PLUG_ENTRY / 2, usb_center_z())):
            Box(USB_W, USB_PLUG_ENTRY, USB_H, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # 樹脂用の浅い座ぐり（外面から USB_COUNTERBORE mm だけ）
        with Locations((db_x, y_rear_outer - USB_COUNTERBORE / 2, usb_center_z())):
            Box(USB_PLUG_W + CLEARANCE * 2, USB_COUNTERBORE,
                USB_PLUG_H + CLEARANCE * 2, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # 内側のポケット。**幅は XIAO の外形＋逃げ。**深さは残りの壁。
        with Locations((db_x, y_rear_outer - WALL + XIAO_POCKET_D / 2,
                        FLOOR + DB_BOSS_H + DB_T + DB_STACK_H / 2)):
            Box(XIAO_OUTLINE_W + CLEARANCE * 2, XIAO_POCKET_D,
                DB_STACK_H + CLEARANCE * 2, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))

        # 6-0a. 奥の窓（電池箱の出し入れ口。**案 A・2026-09-05**）
        #
        # 電池箱の断面（横倒し: 109 × 16.6）＋逃げを、**床から天井まで**抜く。
        # 窓の上（箱〜天井）にも壁は残さない——そこは奥板が塞ぎ、板の上縁の
        # リップが上シェルの天井を押さえる。左は内壁で止める（箱は内壁から
        # 0.2 しか無い。旧・蓋の口と同じ）。
        wx0, wz0, wx1, _wz1 = rear_window(half, w)
        with Locations(((wx0 + wx1) / 2, y_rear_outer - WALL / 2, wz0)):
            Box(wx1 - wx0, WALL * 3, z_max, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 奥板が面一で沈む座ぐり（外面から REAR_PLATE_T・左右に FRAME）。
        # 下は床の上面まで（板は床の上に立つ）。
        rx0, rx1 = rear_plate_rebate(half, w)
        with Locations(((rx0 + rx1) / 2, y_rear_outer + 0.5, wz0)):
            Box(rx1 - rx0, REAR_PLATE_T + 0.5, z_max, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.MAX, Align.MIN))
        # 奥板の足が入る床の溝。板は据えてから下へ REAR_TONGUE_H 落として留める
        # （旧・庇と舌の代わり。撓ませない）。
        with Locations(((wx0 + wx1) / 2, rear_groove_y(h_body), FLOOR - REAR_GROOVE_D)):
            Box((wx1 - wx0) - 2.0, REAR_GROOVE_W, REAR_GROOVE_D + 0.5,
                mode=Mode.SUBTRACT, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 電池箱の取付ボス（仕切り壁の手前側に横向きの柱）。箱の床の穴 2 個
        # （φ2.4・データシート）に M2 を通し、仕切り壁のインサートへ締める。
        # ドライバーは奥の窓から箱の中を通す（箱の座ぐりに頭が沈む）。
        _bz = FLOOR + BATT_HOLE_Z_FROM_EDGE
        _yd_front = y_div - WALL / 2
        for hx in battery_hole_xs(half, w):
            with Locations((hx, _yd_front - 2.5, _bz)):
                Box(M2_BOSS_D, 5.5, M2_BOSS_D,
                    align=(Align.CENTER, Align.CENTER, Align.CENTER))
            with Locations((hx, y_div + WALL / 2 - 2.25 + 0.01, _bz)):
                Cylinder(M2_INSERT_D / 2, 4.5, rotation=(90, 0, 0),
                         mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # 箱の両端から出るリード線の逃げ（仕切り壁の両端の切り欠き）。
        _bx = battery_x_center(half, w)
        for nx in (_bx - BATT_X / 2 + BATT_WIRE_NOTCH / 2,
                   _bx + BATT_X / 2 - BATT_WIRE_NOTCH / 2):
            with Locations((nx, y_div, FLOOR)):
                Box(BATT_WIRE_NOTCH, WALL * 2, BATT_WIRE_NOTCH, mode=Mode.SUBTRACT,
                    align=(Align.CENTER, Align.CENTER, Align.MIN))

        # 6-0b. 電源スイッチのポケットとスロット（奥の壁）
        #
        # スイッチは基板に載らない。右アングルなので、壁の内側に掘った
        # ポケットへ落とし込むと操作部が壁のスロットから外へ出る。
        # 経緯は docs/hardware/decisions/2026-08-08-power-switch.md。
        #
        # **ここは「彫る」のではなく「足す」。**
        #
        # 奥の壁の内側は電池室の空洞で、もともと材料が無い。座ぐりを
        # 掘っても空気を削るだけで、スイッチを受ける面ができない
        # （最初そう書いて、故意に壊す検査が「壊しても落ちない」形で
        # 見つけた）。**受けの箱を足してから、中身を抜く。**
        #
        # **上から落とし込む溝にする**（2026-08-12・#18 の抜け止め）。
        #
        # 以前は手前（ケースの内側）が開いた箱で、そこから押し込む形
        # だった。**押し込む向きに留めが無い**（利用者の指摘）。
        # ところが留めを足せない:
        #   * 本体は壁に当たるまで **3.5mm** しか入らないのに、入口は
        #     **11mm 奥**（端子 5.0 とリード線のぶん）。入口に爪を置いても
        #     本体に届かない
        #   * 奥（深さ 3.5）に爪を置くと、**入れるときに本体が通れない**
        #   * 撓む爪にするとひずみが PLA の限界を超える（リブ 1.6mm を
        #     0.5mm 撓ませると ε=3.3%。上限は 1.0%）
        #
        # → **爪をやめる。**上を開けた溝にして、スイッチを**上から
        # 落とし込む。**奥はリブで塞ぐので、押し込む向きは**剛体で**
        # 止まる。端子は奥のリブの真ん中に開けた縦スリットを通す。
        # スリットは上まで抜けているので、落とし込むときに一緒に降りる。
        sw_x = power_switch_x_center(half, w)
        sw_z = power_switch_center_z()
        y_rear_inner = y_rear_outer - WALL
        holder_d = SW_PWR_BODY_D + CLEARANCE + SW_RIB   # 本体ぶん＋奥のリブ
        sw_bot = sw_z - SW_PWR_H / 2 - CLEARANCE / 2    # 溝の底（ここに座る）
        with Locations((sw_x, y_rear_inner - holder_d / 2,
                        sw_bot - SW_RIB)):
            Box(SW_PWR_W + CLEARANCE + SW_RIB * 2, holder_d,
                SW_HOLD_H + SW_RIB,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 本体の空所。**上へ突き抜けさせる**（落とし込む口）。
        with Locations((sw_x, y_rear_inner - (SW_PWR_BODY_D + CLEARANCE) / 2,
                        sw_bot)):
            Box(SW_PWR_W + CLEARANCE, SW_PWR_BODY_D + CLEARANCE,
                SW_PWR_H * 3, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 端子の縦スリット（奥のリブを貫く）。**ここも上まで抜く。**
        # 端子は 3 本・2.5 ピッチで**上下に並ぶ**（本体を縦向きに付けるため）
        # ので、x 方向には 1 本ぶんの幅で足りる。
        # ⚠️ **奥へ向かってだけ切る。**深さを 2 倍にして中心に置いたら、
        # 手前側が**奥の壁を突き抜けて外に出た**（2026-08-12・利用者が
        # Blender で見て発見。外から本体が見えていた）。
        # 起点を本体の空所の奥の面に固定し、そこから奥へ抜く。
        with Locations((sw_x, y_rear_inner - (SW_PWR_BODY_D + CLEARANCE),
                        sw_bot)):
            Box(SW_PWR_PIN_W + CLEARANCE, holder_d,
                SW_PWR_H * 3, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.MAX, Align.MIN))
        # 指の逃げの窪み（外面から SW_DISH_D）。**スロットより先に掘る。**
        with Locations((sw_x, y_rear_outer - SW_DISH_D / 2, sw_z)):
            Box(power_switch_dish_w(half, w), SW_DISH_D, SW_DISH_H,
                mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
        _sl0, _sl1 = power_switch_slot_z(half, w)
        with Locations((sw_x, y_rear_outer, _sl0)):
            Box(SW_SLOT_W, WALL * 4, _sl1 - _sl0,
                mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 6-0c. 奥面 3 本目のネジのバカ穴（奥壁を貫いて上シェルのボスへ）
        _x3, _z3 = rear_screw3(half, w, h_body)
        with Locations((_x3, y_rear_outer - WALL / 2, _z3)):
            Cylinder(M2_CLEAR_D / 2, WALL * 3, rotation=(90, 0, 0), mode=Mode.SUBTRACT,
                     align=(Align.CENTER, Align.CENTER, Align.CENTER))



        # 6-1〜3. **底面の電池蓋は廃止した**（2026-08-12・利用者の決定）。
        #
        # 電池の出し入れはコブの奥面の蓋（#35）に移した。底に 109 × 16.6mm の
        # 貫通穴とレールと蓋が残っていたが、**用途はもう無い。**しかも
        # それは #35 で「外から開かない」と判定した蓋そのもので、
        # **裏面に振動吸収シートを貼れなくなる**（利用者が奥面を選んだ
        # 理由の 1 つ）。**置き換えたのに古い方を消していなかった。**
        # 床は塞がったままになる（剛性も上がる）。

        # 7. 三脚ネジ穴（1/4-20 の六角ナットを底面から埋め込む）
        #
        # **床から立つものは、すべて基板の下面で頭を切る。**
        # ここだけ切っていなかったため、プレートを実機の高さまで下げたときに
        # ボスの頂点 11.40mm がソケット下端 8.84mm を突き上げ、
        # 250mm^3 の食い込みとして検出された。ナット（厚 5.7mm）は
        # 切ったあとの高さでも完全に収まる。
        add(nut_boss, mode=Mode.ADD)
        with Locations((0, 0, 0)):
            Cylinder(NUT_THRU_D / 2, NUT_BOSS_H + FLOOR * 2, mode=Mode.SUBTRACT,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
        # **ポケットは底面に開いている（下から入れる）。**逃げ 0.30mm では
        # **持ち上げるとナットが落ちる**（2026-08-12 に発見。利用者の
        # 「固定が弱いところは無いか」から）。締めれば天井に当たるので
        # 機能はするが、使わないときに落ちるのは製品として成立しない。
        #
        # → **入口だけ狭めて、押し込んだら戻らないようにする。**
        # 深さ NUT_LIP_H の帯だけ二面幅を NUT_LIP_UNDER 狭くする。
        # **公差に依存しない**（#11 のクーポン待ちの CLEARANCE を使わない）。
        # 噛んでいることは test_the_tenting_nut_is_captured が形で確かめる。
        _hex_r = NUT_AF / 2 / __import__("math").cos(radians(30))
        with BuildSketch(Plane.XY.offset(NUT_LIP_H)):
            RegularPolygon(_hex_r, 6)
        extrude(amount=NUT_T - NUT_LIP_H, mode=Mode.SUBTRACT)
        with BuildSketch(Plane.XY):
            RegularPolygon(
                (NUT_AF - NUT_LIP_UNDER) / 2 / __import__("math").cos(radians(30)), 6)
        extrude(amount=NUT_LIP_H, mode=Mode.SUBTRACT)

        # 8. ゴム足の座ぐりと、チルト脚の差し込み穴（いずれも底面）
        for fx, fy in _rubber_positions(w, h_body):
            with Locations((fx, fy, 0)):
                Cylinder(RUBBER_D / 2, RUBBER_RECESS, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        # ピン穴は床(2.4mm)と同深なので、そのまま開けると内部へ貫通する。
        # メッシュの種数が 4 になって発覚した。内側にボスを立てて盲穴にする。
        # キャップは FOOT_BOSS_CAP。**ボス頂は 3.6mm に抑える**（真上に
        # J_MAIN コネクタが 4.31mm まで下がってくる。FOOT_PEG_H の注記）。
        for fx, fy in _foot_positions(w, h_body):
            with Locations((fx, fy, 0)):
                Cylinder(FOOT_PEG_D / 2 + 2.0, FOOT_PEG_H + FOOT_BOSS_CAP,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 穴の奥の溝（返しが開いて噛む場所）。**穴より先に掘らない**
        # ——順序を変えると、細い穴が太い溝を削り取る。
        for fx, fy in _foot_positions(w, h_body):
            with Locations((fx, fy, FOOT_PEG_H - FOOT_BARB_H)):
                Cylinder(FOOT_GROOVE_D / 2, FOOT_BARB_H, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        for fx, fy in _foot_positions(w, h_body):
            with Locations((fx, fy, 0)):
                Cylinder(FOOT_PEG_D / 2 + CLEARANCE / 2, FOOT_PEG_H,
                         mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))

        # 最後に外形で切り落とす。
        # **ボスは壁と一体で、平面図では外形をわずかに越える**（手前のボスは
        # 0.021mm 出る）。外形を保証するために最後に必ず通す。
        with BuildSketch():
            with Locations((0, y_off)):
                RectangleRounded(w, h, CORNER_R)
        extrude(amount=z_max, mode=Mode.INTERSECT)

    # 底縁の丸め（BOTTOM_EDGE_R）。床の外周の辺だけ。
    part = case.part
    # **外周の辺だけ**（ゴム足の座ぐりの円やナットの穴の辺を含めるとカーネルが
    # 拒否する。2026-09-05 に R0.5 まで全部失敗した）
    bb = part.bounding_box()
    bottom_edges = [e for e in part.edges()
                    if e.center().Z < 0.01 and e.length > 5.0
                    and (abs(abs(e.center().X) - bb.max.X) < 3.5
                         or abs(e.center().Y - bb.min.Y) < 3.5
                         or abs(e.center().Y - bb.max.Y) < 3.5)]
    _v0, _b0 = part.volume, part.bounding_box()
    part = part.fillet(BOTTOM_EDGE_R, bottom_edges)
    # **フィレットは失敗を黙る**（上シェルの手前 R2 で奥の天井が消えた・
    # 2026-09-05）。削れた体積が外周 × R² × (1−π/4) の見積りから 30% 以上
    # ずれたら、どこか別の面を失っている
    _per = 2 * ((_b0.max.X - _b0.min.X) + (_b0.max.Y - _b0.min.Y))
    _est = _per * (1 - 3.14159265 / 4) * BOTTOM_EDGE_R ** 2
    _got = _v0 - part.volume
    if abs(_got - _est) > 0.3 * _est or len(part.solids()) != 1:
        raise ValueError(f"底縁の丸めで {_got:.0f}mm³ 減った（見積り {_est:.0f}）。"
                         "**カーネルが別の面を失った**")
    return part, (w, h_body), (z_front, z_rear)


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
    h_lo, h_hi = lo + CLEARANCE + hw, hi - CLEARANCE - hw
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
    _rx0, rx1 = rear_plate_rebate(half, w)
    lo = max(bx + BATT_X / 2, rx1)          # 電池と蓋の座ぐりの右端
    hi = dx - DB_W / 2                      # 子基板のポケットの左端
    if half == "right":                     # 左右で並びが反転する
        _rx0b = rear_plate_rebate(half, w)[0]
        lo, hi = dx + DB_W / 2, min(bx - BATT_X / 2, _rx0b)
    return (lo, hi) if lo < hi else (hi, lo)


def power_switch_dish_w(half, w):
    """指の窪みの幅。**空きから決める**（power_switch_free_span を見ること）。"""
    lo, hi = power_switch_free_span(half, w)
    return min(SW_DISH_W, (hi - lo) - SW_DISH_EDGE * 2)


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
    """上シェル（ベゼル＋コブ天井＋スカート）。**2026-09-05・案 A。**

    合わせ目（SEAM_Z）より上の側壁・手前壁を持ち、下シェルの壁を外側から
    被る。天井も持つので、奥板のリップに押さえられて奥が浮かない（#12）。
    見せ面（ベゼル面＋コブ天井）は**一枚の 7.3° の平面**なので、裏返して
    ベッドに置いて刷る。

    断面（前縁）::

        17.50 ┬─────┐                    ベゼル上面＝手前端（実機基準）
              │     │
        10.99 │     └────────┐           プレート上面（内側はここに載る）
         9.49 │     ┌────────┘           リム（プレートを受ける 1.2 の段）
         9.00 └─────┘                    スカートの下端＝合わせ目
              ├2.4mm┤                    壁（相欠きの帯だけ 1.2）

    **数字は PLATE_TOP_FRONT から導かれる。**
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

    # 切削・保持用の立体はコンテキストの外で作る（中で作ると即座に合体される）。
    cut_above_top = tilted_cutter(w, h_body, BEZEL_TOP_FRONT)
    above_rim = tilted_cutter(w, h_body, rim)
    under_ceiling = tilted_cutter(w, h_body, BEZEL_TOP_FRONT - WALL)
    # 空洞 1: スカート SKIRT_T の内側、リム面より下（本体・コブとも。ここに
    # 下シェルの側壁の帯と中身——基板・電池・子基板——が入る。**プレートを
    # 受ける段は作らない**（受けるのは下シェル。SKIRT_T の注記）。
    # **本体とコブの境に壁を作らない**（子基板と電池箱が境をまたぐ）。
    with BuildPart() as _cav:
        with BuildSketch():
            with Locations((0, y_off)):
                RectangleRounded(w - SKIRT_T * 2, h - SKIRT_T * 2, max(CORNER_R - SKIRT_T, 0.5))
        extrude(amount=z_max)
    cav_below_rim = _cav.part - above_rim
    # 空洞 2: コブ（y > 本体の奥端）は天井の下面まで
    with BuildPart() as _cavb:
        with BuildSketch():
            with Locations((0, y_off)):
                RectangleRounded(w - SKIRT_T * 2, h - SKIRT_T * 2, max(CORNER_R - SKIRT_T, 0.5))
        extrude(amount=z_max)
        with Locations((0, h_body / 2 - 100, 0)):
            Box(w * 3, 200, z_max * 3, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    cav_bump = _cavb.part - under_ceiling
    # プレートの座ぐり: 壁 BEZEL_WALL の内側、リム面より上・プレート上面+0.1 より下。
    # プレート上面から 0.1mm 逃がす。**当たりにはしない。**公差が未確定
    # （#11）なので、押し付ける設計にすると個体差でプレートが反る。
    with BuildPart() as _inner:
        with BuildSketch():
            RectangleRounded(w - BEZEL_WALL * 2, h_body - BEZEL_WALL * 2,
                             max(CORNER_R - BEZEL_WALL, 0.5))
        extrude(amount=z_max)
    # ⚠️ **`.intersect(...)` の結果から `-` で引いてはいけない。**引き算が効かず、
    # リム面より上の材料が丸ごと消えた（2026-09-05。ベゼルの縁が全周で無くなり、
    # 利用者が .blend で「押さえられていない」と指摘。私は数字で確かめる前に
    # 「押さえている」と 2 度言った）。**引いてから intersect** の順にする。
    # ⚠️ **リム面より下まで引いてはいけない。**一度「リムより下は空洞だから
    # intersect は要らない」と書いて、リムより下に**後から足す棚**まで削った
    # （2026-09-05。test_the_plate_rear_edge_rests_on_the_case が捕まえた。
    # 棚の無い上シェルを利用者が刷り始めていた）。引いてから intersect。
    rebate = (_inner.part - tilted_cutter(w, h_body, PLATE_TOP_FRONT + 0.1)
              ).intersect(above_rim)
    # 奥端の上だけ隙間を PLATE_REAR_GAP に広げる（傾けて差し込むため）
    with BuildPart() as _rg:
        with Locations((0, h_body / 2 - BEZEL_WALL - (PLATE_SHELF_D + 2.0) / 2, 0)):
            Box(w - BEZEL_WALL * 2, PLATE_SHELF_D + 2.0, z_max,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    rear_gap = (_rg.part - tilted_cutter(w, h_body, PLATE_TOP_FRONT + PLATE_REAR_GAP)
                ).intersect(above_rim)                # 引いてから intersect（上の注記）
    # 奥の隅は下シェルの柱。天井より下のスカートをそこで止める
    with BuildPart() as _rc:
        with Locations((0, y_out - REAR_CORNER_D - CLEARANCE + 100, 0)):
            Box(w * 3, 200, z_max * 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
    rear_corner_cut = _rc.part - under_ceiling
    # 手前壁の帯（y < 手前の外面 + WALL）は下シェルが全高で持つ。上シェルは
    # リム面より下を持たない（突き合わせ。SEAM_Z の注記）
    with BuildPart() as _fc:
        with Locations((0, -h_body / 2 + WALL + CLEARANCE - 100, 0)):
            Box(w * 3, 200, z_max * 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
    front_cut = _fc.part - above_rim
    # 奥板が立つ帯（奥面から REAR_PLATE_T + CLEARANCE）は天井も無い。
    # 板が床から天井の上面まで一枚で立ち、リップで天井の奥縁に被る。
    rx0, rx1 = rear_plate_rebate(half, w)
    with BuildPart() as _pb:
        with Locations(((rx0 + rx1) / 2, y_out - REAR_PLATE_T - CLEARANCE, 0)):
            Box((rx1 - rx0) + CLEARANCE * 2, 100, z_max * 3,
                align=(Align.CENTER, Align.MIN, Align.MIN))
    plate_band_cut = _pb.part
    # リップの座ぐり（天井の奥縁を REAR_PLATE_T 削る）。桟が真下で裏打ちする。
    with BuildPart() as _lr:
        with Locations(((rx0 + rx1) / 2, y_out, 0)):
            Box((rx1 - rx0) + CLEARANCE * 2, (REAR_PLATE_LIP + CLEARANCE) * 2, z_max * 3,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    lip_rebate = _lr.part.intersect(tilted_cutter(w, h_body, BEZEL_TOP_FRONT - REAR_PLATE_T))
    # 奥の桟（奥板のネジ 2 本を受ける）。天井の下・窓の x 範囲・奥板の手前。
    wx0, _, wx1, _ = rear_window(half, w)
    rail_y0, rail_y1 = rear_rail_y(h_body)
    rail_z0 = rear_rail_z0(h_body)
    if rail_z0 < FLOOR + BATT_H + 1.0:
        raise ValueError(f"{half}: 奥の桟の下端 {rail_z0:.2f} が電池箱の上面 "
                         f"{FLOOR + BATT_H:.2f} に 1mm 以内。桟を薄くすること")
    with BuildPart() as _rail:
        with Locations(((wx0 + wx1) / 2, (rail_y0 + rail_y1) / 2, rail_z0)):
            Box((wx1 - wx0) - 1.0, REAR_RAIL_D, REAR_RAIL_H + 8.0,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    rail = _rail.part - cut_above_top
    # 奥面 3 本目のネジを受けるボス（桟と同じ高さ・奥壁の内面に接する）
    _x3, _z3 = rear_screw3(half, w, h_body)
    with BuildPart() as _b3:
        with Locations((_x3, y_out - WALL - CLEARANCE - REAR_RAIL_D / 2, rail_z0)):
            Box(REAR_SCREW3_BOSS_W, REAR_RAIL_D, REAR_RAIL_H + 8.0,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    boss3 = _b3.part - cut_above_top
    # 電源スイッチの押さえ柱（天井から溝の上 0.3mm まで）。溝は上が開いて
    # いる（落とし込むため）ので、上シェルが上への抜けを塞ぐ。
    from envelopes import SW_PWR_BODY_D, SW_PWR_H
    sw_x = power_switch_x_center(half, w)
    sw_bot = power_switch_center_z() - SW_PWR_H / 2 - CLEARANCE / 2
    holder_d = SW_PWR_BODY_D + CLEARANCE + SW_RIB
    with BuildPart() as _kp:
        with Locations((sw_x, y_out - WALL - holder_d / 2, sw_bot + SW_PWR_H + 0.3)):
            Box(SW_KEEPER, SW_KEEPER, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
    keeper = _kp.part - cut_above_top
    # プレートの奥端を受ける棚（2026-08-29 の指摘「奥端が宙吊り」）。ベゼルの
    # 奥のバーの下に、リム面から PLATE_SHELF_T の厚みで出す。XIAO の上は切り欠く。
    _sy0, _sy1 = h_body / 2 - PLATE_SHELF_D, h_body / 2
    with BuildPart() as _sh:
        with Locations((0, (_sy0 + _sy1) / 2, 0)):
            # 幅は下シェルの側壁の帯（内面 ±(w/2 − WALL)）に触れない所まで
            Box(w - WALL * 2 - CLEARANCE * 2, _sy1 - _sy0, z_max,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        _dbx = daughterboard_x_center(half, w)
        with Locations((_dbx, (_sy0 + _sy1) / 2, 0)):
            Box(XIAO_W + 6.0, (_sy1 - _sy0) + 2.0, z_max, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    shelf = (_sh.part - above_rim).intersect(tilted_cutter(w, h_body, rim - PLATE_SHELF_T))
    # LED の窓（#43）。XIAO の真上の天井を、外面から LED_WIN_SKIN だけ残して
    # 内側から薄くする。奥壁の内面より奥へは食い込ませない（#43 の注記）。
    _led_x = daughterboard_x_center(half, w) + XIAO_LED_DX
    _led_y = (y_out - WALL - DB_FROM_REAR - DB_D / 2 + XIAO_LED_DY)
    with BuildPart() as _lw:
        with Locations((_led_x, _led_y, FLOOR)):
            Cylinder(LED_WIN_D / 2, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((0, y_out - WALL + 50, 0)):
            Box(w * 2, 100, z_max * 3, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
    led_window_void = _lw.part - tilted_cutter(w, h_body, BEZEL_TOP_FRONT - LED_WIN_SKIN)
    pose = plate_placement(w, h_plate)
    blank_covers = _bottom_blank_covers(positions, keys, key_w, key_h, w, h_body, z_max, pose)
    # キーの開口。**プレートと同じ 7.3° に傾けて切る**（2026-09-05）。
    # 垂直に切ると開口の壁とキャップの面が 7.3° ずれ、手前段ではキャップが
    # 上へ行くほど縁に近づく（箱モードで 0.03mm³ 触れた。旧・隙間 0.9 でも
    # 縁との余裕は 0.18 しか無く、奥の段は逆に広すぎた）。傾けて切れば
    # 全段で隙間が BEZEL_OPENING_GAP になる（実機 §4 の 5「窪んだトレイ」）。
    with BuildPart() as _op:
        with BuildSketch():
            RectangleRounded(key_w + BEZEL_OPENING_GAP * 2,
                             key_h + BEZEL_OPENING_GAP * 2, 1.5)
        extrude(amount=100.0, both=True)
    opening_cut = pose * _op.part

    with BuildPart() as top:
        with BuildSketch():
            with Locations((0, y_off)):
                RectangleRounded(w, h, CORNER_R)
        extrude(amount=z_max)
        with Locations((0, 0, SEAM_Z)):                      # 合わせ目より下は無い
            Box(w * 3, h * 6, z_max * 3, mode=Mode.INTERSECT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        add(cav_below_rim, mode=Mode.SUBTRACT)
        add(cav_bump, mode=Mode.SUBTRACT)
        add(rear_corner_cut, mode=Mode.SUBTRACT)
        add(front_cut, mode=Mode.SUBTRACT)
        add(plate_band_cut, mode=Mode.SUBTRACT)
        add(rail, mode=Mode.ADD)
        add(boss3, mode=Mode.ADD)
        add(keeper, mode=Mode.ADD)
        add(shelf, mode=Mode.ADD)
        add(cut_above_top, mode=Mode.SUBTRACT)       # ベゼル上面で切る
        add(rebate, mode=Mode.SUBTRACT)              # プレートが入る座ぐり
        add(rear_gap, mode=Mode.SUBTRACT)
        add(lip_rebate, mode=Mode.SUBTRACT)
        add(led_window_void, mode=Mode.SUBTRACT)
        # キーの開口（プレートと同じ姿勢。上の opening_cut の注記）
        add(opening_cut, mode=Mode.SUBTRACT)
        # 最下段の無キー帯を覆う（2026-08-24・利用者の指摘。実機は最下段の
        # 左右の余白を筐体の面で覆っている）
        add(blank_covers, mode=Mode.ADD)
        # ネジ穴（手前 3 箇所）。頭は座ぐりに沈める（傾いたベゼル上面から掘る）
        for bx, by in _boss_positions(half):
            with Locations((bx, by, 0)):
                Cylinder(M2_CLEAR_D / 2, z_max * 2, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.CENTER))
            z_top = BEZEL_TOP_FRONT + (by + h_body / 2) * tan(radians(TILT_DEG))
            with Locations((bx, by, z_top - SCREW_HEAD_H - 0.4)):
                Cylinder(SCREW_HEAD_D / 2 + 0.3, z_max, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 奥板のネジ（桟へ横向きに。熱圧入インサートの下穴）
        for sx, sz in rear_screw_positions(half, w, h_body):
            with Locations((sx, rail_y1 - 2.5 + 0.01, sz)):
                Cylinder(M2_INSERT_D / 2, 5.0, rotation=(90, 0, 0), mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # 3 本目（奥壁の内面に接するボスへ）
        with Locations((_x3, y_out - WALL - CLEARANCE - 2.5 + 0.01, _z3)):
            Cylinder(M2_INSERT_D / 2, 5.0, rotation=(90, 0, 0), mode=Mode.SUBTRACT,
                     align=(Align.CENTER, Align.CENTER, Align.CENTER))
    # 手前面の傾き（FRONT_FACET_*）: 上端から FRONT_FACET_H の帯を、上端を
    # 支点に 12° 内側へ倒した平面で切る。外形は変わらない（上端が最前点）。
    y_front = -h_body / 2
    z_edge = BEZEL_TOP_FRONT
    # X 軸まわり +θ: 面の下端（局所 z<0）が +y（内側）へ倒れる。−θ にすると
    # 外へ倒れて何も切れない（2026-09-05 に実際にそうなった。z=14 で 0.0）
    part = top.part
    if FRONT_FACET_H > 0:
        wedge = (Location((0, y_front, z_edge), (FRONT_FACET_DEG, 0, 0))
                 * Box(w * 3, 20.0, FRONT_FACET_H * 3,
                       align=(Align.CENTER, Align.MAX, Align.CENTER)))
        # 帯の下端より下は切らない（垂直のまま）
        with BuildPart() as _fw:
            add(wedge)
            with Locations((0, 0, z_edge - FRONT_FACET_H)):
                Box(w * 3, 200, 100, mode=Mode.INTERSECT,
                    align=(Align.CENTER, Align.CENTER, Align.MIN))
        part = part - _fw.part
    # 上端の縁を丸める（手前だけ。左右はカーネルが拒否する）
    bb = part.bounding_box()
    front_edges = [e for e in part.edges()
                   if e.center().Z > z_edge - 1.0 and e.center().Y < bb.min.Y + 2.0
                   and e.length > 20.0]
    if FRONT_EDGE_R > 0:
        if not front_edges:
            raise ValueError("手前の上縁が見つからない（丸める対象が無い）")
        _before = part.bounding_box()
        part = part.fillet(FRONT_EDGE_R, front_edges)
        _after = part.bounding_box()
        # **フィレットは失敗を黙る。**外形（丸めた辺以外）が動いたら止める
        if abs(_after.max.Z - _before.max.Z) > 1e-3 or abs(_after.max.Y - _before.max.Y) > 1e-3:
            raise ValueError("手前の丸めで奥の形が変わった（カーネルが面を失った）")
    return part, (w, h_body)


def rear_window(half, w):
    """奥の窓 (x0, z0, x1, z1)。電池箱の断面＋逃げ。**上は天井まで開ける**
    （z1 は「上限は無い」の意味の大きな値。奥板が塞ぐ）。

    **ケース・奥板・検査がこの 1 つから取る。**
    """
    bx = battery_x_center(half, w)
    x0 = max(bx - BATT_X / 2 - REAR_PLATE_CLR, -(w / 2 - WALL))
    x1 = min(bx + BATT_X / 2 + REAR_PLATE_CLR, w / 2 - WALL)
    return x0, FLOOR, x1, 1e3


def rear_plate_rebate(half, w):
    """奥板が沈む座ぐりの x 範囲 (x0, x1)。外皮を 1.0 は残す。"""
    x0, _, x1, _ = rear_window(half, w)
    return (max(x0 - REAR_PLATE_FRAME, -(w / 2 - 1.0)),
            min(x1 + REAR_PLATE_FRAME, w / 2 - 1.0))


def rear_groove_y(h_body):
    """奥板の足が入る床の溝の中心 y。板の内面から CLEARANCE 空けた所。"""
    y_out = h_body / 2 + BUMP_DEPTH
    return y_out - REAR_PLATE_T - CLEARANCE - REAR_GROOVE_W / 2


def rear_rail_y(h_body):
    """上シェルの奥の桟の y 範囲 (手前, 奥)。奥板の手前に CLEARANCE 空ける。"""
    y_out = h_body / 2 + BUMP_DEPTH
    y1 = y_out - REAR_PLATE_T - CLEARANCE
    return y1 - REAR_RAIL_D, y1


def rear_rail_z0(h_body):
    """桟の下端 z。天井の下面（桟の手前端での高さ）から REAR_RAIL_H 下。"""
    y0, _ = rear_rail_y(h_body)
    z_under = (BEZEL_TOP_FRONT - WALL) + (y0 + h_body / 2) * tan(radians(TILT_DEG))
    return z_under - REAR_RAIL_H


def rear_screw_positions(half, w, h_body):
    """奥板のネジ 2 本 (x, z)。桟の中心高さ、電池箱中心 ± REAR_SCREW_DX。"""
    bx = battery_x_center(half, w)
    z = rear_rail_z0(h_body) + REAR_RAIL_H / 2
    return [(bx - REAR_SCREW_DX, z), (bx + REAR_SCREW_DX, z)]


def rear_screw3(half, w, h_body):
    """奥面 3 本目のネジ (x, z)。子基板の中心から電池側へ REAR_SCREW3_DX、
    高さは桟と同じ（天井の下 REAR_RAIL_H の中心）。"""
    x = daughterboard_x_center(half, w) - inner_sign(half) * REAR_SCREW3_DX
    return x, rear_rail_z0(h_body) + REAR_RAIL_H / 2


def battery_hole_xs(half, w):
    """電池箱の取付穴 2 個の x。黒線側の端を外壁側と仮定（現物で確認。
    値の出所は BATT_HOLE_X1/X2_FROM_END）。"""
    bx = battery_x_center(half, w)
    sign = 1 if half == "left" else -1
    x_end = bx - sign * BATT_X / 2
    return [x_end + sign * d for d in (BATT_HOLE_X1_FROM_END, BATT_HOLE_X2_FROM_END)]


def build_rear_plate(half, keys):
    """奥板（電池窓を塞ぐ板。2026-09-05・案 A。旧・スライド式の電池蓋の代わり）。

    **ケース座標のまま作る**（旧・蓋で回して 5 回取り違えた教訓）。
      板   … 床の上面から天井の上面まで一枚。奥壁の座ぐりに面一で沈む
      リップ … 上縁が REAR_PLATE_LIP だけ手前へ折れ、天井の奥縁に被る
              ＝上シェルを押さえる（#12 の奥の留め）
      足   … 下端が内側へ L 字に出て、床の溝へ REAR_TONGUE_H 落ちる
      ネジ … M2×2 を上シェルの桟へ。板を桟へ引き付け、足が下シェルへ
              繋ぐので、上シェルの奥が下シェルへ留まる
    外し方: ネジ 2 本を外す → 板を 1.2 持ち上げる → 奥へ引く。
    """
    _positions, (w, h_plate) = plate_positions(keys)
    h_body = plan_depth(h_plate)
    y_out = h_body / 2 + BUMP_DEPTH
    wx0, _wz0, wx1, _ = rear_window(half, w)
    rx0, rx1 = rear_plate_rebate(half, w)
    px0, px1 = rx0 + CLEARANCE / 2, rx1 - CLEARANCE / 2
    cx = (px0 + px1) / 2
    z_top_out = BEZEL_TOP_FRONT + (h_body + BUMP_DEPTH) * tan(radians(TILT_DEG))
    cut_above_top = tilted_cutter(w, h_body, BEZEL_TOP_FRONT)
    with BuildPart() as _lip:
        with Locations((cx, y_out - REAR_PLATE_LIP / 2, FLOOR)):
            Box(px1 - px0, REAR_PLATE_LIP, z_top_out + 5,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    lip = _lip.part.intersect(tilted_cutter(w, h_body, BEZEL_TOP_FRONT - REAR_PLATE_T))
    gy = rear_groove_y(h_body)
    with BuildPart() as p:
        with Locations((cx, y_out - REAR_PLATE_T / 2, FLOOR)):
            Box(px1 - px0, REAR_PLATE_T, z_top_out + 5,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        add(lip, mode=Mode.ADD)
        add(cut_above_top, mode=Mode.SUBTRACT)
        # 足: 板の内面から溝の上まで水平に、そこから溝へ下りる
        _fx0, _fx1 = wx0 + 1.0 + CLEARANCE / 2, wx1 - 1.0 - CLEARANCE / 2
        _fy0 = gy - REAR_TONGUE_T / 2
        with Locations(((_fx0 + _fx1) / 2, (_fy0 + (y_out - REAR_PLATE_T + 0.1)) / 2, FLOOR)):
            Box(_fx1 - _fx0, (y_out - REAR_PLATE_T + 0.1) - _fy0, REAR_TONGUE_T,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations(((_fx0 + _fx1) / 2, gy, FLOOR - REAR_TONGUE_H)):
            Box(_fx1 - _fx0, REAR_TONGUE_T, REAR_TONGUE_H + 0.1,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # ネジのバカ穴
        for sx, sz in rear_screw_positions(half, w, h_body):
            with Locations((sx, y_out - REAR_PLATE_T / 2, sz)):
                Cylinder(M2_CLEAR_D / 2, REAR_PLATE_T * 3, rotation=(90, 0, 0),
                         mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.CENTER))
    b = p.part.bounding_box()
    if abs(b.max.Y - y_out) > 1e-6:
        raise ValueError(f"奥板の外面が y={b.max.Y:.2f}。奥面 {y_out:.2f} と一致しない")
    if abs(b.min.Z - (FLOOR - REAR_TONGUE_H)) > 1e-6:
        raise ValueError(f"足の先が z={b.min.Z:.2f}。溝の底 {FLOOR - REAR_TONGUE_H:.2f} に届かない")
    if len(p.part.solids()) != 1:
        raise ValueError(f"奥板が {len(p.part.solids())} 個に分かれている")
    return p.part, (px1 - px0, z_top_out - FLOOR)


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
        rp, (rw, rh) = build_rear_plate(name, keys)
        rmesh, rstl = to_mesh(rp, f"rear_plate_{name}")
        written.append(rstl.name)
        assert_watertight(rmesh, rstl.name)
        print(f"      奥板 {rw:.2f} x {rh:.2f}mm -> {rstl.name}")
        render_outline_2d(part, BUILD / f"case_{name}_section.png", axis="X",
                          title=f"case {name} - side section", annotate_count=False)
        bb = part.bounding_box()
        print(f"{name:5s} 設計値 {w:6.2f} x {h:6.2f}mm  "
              f"プレート上面 前 {z_front:.1f} / 奥 {z_rear:.1f}mm  傾斜 {TILT_DEG}°")
        print(f"      実測値 {bb.size.X:6.2f} x {bb.size.Y:6.2f} x {bb.size.Z:6.2f}mm  "
              f"水密={mesh.is_watertight}")
        # 奥行はコブぶん長い（実機も本体 108 ＋ コブ 12 ＝ 120mm）
        assert abs(bb.size.X - w) < 0.01, "幅が設計値と違う"
        assert abs(bb.size.Y - (h + BUMP_DEPTH)) < 0.01, "奥行が設計値と違う"
        # 最も高いのはコブの後端の奥壁の上端＝天井（上シェル）の下面 − CLEARANCE
        z_top = (BEZEL_TOP_FRONT + (h + BUMP_DEPTH) * tan(radians(TILT_DEG))
                 - WALL - CLEARANCE)
        assert abs(bb.size.Z - z_top) < 0.05, f"高さが設計値と違う（{bb.size.Z:.2f} vs {z_top:.2f}）"
        tb = topc.bounding_box()
        assert abs(tb.min.Z - SEAM_Z) < 0.05, f"上シェルの下端が合わせ目 {SEAM_Z} でない（{tb.min.Z:.2f}）"

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
