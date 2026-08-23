# -*- coding: utf-8 -*-
"""#23 の実測（手 0）の置き方を図にする。

（2026-08-23・利用者「ちょっとよくわからないので、SVG 手書き図を
起こしてくれませんか？」）

**言葉だけでは伝わらない置き方がある。**とくに C——本体基板は
アンテナの真横にも真上にも無く、**斜め上の前方**にある。
「ホイルを横に立てる」では再現できない。

    .venv/bin/python3 tools/gen_antenna_setup_svg.py
    → docs/hardware/img/antenna-hand0-setup.svg

⚠️ **絵は出したら見ること。**3 回とも文字が重なっていて、
そのつど直した（Chrome の --headless --screenshot で確認できる）。
"""
W, H = 1000, 1670
S = []
A = S.append

def txt(x, y, t, size=15, anchor="start", weight="normal", fill="#222"):
    A(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" '
      f'font-weight="{weight}" fill="{fill}" '
      f'font-family="Hiragino Sans, Noto Sans JP, sans-serif">{t}</text>')

def rect(x, y, w, h, fill="none", stroke="#333", sw=2, rx=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    A(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" '
      f'stroke="{stroke}" stroke-width="{sw}" rx="{rx}"{d}/>')

def line(x1, y1, x2, y2, stroke="#333", sw=2, dash=None, head=False):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = ' marker-end="url(#ar)"' if head else ""
    A(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
      f'stroke-width="{sw}"{d}{m}/>')

def dim(x1, y1, x2, y2, label, off=0):
    """寸法線（両端に矢印）。"""
    A(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#c0392b" '
      f'stroke-width="1.6" marker-start="url(#ar2)" marker-end="url(#ar2)"/>')
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    txt(mx, my - 6 + off, label, 14, "middle", "bold", "#c0392b")

A(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
  f'viewBox="0 0 {W} {H}">')
A('<defs>'
  '<marker id="ar" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">'
  '<path d="M0,0 L0,6 L8,3 z" fill="#333"/></marker>'
  '<marker id="ar2" markerWidth="8" markerHeight="8" refX="6" refY="2.5" orient="auto">'
  '<path d="M0,0 L0,5 L6,2.5 z" fill="#c0392b"/></marker>'
  '</defs>')
A(f'<rect width="{W}" height="{H}" fill="#fdfdfb"/>')

txt(30, 40, "#23 アンテナの実測（手 0）— 置き方", 26, "start", "bold")
txt(30, 66, "XIAO を 2 個使い、A→F の順に RSSI を測る。同じ日・同じ場所・同じ置き方で。", 15, "start", "normal", "#555")

# ---- 凡例 -------------------------------------------------------------
y0 = 92
rect(30, y0, 46, 16, "#cfe3f7", "#2c6fad")
txt(84, y0 + 13, "XIAO（基板）", 14)
rect(210, y0, 46, 16, "#f7d9d9", "#b03a3a")
txt(264, y0 + 13, "アンテナ（基板の端）", 14)
rect(420, y0 + 3, 40, 10, "#d9d9d9", "#666")
txt(468, y0 + 13, "アルミホイル", 14)
rect(590, y0, 34, 16, "#e8f0d9", "#6a8a3a")
txt(632, y0 + 13, "刷ったスペーサー", 14)
line(790, y0 + 8, 850, y0 + 8, "#e07b39", 3)
txt(858, y0 + 13, "リード線", 14)

def xiao(x, y, label=None, scale=1.0):
    """XIAO を上から。左端がアンテナ。"""
    w, h = 105 * scale, 90 * scale
    rect(x, y, w, h, "#cfe3f7", "#2c6fad", 2, 3)
    rect(x, y, 22 * scale, h, "#f7d9d9", "#b03a3a", 2, 3)
    txt(x + 11 * scale, y + h / 2 + 4, "ア", 13, "middle", "bold", "#b03a3a")
    txt(x + w / 2 + 10, y + h / 2 + 5, "XIAO", 14, "middle", "bold", "#2c6fad")
    if label:
        txt(x + w / 2, y - 8, label, 14, "middle", "bold")
    return x, y, w, h

# ---- A ----------------------------------------------------------------
yA = 150
txt(30, yA, "A  XIAO だけ（原点）", 18, "start", "bold")
txt(30, yA + 22, "まず A を 2 分見て、値がどれだけ揺れるか（ふらつきの幅）を測る。これが判定の物差し。", 14, "start", "normal", "#555")
x, y, w, h = xiao(60, yA + 36)
line(x + w + 20, y + h / 2, x + w + 150, y + h / 2, "#888", 2, "6 4", True)
txt(x + w + 160, y + h / 2 + 5, "スマホ（30cm）", 14)
txt(60, y + h + 22, "給電は USB でよい。ケーブルの向きは A〜F で変えないこと。", 13, "start", "normal", "#777")

# ---- B ----------------------------------------------------------------
yB = 350
txt(30, yB, "B  ＋ リード線（★ いちばん大事）", 18, "start", "bold")
txt(30, yB + 22, "GND ピンにジャンパで繋ぎ、アンテナの脇を通して伸ばす。160 → 80 → 40mm と切り詰めながら 3 回測る。", 14, "start", "normal", "#555")
x, y, w, h = xiao(140, yB + 50)
# リード線: XIAO の下から出て、アンテナの脇（左）を通り、そこから右へ伸ばす
A(f'<path d="M {x+70} {y+h} L {x+70} {y+h+30} L {x-60} {y+h+30} '
  f'L {x-60} {y-24} L {x+480} {y-24}" '
  f'fill="none" stroke="#e07b39" stroke-width="3.5"/>')
txt(x + 280, y + 6, "リード線（160 / 80 / 40mm と切り詰める）", 14, "start", "bold", "#e07b39")
txt(x + 76, y + h + 48, "GND ピンへ（ジャンパで挿す）", 13, "start", "normal", "#e07b39")
txt(x - 56, y + 30, "アンテナの", 12, "start", "normal", "#e07b39")
txt(x - 56, y + 46, "脇を通す", 12, "start", "normal", "#e07b39")
txt(60, y + h + 76, "⚠ 繋がっていないと「共振していない」という都合のよい答えが出る。測る前後で接触を確かめること。", 13, "start", "bold", "#b03a3a")

# ---- C ----------------------------------------------------------------
# ⚠ 2026-08-23 に描き直した。前の版は「斜め上 5mm に斜めに構える」と描いていたが
# 誤り。板を XIAO の途中に立てており、XIAO は 21mm あるのでそこには置けない。
# 実測は「板を垂直に立てて、XIAO の外側からアンテナへ近づける」で行った。
yC = 630
txt(30, yC, "C  ＋ アルミ箔を貼った板を「垂直に立てて」アンテナへ近づける", 18, "start", "bold")
txt(30, yC + 22, "アンテナは XIAO の端にある。板はその外側に、アンテナと向き合わせて立てる（XIAO の途中には置けない）。", 14, "start", "normal", "#555")
# 横から見た図
bx, by = 90, yC + 60
txt(bx, by - 8, "【横から見た図】", 14, "start", "bold")
line(bx - 20, by + 96, bx + 420, by + 96, "#aaa", 2)          # 机
txt(bx + 424, by + 100, "机", 13, "start", "normal", "#888")
rect(bx + 120, by + 84, 180, 12, "#cfe3f7", "#2c6fad")         # XIAO 断面（21mm）
rect(bx + 120, by + 84, 30, 12, "#f7d9d9", "#b03a3a")          # アンテナ（端）
txt(bx + 225, by + 78, "XIAO（21mm）", 13, "middle", "normal", "#2c6fad")
txt(bx + 135, by + 116, "アンテナ", 12, "middle", "normal", "#b03a3a")
txt(bx + 135, by + 132, "（端にある）", 11, "middle", "normal", "#b03a3a")
# アルミ箔を貼った板（垂直・XIAO の外側）
rect(bx + 80, by + 16, 12, 80, "#d9d9d9", "#666")
txt(bx + 100, by + 6, "アルミ箔を貼った板（垂直）", 13, "middle", "normal", "#555")
dim(bx + 92, by + 60, bx + 120, by + 60, "")
txt(bx + 106, by + 48, "この隙間", 13, "middle", "bold", "#c0392b")
txt(bx, by + 156, "板は XIAO の外側。立て方は自由（本に立てかける・手で持つ）。", 13, "start", "normal", "#777")
txt(bx, by + 176, "⚠ 距離は振って測る（C-近＝数 mm ／ C-遠＝約 2cm）。実測値を記録すれば後から読める。", 13, "start", "bold", "#b03a3a")

# ---- D ----------------------------------------------------------------
yD = 890
txt(30, yD, "D  ＋ 単3 電池 2 本を「横 17mm」", 18, "start", "bold")
txt(30, yD + 22, "定規で測って横に置くだけ。スペーサーは要らない。", 14, "start", "normal", "#555")
x, y, w, h = xiao(90, yD + 44)
txt(90, y - 8, "【上から見た図】", 14, "start", "bold")
# 電池
rect(x + w + 100, y + 6, 150, 26, "#efe6cf", "#8a7a3a", 2, 6)
rect(x + w + 100, y + 44, 150, 26, "#efe6cf", "#8a7a3a", 2, 6)
txt(x + w + 175, y + 24, "単3", 13, "middle", "normal", "#8a7a3a")
txt(x + w + 175, y + 62, "単3", 13, "middle", "normal", "#8a7a3a")
dim(x + 22, y + h + 24, x + w + 100, y + h + 24, "17mm（アンテナの端から）")
txt(90, y + h + 56, "アンテナは XIAO の端（赤い部分）。そこから電池までを 17mm。", 13, "start", "normal", "#777")

# ---- E / F ------------------------------------------------------------
yE = 1120
txt(30, yE, "E  B ＋ C ＋ D を全部いっぺんに（実機に近い状態）", 18, "start", "bold")
txt(30, yE + 22, "リード線・アルミ箔・電池を全部置いた状態で測る。ここが本番に近い。", 14, "start", "normal", "#555")

yF = 1180
txt(30, yF, "F  参考: アルミホイルを「真上 4mm」に水平に置く", 18, "start", "bold")
txt(30, yF + 22, "作り直す前の姿（アンテナの真上に地板があった頃）。今回の変更が何 dB 買ったかを見るためだけ。", 14, "start", "normal", "#555")
bx, by = 90, yF + 54
line(bx - 20, by + 96, bx + 420, by + 96, "#aaa", 2)
rect(bx + 60, by + 84, 120, 12, "#cfe3f7", "#2c6fad")
rect(bx + 60, by + 84, 26, 12, "#f7d9d9", "#b03a3a")
txt(bx + 120, by + 78, "XIAO", 13, "middle", "normal", "#2c6fad")
# スペーサー 4mm 側（低い）
rect(bx + 40, by + 60, 14, 24, "#e8f0d9", "#6a8a3a")
rect(bx + 190, by + 60, 14, 24, "#e8f0d9", "#6a8a3a")
txt(bx + 20, by + 116, "スペーサー 4mm 側（低いほう）", 12, "start", "normal", "#6a8a3a")
# アルミ箔（水平）
A(f'<path d="M {bx+10} {by+56} L {bx+250} {by+56}" stroke="#666" stroke-width="7" '
  f'stroke-linecap="round"/>')
txt(bx + 258, by + 60, "アルミホイル（水平）", 13, "start", "normal", "#555")
line(bx + 73, by + 84, bx + 73, by + 56, "#c0392b", 1.6)
txt(bx + 80, by + 46, "4mm", 14, "start", "bold", "#c0392b")

# ---- 判定 -------------------------------------------------------------
yJ = 1430
rect(30, yJ, W - 60, 200, "#fff8f0", "#d9a441", 2, 6)
txt(50, yJ + 28, "測ったあとの判定", 18, "start", "bold")
rows = [
    ("B が 3 本ともふらつきの幅以内", "共振していない。いちばん大きな未知が消える", "#2c7a3a"),
    ("B が長さによって大きく変わる", "共振している。FFC の長さを設計で決め打ちにできない", "#b03a3a"),
    ("B が 3 本とも同じくらい悪い（10dB 以上）", "導体が近いこと自体が効いている。引き回しで離す", "#b06a3a"),
    ("E の差が 20dB 以上", "発注しない。案 A（USB 内部延長）か案 B（モジュール変更）へ", "#b03a3a"),
]
for i, (l, r, c) in enumerate(rows):
    yy = yJ + 60 + i * 32
    txt(50, yy, "・" + l, 15, "start", "bold", c)
    txt(470, yy, "→ " + r, 14, "start", "normal", "#444")

A('</svg>')
open("docs/hardware/img/antenna-hand0-setup.svg", "w").write("\n".join(S))
print("docs/hardware/img/antenna-hand0-setup.svg")
