#!/usr/bin/env python3
"""オシロで電流を時系列に記録するときの配線（GND 側シャント）。

    .venv/bin/python3 tools/gen_scope_shunt.py

--------------------------------------------------------------------------
なぜ GND 側に入れられるようになったか
--------------------------------------------------------------------------
**以前はハイサイド（電池の＋側）しか使えなかった。**測定 A で USB を挿す
必要があり、GND 側にシャントを入れると「オシロのアース — Mac — USB の
シールド — 回路 GND」でシャントを迂回するから（task-c4-c5-power.md の
§6 の警告 2）。

**いまは左を電池だけで動かす。**USB を挿さないので、その経路が存在しない。
→ **GND 側に入れられる。**片側が電池の − なので、**普通のプローブ 1 本**で
読める（差動プローブも A−B 演算も要らない）。

--------------------------------------------------------------------------
なぜ 100Ω か
--------------------------------------------------------------------------
```
0.3〜0.9mA を読む          10Ω → 3〜9mV（小さすぎる）
                          **100Ω → 30〜90mV**
                          1kΩ → 300〜900mV（降下しすぎ）
```
レールの降下は 0.03〜0.09V。2.75V に対して問題ない。

**そして 100µF がシャントの下流にある。**
```
100Ω × 100µF = 時定数 10ms
 → BLE の送信バースト（数 ms・10mA 級）はコンデンサが吸う
 → シャントには平均が流れる
```
**測りたいもの（平均電流）が、そのまま電圧として出る。**振り切れない。
"""

from pathlib import Path

import gen_breadboard_c4 as C4

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/hardware/img/scope-shunt-hookup.svg"

col, row = C4.col, C4.row
SHUNT_OHM = 100

# ==========================================================================
# 治具に対する変更は 2 つだけ。**唯一の出どころ。**
# ==========================================================================
MOVE_BATT_MINUS = ((12, "a"), (10, "a"))     # 電池 −（黒）を 12 列から 10 列へ
SHUNT = ((10, "b"), (12, "d"))               # そこへ 100Ω を渡す
PROBE_TIP = (12, "a")                        # 回路 GND 側（電池 − が抜けた穴）
PROBE_CLIP = (10, "c")                       # 電池 − 側
JUMPER_HIGH = ((29, "c"), (27, "c"))         # テスターを抜いてジャンパにする

_used = {h for _n, p, q, _k in C4.LINKS for h in (p, q) if h} | set(C4.XIAO_PINS)
_used -= {MOVE_BATT_MINUS[0]}                # 電池 − は抜くので空く
for _h in (MOVE_BATT_MINUS[1], SHUNT[0], SHUNT[1], PROBE_TIP, PROBE_CLIP):
    assert _h not in _used, ("ふさがっている穴", _h)
    assert _h not in C4.COVERED, ("部品の胴体の下", _h)
# シャントは電池 − と回路 GND の間に入っていること
assert SHUNT[0][0] == MOVE_BATT_MINUS[1][0], "シャントが電池 − と同じ列に無い"
assert SHUNT[1][0] == MOVE_BATT_MINUS[0][0], "シャントの反対側が GND の列に無い"
assert PROBE_CLIP[0] == MOVE_BATT_MINUS[1][0], "GND クリップが電池 − 側に無い"
assert PROBE_TIP[0] == MOVE_BATT_MINUS[0][0], "プローブ先が回路 GND 側に無い"

RED, BLK, GREY, ORA, GOLD = "#c0392b", "#333333", "#8c959d", "#d35400", "#c9a227"
DIM = "#dfe4e8"
DY = -30

o = []
a = o.append


def txt(x, y, s, color="#111", size=11.5, anchor="middle", bold=True):
    w = ' font-weight="bold"' if bold else ""
    a(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"{w} '
      f'fill="{color}">{s}</text>')


def hole(h):
    return col(h[0]), row(h[1]) + DY


a('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1020 940" width="1020" '
  'height="940" font-family="Helvetica, Arial, sans-serif">')
a('<rect width="1020" height="940" fill="#ffffff"/>')

txt(24, 34, "オシロで電流を時系列に記録する — GND 側シャント", "#111", 18, "start")
txt(24, 56, "左（セントラル）の C4 の治具を、2 か所だけ変える。"
            "USB を挿さないので GND 側に入れられる（プローブ 1 本で読める）。",
    "#666", 12, "start", bold=False)

