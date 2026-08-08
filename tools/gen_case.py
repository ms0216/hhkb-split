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
from gen_plate import build_plate, halves, plate_positions  # noqa: E402
from interface import (  # noqa: E402
    BEZEL_OPENING_GAP,
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
OUR_CAPS = {
    "bottom": 7.6,
    "ZXCV": 7.6,
    "home": 7.6,
    "QWERTY": 7.6,
    "number": 7.6,
}
CAP_H_HOME = OUR_CAPS["home"]   # [暫定] ケースの高さはホーム段だけで決まる
_Y_HOME = 6.375 + 2.5 * 19.05          # ホーム段のキー中心（手前から）
PLATE_TOP_FRONT = round(
    TARGET_KEYTOP_HOME - CAP_LIFT - CAP_H_HOME - _Y_HOME * tan(radians(TILT_DEG)), 2)

# --------------------------------------------------------------------------
# 3Dプリント（K1 Max / PLA / ノズル 0.4mm）に合わせた値
# --------------------------------------------------------------------------
WALL = 2.4               # 側壁。0.4mm の 6 倍
FLOOR = 2.4              # 底板。0.4mm の 6 倍。
                         # 当初 2.0mm にしていたが、蓋(1.6mm)をレールに落とし込むと
                         # 床の内面より上に出て電池に食い込んだため厚くした。
CLEARANCE = 0.2          # 収縮を見込んだ嵌合の逃げ

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
BATT_H = AA_D + 1.0              # 占有高さ
BATT_W = AA_D + 1.0              # 占有奥行（左右に寝かせるので 1 本ぶん）
BATT_X = AA_L * 2 + 8.0          # 占有幅（2 本直列＋電極）
BATT_MARGIN_REAR = 2.0           # 電池と後壁の間隔
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
BUMP_DEPTH = 18.0                # 実機は 12mm。MX ＋ ソケットが Topre より
                                 # 5mm 厚いぶん、6mm 深くなる。12/14/16 では
                                 # 電池が基板に食い込むことを検査で確認した

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
DB_W = 21.0              # 子基板の幅（左右）。XIAO は 17.8mm 幅。
                         # 20.0 では FFC コネクタと取付穴が入らなかった。
                         # 22.0 でも電池からは 10.2mm 離れ、条件を満たす
# **2.4GHz のアンテナから金属を遠ざける距離。**
#
# XIAO のアンテナは USB と反対の端にある。単3 電池は金属の塊で、至近距離に
# あるとアンテナを大きく狂わせる。左右間の BLE 接続はこのキーボードの
# 中核要件なので、その通信距離を自分で潰してはいけない。
#
# 一度 1.0mm まで寄せていた（電池を外へ寄せて子基板の場所を作った副作用）。
# 幾何の干渉だけを見て電波を見ていなかった。
DB_ANTENNA_KEEPOUT = 10.0
# 奥行 30mm。**XIAO とネジを同時に載せるには、この深さが要る。**
#
# 22mm では取付穴の置ける場所が 0 箇所だった。XIAO は 17.8x21mm で、
# ネジの逃げ（φ2.4＋ランド → 半径 2.2mm）が入る余地が残らない。
#   ネジを XIAO の脇に置く  → 幅 26.6mm 必要（使える幅は 22.2mm。不可）
#   ネジを XIAO の前後に置く → 奥行 29.8mm 必要
# コブの奥の内面 y=69.16 から 30mm 前は y=39.16。そこでの本体基板の
# 下端は 13.97mm で、子基板スタック 12.0mm に対して余裕がある。
DB_D = 32.0
DB_T = 1.6
DB_BOSS_H = 4.0          # 床からの高さ。これが USB-C の高さを決める
# 取付ボスは**対角に 2 本**。XIAO のパッド列（x=±7.62）と本体を避けると
# ここしか残らない。中心線上に 2 本だと回ってしまうので対角にする。
DB_BOSS_POS = [(-8.0, -13.5), (8.0, 13.5)]
DB_FROM_REAR = 1.0       # 奥の壁の内側と子基板の隙間
USB_W = 10.0             # 奥の壁の切り欠き（USB-C プラグの外形）
USB_H = 6.0
USB_Z_ABOVE_PCB = 1.6    # 子基板の上面から USB-C コネクタの中心まで

# 電源スイッチ（C&K OS102011MA1QN1・右アングル）。**基板には載らない。**
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
SW_RIB = 1.6             # スイッチを受ける箱の壁厚（印刷できる最小側）
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

from envelopes import (PCB_T, PLATE_TO_PCB, SOCKET_DROP,  # noqa: E402
                       SW_PWR_D, SW_PWR_H, SW_PWR_W)


# --------------------------------------------------------------------------
# 電池蓋（底面のスライド蓋）
#
# 実機と同じく底面から電池を出し入れする。蓋は奥へスライドして抜ける。
# レールは 1.2mm の段。K1 Max ならサポート無しでブリッジできる。
# --------------------------------------------------------------------------
LID_T = 1.6              # 蓋の厚み（0.4mm の 4 倍）
RAIL_W = 2.0             # レールの掛かり幅
RAIL_H = LID_T           # 段の深さ＝蓋の厚み。こうすると蓋が床の内面と面一になる。
                         # 段を蓋より浅くすると蓋が内側へ出っ張り、電池と干渉する
                         # （組み立て検査で 233mm^3 の食い込みとして検出された）。
LID_STOP = 2.0           # 手前側のストッパー

# --------------------------------------------------------------------------
# チルト脚
#
# 実機はヒンジ式の折りたたみ脚が 2 組。3Dプリントでヒンジを作ると壊れやすいので、
# 高さの違う差し込み脚を 2 組用意して 0° / 3° / 6° を作る。機能は同じ。
# 脚は前縁を支点に後縁を持ち上げるので、必要な高さは支点からの距離で決まる。
# --------------------------------------------------------------------------
FOOT_INSET_REAR = 10.0   # 後縁から脚中心までの距離
FOOT_D = 12.0            # 脚の直径
FOOT_PEG_D = 4.0         # 差し込みピンの径
FOOT_PEG_H = 4.0
# 脚は**後ろの隅**に差し、そこが設置点になる。実機の折りたたみ脚と同じ役割。
# 0° 用の短い脚も作るので、脚は常に 2 個使う（外すのではなく差し替える）。
# 当初は脚を内側に置き、電池室と蓋の中にボスが立っていた。
TILT_STEPS = [0.0, 3.0, 6.0]
FOOT_BASE_H = 2.0        # 0° の脚の高さ。前側のゴム足と同じ厚み

# --------------------------------------------------------------------------
# 三脚ネジ穴（テンティング用。普段は使わない）
# 1/4-20 の六角ナットを埋め込む。二面幅 11.1mm / 厚み 5.5mm
# --------------------------------------------------------------------------
NUT_AF = 11.1 + 0.3      # 二面幅＋逃げ
NUT_T = 5.5 + 0.2
NUT_BOSS_D = 18.0
NUT_BOSS_H = 9.0
NUT_THRU_D = 7.0

# ゴム足（市販 Φ10 × 厚 2mm を想定）
RUBBER_D = 10.0
RUBBER_RECESS = 0.6      # 座ぐりの深さ
RUBBER_INSET = 12.0      # 縁からの距離


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
    cutter_bump = tilted_cutter(w, h_body, BEZEL_TOP_FRONT)
    # ボスの頭を止める面（基板の下面）。これも**必ず**コンテキストの外で作る。
    # 中で作ると即座に部品へ合体され、外形が 538x614mm に膨れる（実際にやった）。
    cutter_pcb = tilted_cutter(w, h_body, rim_front - PLATE_TO_PCB - PCB_T)
    # ボスも外で作って外で切る。基板はボスの上に載り、ネジはプレート→基板→
    # ボスの順に通るので、ボスの頭は基板の下面で止める。
    with BuildPart() as _b:
        for bx, by in _boss_positions(half):
            with Locations((bx, by, FLOOR)):
                Cylinder(M2_BOSS_D / 2, z_max,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
    # **ボスの頭はプレートの下面（リム）で止める。**
    # 以前は基板の下面で止めていた（基板をボスに載せる設計だったため）。
    # 上ケース方式ではネジは上ケースから入り、プレートはボスの上に載る。
    bosses = _b.part - cutter
    # コブの天井（傾いた板）。コンテキストの外で作る。
    with BuildPart() as _bl:
        with Locations((0, h_body / 2 + BUMP_DEPTH / 2, 0)):
            Box(w - WALL * 2, BUMP_DEPTH, z_max * 2,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
    bump_lid = ((_bl.part - tilted_cutter(w, h_body, BEZEL_TOP_FRONT))
                .intersect(tilted_cutter(w, h_body, BEZEL_TOP_FRONT - WALL)))
    # 電池室の仕切り壁。**基板の下面（ソケットの先端）で頭を切る。**
    #
    # 電池を前へ動かしたぶん仕切りも前へ来る。前ほど打鍵面が低いので、
    # BATT_H いっぱいに立てると傾いた基板を突き上げる（186mm^3 の食い込みとして
    # 組み立て検査が検出）。ボスと同じく、コンテキストの外で作って外で切る。
    cutter_under_pcb = tilted_cutter(
        w, h_body, rim_front - PLATE_TO_PCB - PCB_T - SOCKET_DROP)
    y_div = (battery_center(h_body) - BATT_W / 2 - WALL / 2 - CLEARANCE)
    with BuildPart() as _d:
        with Locations((battery_x_center(half, w), y_div, FLOOR)):
            Box(BATT_X, WALL, BATT_H,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    divider = _d.part - cutter_under_pcb
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

        # 3-2. **コブに天井を張る。**
        #
        # 内側のくり抜きは奥まで通しているので、コブが上に開いたままだった
        # （電池が上から露出する）。本体側はプレートと上ケースが覆うが、
        # コブの上には何も載らないので、ケース自身が塞ぐ必要がある。
        # 「メッシュが水密」は「箱として閉じている」を意味しない。
        add(bump_lid, mode=Mode.ADD)

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
        # 奥の壁を貫く。壁の厚みより長い立体で切らないと薄皮が残る。
        with Locations((db_x, y_rear_outer, usb_center_z())):
            Box(USB_W, WALL * 4, USB_H, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))

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
        # 順序: 箱を足す → スイッチの空所を抜く → 操作部のスロットを貫く。
        sw_x = power_switch_x_center(half, w)
        sw_z = power_switch_center_z()
        y_rear_inner = y_rear_outer - WALL
        holder_d = SW_PWR_D + SW_RIB          # 奥側にも壁を残す
        with Locations((sw_x, y_rear_inner - holder_d / 2, sw_z)):
            Box(SW_PWR_W + CLEARANCE + SW_RIB * 2, holder_d,
                SW_PWR_H + CLEARANCE + SW_RIB * 2,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # 中身を抜く。**内側（手前）は開けたまま**にして、そこから挿す。
        with Locations((sw_x, y_rear_inner - SW_PWR_D / 2, sw_z)):
            Box(SW_PWR_W + CLEARANCE, SW_PWR_D + SW_RIB, SW_PWR_H + CLEARANCE,
                mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
        with Locations((sw_x, y_rear_outer, sw_z)):
            Box(SW_SLOT_W, WALL * 4, SW_SLOT_LEN,
                mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))



        ox, oy, ow, oh = _lid_opening(half, w, h_body)
        # 6-1. 貫通させるのは狭い方（両側に RAIL_W の段を残す）
        with Locations((ox, oy, 0)):
            Box(ow - RAIL_W * 2, oh, FLOOR * 3, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # 6-2. 蓋が落ち込む座ぐりは広い方。床の上側 RAIL_H だけ削る
        with Locations((ox, oy, FLOOR - RAIL_H)):
            Box(ow, oh, RAIL_H, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 6-3. 手前側のストッパー（蓋は奥へ抜ける）
        with Locations((ox, oy - oh / 2 + LID_STOP / 2, FLOOR - RAIL_H)):
            Box(ow, LID_STOP, RAIL_H, align=(Align.CENTER, Align.CENTER, Align.MIN))

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
        with BuildSketch(Plane.XY):
            RegularPolygon(NUT_AF / 2 / __import__("math").cos(radians(30)), 6)
        extrude(amount=NUT_T, mode=Mode.SUBTRACT)

        # 8. ゴム足の座ぐりと、チルト脚の差し込み穴（いずれも底面）
        for fx, fy in _rubber_positions(w, h_body):
            with Locations((fx, fy, 0)):
                Cylinder(RUBBER_D / 2, RUBBER_RECESS, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        # ピン穴は床(2.0mm)より深い(4.0mm)ので、そのまま開けると内部へ貫通する。
        # メッシュの種数が 4 になって発覚した。内側にボスを立てて盲穴にする。
        for fx, fy in _foot_positions(w, h_body):
            with Locations((fx, fy, 0)):
                Cylinder(FOOT_PEG_D / 2 + 2.0, FOOT_PEG_H + 1.6,
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

    return case.part, (w, h_body), (z_front, z_rear)


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


def inner_sign(half):
    """分割の**内縁**（相手側の半分に面する側）が +X か −X か。

    左半分は右端が内縁、右半分は左端が内縁。
    """
    return 1.0 if half == "left" else -1.0


def battery_x_center(half, w):
    """電池室の中心 X。**外側へ寄せる。**

    奥の壁ぎわの中央に置くと、子基板の場所が無くなる。外へ寄せれば
    内縁側に 24mm（左）/ 56mm（右）空き、そこへ子基板が入る。
    ケースの外形も電池の向きも変えずに済むのが、この寄せ方の利点。
    """
    return -inner_sign(half) * ((w / 2 - WALL) - BATT_X / 2 - CLEARANCE)


def daughterboard_x_center(half, w):
    """子基板の中心 X。電池の内側端と、奥のネジボスの間に置く。

    **奥のネジボスに当たらないこと**が効く制約。左半分では使える幅が
    24.1mm しかなく、子基板 24.0mm でほぼ一杯になる。
    """
    s = inner_sign(half)
    # 電池の**内縁側の端**。中心の絶対値に足すと外縁側の端になる（一度間違えた）。
    lo = abs(battery_x_center(half, w) + s * BATT_X / 2) + CLEARANCE
    # **本体のネジボスは制約にならない。** 子基板はコブの中にあり、
    # ボスは本体側（コブより手前）に立っているため。以前これを制約に
    # 入れていたせいで、子基板を電池側へ寄せざるをえず、アンテナが
    # 電池から 1.0mm の位置になっていた。
    # 壁から 0.8mm 離す。0.2mm では内側の角丸（R0.6）に当たり、組み立て検査が
    # 68mm^3 の食い込みを出した。1.5mm だと子基板を内側へ寄せきれず、
    # アンテナと電池の距離が 8.9mm（要 10mm）に落ちた。
    hi = w / 2 - WALL - 0.8
    if hi - lo < DB_W:
        raise RuntimeError(
            f"{half}: 子基板の場所が {hi - lo:.1f}mm しかない（{DB_W}mm 必要）")
    # **電池から最も遠い位置（＝内側の壁ぎわ）に寄せる。**アンテナのため。
    return s * (hi - DB_W / 2)


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
    return (lo + hi) / 2


def power_switch_center_z():
    """電源スイッチの中心高さ。電池の中心に合わせる。

    コブの中で電池と同じ高さ帯に置けば、上下に余裕が残る。
    """
    from envelopes import AA_D
    return FLOOR + AA_D / 2


def usb_center_z():
    """奥の壁に開ける USB-C 切り欠きの中心高さ。

    子基板の載る高さから導く。数値を直接書くと、ボスの高さを変えたときに
    穴だけ取り残される。
    """
    return FLOOR + DB_BOSS_H + DB_T + USB_Z_ABOVE_PCB


def _lid_opening(half, w, h_body):
    """電池蓋の開口（中心 x, y と 大きさ）。電池室の真下に開ける。

    y は**本体部分の中心を原点**とした座標。
    x は電池を外側へ寄せたぶんだけずれる。
    """
    return (battery_x_center(half, w), battery_center(h_body), BATT_X, BATT_W)


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


def build_topcase(keys, half):
    """上ケース（ベゼル）。キーの周りに立つ枠。

    **これが手前端 17mm と「ネジがキー領域に無いこと」を同時に成立させる。**
    経緯は docs/hardware/decisions/2026-08-07-top-case.md。

    断面（前縁）::

        17.50 ┬─────┐                    ベゼル上面
              │     │
        11.78 │     └────────┐           プレート上面（内側はここに載る）
        10.28 └──────────────┘           リム（下ケースの壁の上）
              ├1.6mm┤                    上ケースの壁
    """
    positions, (w, h_plate) = plate_positions(keys)
    h_body = plan_depth(h_plate)
    key_w = w - PLATE_MARGIN_X * 2
    key_h = h_body - PLATE_MARGIN_Y * 2
    rim = PLATE_TOP_FRONT - PLATE_T
    z_max = BEZEL_TOP_FRONT + h_body * tan(radians(TILT_DEG)) + 5.0

    # 切削・保持用の立体はコンテキストの外で作る（中で作ると即座に合体される）。
    keep_above_rim = tilted_cutter(w, h_body, rim)
    cut_above_top = tilted_cutter(w, h_body, BEZEL_TOP_FRONT)
    # 内側の座ぐり: 壁より内で、プレート上面より下を削る
    with BuildPart() as _inner:
        with BuildSketch():
            RectangleRounded(w - BEZEL_WALL * 2, h_body - BEZEL_WALL * 2,
                             max(CORNER_R - BEZEL_WALL, 0.5))
        extrude(amount=z_max)
    # プレート上面から 0.1mm 逃がす。**当たりにはしない。**
    # 3Dプリントの公差が未確定（docs/hardware/open-gaps.md #11）なので、
    # 押し付ける設計にすると個体差でプレートが反る。薄いガスケットで詰める。
    rebate = _inner.part - tilted_cutter(w, h_body, PLATE_TOP_FRONT + 0.1)

    with BuildPart() as top:
        with BuildSketch():
            RectangleRounded(w, h_body, CORNER_R)
        extrude(amount=z_max)
        add(keep_above_rim, mode=Mode.INTERSECT)     # リムより下を落とす
        add(cut_above_top, mode=Mode.SUBTRACT)       # ベゼル上面で切る
        add(rebate, mode=Mode.SUBTRACT)              # プレートが入る座ぐり
        # キーの開口
        with BuildSketch():
            RectangleRounded(key_w + BEZEL_OPENING_GAP * 2,
                             key_h + BEZEL_OPENING_GAP * 2, 1.5)
        extrude(amount=z_max, mode=Mode.SUBTRACT)
        with BuildSketch(Plane.XY.offset(-z_max)):
            RectangleRounded(key_w + BEZEL_OPENING_GAP * 2,
                             key_h + BEZEL_OPENING_GAP * 2, 1.5)
        extrude(amount=z_max, mode=Mode.SUBTRACT)
        # ネジ穴（手前 3 箇所）。頭は座ぐりに沈める。
        for bx, by in _boss_positions(half):
            with Locations((bx, by, 0)):
                Cylinder(M2_CLEAR_D / 2, z_max * 2, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.CENTER))
    return top.part, (w, h_body)


def build_battery_lid(half, keys):
    """電池蓋。ケースのレールに差し込んで奥へスライドさせる。

    開口の位置と大きさはケース側の造作なので、平面図の奥行で計算する。
    プレートの平らな奥行を渡すと 0.42mm ずれる。
    """
    _, (w, h_plate) = plate_positions(keys)
    _, _, ow, oh = _lid_opening(half, w, plan_depth(h_plate))
    lw = ow - CLEARANCE                      # 開口より少し小さく
    lh = oh - LID_STOP - CLEARANCE
    with BuildPart() as lid:
        with BuildSketch():
            RectangleRounded(lw, lh, 1.5)
        extrude(amount=LID_T)
        # 指掛かりの窪み。切削用の立体は上面より外へ突き出させる。
        # 上面とちょうど同一平面にすると境界が縮退し、水密でないメッシュになる。
        with Locations((0, -lh / 2 + 6.5, LID_T + 1.0)):
            Cylinder(4.0, 1.8, mode=Mode.SUBTRACT,
                     align=(Align.CENTER, Align.CENTER, Align.MAX))
    return lid.part, (lw, lh)


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
    from verify import BUILD, assert_watertight, render_outline_2d, to_mesh

    BUILD.mkdir(exist_ok=True)
    for name, keys in halves().items():
        part, (w, h), (z_front, z_rear) = build_case(keys, name)
        mesh, stl = to_mesh(part, f"case_{name}")
        assert_watertight(mesh, stl.name)

        lid, (lw, lh) = build_battery_lid(name, keys)
        lmesh, lstl = to_mesh(lid, f"battery_lid_{name}")
        assert_watertight(lmesh, lstl.name)
        print(f"      電池蓋 {lw:.1f} x {lh:.1f} x {LID_T}mm -> {lstl.name}")

        for deg in TILT_STEPS:
            foot, fz = build_tilt_foot(deg, h)
            fmesh, fstl = to_mesh(foot, f"tilt_foot_{int(deg)}deg_{name}")
            assert_watertight(fmesh, fstl.name)
            print(f"      チルト脚 +{deg:.0f}° 高さ {fz:.2f}mm -> {fstl.name}")
        # 上ケース（ベゼル）
        topc, (tw, th) = build_topcase(keys, name)
        tmesh, tstl = to_mesh(topc, f"topcase_{name}")
        assert_watertight(tmesh, tstl.name)
        print(f"      上ケース {tw:.2f} x {th:.2f} x "
              f"{topc.bounding_box().size.Z:.2f}mm -> {tstl.name}")
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
        # 最も高いのはコブの後端（ベゼル上面）
        z_top = BEZEL_TOP_FRONT + (h + BUMP_DEPTH) * tan(radians(TILT_DEG))
        assert abs(bb.size.Z - z_top) < 0.05, f"高さが設計値と違う（{bb.size.Z:.2f} vs {z_top:.2f}）"
    return 0


if __name__ == "__main__":
    sys.exit(main())
