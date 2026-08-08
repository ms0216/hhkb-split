"""回路を**データとして**宣言する。ここが回路の唯一の出所。

なぜ要るか
----------
この案件で最も高くついた見落としは、どれも回路の側にあった。

  - バルクコンデンサが無く、電池を使い切る前にブラウンアウトする
  - パスコンが無く、74HC595 のノイズが行の入力へ回り込む
  - 74HC595 の MR/OE が浮いていて、動かないか不安定になる

**3 つとも、私が指示されて見直すまで誰も気づかなかった。** 幾何には DRC と
干渉検査があるのに、回路には検査が 1 つも無かったのが理由。KiCad の ERC は
回路図が要るが、この案件では基板を Python が直接組んでいて回路図が存在しない。

そこで回路をここに宣言し、tools/test_circuit.py が電気的な規則を検査する。
基板を組むときもここを読むようにすれば、回路と基板が食い違うこともなくなる。

書き方
------
    PART(参照名, 種類, {端子名: ネット名})

**繋がないことにも意味がある端子（74HC595 の未使用出力など）は
NC と書く。**書き忘れと区別がつかないと、浮きピンの検査ができない。
"""

import re

# 電池は単3×2。新品のアルカリは 1 本 1.6V まで上がりうる。
BATT_CELLS = 2
BATT_V_MAX = 1.65 * BATT_CELLS
BATT_V_NOMINAL = 1.5 * BATT_CELLS

SCHOTTKY_VF = 0.4                    # SB240LES の順方向電圧降下。
                                     # データシートの定格電流での値。実使用の
                                     # 10mA では 0.2V 程度のはず。Task C4 で実測する
MCU_V_MIN = 1.7                      # nRF52840 の動作下限
MCU_MARGIN = 0.1                     # 下限に対して残す余裕

# **使い切れる下限は、望みではなく回路で決まる。**
#
# 当初 0.9V/本（＝完全放電）と書いていたが、test_circuit の
# test_the_mcu_still_runs_on_depleted_cells が「マイコンへ 1.40V しか
# 届かない（下限 1.7V）」と検出した。直列のショットキーが降下するぶん、
# 電池の電圧はマイコンの下限より高いところで打ち止めになる。
#
#   必要な電池電圧 = マイコン下限 1.7V ＋ 余裕 0.1V ＋ ショットキー降下
#
# 降下 0.4V なら 2.20V（1.10V/本）。アルカリ単3 を低負荷で使う場合、
# ここで止めると容量の 1 割ほどを残すことになる。
#
# 逆流防止は安全のため外せないので、この 1 割は**ショットキーを選んだ
# 代償**として受け入れる。0.4V はデータシートの定格電流での値であり、
# 実際の 10mA では 0.2V ほどまで下がるはず。**Task C4 で実測する。**
# 実測できたら SCHOTTKY_VF を下げ、下限もそのぶん下げられる。
BATT_V_MIN = MCU_V_MIN + MCU_MARGIN + SCHOTTKY_VF

DIVIDER_R_HIGH = 1_000_000
DIVIDER_R_LOW = 1_000_000

# 74HC595 のピン名。データシートの呼び名に合わせる。
_595_OUTPUTS = ["Q0", "Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"]


def _shift_register(ref, cols, first_col, serial_in, serial_out):
    """74HC595 を 1 個ぶん。cols 本ぶん列に繋ぎ、残りは NC。

    **MR は VCC、OE は GND に必ず固定する。**浮かせると、MR はノイズで
    中身が消え、OE は出力が High-Z になって全キーが反応しない。
    """
    pins = {
        "VCC": "V3V3", "GND": "GND",
        "MR": "V3V3",          # マスタリセット。Low で消える
        "OE": "GND",           # 出力許可。Low で有効
        "DS": serial_in,
        "SH_CP": "SPI_SCK",
        "ST_CP": "CS",
        "Q7S": serial_out,     # 数珠つなぎの送り出し
    }
    for i, name in enumerate(_595_OUTPUTS):
        pins[name] = f"COL{first_col + i}" if i < cols else "NC"
    return (ref, "74HC595", pins)