# ================= 板 =================
a('<rect x="102" y="138" width="756" height="290" rx="9" fill="#f7f8f9" '
  'stroke="#ccd2d8" stroke-width="2"/>')
a('<rect x="102" y="274" width="756" height="20" fill="#e6eaee"/>')
for n in range(1, 31):
    for r in "jihgfedcba":
        a(f'<circle cx="{col(n)}" cy="{row(r)+DY}" r="4" fill="none" '
          'stroke="#bcc3ca" stroke-width="1.2"/>')
for n in (1, 3, 5, 10, 12, 14, 17, 20, 25, 27, 29):
    txt(col(n), 128, str(n), GREY, 10.5, bold=False)
for r in "jihgfedcba":
    txt(88, row(r) + DY + 4, r, GREY, 11, bold=False)

# 既存の配線は薄く（触らない）
for name, p, q, kind in C4.LINKS:
    if p is None or q is None or "起動用" in name or name.startswith("①"):
        continue
    if name == "電池 −（黒）":
        continue
    x0, y0 = hole(p) if p else (0, 0)
    x1, y1 = hole(q)
    a(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="{DIM}" '
      'stroke-width="2.4"/>')

# XIAO
BY0, BY1 = row("h") + DY + 11, row("d") + DY - 11
a(f'<rect x="118" y="{BY0}" width="172" height="{BY1-BY0}" rx="6" fill="#1f2933" '
  'stroke="#0d1216" stroke-width="2"/>')
txt(204, (BY0 + BY1) / 2 + 4, "XIAO（左）", "#c9d3dc", 12, bold=False)
for (n, r), t in C4.XIAO_PINS.items():
    a(f'<circle cx="{col(n)}" cy="{row(r)+DY}" r="5" fill="{GOLD}"/>')

