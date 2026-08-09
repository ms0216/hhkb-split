#!/usr/bin/env python3
"""右半分（ペリフェラル）の電流を測る配線図。**治具と C3 の右を線 2 本でつなぐ。**

    .venv/bin/python3 tools/gen_breadboard_right_current.py

--------------------------------------------------------------------------
なぜ XIAO を載せ替えないか
--------------------------------------------------------------------------
**右のキーが残らないと、接続できているかを確かめられない。**

右の XIAO を C4 の治具へ移せば配線は 1 か所で済むが、右のブレッドボードの
スイッチが使えなくなる。すると「本当にペアリングしているか」を確かめる
手段が消える。**広告中のペリフェラルを測って「これが待機電流だ」と書くのは、
左で 3.7mA を掴んだのとまったく同じ間違い**（Task C4・C5 の §6）。

線 2 本で給電すれば右のキーが残るので、**`c` `d` が出ることを確かめてから
測れる。**

--------------------------------------------------------------------------
配線とスイッチの位置は、**両方の生成器の LINKS から読む。**
片方を直したときにこの図だけ古いまま、が起きないようにするため。
"""

from pathlib import Path

import gen_breadboard_c3 as C3
import gen_breadboard_c4 as C4

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/hardware/img/breadboard-right-current.svg"

VW, H = 1010, 1130
DY = 470                      # 2 枚目（右のボード）の縦オフセット

BLUE, RED, GREY = "#2b4a97", "#c0392b", "#8c959d"
DIM, DIMB = "#c9ced3", "#eef0f2"   # 既存の配線・部品は薄く描く
ORA, BLK, GOLD = "#d35400", "#333333", "#c9a227"

col, row = C4.col, C4.row

# **つなぐ 2 本。ここが唯一の出どころ。**
#   (名前, 治具側の穴, 右のボード側の穴, 色)
BRIDGE = (("レール（3V3）", (14, "b"), (3, "j"), ORA),
          ("GND", (12, "d"), (2, "i"), BLK))

o = []
a = o.append


