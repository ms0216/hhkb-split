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
# [記録のみ] ソケットの範囲は bands.py（SOCK_X_LO..HI / SOCK_LO..HI）に一本化
# したので、この値はもう読まれていない。**両方に書いて食い違った前科がある。**
SOCKET_INSET = 7.0       # ソケットが存在する範囲。基板の全面ではなく
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
# [記録のみ] **この 3 つはどこからも読まれていない。**ケースに効くのは
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


_BOARD_KEY = {"left": "left", "right": "right"}


def pcb_envelope(w, h_plate, half, keys):
    """基板（板だけ）が占有する空間（プレート座標系、原点は板の中心）。

    基板はプレートと平行に、その下へ入る。取付ネジの位置には穴が要る
    （ケースのボスが貫くため）。

    **ソケットは socket_envelope に分けた**（open-gaps #29）。ソケットは
    実物（Kailh の部品）であって板の一部ではないし、箱は保守的に太らせて
    あるので、実体のダイオードとの重なりを板と区別して扱う必要がある。
    """
    # **外形は実基板から取る。**以前は「プレートの外形 − PCB_INSET」で
    # 概算していたが、実基板より奥行が 4.6mm・手前側で 2.3mm 大きく、
    # ネジボスやケースと重なって見えていた（許容値でごまかしていた）。
    # 基板が設計済みになった今、概算を持つ理由は無い。
    # **記録（pcb_parts.json）から読むので KiCad は要らない。**
    import pcb_parts

    x0, y0, _z0, x1, y1, _z1 = pcb_parts.load()[_BOARD_KEY[half]]["board_bbox"]
    with BuildPart() as env:
        with BuildSketch():
            with Locations(((x0 + x1) / 2, (y0 + y1) / 2)):
                RectangleRounded(x1 - x0, y1 - y0, CORNER_R)
            with Locations(*boss_positions(half)):
                Circle(M2_CLEAR_D / 2, mode=Mode.SUBTRACT)
        extrude(amount=-PCB_T)
    return env.part


def socket_envelope(half):
    """Kailh ホットスワップソケットが基板の裏に占める空間（プレート座標系）。

    **平面の形は実物のモデルから、深さだけ保守的に取る。**
    以前は平面も「フットプリント＋はんだ余裕」で太らせていて、隣に載る
    実物のダイオードと 110〜139mm^3 重なって見えていた（許容値でごまかして
    いた）。**実物の形が手に入った今、太らせる理由は平面には無い。**

    深さ（SOCKET_DROP）だけは実測待ちのまま保守側に残す。ケースの床や
    電池との取り合いを決めるのはこの深さで、確定するのは現物のノギス。
    データシート（PG151101S11: 板下 1.80）とモデル（端子込み 2.01）には
    一致を確認済みで、3.2 はそれより 1.19mm 深い。

    **記録（pcb_parts.json）から読むので KiCad は要らない。**
    """
    import pcb_parts

    boxes = (pcb_parts.keyswitch_boxes(half, "kailh_socket")
             + pcb_parts.keyswitch_boxes(half, "kailh_socket_leg"))
    with BuildPart() as env:
        with BuildSketch(Plane.XY.offset(-PCB_T)):
            for x0, y0, _z0, x1, y1, _z1 in boxes:
                with Locations(((x0 + x1) / 2, (y0 + y1) / 2)):
                    Rectangle(x1 - x0, y1 - y0)
        extrude(amount=-SOCKET_DROP)
    return env.part


def place_pcb(env, h_plate, rim_front):
    """基板の占有空間を、傾いたプレートの下へ置く。

    **持ち上げ量は平面図の奥行で決める。**平らな奥行（108）で決めると、
    ケース側の造作（tilted_cutter は平面図の奥行 107.12 を使う）と
    0.056mm ずれる。**この案件で 4 回目の「平ら／平面図」の取り違え**
    （電池蓋 0.42mm、プレートの覆い、プレートの座ぐり、そしてここ）。
    ずれは小さいが、三脚ナットの座がソケットへ 0.54mm^3 食い込む形で出た。
    """
    mid_z = rim_front + (h_plate / 2) * tan(radians(TILT_DEG))
    return (Location((0, 0, mid_z), (TILT_DEG, 0, 0))
            * Location((0, 0, -PLATE_TO_PCB)) * env)


