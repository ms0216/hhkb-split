#!/usr/bin/env python3
"""UART ログを Saleae で読むときの、プローブ 2 本の挿し場所。

    .venv/bin/python3 tools/gen_saleae_hookup.py

--------------------------------------------------------------------------
挿す穴は **C4 の治具の LINKS から導く。**治具の配線が変わったら、
ここも一緒に動く（穴の取り合いを検査で見張っている）。

**ログの出口は D6（P1.11）。**Zephyr の xiao_ble-pinctrl.dtsi で uart0 の
TX がそこだと確認済み。**設定は 2 つとも要る**（2026-08-09 に 2 回はまった）:

    chosen { zephyr,console = &uart0; };   ← 既定は USB CDC。向け直す
    &uart0 { status = "okay"; };           ← ドライバを引き込む
"""

from pathlib import Path

import gen_breadboard_c4 as C4

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/hardware/img/saleae-uart-hookup.svg"

col, row = C4.col, C4.row

# ==========================================================================
# 挿す 2 穴。**唯一の出どころ。**
#   XIAO の D6 は 7 列 d 行、GND は 2 列 h 行。どちらもピンが刺さっているので、
#   **同じ列の空き穴**（板の内部で繋がっている）にプローブを挿す。
# ==========================================================================
PROBE = (
    ("CH0", (7, "c"), "D6（P1.11）＝ログの出口", "#c0392b"),
    ("GND", (2, "i"), "XIAO の GND と同じ列", "#333333"),
)

# **取り合いの検査。**治具の配線とぶつかっていないこと。
_used = {h for _n, p, q, _k in C4.LINKS for h in (p, q) if h} | set(C4.XIAO_PINS)
for _nm, _h, _d, _c in PROBE:
    assert _h not in _used, ("すでに何か挿さっている穴", _nm, _h)
    assert _h not in C4.COVERED, ("部品の胴体でふさがれている穴", _nm, _h)
# 同じ列の XIAO のピンと、板の内部で繋がっていること（上半分 f..j / 下半分 a..e）
_half = lambda r: "top" if r in "jihgf" else "bot"
assert _half(PROBE[0][1][1]) == _half("d") and PROBE[0][1][0] == 7
assert _half(PROBE[1][1][1]) == _half("h") and PROBE[1][1][0] == 2

GREY, ORA, GOLD = "#8c959d", "#d35400", "#c9a227"

o = []
a = o.append


def txt(x, y, s, color="#111", size=11.5, anchor="middle", bold=True):
    w = ' font-weight="bold"' if bold else ""
    a(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"{w} '
      f'fill="{color}">{s}</text>')


a('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 900" width="1000" '
  'height="900" font-family="Helvetica, Arial, sans-serif">')
a('<rect width="1000" height="900" fill="#ffffff"/>')

txt(24, 34, "Saleae で UART ログを読む — プローブ 2 本の挿し場所", "#111", 18, "start")
txt(24, 56, "C4 の治具（左＝セントラル）はそのまま。電池もテスターも外さない。挿すのは 2 本だけ。",
    "#666", 12, "start", bold=False)

# ================= 板 =================
a('<rect x="102" y="138" width="756" height="290" rx="9" fill="#f7f8f9" '
  'stroke="#ccd2d8" stroke-width="2"/>')
a('<rect x="102" y="274" width="756" height="20" fill="#e6eaee"/>')
for n in range(1, 31):
    for r in "jihgfedcba":
        a(f'<circle cx="{col(n)}" cy="{row(r)-30}" r="4" fill="none" '
          'stroke="#bcc3ca" stroke-width="1.2"/>')
for n in (1, 2, 3, 5, 7, 10, 14, 17, 20, 25, 29):
    txt(col(n), 128, str(n), GREY, 10.5, bold=False)
for r in "jihgfedcba":
    txt(88, row(r) - 26, r, GREY, 11, bold=False)

# 治具の配線は薄く（触らないことを示す）
for name, p, q, kind in C4.LINKS:
    if p is None or q is None:
        continue
    x0, y0, x1, y1 = col(p[0]), row(p[1]) - 30, col(q[0]), row(q[1]) - 30
    a(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="#dfe4e8" '
      'stroke-width="2.4"/>')