def txt(x, y, s, color="#111", size=11.5, anchor="middle", bold=True):
    w = ' font-weight="bold"' if bold else ""
    a(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"{w} fill="{color}">{s}</text>')


def wire(pts, color, halo=True, dash=None):
    d = "M " + " L ".join(f"{x} {y}" for x, y in pts)
    if halo:
        a(f'<path d="{d}" fill="none" stroke="#ffffff" stroke-width="7" '
          'stroke-linejoin="round" stroke-linecap="round"/>')
    a(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.6" '
      + (f'stroke-dasharray="{dash}" ' if dash else "")
      + 'stroke-linejoin="round" stroke-linecap="round"/>')
    for x, y in (pts[0], pts[-1]):
        a(f'<circle cx="{x}" cy="{y}" r="4.5" fill="{color}"/>')


def board(dy, title, sub, tx=110):
    a(f'<rect x="102" y="{168+dy}" width="756" height="290" rx="9" fill="#f7f8f9" '
      'stroke="#ccd2d8" stroke-width="2"/>')
    a(f'<rect x="102" y="{304+dy}" width="756" height="20" fill="#e6eaee"/>')
    for n in range(1, 31):
        for r in "jihgfedcba":
            a(f'<circle cx="{col(n)}" cy="{row(r)+dy}" r="4" fill="none" '
              'stroke="#bcc3ca" stroke-width="1.2"/>')
    for n in (1, 2, 3, 5, 10, 12, 14, 16, 17, 18, 20, 25, 29):
        txt(col(n), 158 + dy, str(n), GREY, 10, bold=False)
    for r in "jihgfedcba":
        txt(88, row(r) + dy + 4, r, GREY, 11, bold=False)
    txt(tx, 122 + dy, title, "#111", 14, "start")
    txt(tx, 140 + dy, sub, "#666", 11.5, "start", bold=False)


def draw_xiao(dy, pins, label, empty=False):
    y0, y1 = row("h") + dy + 11, row("d") + dy - 11
    fill = "#eef1f4" if empty else "#1f2933"
    a(f'<rect x="118" y="{y0}" width="172" height="{y1-y0}" rx="6" fill="{fill}" '
      f'stroke="{"#b6bec6" if empty else "#0d1216"}" stroke-width="2"'
      + (' stroke-dasharray="6 4"' if empty else "") + '/>')
    if empty:
        txt(204, (y0 + y1) / 2 + 5, label, "#8a939b", 12)
        return
    a(f'<rect x="92" y="{(y0+y1)/2-16}" width="28" height="32" rx="3" fill="#b8bcc2" '
      'stroke="#8a8f96" stroke-width="1.5"/>')
    txt(106, (y0 + y1) / 2 + 5, "USB", "#3c4147", 8.5)
    txt(204, (y0 + y1) / 2 + 5, label, "#c9d3dc", 12, bold=False)
    for (n, r), t in pins.items():
        c = {"GND": BLK, "3V3": ORA}.get(t, "#7d838a")
        a(f'<circle cx="{col(n)}" cy="{row(r)+dy}" r="5" fill="{GOLD}"/>')
        txt(col(n), row(r) + dy - 13 if r == "h" else row(r) + dy + 20, t, c, 9)


def part(p, q, dy, label, color=DIM, body=DIMB, edge=DIM):
    x0, x1, y = col(p[0]), col(q[0]), row(p[1]) + dy
    a(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{color}" stroke-width="2"/>')
    mx = (x0 + x1) / 2
    a(f'<rect x="{mx-25}" y="{y-9}" width="50" height="18" rx="4" fill="{body}" '
      f'stroke="{edge}" stroke-width="1.5"/>')
    for x in (x0, x1):
        a(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')
    txt(mx, y - 15, label, "#9aa1a8", 9.5)


# ================= 見出し =================
a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VW} {H}" width="{VW}" height="{H}" '
  'font-family="Helvetica, Arial, sans-serif">')
a(f'<rect width="{VW}" height="{H}" fill="#ffffff"/>')
txt(24, 32, "右半分（ペリフェラル）の電流を測る", size=18, anchor="start")
txt(24, 54, "C4 の治具から線 2 本で右のボードへ給電する。XIAO は載せ替えない（右のキーを残すため）。",
    "#666", 12.5, "start", bold=False)
txt(24, 112, "薄いものは組んであるので触らない。濃いものが今つなぐもの。", "#666", 12, "start", bold=False)
txt(24, 74, "⚠️ 測る前に、右の 10 列・14 列を押して c・d が出ることを確かめる。"
            "接続していないペリフェラルを測ると、待機電流ではなく広告中の電流になる。",
    RED, 12.5, "start")

# ================= 1 枚目: C4 の治具 =================
board(0, "1 枚目 — Task C4 の治具（そのまま使う）",
      "XIAO は抜いたまま。シャントの位置にテスターを直列で入れておく")
draw_xiao(0, C4.XIAO_PINS, "XIAO は挿さない（空のまま）", empty=True)

# 電源の鎖を LINKS から描く
for name, p, q, kind in C4.LINKS:
    if p is None or q is None or name.startswith("①"):
        continue                                  # シャントの位置にはテスターが入る
    if kind in ("part", "series"):
        part(p, q, 0, name.split()[0])
    elif "起動用" not in name:
        wire([(col(p[0]), row(p[1])), (col(q[0]), row(q[1]))], DIM, halo=False)
txt(858, 478, "XIAO へ行く 3 本は、抜いてあるので効いていない（挿したままでよい）",
    "#9aa1a8", 10, "end", bold=False)

# スライドスイッチ
_com, _out, _r = C4.span("② スライドスイッチ")
a(f'<rect x="{col(_out)-13}" y="{row(_r)-18}" width="{col(_com+1)-col(_out)+26}" height="36" '
  f'rx="4" fill="{DIMB}" stroke="{DIM}"/>')
for n in (_out, _com, _com + 1):
    a(f'<circle cx="{col(n)}" cy="{row(_r)}" r="4" fill="{DIM}"/>')
txt(col(_com), row(_r) + 30, "電源スイッチ", "#9aa1a8", 9.5)

# テスター（シャントの位置に直列）
_sp, _sq = C4.LINK["① シャント"]
mx = (col(_sp[0]) + col(_sq[0])) / 2
a(f'<line x1="{col(_sq[0])}" y1="{row("c")}" x2="{col(_sp[0])}" y2="{row("c")}" '
  f'stroke="{RED}" stroke-width="2"/>')
a(f'<rect x="{mx-34}" y="{row("c")-16}" width="68" height="32" rx="5" fill="#fff3f1" '
  f'stroke="{RED}" stroke-width="2"/>')
txt(mx, row("c") - 2, "テスター", RED, 10)
txt(mx, row("c") + 11, "mA 直列", RED, 9)
for x in (col(_sp[0]), col(_sq[0])):
    a(f'<circle cx="{x}" cy="{row("c")}" r="4" fill="{RED}"/>')

# 電池
BATY = 500
a(f'<rect x="560" y="{BATY}" width="298" height="52" rx="7" fill="#f2f4f6" '
  'stroke="#8c959d" stroke-width="1.6"/>')
txt(709, BATY + 32, "単3 × 2（直列 3.0V）", "#111", 12)
for nm in ("電池 −（黒）", "電池 ＋（赤）"):
    _, h = C4.LINK[nm]
    wire([(col(h[0]), row(h[1])), (col(h[0]), BATY)], DIM, halo=False)

# ================= 2 枚目: C3 の右 =================
# 左端は治具から来る 2 本が通るので、見出しは右へ寄せる
board(DY, "2 枚目 — Task C3 の右（そのまま使う）", "USB は抜く。電源は 1 枚目から来る", tx=300)
draw_xiao(DY, C3.XIAO_PINS, "XIAO（proto_split_right）")
for name, p, q, kind in C3.LINKS:
    if kind == "wire":
        wire([(col(p[0]), row(p[1]) + DY), (col(q[0]), row(q[1]) + DY)], DIM, halo=False)
for lo, hi, mark in ((10, 12, "c"), (14, 16, "d")):
    x0, x1 = col(lo) - 13, col(hi) + 13
    y0, y1 = row("e") + DY - 13, row("b") + DY + 13
    a(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" rx="5" fill="#39434d" '
      'stroke="#161c22" stroke-width="1.5"/>')
    for n in (lo, hi):
        for r in ("b", "e"):
            a(f'<circle cx="{col(n)}" cy="{row(r)+DY}" r="4.5" fill="{GOLD}"/>')
    txt((x0 + x1) / 2, (y0 + y1) / 2 + 6, mark, "#eef2f5", 17)
    txt((x0 + x1) / 2, y1 + 18, f"押すと {mark}", RED, 10)
txt(col(18), row("a") + DY + 26, "GND バス", "#9aa1a8", 10)

# ================= つなぐ 2 本 =================
for (name, p, q, c), band in zip(BRIDGE, (512, 488)):
    x0, y0 = col(p[0]), row(p[1])
    x1, y1 = col(q[0]), row(q[1]) + DY
    wire([(x0, y0), (x0, band), (x1, band), (x1, y1)], c)
    txt(x1 - 14, band - 8, f"{name}：{p[0]} 列 {p[1]} 行 → {q[0]} 列 {q[1]} 行", c, 11, "start")

# ================= 下段 =================
LY = 990
a(f'<rect x="24" y="{LY-26}" width="962" height="118" rx="6" fill="#fafbfc" '
  'stroke="#dde1e5" stroke-width="1.2"/>')
txt(44, LY, "手順", "#111", 14, "start")
for i, t in enumerate((
        "1. 右のブレッドボードの USB を抜く　2. 上の 2 本をつなぐ　3. 治具の電源スイッチを入れる",
        "4. 左（USB 給電）を Mac につなぐ　5. **右の 10 列・14 列を押して c・d が出ることを確認**（接続の証拠）",
        "6. 10 秒ほど触らずに置いてから、治具のテスターを読む",
        "※ 治具の分圧（1MΩ×2）は右半分の消費に含めて数える。本番の右基板にも分圧は載るため。")):
    txt(44, LY + 24 + i * 21, t, "#3c4147", 12, "start", bold=False)

a('</svg>')

SVG = "\n".join(o)

if __name__ == "__main__":
    OUT.write_text(SVG)
    print(f"wrote {OUT.relative_to(ROOT)}")