def under_pcb_base(h_plate, rim_front, drop):
    """**place_pcb で置いた基板の「下から drop の面」**を、tilted_cutter に
    渡すための base（前縁での高さ）。

    ケース側は「rim_front − drop」で切っていたが、**基板は傾いた面に対して
    垂直に drop だけ下がる**ので、実際の面はさらに drop×(1/cos−1) 低い。
    さらに平らな奥行と平面図の奥行の取り違えが重なり、両者は 0.068mm
    ずれていた。三脚ナットの座がソケットへ食い込む形で出た（2026-08-10）。
    **切る面は、置き方から導く。**別々に計算しない。
    """
    from math import cos
    from interface import plan_depth

    t = radians(TILT_DEG)
    mid_z = rim_front + (h_plate / 2) * tan(t)
    return mid_z - (plan_depth(h_plate) / 2) * tan(t) - drop / cos(t)


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

# 利用者が挿す USB-C ケーブルの、**オス側プラグの樹脂の胴体**（open-gaps #28）。
#
# **金属のシェル（8.34 x 2.56mm・規格値）ではない。**壁の穴を通るかどうかを
# 決めるのはこの樹脂で、金属ではない。ここを取り違えていて、
# 「開口 10 x 6mm で足りる」としていた。
#
# 利用者が手持ちのケーブル数本を測った**最大値**（分解能 1mm の器具・2026-08-09）。
USB_PLUG_W = 12.0        # [暫定] 実測（幅）
USB_PLUG_H = 7.0         # [暫定] 実測（厚さ）

# **壁の穴の大きさを決めるのは、樹脂ではなく金属のほう。**
#
# 一度「完全に挿さると樹脂の面がメスの面に突き当たる」と書いたが、**誤り**。
# 実機（HHKB Professional HYBRID）に挿した写真を見ると、
# **樹脂は完全にケースの外にあり、金属が 1mm ほど見えたまま**挿さっている。
# 実機の穴も、金属の形そのもの（細いスリット）で、樹脂が入る大きさではない。
# **実物を見ずに推測で書いていた。**
USB_SHELL_W = 8.34       # [確定] USB Type-C プラグの金属シェル（規格値）
USB_SHELL_H = 2.56       # [確定] 同上
# 完全に挿さった状態で、樹脂の面からケース表面までに見えている金属の長さ。
# **メスをこの長さまで奥へ引っ込めても、樹脂は外に残る。**
# 利用者が実機に挿して測った値（2026-08-09）。
USB_SHELL_EXPOSED = 1.0  # [暫定] 実測（実機 ＋ 手持ちのケーブル 1 本）

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


# --------------------------------------------------------------------------
# キーの上下に付く実物（open-gaps #29。物として置いて初めて検査になる）
# --------------------------------------------------------------------------
# MX スイッチの外形。**データシートの代表値。現物を測ったら差し替える。**
SW_BODY_W = 15.6         # [暫定] 上部ハウジングのつば（プレートの上に載る）
SW_UNDER_W = 14.0        # [暫定] プレート下の下部ハウジング（開口 14.0 を通る）
# **プレートの板厚の中と、基板の穴の中は置かない。**開口 14.0 に対して
# 本体 14.0（隙間 0）なので、置くと接触ノイズだけが出る。中心ピンと端子も
# 実基板には穴があるが、pcb の占有空間（穴の無い板）に当たるので置かない。
# → 置くのは「プレート上のつば〜キャップ底」と「プレート下面〜基板上面」の 2 段。

# キーキャップ（DSA・暫定候補 open-gaps #21）。
# 幅 = キーの u 数 × 19.05 − CAP_GAP。1u で 18.4mm になる（DSA の公称）。
CAP_GAP = 0.65           # [暫定] 隣のキャップとの隙間（DSA 公称 18.4 から逆算）

