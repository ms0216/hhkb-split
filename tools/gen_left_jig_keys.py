#!/usr/bin/env python3
"""左の治具（C4）にキーを 2 個足す。**書き込みとボンド消しを、キー操作で。**

    .venv/bin/python3 tools/gen_left_jig_keys.py

--------------------------------------------------------------------------
なぜ足すか
--------------------------------------------------------------------------
**2026-08-10 の後半だけで、リセットボタンを 20 回以上押した。**利用者から
「ボタンがへたってきたかも」と申告があった。

| キー | 割り当て | 無くなる往復 |
|---|---|---|
| D1 | `&bootloader` | **リセット素早く 2 回押し**（書き込みのたび） |
| D2 | `&bt BT_CLR`  | **`settings_reset` を焼く → 本来のを焼く**（マウント 2 回） |

**`&bt BT_CLR` は、いま選ばれているホストのボンドだけを消す。**
`settings_reset` と違って**分割リンクの結合は残る**ので、
**右を焼き直す必要が無くなる**（今日はそれで往復が倍になっていた）。

--------------------------------------------------------------------------
置き場所の決め方
--------------------------------------------------------------------------
**既存の配線を 1 本も動かさない。**電源の鎖は下半分の 12〜29 列に集中して
いるので、空いている **9〜11 列（下半分）** と **15〜17 列（上半分）** を使う。

**XIAO の胴体は 1〜8 列の d〜h 行を覆う**ので、そこは避ける。
1〜8 列でも **a・b・c 行は空いている**（1 列 b 行の分圧タップを除く）。

--------------------------------------------------------------------------
⚠️ オシロの GND 側シャント（scope-shunt-hookup.svg）とは同時に組めない
--------------------------------------------------------------------------
**どちらも 12 列 d 行を使う。**オシロで測るときは、この GND バスの
ジャンパを抜くこと。
"""

from pathlib import Path

import gen_breadboard_c4 as C4

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/hardware/img/left-jig-keys.svg"

col, row = C4.col, C4.row

# ==========================================================================
# 足すもの。**唯一の出どころ。**
# ==========================================================================
# タクトスイッチ: (左の列, 右の列, 足の行 2 つ, 名前, 割り当て)
SWITCHES = (
    (9, 11, ("b", "e"), "① D1", "&bootloader"),
    (15, 17, ("i", "f"), "② D2", "&bt BT_CLR"),
)
# ジャンパ: (名前, 穴, 穴)
JUMPERS = (
    ("D1 → スイッチ ①", (2, "a"), (9, "a")),
    ("スイッチ ① → GND バス", (11, "a"), (19, "b")),
    ("D2 → スイッチ ②", (3, "a"), (15, "j")),
    ("スイッチ ② → GND バス", (17, "j"), (19, "c")),
    ("GND → GND バス", (12, "d"), (19, "a")),
)

# **取り合いの検査。**既存の配線とぶつからないこと。
_used = {h for _n, p, q, _k in C4.LINKS for h in (p, q) if h} | set(C4.XIAO_PINS)
for _nm, _p, _q in JUMPERS:
    for _h in (_p, _q):
        assert _h not in _used, ("すでに何か挿さっている穴", _nm, _h)
        assert _h not in C4.COVERED, ("部品の胴体でふさがれている穴", _nm, _h)
for _lo, _hi, _rows, _nm, _beh in SWITCHES:
    for _n in (_lo, _hi):
        for _r in _rows:
            assert (_n, _r) not in _used, ("スイッチの足がぶつかる", _nm, _n, _r)
            assert (_n, _r) not in C4.COVERED, ("XIAO の胴体の下", _nm, _n, _r)
    # 胴体が覆う範囲も、既存の配線とぶつからないこと
    _r0, _r1 = _rows
    _span = "edcb" if _r0 in "abcde" else "ihgf"
    for _n in range(_lo, _hi + 1):
        for _r in _span:
            assert (_n, _r) not in _used, ("スイッチの胴体が既存の配線を覆う", _nm, _n, _r)
