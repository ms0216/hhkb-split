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

# 種類 → LCSC の部品番号。**フットプリントは pcb/ の実物と突き合わせた。**
#
# 区分・在庫・単価は JLCPCB の検索 API から取った（2026-08-08）。
# ブラウザが要ると思い込んで 3 回見積もりを外したので、**取り方を残す**:
#
#   POST https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/
#        smtGood/selectSmtComponentList
#   Content-Type: application/json / Origin: https://jlcpcb.com
#   {"currentPage":1,"pageSize":10,"keyword":"C81598","searchSource":"search"}
#
#   componentLibraryType  base=Basic / expand=Extended
#   preferredComponentFlag  true なら Preferred（Extended でも段取り費 $0）
#   stockCount / componentPrices  在庫と数量別価格
#
# ## 費用（5 セット分・2026-08-08 の単価）
#
#   部品代の合計   約 $22.8（¥3,400）
#   段取り費       Extended 3 種 x $3 = $9（¥1,350）… **部品代の 4 割**
#   半田付け       1 点 $0.0017。左 150 点で $0.26。誤差
#
# **効くのは段取り費。**単価ではない。
PARTS = {
    # --- Basic（段取り費 $0）--------------------------------------------
    "diode":     {"lcsc": "C81598",
                  "desc": "1N4148W SOD-123 75V 150mA"},
    "schottky":  {"lcsc": "C8598",
                  "desc": "B5819W SOD-123 ショットキー 40V 1A"},
    "cap_100n":  {"lcsc": "C49678",
                  "desc": "0.1uF 0805 50V X7R (CC0805KRX7R9BB104)"},
    "res_1M":    {"lcsc": "C17514",
                  "desc": "1MOhm 0805 1% 1/8W (0805W8F1004T5E)"},
    # **100uF 1206 にも Basic があった。**Samsung CL31A107MQHNNNE 6.3V X5R。
    # 6.3V なので 3V を掛けると容量が半分程度まで落ちる（DC バイアス）。
    # 実効 50uF・電池 ESR 4Ω・送信 15mA で降下 60mV、余裕 100mV の内側。
    # **余裕の 6 割を使う。**1206 で 10V 以上の 100uF は存在しないので、
    # 容量を増やすなら実装面積を増やすしかない。
    "cap_100u":  {"lcsc": "C15008",
                  "desc": "100uF 1206 6.3V X5R (CL31A107MQHNNNE)"},

    # --- Extended（1 種類 $3）--------------------------------------------
    # **在庫を必ず見ること。**最初 C5184526 を書いたが在庫 0 だった。
    # 在庫があるのは -2（C49352235・37,697 個）。
    "keyswitch": {"lcsc": "C49352235",
                  "desc": "Kailh CPG151101S11-2 MX ホットスワップソケット"},
    # **在庫が最も薄い（2,868 個）。**必要 15 個なので足りるが、
    # 発注時にもう一度見ること。FH12-12S-0.5SH(54) は製造中止（後継 FH52K）。
    # (55) はまだある。単価 $0.2635 で 15 個 ¥600 程度。安価品（JUSHUO
    # AFC01-S12FCA-00 $0.064）はランドパターンが違い、差し替えられない
    # （縦の総寸法 4.13mm 対 FH12 5.0mm）。**¥600 なので探す必要も無い。**
    "ffc_12p":   {"lcsc": "C88360",
                  "desc": "FFC 12P 0.5mm Hirose FH12-12S-0.5SH(55)"},
    # **SOIC-16 の C5947 は Basic。**TSSOP-16 は preferredComponentFlag も
    # false で、正真正銘の Extended（$3）。SOIC-16 は 90 度回せば帯に入る
    # （7.40mm。余裕 +0.92mm）が、幅が 6.4→10.4mm になって隣と 0.4mm 重なり、
    # 配線し直すと右基板に違反が 9 件出た。$3（¥450）と引き換えに DRC 0 の
    # 基板を崩す判断は、利用者に確認してから。
    "74HC595":   {"lcsc": "C5948",
                  "desc": "74HC595 TSSOP-16 (Nexperia 74HC595PW,118)"},
}