# スタビライザ（2u/3u キーの下、基板に載る）。KiCad に 3D モデルが無く
# STEP に出てこないので、ここで箱として置く。
STAB_BODY_D = 7.0        # [暫定] 前後方向の占有
STAB_BODY_XPAD = 4.0     # [暫定] ワイヤ両端の外側余裕
# スタビライザの足は実基板の穴を貫くが、pcb の占有空間には穴が無いので
# 置かない（スイッチの端子と同じ扱い）。

# 利用者の USB プラグが「完全に挿さった」ときの金属の進入量。
# メスの奥行（XIAO のコネクタ 約7.4mm）に対しプラグ金属 6.5mm のうち
# 外に USB_SHELL_EXPOSED だけ見えて残りが入る、の関係から置いた概数。
USB_MATE_DEPTH = 6.0     # [暫定] 金属シェルがメスの前面から入る深さ
USB_PLUG_BODY_L = 10.0   # [暫定] 樹脂胴体の長さ。検査で効くのは前面の位置だけ

# FFC ケーブル（12 芯 0.5mm ピッチ）。リボンの幅と、経路の占有厚み。
FFC_RIBBON_W = 7.0       # [暫定] 6.0mm 幅＋振れの余裕

# M2 なべ小ネジ。**まだ買っていない。**長さは幾何から選んだ候補。
SCREW_SHAFT_D = 2.0      # [確定] M2 の呼び径（軸）。インサートの穴もこの径
SCREW_HEAD_D = 3.8       # [暫定] 頭の直径
SCREW_HEAD_H = 1.6       # [暫定] 頭の高さ
SCREW_L_MAIN = 12.0      # [暫定] 上ケース → プレート → ボスのインサートまで
SCREW_L_DB = 5.0         # [暫定] 子基板 → 子基板ボスのインサートまで

# テンティング用 1/4-20 六角ナット（規格品）。ポケットは gen_case 側
# （NUT_AF=11.4, NUT_T=5.7 は逃げ込み）。
NUT_QUARTER_AF = 11.1    # [確定] 二面幅（規格）
NUT_QUARTER_T = 5.5      # [確定] 厚み（規格）


def key_stack_envelopes(positions, keys, plate_t, cap_lift, cap_h):
    """キースイッチ（2 段）とキーキャップの占有空間。プレート座標系。

    z=0 がプレートの下面、z=plate_t が上面（gen_assembly.plate_placement が
    プレートを置くのと同じ基準）。戻りは (switches, keycaps) の 2 部品。
    61 個を 1 部品にまとめる（部品対の数を増やさないため。自己交差は無い）。
    """
    from build123d import Align, Box, BuildPart, Locations

    with BuildPart() as sw:
        for (kx, ky), _k in zip(positions, keys):
            with Locations((kx, ky, -PLATE_TO_PCB)):
                Box(SW_UNDER_W, SW_UNDER_W, PLATE_TO_PCB,
                    align=(Align.CENTER, Align.CENTER, Align.MIN))
            with Locations((kx, ky, plate_t)):
                Box(SW_BODY_W, SW_BODY_W, cap_lift,
                    align=(Align.CENTER, Align.CENTER, Align.MIN))
    with BuildPart() as caps:
        for (kx, ky), k in zip(positions, keys):
            with Locations((kx, ky, plate_t + cap_lift)):
                Box(k.w_u * 19.05 - CAP_GAP, 19.05 - CAP_GAP, cap_h,
                    align=(Align.CENTER, Align.CENTER, Align.MIN))
    return sw.part, caps.part


def stab_envelope(stabs):
    """スタビライザの占有空間（プレート座標系・z=0 がプレート下面）。

    stabs は [((x, y), s), ...]。s はワイヤ半間隔（interface.stab_offset_for）。
    **ハウジングはワイヤの両端（キー中心から ±s）に 1 個ずつ。**キー中心には
    スイッチ本体が居るので、全幅の 1 本棒で置くとスイッチと重なって
    偽の干渉になる（実際になった）。ワイヤ自体は φ2 程度で基板のすぐ上を
    通るため、ハウジングの箱に含めて別には置かない。
    """
    from build123d import Align, Box, BuildPart, Locations

    with BuildPart() as env:
        for (kx, ky), s in stabs:
            for side in (-1, 1):
                with Locations((kx + side * s, ky, -PLATE_TO_PCB)):
                    Box(STAB_BODY_XPAD * 2, STAB_BODY_D, PLATE_TO_PCB,
                        align=(Align.CENTER, Align.CENTER, Align.MIN))
    return env.part