# ハイサイドはジャンパに戻す（テスターを抜く）
x0, y0 = hole(JUMPER_HIGH[0])
x1, y1 = hole(JUMPER_HIGH[1])
a(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="{ORA}" stroke-width="3"/>')
for x, y in ((x0, y0), (x1, y1)):
    a(f'<circle cx="{x}" cy="{y}" r="5" fill="{ORA}"/>')
txt((x0 + x1) / 2, y0 - 14, "① テスターを抜いてジャンパ", ORA, 10.5)

# ================= ② シャント =================
sx0, sy0 = hole(SHUNT[0])
sx1, sy1 = hole(SHUNT[1])
a(f'<line x1="{sx0}" y1="{sy0}" x2="{sx1}" y2="{sy1}" stroke="{BLK}" stroke-width="3"/>')
mx = (sx0 + sx1) / 2
a(f'<rect x="{mx-28}" y="{sy0-10}" width="56" height="20" rx="4" fill="#ffffff" '
  f'stroke="{BLK}" stroke-width="2"/>')
txt(mx, sy0 + 5, f"{SHUNT_OHM}Ω", "#111", 11)
for x, y in ((sx0, sy0), (sx1, sy1)):
    a(f'<circle cx="{x}" cy="{y}" r="5" fill="{BLK}"/>')
txt(mx, sy0 - 18, "② シャント", "#111", 11)

# ================= 電池 =================
BATY = 470
bx0, bx1 = col(10) - 40, col(29) + 40
a(f'<rect x="{bx0}" y="{BATY}" width="{bx1-bx0}" height="46" rx="7" fill="#f2f4f6" '
  'stroke="#8c959d" stroke-width="1.6"/>')
txt((bx0 + bx1) / 2, BATY + 29, "単3 × 2（直列 3.0V）", "#111", 12)
# ＋ はそのまま 29 列
px, py = hole((29, "a"))
a(f'<line x1="{px}" y1="{py}" x2="{px}" y2="{BATY}" stroke="{RED}" stroke-width="2.6"/>')
txt(px + 8, (py + BATY) / 2, "＋", RED, 12, "start")
# − は 12 列 → 10 列へ移す
nx, ny = hole(MOVE_BATT_MINUS[1])
a(f'<line x1="{nx}" y1="{ny}" x2="{nx}" y2="{BATY}" stroke="{BLK}" stroke-width="2.6"/>')
a(f'<circle cx="{nx}" cy="{ny}" r="5" fill="{BLK}"/>')
txt(nx - 8, (ny + BATY) / 2, "−", BLK, 12, "end")
# もとの穴には ✕
ox, oy = hole(MOVE_BATT_MINUS[0])
a(f'<line x1="{ox-7}" y1="{oy-7}" x2="{ox+7}" y2="{oy+7}" stroke="{RED}" stroke-width="2"/>')
a(f'<line x1="{ox-7}" y1="{oy+7}" x2="{ox+7}" y2="{oy-7}" stroke="{RED}" stroke-width="2"/>')
txt(ox, oy + 26, "③ ここから抜く", RED, 10.5)

# ================= オシロのプローブ =================
for nm, h, color, ty in (("プローブ先", PROBE_TIP, RED, 566),
                         ("GND クリップ", PROBE_CLIP, BLK, 624)):
    x, y = hole(h)
    lx = 150
    a(f'<path d="M {x} {y} C {x-60} {ty-70}, {lx+180} {ty-40}, {lx+150} {ty}" '
      f'fill="none" stroke="#ffffff" stroke-width="8"/>')
    a(f'<path d="M {x} {y} C {x-60} {ty-70}, {lx+180} {ty-40}, {lx+150} {ty}" '
      f'fill="none" stroke="{color}" stroke-width="3"/>')
    a(f'<circle cx="{x}" cy="{y}" r="6" fill="{color}"/>')
    a(f'<rect x="{lx}" y="{ty-17}" width="150" height="34" rx="6" fill="#ffffff" '
      f'stroke="{color}" stroke-width="2"/>')
    txt(lx + 75, ty + 5, f"オシロ {nm}", color, 12)
    txt(lx + 162, ty + 5, f"{h[0]} 列 {h[1]} 行", "#111", 12, "start")

# ================= 設定 =================
a('<rect x="600" y="556" width="392" height="188" rx="8" fill="#fbfcfd" '
  'stroke="#d5dae0" stroke-width="1.5"/>')
txt(620, 582, "オシロの設定", "#111", 13, "start")
for i, (k, v) in enumerate((("時間軸", "ロールモード 10〜30 秒/div"),
                            ("垂直", "20mV/div・DC 結合"),
                            ("読み方", f"電流[mA] ＝ 電圧[mV] ÷ {SHUNT_OHM}"),
                            ("目安", "0.30mA→30mV／0.90mA→90mV"),
                            ("記録", "5 分ぶん。画面を撮る"))):
    y = 608 + i * 24
    txt(620, y, k, "#666", 11, "start", bold=False)
    txt(976, y, v, "#111", 11.5, "end")
txt(620, 732, "USB は挿さない（挿すとアース経由でシャントを迂回する）", ORA, 11, "start")

# ================= 注意 =================
txt(24, 786, "⚠️ 変えるのは 3 か所だけ。ダイオード・抵抗・コンデンサ・XIAO への 3 本は触らない。",
    "#111", 12.5, "start")
txt(24, 810, "⚠️ 100µF はシャントの下流にある。BLE のバーストはコンデンサが吸うので、"
             "シャントには平均が流れる（時定数 10ms）。", "#666", 12, "start", bold=False)
txt(24, 834, "⚠️ レールが 0.03〜0.09V 下がる。2.75V に対して問題ないが、"
             "電圧を読むときはこのぶんを引いて考えること。", "#666", 12, "start", bold=False)
txt(24, 858, "⚠️ 分圧タップ（1MΩ×2）はシャントの上流に繋がっているので、"
             "その 1.5µA もこの読みに含まれる。", "#666", 12, "start", bold=False)
txt(24, 890, "見たいもの: 落ちる瞬間の形（段差か、なだらかか）／周期があるか／"
             "落ちるまでの時間", RED, 12.5, "start")

a("</svg>")
OUT.write_text("\n".join(o), encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}")
print(f"  ① {JUMPER_HIGH[0][0]} 列 ↔ {JUMPER_HIGH[1][0]} 列 をジャンパに戻す（テスターを抜く）")
print(f"  ② {SHUNT_OHM}Ω を {SHUNT[0][0]} 列 {SHUNT[0][1]} 行 → {SHUNT[1][0]} 列 {SHUNT[1][1]} 行")
print(f"  ③ 電池 − を {MOVE_BATT_MINUS[0][0]} 列 → {MOVE_BATT_MINUS[1][0]} 列 へ移す")
print(f"  プローブ先 {PROBE_TIP[0]} 列 {PROBE_TIP[1]} 行 ／ GND クリップ "
      f"{PROBE_CLIP[0]} 列 {PROBE_CLIP[1]} 行")