# 電子部品の参照名（基板上の名前）。
#
# **接頭辞で走査しない。**`D` や `SW` で拾うとダイオード 61 個と
# キースイッチ 61 個を巻き込む。この案件で 4 回起きた事故。
#
# **生成側（gnd_fanout）と検査側（test_pcb）の両方が使う。**別々に持つと
# 片方だけ直して静かにずれる。実際、電源スイッチが SW_PWR から
# SW_PWR_1 / SW_PWR_2 に変わったとき、両方を直す必要があった。
ELEC_REF = re.compile(r"U\d+|C_[A-Z0-9]+|R_[A-Z]+|D_PWR|SW_PWR_\d|J_DB|BT1_[+-]")


# ケースの中で配線し、基板側はランド 2 個で受ける部品。
#
# **生成側（gen_pcb）と検査側の両方が使う。**別々に持つと、部品を足した
# ときに片方だけ直して静かにずれる（実際、電源スイッチをランドに変えた
# とき、検査 6 件が BT1 しか知らずに落ちた）。
WIRE_PAD_KINDS = {"battery_holder", "wire_pads"}


def board_refs(ref, kind, pins):
    """その部品が基板上で名乗る参照名。ランド 2 個の部品は 2 つに分かれる。"""
    if kind in WIRE_PAD_KINDS:
        return [f"{ref}_{p}" for p in pins]
    return [ref]


def netlist(half):
    """その半分の回路。[(参照名, 種類, {端子: ネット}), ...] を返す。"""
    n_cols = 6 if half == "left" else 9
    parts = [
        # ---- 電源 ----
        ("BT1", "battery_holder", {"+": "VBATT_RAW", "-": "GND"}),
        # 参照名は SW_PWR。**SW1 にするとキースイッチの SW1 と衝突する**
        # （conformance の検査が初回に見つけた）。
        # **基板には載らない。**背面のパネルに付けて配線で繋ぐ。基板側は
        # ランド 2 個で受ける（電池ボックスと同じ形）。基板の後端から
        # ケース背面まで 23.3mm あり、基板上のどこに置いても手が届かない。
        # 経緯は docs/hardware/open-gaps.md #17。
        ("SW_PWR", "wire_pads", {"1": "VBATT_RAW", "2": "VBATT_SW"}),
        # ショットキー 1 個が「電池への充電を止める」と「USB を挿すと電池を
        # 自動で切り離す」の 2 役を兼ねる。P-MOSFET は不要。
        ("D_PWR", "schottky", {"A": "VBATT_SW", "K": "V3V3"}),
        # バルク。アルカリは消耗すると内部抵抗が上がり、BLE 送信のパルスで
        # 電圧が落ちる。これが無いと電池を使い切る前に落ちる。
        ("C_BULK", "cap_100u", {"1": "V3V3", "2": "GND"}),
        ("C_MCU", "cap_100n", {"1": "V3V3", "2": "GND"}),
        # 電池電圧の分圧。**スライドスイッチの後ろ**に置く。前だと電源を
        # 切っても流れ続ける。**ショットキーの手前**なので、USB 接続中も
        # 電池そのものの電圧が読める。
        ("R_HI", "res_1M", {"1": "VBATT_SW", "2": "VBATT_SENSE"}),
        ("R_LO", "res_1M", {"1": "VBATT_SENSE", "2": "GND"}),
    ]

    # ---- シフトレジスタ ----
    if half == "left":
        parts.append(_shift_register("U1", n_cols, 0, "SPI_MOSI", "NC"))
        parts.append(("C_U1", "cap_100n", {"1": "V3V3", "2": "GND"}))
    else:
        # 最上段が 9 キーあるので 9 列要る。2 個を数珠つなぎにする。
        parts.append(_shift_register("U1", 8, 0, "SPI_MOSI", "U1_U2"))
        parts.append(_shift_register("U2", 1, 8, "U1_U2", "NC"))
        parts.append(("C_U1", "cap_100n", {"1": "V3V3", "2": "GND"}))
        parts.append(("C_U2", "cap_100n", {"1": "V3V3", "2": "GND"}))

    # ---- 子基板へのケーブル ----
    # 並び順は docs/hardware/decisions/2026-08-07-daughterboard.md のとおり。
    # 最も速い SCK を GND の隣に置き、両端も GND にしてループ面積を小さくする。
    parts.append(("J_DB", "ffc_12p", {
        # **並びは配線の順序で決まる。**子基板では FFC が手前、XIAO の
        # パッドが左右 2 列。手前から上がる配線は、近いパッドへ行くものほど
        # 外側を通す必要がある。ピン順がそれと逆だと交差する（最初の並びで
        # 6 箇所が短絡した）。左群(2-7) は左列を y の大きい順、右群(8-12) は
        # 右列を y の小さい順。GND はベタで受けるので順序に影響しない。
        # SCK(10) の隣を GND(11) にしてある（ループ面積を小さく）。
        "1": "CS", "2": "GND", "3": "SPI_SCK", "4": "SPI_MOSI",
        "5": "V3V3", "6": "VBATT_SENSE",
        "7": "ROW0", "8": "ROW1", "9": "ROW2", "10": "ROW3", "11": "ROW4",
        "12": "GND",
    }))

    # ---- マトリクス ----
    # col2row。列 → スイッチ → ダイオード → 行。
    n_keys = 27 if half == "left" else 34
    from matrix import assignments
    for i, (r, c) in enumerate(assignments(half), start=1):
        parts.append((f"SW{i}", "keyswitch", {"1": f"COL{c}", "2": f"SW{i}_D"}))
        parts.append((f"D{i}", "diode", {"A": f"SW{i}_D", "K": f"ROW{r}"}))
    assert len([p for p in parts if p[1] == "keyswitch"]) == n_keys

    return parts


