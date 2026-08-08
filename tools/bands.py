"""電子部品を置く帯の位置。

**gen_pcb.py と test_pcb.py の両方が使う。** 生成側と検査側で別々に
持つと、片方だけ直したときに静かにずれる。

pcbnew を import しないこと。test_pcb.py は通常の venv から走る。
"""

from layout import UNIT

# ソケットがキー中心に対して占める範囲（レイアウト座標・Y 上向き）。
#
# **非対称。**段と段の中間に置くと 0.9mm ソケットに掛かる（実際に掛かって
# 短絡した）。ソケットの中心ぶんずらす必要がある。
#
# **この 2 つは実フットプリントを囲む値。**test_pcb の
# test_the_declared_socket_envelope_contains_the_real_footprint が、
# 基板上の全スイッチのパッドとコートヤードがこの中に入ることを確かめる。
# 手で書いた数字なので、外の事実に繋いでおかないと静かにずれる。
#
# **envelopes.py も同じ値を SOCKET_Y0/Y1 として別に持っていた。**変異検査で
# どちらも生き残ったので分かった。ここを唯一の出所にして、envelopes は
# ここから読む（逆向きにできないのは、envelopes が build123d を import
# しており、gen_pcb は KiCad の Python 3.9 で動くため）。
SOCK_LO, SOCK_HI = -2.6, 7.2

# 左右方向の張り出し。帯の高さには効かないが、ケースのボスとの干渉に効く。
SOCK_X_LO, SOCK_X_HI = -9.0, 7.8

_SOCK_MID = (SOCK_HI + SOCK_LO) / 2

# 帯の中心（レイアウト座標・原点中心・Y 上向き）。奥から手前へ 4 本。
BAND_Y = [28.575 + _SOCK_MID, 9.525 + _SOCK_MID,
          -9.525 + _SOCK_MID, -28.575 + _SOCK_MID]

# 段と段の間で部品を置ける高さ。**キーピッチからソケットの占有を引いた残り。**
#
# 以前は 9.25 と直書きしていた。**由来がどこにも書いておらず、変異検査で
# 10.175 に書き換えても 271 件が全部通った。**帯を広げると帯の検査は緩む
# だけなので、誰も気づかない。導出にすれば書き換えようがない。
BAND_H = UNIT - (SOCK_HI - SOCK_LO)


def band_bounds_kicad(i, origin_y=100.0):
    """帯 i の KiCad 座標での範囲 (y_lo, y_hi) を返す。

    KiCad は Y 下向きなので、レイアウト座標から符号が反転する。
    """
    center = origin_y - BAND_Y[i]
    return center - BAND_H / 2, center + BAND_H / 2
