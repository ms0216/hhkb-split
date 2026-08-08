"""電子部品を置く帯の位置。

**gen_pcb.py と test_pcb.py の両方が使う。** 生成側と検査側で別々に
持つと、片方だけ直したときに静かにずれる。

pcbnew を import しないこと。test_pcb.py は通常の venv から走る。
"""

# ソケットの占有はキー中心に対して非対称（-2.6 〜 +7.2mm）なので、
# 段と段の中間に置くと 0.9mm ソケットに掛かる（実際に掛かって短絡した）。
# ソケットの中心ぶんずらす。
_SOCK_MID = (7.2 + (-2.6)) / 2

# 帯の中心（レイアウト座標・原点中心・Y 上向き）。奥から手前へ 4 本。
BAND_Y = [28.575 + _SOCK_MID, 9.525 + _SOCK_MID,
          -9.525 + _SOCK_MID, -28.575 + _SOCK_MID]

# 段と段の間で部品を置ける高さ。
BAND_H = 9.25


def band_bounds_kicad(i, origin_y=100.0):
    """帯 i の KiCad 座標での範囲 (y_lo, y_hi) を返す。

    KiCad は Y 下向きなので、レイアウト座標から符号が反転する。
    """
    center = origin_y - BAND_Y[i]
    return center - BAND_H / 2, center + BAND_H / 2
