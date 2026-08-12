"""ピン名 → パッド番号と、ピンの電気的種別。**ここが唯一の出どころ。**

なぜ要るか
----------
**2026-08-12 に、この対応表が無かったせいで発注寸前の基板が死んでいた。**

`circuit.py` はピンを名前で宣言する（`VCC` / `MR` / `SH_CP` / `A` / `K`）。
一方フットプリントのパッドは番号（`1`..`16`）。`gen_pcb._place_electronics` は

    pad = fp.FindPadByNumber(pin)   # "VCC" では見つからない → None
    if pad is not None:             # ← ここが黙って握り潰していた
        pad.SetNet(net(netname))

としていたので、**74LVC595 の 16 パッド全部と、ショットキー D_PWR の
2 パッドにネットが 1 つも付いていなかった。**列を駆動する回路と電源経路が
基板上に存在しないまま、DRC 0 件・未配線 0 件で緑になっていた
（ネットの無いパッドは「未配線」に数えられない）。

**この表を通さずにパッドを引かないこと。**引けなかったら落とす
（`resolve` が KeyError を投げる）。黙って飛ばす経路をもう作らない。

電気的種別は何のためか
----------------------
KiCad の ERC は種別を見て「電源入力がどこからも駆動されていない」
「出力どうしがぶつかっている」を検出する。**種別を書かないと ERC は
ただ通るだけの飾りになる。**

出どころ
--------
外の事実で裏を取ったものだけを書く。自分の生成物は根拠にしない。

  74LVC595   TI SN74LVC595A データシート SCASE93A（2025-10 改訂）
             「4 Pin Configuration and Functions」Table 4-1（PW/TSSOP-16）
  diode      KiCad 標準 Diode_SMD:D_SOD-123。2 端子ダイオードは
  schottky   パッド 1 = カソード、パッド 2 = アノード
"""

# --- 電気的種別（KiCad の名前をそのまま使う） ---
PASSIVE = "passive"
POWER_IN = "power_in"
POWER_OUT = "power_out"
INPUT = "input"
OUTPUT = "output"
TRISTATE = "tri_state"
BIDI = "bidirectional"


def _numbered(n, etype=PASSIVE):
    """パッド番号がそのままピン名の部品（コンデンサ・抵抗・コネクタなど）。"""
    return {str(i): (str(i), etype) for i in range(1, n + 1)}


# 種類 → {ピン名: (パッド番号, 電気的種別)}
PINS = {
    # SN74LVC595A PW（TSSOP-16）。SCASE93A Table 4-1。
    #
    #   1 QB   2 QC   3 QD   4 QE   5 QF   6 QG   7 QH   8 GND
    #   9 QH'  10 SRCLR  11 SRCLK  12 RCLK  13 OE  14 SER  15 QA  16 VCC
    #
    # circuit.py は NXP 系の名前（MR / SH_CP / ST_CP / DS / Q7S）を使う。
    # TI の名前との対応を右に書く。**名前が 2 系統あることが、そもそも
    # この取り違えの温床だった。**
    "74LVC595": {
        "Q0":    ("15", TRISTATE),   # QA
        "Q1":    ("1",  TRISTATE),   # QB
        "Q2":    ("2",  TRISTATE),   # QC
        "Q3":    ("3",  TRISTATE),   # QD
        "Q4":    ("4",  TRISTATE),   # QE
        "Q5":    ("5",  TRISTATE),   # QF
        "Q6":    ("6",  TRISTATE),   # QG
        "Q7":    ("7",  TRISTATE),   # QH
        "GND":   ("8",  POWER_IN),
        "Q7S":   ("9",  OUTPUT),     # QH'。**3 ステートではない**（数珠つなぎ用）
        "MR":    ("10", INPUT),      # SRCLR
        "SH_CP": ("11", INPUT),      # SRCLK
        "ST_CP": ("12", INPUT),      # RCLK
        "OE":    ("13", INPUT),
        "DS":    ("14", INPUT),      # SER
        "VCC":   ("16", POWER_IN),
    },

    # 2 端子ダイオード。KiCad の Diode_SMD:D_SOD-123 は
    # **パッド 1 がカソード**（シルクの帯が付く側）。
    "diode":    {"K": ("1", PASSIVE), "A": ("2", PASSIVE)},
    "schottky": {"K": ("1", PASSIVE), "A": ("2", PASSIVE)},

    # 番号がそのままピン名のもの
    "cap_100n":  _numbered(2),
    "cap_100u":  _numbered(2),
    "res_1M":    _numbered(2),
    "keyswitch": _numbered(2),
    "ffc_12p":   _numbered(12),

    # ケースの中で配線し、基板側はランド 2 個で受ける部品。
    # **基板上では 2 つのフットプリントに分かれる**（circuit.board_refs）。
    # 回路の宣言としては 1 部品 2 端子。
    "wire_pads":      {"1": ("1", PASSIVE), "2": ("1", PASSIVE)},
    "battery_holder": {"+": ("1", POWER_OUT), "-": ("1", POWER_OUT)},

    # 上の 2 つを、**基板と同じ「ランド 1 個」の姿に割ったもの**。
    # 回路図はこちらを使う（gen_sch._expand）。
    #
    # **1 部品 2 ピンのまま回路図に出すと、両ピンが同じパッド番号 1 に
    # なり、ERC が duplicate_pins で落ちる**（実際に落ちた。BT1 の
    # ピン 1 が VBATT_RAW と GND の両方に繋がっている、と正しく指摘された）。
    # 基板では最初から 2 つのフットプリントなので、回路図もそう描くのが
    # 実物に忠実で、突き合わせも 1 対 1 になる。
    "wire_land":    {"1": ("1", PASSIVE)},
    "battery_land": {"1": ("1", POWER_OUT)},

    # XIAO nRF52840。**フットプリントのパッドは名前が付いている**ので
    # 対応は恒等。3V3 を power_out にしてあるのは、USB を挿すと
    # XIAO 側のレギュレータがレールを駆動するため（実際にそうなる）。
    # BAT は**フットプリントにパッドが無い**。電池を BAT に繋がない設計
    # （test_the_battery_never_reaches_the_bat_pin が見張っている）なので、
    # 回路図には出すが基板には出ない。**pad を None にして区別する。**
    "xiao_nrf52840": {
        "GND": ("GND", POWER_IN),
        "3V3": ("3V3", POWER_OUT),
        "5V":  ("5V",  POWER_OUT),
        "BAT": (None,  PASSIVE),
        **{f"D{i}": (f"D{i}", BIDI) for i in range(11)},
    },
}


def resolve(kind, pin):
    """ピン名 → パッド番号。**引けなければ落ちる。**

    基板に無いピン（XIAO の BAT）は None を返す。「表に無い」と
    「基板に出ない」は別物なので、KeyError と None で区別する。
    """
    try:
        return PINS[kind][pin][0]
    except KeyError:
        raise KeyError(
            f"{kind} のピン {pin!r} が pinmap.PINS に無い。"
            "circuit.py に足したなら pinmap.py にも足すこと。"
            "**黙って飛ばすと、そのピンはネットの無いパッドになる**"
            "（2026-08-12 に 74LVC595 と D_PWR で実際に起きた）") from None


def etype(kind, pin):
    """ピン名 → 電気的種別（ERC 用）。"""
    return PINS[kind][pin][1]