# D1・D2 と同じ列に繋がっていること（板の内部で繋がる）
assert JUMPERS[0][1][0] == 2 and C4.XIAO_PINS[(2, "d")] == "D1"
assert JUMPERS[2][1][0] == 3 and C4.XIAO_PINS[(3, "d")] == "D2"

RED, BLU, BLK, GREY, ORA, GOLD = "#c0392b", "#2b4a97", "#333333", "#8c959d", "#d35400", "#c9a227"
DIM = "#dfe4e8"
DY = -30

o = []
a = o.append


def txt(x, y, s, color="#111", size=11.5, anchor="middle", bold=True):
    # **`&bootloader` の `&` は SVG の特殊文字。**逃がさないと描画ごと落ちる
    # （2026-08-10 に実際に落ちた）。
    s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    w = ' font-weight="bold"' if bold else ""
    a(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"{w} '
      f'fill="{color}">{s}</text>')


def hole(h):
    return col(h[0]), row(h[1]) + DY


a('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1020 760" width="1020" '
  'height="760" font-family="Helvetica, Arial, sans-serif">')
a('<rect width="1020" height="760" fill="#ffffff"/>')

txt(24, 34, "左の治具にキーを 2 個足す — 書き込みとボンド消しをキー操作で",
    "#111", 18, "start")
txt(24, 56, "既存の配線は 1 本も動かさない。空いている 9〜11 列（下半分）と "
            "15〜17 列（上半分）を使う。",
    "#666", 12, "start", bold=False)

# ================= 板 =================
a('<rect x="102" y="138" width="756" height="290" rx="9" fill="#f7f8f9" '
  'stroke="#ccd2d8" stroke-width="2"/>')
a('<rect x="102" y="274" width="756" height="20" fill="#e6eaee"/>')
for n in range(1, 31):
    for r in "jihgfedcba":
        a(f'<circle cx="{col(n)}" cy="{row(r)+DY}" r="4" fill="none" '
          'stroke="#bcc3ca" stroke-width="1.2"/>')
for n in (1, 2, 3, 9, 11, 12, 15, 17, 19, 20, 25, 29):
    txt(col(n), 128, str(n), GREY, 10.5, bold=False)
for r in "jihgfedcba":
    txt(88, row(r) + DY + 4, r, GREY, 11, bold=False)

# 既存の配線は薄く
for name, p, q, kind in C4.LINKS:
    if p is None or q is None or "起動用" in name:
        continue
    x0, y0 = hole(p)
    x1, y1 = hole(q)
    a(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="{DIM}" '
      'stroke-width="2.4"/>')
txt(858, 448, "薄い線＝すでに組んである配線。触らない", "#9aa1a8", 10.5, "end", bold=False)

# XIAO
BY0, BY1 = row("h") + DY + 11, row("d") + DY - 11
a(f'<rect x="118" y="{BY0}" width="172" height="{BY1-BY0}" rx="6" fill="#1f2933" '
  'stroke="#0d1216" stroke-width="2"/>')
txt(204, (BY0 + BY1) / 2 + 4, "XIAO（左）", "#c9d3dc", 12, bold=False)
for (n, r), t in C4.XIAO_PINS.items():
    hot = t in ("D1", "D2")
    a(f'<circle cx="{col(n)}" cy="{row(r)+DY}" r="5" fill="{GOLD}"/>')
    if hot:
        txt(col(n), row(r) + DY + 20, t, BLU, 10)

