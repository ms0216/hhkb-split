#!/usr/bin/env python3
"""Task C3（BLE 分割）のブレッドボード配線図を描く。**左右で同じ配線。**

作図規則は gen_breadboard_c4.py と揃えてある。
列 n の x = 132 + 24*(n-1)、上半分 j..f = 196..292、下半分 e..a = 336..432。

**配線を変えたらこのファイルを直して実行する。SVG を直接編集しない。**

    .venv/bin/python3 tools/gen_breadboard_c3.py

--------------------------------------------------------------------------
なぜ C1 の図を流用しないか
--------------------------------------------------------------------------
**C1 は D0・D1、C3 は D1・D2 を使う。**Task C5 で D0 を電池電圧の ADC に
取られたので、2026-08-08 にキーを D1・D2 へ移した（proto_split.dtsi）。

一度は「C1 の図に『1 列ずらして読め』と注記を足す」で済ませようとしたが、
**台の上で見るのは図で、注記ではない。**読み替えを利用者に押し付けるのは、
図を作りたくない側の都合でしかない。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/hardware/img/breadboard-c3.svg"

VW, H = 1010, 800

BLUE, RED, GREY = "#2b4a97", "#c0392b", "#8c959d"
ORA, BLK, GOLD = "#d35400", "#333333", "#c9a227"


def col(n):
    return 132 + 24 * (n - 1)


_ROW = dict(zip("jihgfedcba", (196, 220, 244, 268, 292, 336, 360, 384, 408, 432)))


def row(r):
    return _ROW[r]


def half(r):
    return "top" if r in "jihgf" else "bot"


# ==========================================================================
# 挿す穴の一覧。**図・部品表・検査の唯一の出どころ。**
#
#   (名前, 片方の穴, もう片方の穴, 種類)
#   種類 wire＝ジャンパ、switch＝押したときだけつながる
# ==========================================================================
LINKS = (
    ("ジャンパ（D1 → スイッチ 1）", (2, "a"), (10, "a"), "wire"),
    ("ジャンパ（D2 → スイッチ 2）", (3, "a"), (14, "a"), "wire"),
    ("① スイッチ 1", (10, "b"), (12, "b"), "switch"),
    ("② スイッチ 2", (14, "b"), (16, "b"), "switch"),
    ("ジャンパ（スイッチ 1 → GND バス）", (12, "a"), (18, "a"), "wire"),
    ("ジャンパ（スイッチ 2 → GND バス）", (16, "a"), (18, "b"), "wire"),
    ("ジャンパ（XIAO の GND → GND バス）", (2, "j"), (18, "c"), "wire"),
)
LINK = {name: (p, q) for name, p, q, _k in LINKS}

# XIAO のピンが刺さる穴。**0.6 インチ＝6 ピッチなので h 行と d 行。**
XIAO_ROWS = ("h", "d")
XIAO_PINS = {(n, XIAO_ROWS[0]): t
             for n, t in enumerate(("5V", "GND", "3V3", "D10", "D9", "D8", "D7"), 1)}
XIAO_PINS.update({(n, XIAO_ROWS[1]): t
                  for n, t in enumerate(("D0", "D1", "D2", "D3", "D4", "D5", "D6"), 1)})

# **本体が乗って使えなくなる穴。**
#
# XIAO は 21.0 x 18.0mm（[envelopes.py](../tools/envelopes.py) の実測値）。
# ピンの端から端は 6 ピッチ＝15.24mm しかないので、
#   長辺 21.0mm → 両端に 2.88mm（**1.1 列ぶん**）はみ出す → **8 列にもかぶさる**
#   短辺 18.0mm → ピンの行より 1.4mm 外まで → h・d 行の上に乗るが c・i 行には届かない
# **一度 1〜7 列で止めていた。**8 列を空いていると誤って読む余地が残っていた。
#   タクトスイッチ: 足は b 行と e 行にあり、胴体が c・d 行と間の列を覆う
COVERED = {(n, r) for n in range(1, 9) for r in "hgfed"} - set(XIAO_PINS)
for _lo, _hi in ((10, 12), (14, 16)):
    COVERED |= {(n, r) for n in range(_lo, _hi + 1) for r in "edcb"}
    COVERED -= {(_lo, "b"), (_hi, "b"), (_lo, "e"), (_hi, "e")}

# **足は b 行と e 行の 2 か所に出る。**同じ列の 2 本は内部で常時つながって
# いるので、電気的には 1 つの端子（Task C2 の §6 で実測した手持ち品の寸法）。
SWITCH_FEET = tuple((n, r) for _lo, _hi in ((10, 12), (14, 16))
                    for n in (_lo, _hi) for r in ("b", "e"))

o = []
a = o.append


def txt(x, y, s, color="#111", size=11.5, anchor="middle", bold=True):
    w = ' font-weight="bold"' if bold else ""
    a(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"{w} fill="{color}">{s}</text>')


def wire(pts, color):
    d = "M " + " L ".join(f"{x} {y}" for x, y in pts)
    a(f'<path d="{d}" fill="none" stroke="#ffffff" stroke-width="6.4" '
      'stroke-linejoin="round" stroke-linecap="round"/>')
    a(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.4" '
      'stroke-linejoin="round" stroke-linecap="round"/>')
    for x, y in (pts[0], pts[-1]):
        a(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')


def curve(p0, p1, sag, color):
    (x0, y0), (x1, y1) = p0, p1
    a(f'<path d="M {x0} {y0} C {x0} {sag}, {x1} {sag}, {x1} {y1}" fill="none" '
      f'stroke="#ffffff" stroke-width="6.4"/>')
    a(f'<path d="M {x0} {y0} C {x0} {sag}, {x1} {sag}, {x1} {y1}" fill="none" '
      f'stroke="{color}" stroke-width="2.4"/>')
    for x, y in (p0, p1):
        a(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')


def hole(h):
    return col(h[0]), row(h[1])


# ================= 見出し =================
a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VW} {H}" width="{VW}" height="{H}" '
  'font-family="Helvetica, Arial, sans-serif">')
a(f'<rect width="{VW}" height="{H}" fill="#ffffff"/>')
txt(24, 32, "Task C3 — ブレッドボード上の配置（左右とも同じ）", size=18, anchor="start")
txt(24, 54, "違うのは書き込むファームだけ。左 proto_split_left（a・b）／右 proto_split_right（c・d）。",
    "#666", 12.5, "start", bold=False)
txt(24, 74, "⚠️ 使うのは D1・D2。C1（proto_direct）の D0・D1 とは 1 つずれる。"
            "D0 は Task C5 で電池電圧の ADC に使うため空けてある。", RED, 12.5, "start")

# ================= 板 =================
a('<rect x="102" y="168" width="756" height="290" rx="9" fill="#f7f8f9" '
  'stroke="#ccd2d8" stroke-width="2"/>')
a('<rect x="102" y="304" width="756" height="20" fill="#e6eaee"/>')
txt(620, 319, "中央の溝（またぐのは GND の 1 本だけ）", GREY, 11, "start", bold=False)
for n in range(1, 31):
    for r in "jihgfedcba":
        a(f'<circle cx="{col(n)}" cy="{row(r)}" r="4" fill="none" '
          'stroke="#bcc3ca" stroke-width="1.2"/>')
for n in (1, 2, 3, 5, 10, 12, 14, 16, 18, 20, 25, 30):
    txt(col(n), 158, str(n), GREY, 10.5, bold=False)
for r in "jihgfedcba":
    txt(88, row(r) + 4, r, GREY, 11.5, bold=False)

# ================= GND バス（18 列）=================
a(f'<rect x="{col(18)-10}" y="{row("c")-10}" width="20" height="{row("a")-row("c")+20}" '
  f'rx="9" fill="none" stroke="{BLK}" stroke-width="1.4" stroke-dasharray="4 3"/>')
txt(col(18), row("c") - 18, "GND バス", BLK, 10.5)

# ================= XIAO =================
BY0, BY1 = row(XIAO_ROWS[0]) + 11, row(XIAO_ROWS[1]) - 11
a(f'<rect x="118" y="{BY0}" width="172" height="{BY1-BY0}" rx="6" '
  'fill="#1f2933" stroke="#0d1216" stroke-width="2"/>')
a(f'<rect x="92" y="{(BY0+BY1)/2-16}" width="28" height="32" rx="3" fill="#b8bcc2" '
  'stroke="#8a8f96" stroke-width="1.5"/>')
txt(106, (BY0 + BY1) / 2 + 5, "USB", "#3c4147", 8.5)
txt(204, (BY0 + BY1) / 2 - 4, "XIAO", "#c9d3dc", 13, bold=False)
txt(204, (BY0 + BY1) / 2 + 13, "nRF52840", "#8b97a3", 10, bold=False)
for (n, r), t in XIAO_PINS.items():
    c = {"GND": BLK, "D1": BLUE, "D2": BLUE}.get(t, "#7d838a")
    a(f'<circle cx="{col(n)}" cy="{row(r)}" r="5" fill="{GOLD}"/>')
    txt(col(n), row(r) - 13 if r == XIAO_ROWS[0] else row(r) + 20, t, c, 9.5)

# ================= タクトスイッチ =================
for i, ((lo, hi), name) in enumerate(zip(((10, 12), (14, 16)), ("①", "②"))):
    x0, x1 = col(lo) - 13, col(hi) + 13
    y0, y1 = row("e") - 13, row("b") + 13
    a(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" rx="5" '
      'fill="#39434d" stroke="#161c22" stroke-width="1.5"/>')
    for n in (lo, hi):
        for r in ("b", "e"):
            a(f'<circle cx="{col(n)}" cy="{row(r)}" r="4.5" fill="{GOLD}"/>')
        a(f'<line x1="{col(n)}" y1="{row("e")}" x2="{col(n)}" y2="{row("b")}" '
          f'stroke="{GOLD}" stroke-width="2.4"/>')
    txt((x0 + x1) / 2, (y0 + y1) / 2 + 6, name, "#eef2f5", 17)
    txt((x0 + x1) / 2, y0 - 10, f"{lo} 列と {hi} 列", "#111", 10.5)

# ================= 配線 =================
# 下半分の 4 本は板の下へ回す。深さを変えて交差を避ける。
for name, sag, color in (("ジャンパ（D1 → スイッチ 1）", 512, BLUE),
                         ("ジャンパ（D2 → スイッチ 2）", 556, BLUE),
                         ("ジャンパ（スイッチ 1 → GND バス）", 478, BLK),
                         ("ジャンパ（スイッチ 2 → GND バス）", 478, BLK)):
    p, q = LINK[name]
    curve(hole(p), hole(q), sag, color)

# 溝をまたぐ 1 本（XIAO の GND は上半分のピン）
_p, _q = LINK["ジャンパ（XIAO の GND → GND バス）"]
wire([hole(_p), (60, 196), (60, 596), (576, 596), (576, row("c")), hole(_q)], BLK)
txt(300, 590, "XIAO の GND（2 列 j 行）→ GND バス（18 列 c 行）", BLK, 11, "end")

# 挿す場所の一覧は、板の右側が丸ごと空いているのでそこへ置く。
# **図の中に置く。**別の場所に表を作ると、台の上で目を往復させることになる。
a(f'<rect x="{col(19)}" y="176" width="292" height="128" rx="6" fill="#ffffff" '
  'fill-opacity="0.94" stroke="#dde1e5" stroke-width="1.2"/>')
txt(col(19) + 14, 192, "挿す場所（左右とも同じ）", "#111", 11, "start")
for i, t in enumerate((
        "XIAO …… 1〜7 列（上の足 h 行 / 下の足 d 行）",
        "① スイッチ …… 10・12 列（足は b 行と e 行）",
        "② スイッチ …… 14・16 列",
        "2 列 a 行 → 10 列 a 行　　（D1）",
        "3 列 a 行 → 14 列 a 行　　（D2）",
        "12 列 a 行 → 18 列 a 行",
        "16 列 a 行 → 18 列 b 行",
        "2 列 j 行 → 18 列 c 行　　（GND）")):
    c = BLUE if "（D" in t else (BLK if "GND" in t or "18 列" in t else "#3c4147")
    txt(col(19) + 14, 206 + i * 13, t, c, 10, "start", bold=False)

# ================= 2 列は上下で別物 =================
a(f'<rect x="{col(2)-40}" y="96" width="200" height="40" rx="5" fill="#fff8e6" '
  'stroke="#c9821f" stroke-width="1.4"/>')
txt(col(2) - 30, 112, "2 列は上下で別の配線", "#8a6410", 10.5, "start")
txt(col(2) - 30, 128, "上半分 j 行 = GND ／ 下半分 a 行 = D1", "#8a6410", 10.5, "start")

# ================= 下段 =================
LY = 646
a(f'<rect x="24" y="{LY-26}" width="556" height="130" rx="6" fill="#fafbfc" '
  'stroke="#dde1e5" stroke-width="1.2"/>')
txt(44, LY, "要点", "#111", 14, "start")
for i, t in enumerate((
        "・使うのは D1（2 列）と D2（3 列）。C1 の図の D0・D1 とは 1 つずれる。",
        "・2 列は上半分が GND、下半分が D1。溝で分かれているので短絡しない。",
        "・スイッチの足が入る列（10・12・14・16）で使える穴は a 行だけ。",
        "・押したときだけ鳴る 2 本をテスターで確かめる（この手持ち品は 2 マス）。")):
    txt(44, LY + 26 + i * 22, t, "#3c4147", 12.5, "start", bold=False)

a(f'<rect x="600" y="{LY-26}" width="386" height="130" rx="6" fill="#fafbfc" '
  'stroke="#dde1e5" stroke-width="1.2"/>')
txt(618, LY, "押すと出る文字", "#111", 14, "start")
for i, t in enumerate((
        "左 proto_split_left  …… 10 列 → a ／ 14 列 → b",
        "右 proto_split_right …… 10 列 → c ／ 14 列 → d",
        "",
        "左だけ USB で Mac へ。右は電源が入っていればよい。")):
    txt(618, LY + 26 + i * 22, t, "#3c4147", 12.5, "start", bold=False)

a('</svg>')

SVG = "\n".join(o)

if __name__ == "__main__":
    OUT.write_text(SVG)
    print(f"wrote {OUT.relative_to(ROOT)}")