def daughterboard_netlist():
    """子基板。XIAO とパスコンとケーブルのコネクタだけ。"""
    return [
        ("J_MAIN", "ffc_12p", {
            # **並びは配線の順序で決まる。**子基板では FFC が手前、XIAO の
            # パッドが左右 2 列。手前から上がる配線は、近いパッドへ行くものほど
            # 外側を通す必要がある。ピン順がそれと逆だと交差する（最初の並びで
            # 6 箇所が短絡した）。左群(2-7) は左列を y の大きい順、右群(8-12) は
            # 右列を y の小さい順。GND はベタで受けるので順序に影響しない。
            # SCK(10) の隣を GND(11) にしてある（ループ面積を小さく）。
            "1": "CS", "2": "GND", "3": "SPI_SCK", "4": "SPI_MOSI",
            "5": "V3V3", "6": "VBATT_SENSE",
            "7": "ROW0", "8": "ROW1", "9": "ROW2", "10": "ROW3", "11": "ROW4",
            "12": "GND",
        }),
        # **BAT 端子はどこにも繋がない。**リポ用充電回路に直結しており、
        # 乾電池を繋ぐと USB 接続時に一次電池を充電しようとする。
        ("U_MCU", "xiao_nrf52840", {
            "GND": "GND", "3V3": "V3V3", "5V": "NC", "BAT": "NC",
            "D0": "VBATT_SENSE",
            "D1": "ROW0", "D2": "ROW1", "D3": "ROW2", "D4": "ROW3", "D5": "ROW4",
            "D6": "NC", "D7": "CS", "D8": "SPI_SCK", "D9": "NC", "D10": "SPI_MOSI",
        }),
        ("C_DB", "cap_100n", {"1": "V3V3", "2": "GND"}),
    ]


# その種類の部品が「電源端子を持つ IC」かどうか。パスコンの検査に使う。
ICS = {"74HC595", "xiao_nrf52840"}

# 電源ネット。ここに繋がるだけの端子は「駆動されていない」と見なさない。
POWER_NETS = {"V3V3", "GND", "VBATT_RAW", "VBATT_SW"}
