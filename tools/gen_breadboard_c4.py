#!/usr/bin/env python3
"""Task C4・C5（乾電池給電と電池残量測定）のブレッドボード配線図を描く。

作図規則は breadboard-c2-r2.svg / gen_breadboard.py と揃えてある（並べて見るため）。
列 n の x = 132 + 24*(n-1)、上半分 j..f = 196..292、下半分 e..a = 336..432。

**配線を変えたらこのファイルを直して実行する。SVG を直接編集しない。**
`test_the_c4_breadboard_figure_is_generated_from_this_file` が食い違いを見張る。

    .venv/bin/python3 tools/gen_breadboard_c4.py

--------------------------------------------------------------------------
なぜこの置き方か
--------------------------------------------------------------------------
**電源の鎖を全部「下半分」に収めた。**C2 と同じ理由（溝をまたぐジャンパを
減らすと間違いが減る）。溝をまたぐのは XIAO へ渡る 3 本だけで、これは
3V3・GND が XIAO の上側のピンだから避けられない。

**シャントは電池の＋側（ハイサイド）に入れる。**手順書 §5 の警告 2 のとおり、
GND 側に入れるとオシロのアース経由で短絡し、電流が流れていても 0V に見える。

**分圧のタップはショットキーの手前（節点 A）。**USB を挿してダイオードが
切れている間も電池の電圧そのものが読めるため。かつタップはシャントより
下流なので、分圧の 1.5µA はシャントの読みを汚さない。

列の役割（下半分だけ使う。上半分は 1〜3 列の j 行以外は空き）:

    12  GND バス      電池 −（a）／100µF −（c）／R2（b）／GND ジャンパ（e）
    14  レール = 3V3  ダイオード カソード（d）／100µF ＋（c）／3V3 ジャンパ（e）
    17  分圧タップ    R1（c）／R2（b）／D0 ジャンパ（e）
    20  節点 A        スイッチから（e）／ダイオード アノード（d）／R1（c）
    23  スイッチ 出力（a）／24 共通（a）／25 空き（a）
    27  シャント と スイッチ の間
    29  電池 ＋       電池 ＋（a）／シャント（c）
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/hardware/img/breadboard-c4.svg"

VW, H = 1010, 900

BLUE, RED, GREY = "#2b4a97", "#c0392b", "#8c959d"
ORA, BLK, GOLD = "#d35400", "#333333", "#b08d57"


def col(n):
    return 132 + 24 * (n - 1)


_ROW = dict(zip("jihgfedcba", (196, 220, 244, 268, 292, 336, 360, 384, 408, 432)))


def row(r):
    return _ROW[r]


# ==========================================================================
# 挿す穴の一覧。**図・部品表・検査の唯一の出どころ。**
#
# 座標を直に書いていたときは、穴の取り違えを誰も見つけられなかった。
# ここを直せば図も表も検査も一緒に動く。
#
#   (名前, 片方の穴, もう片方の穴, 種類)
#   穴は (列, 行)。板の外（電池のリード）は None。
#   種類 wire＝ジャンパ、series＝直列に入る導体（胴体が穴をふさぐ）、
#        part＝両端が別の節点のままの部品（ダイオード・分圧・コンデンサ）
# ==========================================================================
LINKS = (
    ("電池 ＋（赤）", None, (29, "a"), "wire"),
    ("① シャント", (29, "c"), (27, "c"), "series"),   # 導体だが胴体は穴をふさぐ
    ("ジャンパ（シャント → スイッチ）", (27, "d"), (24, "e"), "wire"),
    ("② スライドスイッチ", (24, "a"), (23, "a"), "wire"),
    ("ジャンパ（スイッチ → 節点 A）", (23, "e"), (20, "e"), "wire"),
    ("③ 1N5819", (20, "d"), (14, "d"), "part"),
    ("④ R1 1MΩ", (20, "c"), (17, "c"), "part"),
    ("⑤ R2 1MΩ", (17, "b"), (12, "b"), "part"),
    ("⑥ 100µF", (14, "c"), (12, "c"), "part"),
    ("ジャンパ（レール → XIAO の 3V3）", (14, "e"), (3, "j"), "wire"),
    ("ジャンパ（GND → XIAO の GND）", (12, "e"), (2, "j"), "wire"),
    ("ジャンパ（タップ → XIAO の D0）", (17, "e"), (1, "b"), "wire"),
    ("電池 −（黒）", None, (12, "a"), "wire"),
    # 測定 B のときだけ挿す。1kΩ を迂回して起動させ、スリープしてから抜く。
    # 1kΩ を入れたままでは起動電流（2.2mA）を流せずレールが 1.35V に落ちる。
    ("起動用の短絡ジャンパ（測定 B）", (29, "d"), (27, "e"), "wire"),
)
LINK = {name: (p, q) for name, p, q, _kind in LINKS}

# XIAO のピンが刺さる穴。ここは他に使えない。
#
# **ピン間隔は 0.6 インチ＝6 ピッチなので h 行と d 行**（[Task C2](../docs/hardware/task-c2-keyscan.md) §4）。
# 行の間隔は 2.54mm、溝は 7.62mm なので、a..e が 0..4、f..j が 7..11 ピッチ。
# h(9) − d(3) = 6 で一致する。i 行と c 行だと 8 ピッチになり**入らない**。
XIAO_ROWS = ("h", "d")   # 上側 / 下側のピンが刺さる行
XIAO_PINS = {(n, XIAO_ROWS[0]): t for n, t in enumerate(("5V", "GND", "3V3", "D10", "D9", "D8", "D7"), 1)}
XIAO_PINS.update({(n, XIAO_ROWS[1]): t for n, t in enumerate(("D0", "D1", "D2", "D3", "D4", "D5", "D6"), 1)})

# 本体が上に乗って使えなくなる穴。XIAO は 1〜7 列の g〜e、スイッチは 23〜25 の b。
COVERED = {(n, r) for n in range(1, 8) for r in "gfe"} | {(n, "b") for n in (23, 24, 25)}

# 測定点。**部品の胴体が乗った穴は使えない**ので、レールと分圧の中点は
# a 行から取る。
#
# **記号（Ⓐ Ⓑ …）で呼ばない。**一度そうしたが、台の上では毎回
# 「Ⓓ はどこだったか」と図に戻る手間になった。**穴の名前で呼ぶ。**
#
#   (測るもの, 赤を当てる穴, 黒を当てる穴)
GND_HOLE = (12, "d")
PROBES = (("電池電圧", (29, "e"), GND_HOLE),
          ("シャント両端", (29, "b"), (27, "b")),
          ("レール（3V3）", (14, "a"), GND_HOLE),
          ("分圧の中点（D0 へ行く電圧）", (17, "a"), GND_HOLE))


def span(name):
    """LINKS の 1 行を (列, 列, 行) に開く。両端が同じ行であることも確かめる。"""
    p, q = LINK[name]
    assert p[1] == q[1], f"{name}: 両端の行が違う"
    return p[0], q[0], p[1]


o = []
a = o.append


def txt(x, y, s, color="#111", size=11.5, anchor="middle", bold=True):
    w = ' font-weight="bold"' if bold else ""
    a(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"{w} fill="{color}">{s}</text>')


def wire(pts, color, halo=True):
    """折れ線。halo=True なら白い縁取りを敷き、下を通る線と交差しても読める。"""
    d = "M " + " L ".join(f"{x} {y}" for x, y in pts)
    if halo:
        a(f'<path d="{d}" fill="none" stroke="#ffffff" stroke-width="6.4" '
          'stroke-linejoin="round" stroke-linecap="round"/>')
    a(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.4" '
      'stroke-linejoin="round" stroke-linecap="round"/>')
    for x, y in (pts[0], pts[-1]):
        a(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')


def badge(x, y, n, color=RED):
    a(f'<circle cx="{x}" cy="{y}" r="9" fill="#ffffff" stroke="{color}" stroke-width="1.6"/>')
    txt(x, y + 4, n, color, 11)


# ================= 見出し =================
a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VW} {H}" width="{VW}" height="{H}" '
  'font-family="Helvetica, Arial, sans-serif">')
a(f'<rect width="{VW}" height="{H}" fill="#ffffff"/>')
txt(24, 32, "Task C4・C5 — ブレッドボード上の配置（30 列 × 10 行）", size=18, anchor="start")
txt(24, 54, "電源の鎖はすべて下半分に収める。溝をまたぐのは XIAO へ渡る 3 本（GND・3V3・D0）だけ。",
    "#666", 12.5, "start", bold=False)
txt(24, 74, "乾電池は必ず 3V3 ピンへ。BAT 端子はリポ用の充電回路に直結していて、"
            "つなぐと液漏れ・破裂の危険がある。", RED, 12.5, "start")

# ================= 板 =================
a('<rect x="102" y="168" width="756" height="290" rx="9" fill="#f7f8f9" '
  'stroke="#ccd2d8" stroke-width="2"/>')
a('<rect x="102" y="304" width="756" height="20" fill="#e6eaee"/>')
txt(140, 319, "中央の溝（またがない）", GREY, 11, "start", bold=False)
for n in range(1, 31):
    for r in "jihgfedcba":
        a(f'<circle cx="{col(n)}" cy="{row(r)}" r="4" fill="none" '
          'stroke="#bcc3ca" stroke-width="1.2"/>')
for n in (1, 5, 10, 12, 14, 17, 20, 23, 25, 27, 29):
    txt(col(n), 158, str(n), GREY, 10.5, bold=False)
for r in "jihgfedcba":
    txt(88, row(r) + 4, r, GREY, 11.5, bold=False)

# ================= XIAO =================
# 本体は h 行と d 行のピンのあいだ（g・f・e 行）を覆う
BX0, BY0, BX1, BY1 = 118, row("h") + 11, 290, row("d") - 11
a(f'<rect x="{BX0}" y="{BY0}" width="{BX1-BX0}" height="{BY1-BY0}" rx="6" '
  'fill="#1f2933" stroke="#0d1216" stroke-width="2"/>')
a(f'<rect x="92" y="{(BY0+BY1)/2-16}" width="28" height="32" rx="3" fill="#b8bcc2" '
  'stroke="#8a8f96" stroke-width="1.5"/>')
txt(106, (BY0 + BY1) / 2 + 5, "USB", "#3c4147", 8.5)
txt(204, (BY0 + BY1) / 2 - 4, "XIAO", "#c9d3dc", 13, bold=False)
txt(204, (BY0 + BY1) / 2 + 13, "nRF52840", "#8b97a3", 10, bold=False)
for (n, r), t in XIAO_PINS.items():
    c = {"GND": BLK, "3V3": ORA, "D0": BLUE}.get(t, "#7d838a")
    a(f'<circle cx="{col(n)}" cy="{row(r)}" r="5" fill="#c9a227"/>')
    txt(col(n), row(r) - 13 if r == "h" else row(r) + 20, t, c, 9.5)

# ================= 節点の帯 =================
for n, t, c in ((12, "GND", BLK), (14, "レール", ORA), (17, "タップ", BLUE),
                (20, "節点 A", RED), (29, "電池 ＋", RED)):
    a(f'<rect x="{col(n)-26}" y="172" width="52" height="17" rx="3" fill="#fff" '
      f'stroke="{c}" stroke-width="1.2"/>')
    txt(col(n), 185, t, c, 9.5)

# ================= 部品 =================
def leads(x0, x1, y):
    a(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="#5a6169" stroke-width="2"/>')
    for x in (x0, x1):
        a(f'<circle cx="{x}" cy="{y}" r="4" fill="#5a6169"/>')


def resistor(c0, c1, r):
    x0, x1, y = col(c0), col(c1), row(r)
    leads(x0, x1, y)
    mx = (x0 + x1) / 2
    a(f'<rect x="{mx-24}" y="{y-9}" width="48" height="18" rx="4" fill="#f2e6cf" '
      f'stroke="{GOLD}" stroke-width="1.6"/>')
    for dx in (-10, -2, 6):
        a(f'<line x1="{mx+dx}" y1="{y-9}" x2="{mx+dx}" y2="{y+9}" stroke="#8b6d3f" stroke-width="2.4"/>')


def diode(c_anode, c_cathode, r):
    x0, x1, y = col(c_anode), col(c_cathode), row(r)
    leads(x0, x1, y)
    mx = (x0 + x1) / 2
    a(f'<rect x="{mx-28}" y="{y-10}" width="56" height="20" rx="3" fill="#3a3a3a"/>')
    band = mx + 28 - 11 if x1 > x0 else mx - 28 + 3
    a(f'<rect x="{band}" y="{y-10}" width="8" height="20" fill="#f0f0f0"/>')


def cap(c_plus, c_minus, r):
    xp, xm, y = col(c_plus), col(c_minus), row(r)
    leads(xp, xm, y)
    mx = (xp + xm) / 2
    a(f'<rect x="{mx-15}" y="{y-13}" width="30" height="26" rx="5" fill="#1f2933" stroke="#0d1216"/>')
    a(f'<rect x="{mx+7 if xm > xp else mx-15}" y="{y-13}" width="8" height="26" rx="3" fill="#d8dde2"/>')
    # 測定点 E が 12 列 d 行に来るので、極性は左右へ逃がす
    txt(xp + 16, y - 14, "＋", RED, 12)
    txt(xm - 22, y - 14, "−", BLK, 12)


resistor(*span("① シャント"))
diode(*span("③ 1N5819"))          # 帯＝カソードは 14 列側（LINKS の 2 番目が終端）
resistor(*span("④ R1 1MΩ"))
resistor(*span("⑤ R2 1MΩ"))
cap(*span("⑥ 100µF"))             # ＋が 14 列（LINKS の 1 番目）

# 番号は部品の上に置くと隣と重なるので、溝と a 行の空きへ逃がす。
for bx, by, bn, bc in ((780, 314, "①", GOLD), (516, 314, "③", "#111"), (420, 314, "⑥", "#111"),
                       (552, 432, "④", GOLD), (480, 432, "⑤", GOLD)):
    badge(bx, by, bn, bc)

# スライドスイッチ（23・24・25 の a 行）
sy = row("a")
SW_COM, SW_OUT, _ = span("② スライドスイッチ")   # LINKS は (共通, 出力) の順
SW_SPARE = SW_COM + 1
a(f'<rect x="{col(SW_OUT)-14}" y="{sy-19}" width="{col(SW_SPARE)-col(SW_OUT)+28}" height="38" rx="4" '
  'fill="#39434d" stroke="#161c22"/>')
a(f'<rect x="{col(SW_OUT)-9}" y="{sy-13}" width="32" height="26" rx="3" fill="#c9d3dc"/>')
for n in (SW_OUT, SW_COM, SW_SPARE):
    a(f'<circle cx="{col(n)}" cy="{sy}" r="4" fill="#c9a227"/>')
badge(col(SW_COM), sy - 32, "②", "#111")
txt(col(SW_OUT), sy + 32, "出力", "#111", 9.5)
txt(col(SW_COM), sy + 32, "共通", "#111", 9.5)
txt(col(SW_SPARE), sy + 32, "空き", GREY, 9.5)

# ================= 板の中のジャンパ（節点 A まで） =================
for nm in ("ジャンパ（シャント → スイッチ）", "ジャンパ（スイッチ → 節点 A）"):
    (p, q) = LINK[nm]
    wire([(col(p[0]), row(p[1])), (col(q[0]), row(q[1]))], RED, halo=False)

# 起動用の短絡ジャンパは破線。常設ではない。
_p, _q = LINK["起動用の短絡ジャンパ（測定 B）"]
a(f'<path d="M {col(_p[0])} {row(_p[1])} L {col(_q[0])} {row(_q[1])}" fill="none" '
  f'stroke="{RED}" stroke-width="2.2" stroke-dasharray="6 4"/>')
for _h in (_p, _q):
    a(f'<circle cx="{col(_h[0])}" cy="{row(_h[1])}" r="4" fill="none" '
      f'stroke="{RED}" stroke-width="1.8"/>')
txt(col(28), 476, "破線 = 起動用の短絡（測定 B のときだけ挿す）", RED, 10.5, "end")

# ================= 溝をまたぐ 3 本 =================
# 左端を回り込ませる。3 本は入れ子になっていて、交差するのは D0 の 2 か所だけ。
_p, _q = LINK["ジャンパ（GND → XIAO の GND）"]
wire([(col(_p[0]), row(_p[1])), (380, 348), (380, 482), (36, 482), (36, 136),
      (col(_q[0]), row(_q[1]))], BLK)
txt(150, 477, "GND → XIAO の GND（2 列の j 行）", BLK, 11, "start")
_p, _q = LINK["ジャンパ（レール → XIAO の 3V3）"]
wire([(col(_p[0]), row(_p[1])), (428, 348), (428, 508), (20, 508), (20, 122),
      (col(_q[0]), row(_q[1]))], ORA)
txt(150, 503, "レール → XIAO の 3V3（3 列の j 行）", ORA, 11, "start")
_p, _q = LINK["ジャンパ（タップ → XIAO の D0）"]
wire([(col(_p[0]), row(_p[1])), (500, 348), (500, 534), (132, 534),
      (col(_q[0]), row(_q[1]))], BLUE)
txt(516, 529, "分圧タップ → XIAO の D0（1 列の b 行）", BLUE, 11, "start")

# ================= 電池ボックス =================
BY = 588
a(f'<rect x="370" y="{BY}" width="460" height="80" rx="8" fill="#f2f4f6" '
  'stroke="#8c959d" stroke-width="1.8"/>')
txt(600, BY + 32, "単3 × 2（直列 3.0V）", "#111", 13)
txt(600, BY + 52, "横並びの手持ち品でよい。ケースには入らないが、ここでは支障ない", "#666", 10.5, bold=False)
for nm, cc, lb in (("電池 −（黒）", BLK, "−（黒）"), ("電池 ＋（赤）", RED, "＋（赤）")):
    _, h = LINK[nm]
    wire([(col(h[0]), row(h[1])), (col(h[0]), BY)], cc)
    txt(col(h[0]) - 12, BY - 12, f"{lb} → {h[0]} 列 {h[1]} 行", cc, 11, "end")

# ================= 測定点 =================
for n, r in sorted({h for _w, p, q in PROBES for h in (p, q)}):
    x, y = col(n), row(r)
    a(f'<circle cx="{x}" cy="{y}" r="8.5" fill="none" stroke="{RED}" stroke-width="2"/>')
    txt(x, y - 13, f"{n}{r}", RED, 9)

PROBE_ROWS = tuple(
    f"{what} …… 赤 {p[0]} 列 {p[1]} 行 ／ 黒 {q[0]} 列 {q[1]} 行"
    for what, p, q in PROBES)
a(f'<rect x="470" y="196" width="376" height="{22+len(PROBE_ROWS)*17}" rx="6" '
  'fill="#ffffff" fill-opacity="0.94" stroke="#e2c3bd" stroke-width="1.2"/>')
txt(484, 214, f"測定点（黒は {GND_HOLE[0]} 列 {GND_HOLE[1]} 行 に置いたままでよい）", RED, 11.5, "start")
for i, t in enumerate(PROBE_ROWS):
    txt(484, 232 + i * 17, t, "#3c4147", 10.5, "start", bold=False)

# ================= 下段: 要点 と 部品表 =================
LY = 700
a(f'<rect x="24" y="{LY-26}" width="556" height="192" rx="6" fill="#fafbfc" '
  'stroke="#dde1e5" stroke-width="1.2"/>')
txt(44, LY, "要点", "#111", 14, "start")
for i, t in enumerate((
        "① シャントは電池の＋側（29→27 列）。GND 側に入れてはいけない。",
        "③ ダイオードの帯＝カソードは 14 列側。逆だと 3V3 に電圧が出ない。",
        "⑥ 100µF は極性あり。＋を 14 列、−を 12 列へ。無いと 1kΩ で測れない。",
        "② スイッチは中央（24 列）が共通。ON 側はテスターの導通で確かめる。",
        "・分圧のタップはダイオードの手前。USB 中も電池電圧そのものが読める。",
        "・測定 A のときだけ USB を挿す。Mac の充電器は必ず抜くこと。",
        "・破線は測定 B のときだけ挿す。1kΩ のままでは起動できない（§6 の警告 1）。")):
    txt(44, LY + 26 + i * 22, t, "#3c4147", 12.5, "start", bold=False)

a(f'<rect x="600" y="{LY-26}" width="386" height="192" rx="6" fill="#fafbfc" '
  'stroke="#dde1e5" stroke-width="1.2"/>')
txt(618, LY, "部品（挿す場所）", "#111", 14, "start")
# 部品表も LINKS から作る。図と表が食い違わない。
PART_NOTE = {"① シャント": " 1kΩ / 10Ω"}
_parts = [(n, p, q) for n, p, q, k in LINKS if n[0] in "①②③④⑤⑥"]
for i, (n, p, q) in enumerate(_parts):
    holes = f"{p[0]} → {q[0]} 列（{p[1]} 行）"
    if n.startswith("②"):
        holes = f"{q[0]}・{p[0]}・{p[0]+1} 列（{p[1]} 行）"
    txt(618, LY + 24 + i * 17, f"{n}{PART_NOTE.get(n, '')} …… {holes}",
        "#3c4147", 11, "start", bold=False)
for i, (cc, t) in enumerate(((RED, "電池 ＋（ダイオードの手前）"), (ORA, "レール＝3V3"),
                             (BLK, "GND"), (BLUE, "分圧タップ → D0"))):
    y = LY + 24 + 6 * 17 + 6 + i * 15
    a(f'<line x1="618" y1="{y-4}" x2="642" y2="{y-4}" stroke="{cc}" stroke-width="2.6"/>')
    txt(650, y, t, cc, 11, "start")

a('</svg>')

SVG = "\n".join(o)

if __name__ == "__main__":
    OUT.write_text(SVG)
    print(f"wrote {OUT.relative_to(ROOT)}")
