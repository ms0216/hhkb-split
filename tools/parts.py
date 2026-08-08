"""買う部品。**種類 → LCSC の部品番号**。

export_fab.py（KiCad の Python で動く）と検査（venv で動く）の両方が読む。
**pcbnew を import しないこと。**

番号を埋めるときは、JLCPCB の在庫ページで現物を確認してから書く。
型番だけ合っていても、パッケージが違えば実装できない。フットプリントは
pcb/ に出ている実物と突き合わせること。

「基本部品(Basic)」なら段取り費がかからない。「拡張部品(Extended)」は
1 種類あたり段取り費がかかるので、種類を増やすほど高くなる。
"""

from circuit import WIRE_PAD_KINDS

# 基板に載らない部品。リード線で繋ぐもの（電池・電源スイッチ）と、
# 利用者が挿す XIAO。**BOM にも CPL にも出さない。**
NOT_ASSEMBLED = set(WIRE_PAD_KINDS) | {"xiao_nrf52840"}

# 種類 → (LCSC 番号, 説明, JLCPCB の基本部品か)
#
# **番号は 1 つも埋まっていない。**埋めるときは、JLCPCB の在庫ページで
# 現物を確認してから書くこと。型番だけ合っていても、パッケージが違えば
# 実装できない（フットプリントは pcb/ に出ている実物と突き合わせる）。
#
# 「基本部品(Basic)」なら段取り費がかからない。「拡張部品(Extended)」は
# 1 種類あたり段取り費がかかるので、種類を増やすほど高くなる。
PARTS = {
    "74HC595":   {"lcsc": None, "desc": "8bit シフトレジスタ TSSOP-16"},
    "cap_100n":  {"lcsc": None, "desc": "0.1uF 積層セラミック 0603 25V X7R"},
    "cap_100u":  {"lcsc": None, "desc": "100uF 電解/タンタル 6.3V 以上"},
    "diode":     {"lcsc": None, "desc": "1N4148W SOD-123"},
    "ffc_12p":   {"lcsc": None, "desc": "FFC 12P 0.5mm Hirose FH12-12S-0.5SH"},
    "keyswitch": {"lcsc": None, "desc": "Kailh MX ホットスワップソケット"},
    "res_1M":    {"lcsc": None, "desc": "1MOhm 1% 0603"},
    "schottky":  {"lcsc": None, "desc": "ショットキー Vf<=0.4V @10mA SOD-123"},
}