# ================= タクトスイッチ =================
for lo, hi, (r0, r1), name, beh in SWITCHES:
    x0, x1 = col(lo) - 13, col(hi) + 13
    # **上半分は行の並びが逆**（i は f より上）。min/max で取る
    y0 = min(row(r0), row(r1)) + DY - 13
    y1 = max(row(r0), row(r1)) + DY + 13
    a(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" rx="5" '
      'fill="#39434d" stroke="#161c22" stroke-width="1.5"/>')
    for n in (lo, hi):
        for r in (r0, r1):
            a(f'<circle cx="{col(n)}" cy="{row(r)+DY}" r="4.5" fill="{GOLD}"/>')
        a(f'<line x1="{col(n)}" y1="{row(r0)+DY}" x2="{col(n)}" y2="{row(r1)+DY}" '
          f'stroke="{GOLD}" stroke-width="2.4"/>')
    txt((x0 + x1) / 2, (y0 + y1) / 2 + 5, name.split()[0], "#eef2f5", 15)
    txt((x0 + x1) / 2, y1 + 16, f"{lo} 列と {hi} 列", "#111", 10.5)
    txt((x0 + x1) / 2, y1 + 30, beh, ORA, 10.5)

# ================= GND バス =================
a(f'<rect x="{col(19)-11}" y="{row("c")+DY-11}" width="22" '
  f'height="{row("a")-row("c")+22}" rx="9" fill="none" stroke="{BLK}" '
  'stroke-width="1.4" stroke-dasharray="4 3"/>')
txt(col(19), row("a") + DY + 26, "GND バス", BLK, 10.5)

# ================= ジャンパ =================
for i, (name, p, q) in enumerate(JUMPERS):
    (x0, y0), (x1, y1) = hole(p), hole(q)
    color = BLK if "GND" in name else BLU
    sag = row("a") + DY + 48 + (i % 3) * 22
    a(f'<path d="M {x0} {y0} C {x0} {sag}, {x1} {sag}, {x1} {y1}" fill="none" '
      'stroke="#ffffff" stroke-width="7"/>')
    a(f'<path d="M {x0} {y0} C {x0} {sag}, {x1} {sag}, {x1} {y1}" fill="none" '
      f'stroke="{color}" stroke-width="2.6"/>')
    for x, y in ((x0, y0), (x1, y1)):
        a(f'<circle cx="{x}" cy="{y}" r="4.5" fill="{color}"/>')

# ================= 挿す場所の表 =================
TY = 540
txt(24, TY - 14, "挿す場所", "#111", 14, "start")
rows_out = [("① タクトスイッチ", "9 列 と 11 列（b 行・e 行）", "&bootloader")]
rows_out += [("② タクトスイッチ", "15 列 と 17 列（i 行・f 行）", "&bt BT_CLR")]
rows_out += [(n, f"{p[0]} 列 {p[1]} 行 → {q[0]} 列 {q[1]} 行", "") for n, p, q in JUMPERS]
for i, (a1, a2, a3) in enumerate(rows_out):
    y = TY + 14 + i * 22
    txt(40, y, a1, "#111", 11.5, "start")
    txt(300, y, a2, "#111", 11.5, "start")
    if a3:
        txt(600, y, a3, ORA, 11.5, "start")

txt(24, TY + 14 + len(rows_out) * 22 + 16,
    "⚠️ オシロの GND 側シャント（scope-shunt-hookup.svg）とは同時に組めない。"
    "どちらも 12 列 d 行を使う。", RED, 12, "start")
txt(24, TY + 14 + len(rows_out) * 22 + 36,
    "⚠️ 左のキーは Shift・b でなくなる。打鍵の確認は右の c・d で行う。",
    "#666", 11.5, "start", bold=False)

a("</svg>")
OUT.write_text("\n".join(o), encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}")
for lo, hi, rs, name, beh in SWITCHES:
    print(f"  {name}: {lo} 列 と {hi} 列（{rs[0]} 行・{rs[1]} 行）  → {beh}")
for n, p, q in JUMPERS:
    print(f"  {n}: {p[0]} 列 {p[1]} 行 → {q[0]} 列 {q[1]} 行")
