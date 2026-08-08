#!/usr/bin/env python3
"""Task C2-b の全体配線図（1 枚目 + 2 枚目）を 1 枚の SVG に描く。

docs/hardware/img/ の他の図は手書きの SVG だが、この図は 2 枚のブレッドボードと
板をまたぐ 7 本の配線があって手では追えない。**穴の座標を計算で出す。**

作図規則は既存の breadboard-c2-r2.svg に合わせてある（並べて見るため）。
板の原点を基準に、列 n の x = 132 + 24*(n-1)、
上半分 j..f = 196..292、下半分 e..a = 336..432。

配線を変えたら、このファイルを直して実行する。**SVG を直接編集しない。**
`test_the_breadboard_figure_is_generated_from_this_file` が食い違いを見張る。

    .venv/bin/python3 tools/gen_breadboard.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/hardware/img/breadboard-c2b-full.svg"

VB_X, VW, H = -90, 1100, 1180
B2 = 500  # 2 枚目の縦オフセット

def col(n): return 132 + 24 * (n - 1)
_ROW = dict(zip("jihgfedcba", (196, 220, 244, 268, 292, 336, 360, 384, 408, 432)))
def row(r, dy=0): return _ROW[r] + dy

BLUE, RED, GREY = "#2b4a97", "#c0392b", "#8c959d"
PUR, ORA, BLK = "#6b3fa0", "#d35400", "#333333"

o = []
a = o.append
a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{VB_X} 0 {VW} {H}" width="{VW}" height="{H}" '
  'font-family="Helvetica, Arial, sans-serif">')
a(f'<rect x="{VB_X}" y="0" width="{VW}" height="{H}" fill="#ffffff"/>')
a(f'<text x="{VB_X+20}" y="32" font-size="18" font-weight="bold" fill="#111">'
  'Task C2-b — 1 枚目と 2 枚目をつないだ全体図</text>')
a(f'<text x="{VB_X+20}" y="54" font-size="12.5" fill="#666">'
  '1 枚目は C2-a のまま。外すのは XIAO の D6・D5 から列バスへ引いた 2 本だけで、'
  'その穴に 595 の QA・QB を挿し替える。</text>')
a(f'<text x="{VB_X+20}" y="74" font-size="12.5" fill="#666">'
  '30 列のブレッドボードでは 1 枚目に 595（8 列必要）を置く余地がない（空きは 25〜30 列の 6 列だけ）。'
  'よって 2 枚に分ける。</text>')


def board(dy, label):
    a(f'<rect x="102" y="{168+dy}" width="756" height="290" rx="9" fill="#f7f8f9" '
      'stroke="#ccd2d8" stroke-width="2"/>')
    a(f'<rect x="102" y="{304+dy}" width="756" height="20" fill="#e6eaee"/>')
    for n in range(1, 31):
        for r in "jihgfedcba":
            a(f'<circle cx="{col(n)}" cy="{row(r,dy)}" r="4" fill="none" '
              'stroke="#bcc3ca" stroke-width="1.2"/>')
    for n in (1, 5, 10, 15, 20, 25, 30):
        a(f'<text x="{col(n)}" y="{158+dy}" text-anchor="middle" font-size="10.5" '
          f'fill="{GREY}">{n}</text>')
    for r in "jihgfedcba":
        a(f'<text x="88" y="{row(r,dy)+4}" text-anchor="middle" font-size="11.5" '
          f'fill="{GREY}">{r}</text>')
    a(f'<text x="110" y="{138+dy}" font-size="14" font-weight="bold" fill="#111">{label}</text>')


def wire(pts, color, label=None, lx=None, ly=None, anchor="start"):
    d = "M " + " L ".join(f"{x} {y}" for x, y in pts)
    a(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2" '
      'stroke-linejoin="round" stroke-linecap="round"/>')
    for x, y in (pts[0], pts[-1]):
        a(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')
    if label:
        a(f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" font-size="11.5" '
          f'font-weight="bold" fill="{color}">{label}</text>')


def curve(p0, p1, sag, color, dash=None):
    (x0, y0), (x1, y1) = p0, p1
    a(f'<path d="M {x0} {y0} C {x0} {sag}, {x1} {sag}, {x1} {y1}" fill="none" '
      f'stroke="{color}" stroke-width="2.2"'
      + (f' stroke-dasharray="{dash}"' if dash else "") + '/>')
    a(f'<circle cx="{x0}" cy="{y0}" r="4" fill="{color}"/>')
    a(f'<circle cx="{x1}" cy="{y1}" r="4" fill="{color}"/>')


# ================= 1 枚目 =================
board(0, "1 枚目 — C2-a のまま。触るのは ✕ の 2 本だけ")

# **ピンは h 行と d 行**。ピン間隔 0.6 インチ＝6 ピッチで、行の間隔 2.54mm・
# 溝 7.62mm から a..e = 0..4、f..j = 7..11 ピッチ。h(9) − d(3) = 6 で一致する。
# **以前ここを i 行/c 行（8 ピッチ）で描いていた**（2026-08-08 に直した）。
# 本文（task-c2-keyscan.md §4）とも食い違っていた。配線そのものは変えていない。
a(f'<rect x="118" y="{row("h")+11}" width="172" height="{row("d")-row("h")-22}" rx="6" '
  'fill="#1f2933" stroke="#0d1216" stroke-width="2"/>')
a('<rect x="92" y="286" width="28" height="32" rx="3" fill="#b8bcc2" stroke="#8a8f96" stroke-width="1.5"/>')
a('<text x="106" y="307" text-anchor="middle" font-size="8.5" font-weight="bold" fill="#3c4147">USB</text>')
a('<text x="204" y="299" text-anchor="middle" font-size="13" fill="#c9d3dc">XIAO</text>')
a('<text x="204" y="316" text-anchor="middle" font-size="10" fill="#8b97a3">nRF52840</text>')
for i, (t, c) in enumerate((("5V", "#7d838a"), ("GND", BLK), ("3V3", ORA), ("D10", PUR),
                            ("D9", "#7d838a"), ("D8", PUR), ("D7", PUR))):
    a(f'<circle cx="{col(i+1)}" cy="{row("h")}" r="5" fill="#c9a227"/>')
    a(f'<text x="{col(i+1)}" y="{row("h")-13}" text-anchor="middle" font-size="9.5" '
      f'font-weight="bold" fill="{c}">{t}</text>')
for i, (t, c) in enumerate((("D0", "#7d838a"), ("D1", BLUE), ("D2", BLUE), ("D3", "#7d838a"),
                            ("D4", "#7d838a"), ("D5", RED), ("D6", RED))):
    a(f'<circle cx="{col(i+1)}" cy="{row("d")}" r="5" fill="#c9a227"/>')
    a(f'<text x="{col(i+1)}" y="{row("d")+20}" text-anchor="middle" font-size="9.5" '
      f'font-weight="bold" fill="{c}">{t}</text>')

for x0, ch in ((339, "a"), (435, "b"), (531, "c"), (627, "d")):
    a(f'<rect x="{x0}" y="323" width="66" height="98" rx="5" fill="#39434d" stroke="#161c22" stroke-width="1.5"/>')
    for lx in (x0 + 9, x0 + 57):
        a(f'<line x1="{lx}" y1="336" x2="{lx}" y2="408" stroke="#c9a227" stroke-width="2.6"/>')
    a(f'<text x="{x0+33}" y="378" text-anchor="middle" font-size="15" font-weight="bold" fill="#eef2f5">{ch}</text>')

for (sx, sy), (bx, by), band in (((348, 432), (420, 432), 390.5), ((492, 432), (420, 408), 444.5),
                                 ((540, 432), (612, 432), 582.5), ((684, 432), (612, 408), 636.5)):
    a(f'<line x1="{sx}" y1="{sy}" x2="{bx}" y2="{by}" stroke="#222" stroke-width="2"/>')
    mx, my = (sx + bx) / 2 - 15, (sy + by) / 2 - 7
    a(f'<rect x="{mx}" y="{my}" width="30" height="14" rx="2" fill="#3a3a3a"/>')
    a(f'<rect x="{band}" y="{my}" width="5" height="14" fill="#f0f0f0"/>')

for bx, txt, c in ((287, "C0", RED), (311, "C1", RED), (407, "R0", BLUE), (599, "R1", BLUE)):
    a(f'<rect x="{bx}" y="305" width="26" height="18" rx="3" fill="#fff" stroke="{c}" stroke-width="1.3"/>')
    a(f'<text x="{bx+13}" y="318" text-anchor="middle" font-size="11" font-weight="bold" fill="{c}">{txt}</text>')

curve((156, 432), (420, 384), 492, BLUE)
curve((180, 432), (612, 384), 520, BLUE)
curve((396, 432), (300, 408), 576, RED)
curve((588, 432), (300, 384), 604, RED)
curve((444, 432), (324, 408), 632, RED)
curve((636, 432), (324, 384), 656, RED)

curve((276, 384), (300, 432), 548, "#c3c8cd", dash="6 5")
curve((252, 384), (324, 432), 600, "#c3c8cd", dash="6 5")
a(f'<text x="292" y="480" text-anchor="end" font-size="19" font-weight="bold" fill="{RED}">✕</text>')
a(f'<text x="298" y="480" font-size="12" font-weight="bold" fill="{RED}">D6 → C0 を外す</text>')
a(f'<text x="292" y="536" text-anchor="end" font-size="19" font-weight="bold" fill="{RED}">✕</text>')
a(f'<text x="298" y="536" font-size="12" font-weight="bold" fill="{RED}">D5 → C1 を外す</text>')

# ================= 2 枚目 =================
board(B2, "2 枚目 — 74HC595 を 5〜12 列に、切り欠きを左")

j2, i2, h2, g2, f2 = (row(r, B2) for r in "jihgf")
e2, d2, c2, b2, a2 = (row(r, B2) for r in "edcba")
BX0, BX1, BY0, BY1 = col(5) - 12, col(12) + 12, f2 - 16, e2 + 16
a(f'<rect x="{BX0}" y="{BY0}" width="{BX1-BX0}" height="{BY1-BY0}" rx="4" fill="#2b2f33" '
  'stroke="#111" stroke-width="1.5"/>')
a(f'<path d="M {BX0} {(BY0+BY1)/2-9} A 9 9 0 0 0 {BX0} {(BY0+BY1)/2+9} Z" fill="#f7f8f9"/>')
a(f'<text x="{BX1+14}" y="{(BY0+BY1)/2+5}" font-size="13" font-weight="bold" fill="#111">74HC595</text>')

USED = {16, 15, 14, 13, 12, 11, 10, 1, 8}
# ピン番号 -> (列, 名前)。上段 = 9〜16、下段 = 1〜8（切り欠きを左にしたとき）
PINS_UP = {16: (5, "VCC"), 15: (6, "QA"), 14: (7, "DS"), 13: (8, "OE"),
           12: (9, "STCP"), 11: (10, "SHCP"), 10: (11, "MR"), 9: (12, "Q7S")}
PINS_LO = {1: (5, "QB"), 2: (6, "QC"), 3: (7, "QD"), 4: (8, "QE"),
           5: (9, "QF"), 6: (10, "QG"), 7: (11, "QH"), 8: (12, "GND")}
for pins, py, dn, dp in ((PINS_UP, f2, 15, -11), (PINS_LO, e2, -7, 11)):
    for p, (n, nm) in pins.items():
        fc = "#f2f5f7" if p in USED else "#79828a"
        a(f'<circle cx="{col(n)}" cy="{py}" r="4.5" fill="#c9a227"/>')
        a(f'<text x="{col(n)}" y="{py+dn}" text-anchor="middle" font-size="8" font-weight="bold" fill="{fc}">{nm}</text>')
        a(f'<text x="{col(n)}" y="{py+dp}" text-anchor="middle" font-size="7.5" fill="#79828a">{p}</text>')

# 2 枚目のバス（3V3 = 2 列の上半分／GND = 3 列の下半分）
for x, y0, y1, c, t, ty in ((col(2), j2, g2, ORA, "3V3 バス", j2 - 14),
                            (col(3), e2, a2, BLK, "GND バス", a2 + 18)):
    a(f'<rect x="{x-9}" y="{y0-9}" width="18" height="{y1-y0+18}" rx="8" fill="none" '
      f'stroke="{c}" stroke-width="1.4" stroke-dasharray="4 3"/>')
    a(f'<text x="{x}" y="{ty}" text-anchor="middle" font-size="10.5" font-weight="bold" fill="{c}">{t}</text>')

# ================= 板をまたぐ配線 =================
# 左側の通り道
wire([(156, 196), (156, 150), (-70, 150), (-70, c2), (col(3), c2)], BLK,
     "GND", -64, 144)
wire([(180, 196), (180, 136), (-52, 136), (-52, j2), (col(2), j2)], ORA,
     "3V3", -46, 130)
wire([(204, 196), (204, 122), (-34, 122), (-34, i2), (col(7), i2)], PUR,
     "D10 → DS", -28, 116)
# 右側の通り道
wire([(252, 196), (252, 108), (880, 108), (880, h2), (col(10), h2)], PUR,
     "D8 → SHCP", 874, 102, "end")
wire([(276, 196), (276, 94), (904, 94), (904, g2), (col(9), g2)], PUR,
     "D7 → STCP", 898, 88, "end")

# 2 枚目の中のジャンパ
wire([(col(2), i2), (col(5), g2)], ORA)
wire([(col(2), h2), (col(11), j2)], ORA)
wire([(col(3), b2), (col(12), b2)], BLK)
wire([(col(3), d2), (168, d2), (168, 684), (300, 684), (300, g2)], BLK)

# QA・QB を 1 枚目の列バスへ（外したジャンパと同じ穴）
wire([(col(6), j2), (2, j2), (2, 470), (col(8), 470), (col(8), 432)], RED,
     "QA → C0（8 列の a 行）", 8, 466)
wire([(col(5), d2), (-16, d2), (-16, 446), (col(9), 446), (col(9), 432)], RED,
     "QB → C1（9 列の a 行）", -10, 442)

# ================= 凡例と要点 =================
LY = 1010
a(f'<rect x="{VB_X+20}" y="{LY-26}" width="600" height="146" rx="6" fill="#fafbfc" '
  'stroke="#dde1e5" stroke-width="1.2"/>')
a(f'<text x="{VB_X+40}" y="{LY}" font-size="14" font-weight="bold" fill="#111">要点</text>')
for i, t in enumerate((
        "① 2 枚の GND を必ず共通に。上の GND 線がそれを兼ねる。ここを忘れるのが一番多い失敗。",
        "② MR は 3V3 へ、OE は GND へ。浮かせると動かないか不安定になる。",
        "③ QA・QB は、外した D6・D5 のジャンパと同じ穴（8 列・9 列の a 行）に挿す。",
        "④ 595 の切り欠きは左。1 番ピン（QB）は切り欠き側の e 行。",
        "⑤ QC〜QH・Q7S は未使用。何もつながない。",
        "⑥ 3V3・GND は XIAO の h 行のピン。同じ列の i・j 行が空くが、板をまたぐ線を増やさないよう 2 枚目側で分岐させる。")):
    a(f'<text x="{VB_X+40}" y="{LY+26+i*22}" font-size="12.5" fill="#3c4147">{t}</text>')
for i, (cc, t) in enumerate(((BLUE, "行 D1・D2（1 枚目のまま）"), (RED, "列バス C0・C1 と QA・QB"),
                             (PUR, "SPI（D10・D8・D7）"), (ORA, "3V3"), (BLK, "GND"))):
    y = LY + i * 24
    a(f'<line x1="660" y1="{y}" x2="686" y2="{y}" stroke="{cc}" stroke-width="2.6"/>')
    a(f'<text x="694" y="{y+4}" font-size="12.5" font-weight="bold" fill="{cc}">{t}</text>')

a('</svg>')

# 図は文字列を組み立てるだけなので、読み込み時に作ってしまう。
# 書き出すのは実行したときだけ。検査は SVG と突き合わせるのに使う。
SVG = "\n".join(o)

if __name__ == "__main__":
    OUT.write_text(SVG)
    print(f"wrote {OUT.relative_to(ROOT)}")