def usb_plug_envelope(x, y_recept, z_center):
    """完全に挿さった USB プラグ（ケース座標系）。open-gaps #28 の再発防止。

    **メス（y_recept = XIAO の奥端面）から位置を導く。**壁から導くと、
    XIAO が奥まっても「挿さったことにされる」——#28 はまさにそれだった。
    メスが壁から遠のくと、樹脂の胴体が壁に食い込む形で検査に出る。
    """
    from build123d import Align, Box, BuildPart, Locations

    tip = y_recept - USB_MATE_DEPTH
    shell_l = 6.5            # [確定] USB Type-C プラグの金属部の長さ（規格）
    with BuildPart() as env:
        with Locations((x, tip, z_center)):
            Box(USB_SHELL_W, shell_l, USB_SHELL_H,
                align=(Align.CENTER, Align.MIN, Align.CENTER))
        with Locations((x, tip + shell_l, z_center)):
            Box(USB_PLUG_W, USB_PLUG_BODY_L, USB_PLUG_H,
                align=(Align.CENTER, Align.MIN, Align.CENTER))
    return env.part


def _usb_cavity(x, y_face, z_center):
    """**差込口の空洞。**プラグの金属はここに入る。実物のレセプタクルは
    中空（Seeed の公式モデルで確認）なのに、占有空間を中身の詰まった箱で
    描いていたため、挿さったプラグが常に「食い込んでいる」ことになり、
    許容値でごまかしていた（db 90 / xiao 38mm^3）。
    """
    from build123d import Align, Box, BuildPart, Locations

    with BuildPart() as cav:
        with Locations((x, y_face - USB_MATE_DEPTH / 2, z_center)):
            Box(USB_SHELL_W + 0.2, USB_MATE_DEPTH + 0.2, USB_SHELL_H + 0.2,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
    return cav.part


def daughterboard_envelope(center, w, d, t, holes=(), usb=None):
    """子基板と、その上に載る XIAO が占める空間。

    **基板だけでなく XIAO の高さを含める。** 基板の板厚だけで検査すると、
    その上に立つ部品が本体基板とぶつかるのを見逃す。
    """
    from build123d import Box, BuildPart, Locations, Align

    from build123d import Cylinder, Mode

    with BuildPart() as env:
        with Locations(center):
            Box(w, d, t + DB_STACK_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 取付穴。**実物には穴がある。**塞いだ箱にするとネジが必ず食い込む
        for hx, hy in holes:
            with Locations((hx, hy, center[2])):
                Cylinder(SCREW_HEAD_D / 2 + 0.2, t + DB_STACK_H, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = env.part
    if usb is not None:
        from gen_case import usb_center_z
        part = part - _usb_cavity(usb[0], usb[1], usb_center_z())
    return part


def xiao_overhang_envelope(x, y_board_rear, z_board_top, usb_x=None, usb_face=None):
    """**子基板の奥端から外へ出た XIAO の端**が占める空間（open-gaps #28）。

    子基板の占有空間（daughterboard_envelope）は板の外形までしか無いので、
    はみ出したぶんは**そこに入っていない**。壁のポケットが足りているかは
    ここを別に置かないと検査できない（＝検査対象に入っていない部品は、
    検査していないのと同じ）。
    """
    from build123d import Align, Box, BuildPart, Locations
    from interface import XIAO_OUTLINE_W, XIAO_OVERHANG

    with BuildPart() as env:
        with Locations((x, y_board_rear + XIAO_OVERHANG / 2, z_board_top)):
            Box(XIAO_OUTLINE_W, XIAO_OVERHANG, DB_STACK_H,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = env.part
    if usb_x is not None:
        from gen_case import usb_center_z
        part = part - _usb_cavity(usb_x, usb_face, usb_center_z())
    return part