# XIAO
BY0, BY1 = row("h") - 30 + 11, row("d") - 30 - 11
a(f'<rect x="118" y="{BY0}" width="172" height="{BY1-BY0}" rx="6" fill="#1f2933" '
  'stroke="#0d1216" stroke-width="2"/>')
a(f'<rect x="92" y="{(BY0+BY1)/2-16}" width="28" height="32" rx="3" fill="#b8bcc2" '
  'stroke="#8a8f96" stroke-width="1.5"/>')
txt(106, (BY0 + BY1) / 2 + 5, "USB", "#3c4147", 8.5)
txt(204, (BY0 + BY1) / 2 - 4, "XIAO", "#c9d3dc", 13, bold=False)
txt(204, (BY0 + BY1) / 2 + 13, "左（セントラル）", "#8b97a3", 10, bold=False)
for (n, r), t in C4.XIAO_PINS.items():
    hot = t in ("D6", "GND")
    a(f'<circle cx="{col(n)}" cy="{row(r)-30}" r="5" fill="{GOLD}"/>')
    txt(col(n), row(r) - 30 - 13 if r == "h" else row(r) - 30 + 20, t,
        "#c0392b" if t == "D6" else ("#333" if t == "GND" else "#7d838a"),
        10 if hot else 9)

# ================= プローブ =================
for i, (nm, h, desc, color) in enumerate(PROBE):
    x, y = col(h[0]), row(h[1]) - 30
    ty = 486 + i * 66
    a(f'<path d="M {x} {y} C {x} {ty-40}, {x+150} {ty-30}, {x+190} {ty}" '
      f'fill="none" stroke="#ffffff" stroke-width="8"/>')
    a(f'<path d="M {x} {y} C {x} {ty-40}, {x+150} {ty-30}, {x+190} {ty}" '
      f'fill="none" stroke="{color}" stroke-width="3"/>')
    a(f'<circle cx="{x}" cy="{y}" r="6" fill="{color}"/>')
    a(f'<rect x="{x+190}" y="{ty-18}" width="128" height="36" rx="6" '
      f'fill="#ffffff" stroke="{color}" stroke-width="2"/>')
    txt(x + 254, ty + 5, f"Saleae {nm}", color, 13)
    txt(x + 330, ty - 4, f"{h[0]} 列 {h[1]} 行", "#111", 12, "start")
    txt(x + 330, ty + 13, desc, "#666", 11, "start", bold=False)

# ================= 設定と注意 =================
a('<rect x="600" y="682" width="356" height="186" rx="8" fill="#fbfcfd" '
  'stroke="#d5dae0" stroke-width="1.5"/>')
txt(620, 708, "Saleae Logic 2 の設定", "#111", 13, "start")
for i, (k, v) in enumerate((("アナライザ", "Async Serial"),
                            ("Bit Rate", "1000000 bps"),
                            ("フレーム", "8 bit / 1 stop / parity なし"),
                            ("ビット順", "LSB first"),
                            ("標本化", "24 MS/s（CH0 のみ）"))):
    y = 734 + i * 24
    txt(620, y, k, "#666", 11, "start", bold=False)
    txt(940, y, v, "#111", 11.5, "end")
txt(620, 856, "Automation（MCP）を有効にしておく", ORA, 11, "start")

txt(24, 664, "⚠️ 左は電池のまま。USB を挿すと電池側に電流が流れず、同時に電流を測れない。",
    "#c0392b", 12.5, "start")
txt(24, 686, "⚠️ 治具の配線（薄い線）は触らない。テスターも 29 ↔ 27 列に入れたまま。",
    "#666", 12, "start", bold=False)
txt(24, 708, "⚠️ プローブは XIAO のピンそのものではなく、同じ列の空き穴へ挿す（板の内部で繋がっている）。",
    "#666", 12, "start", bold=False)

a("</svg>")
OUT.write_text("\n".join(o), encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}")
for nm, h, desc, _c in PROBE:
    print(f"  {nm:>3} → {h[0]:>2} 列 {h[1]} 行   {desc}")
