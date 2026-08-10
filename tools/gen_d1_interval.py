#!/usr/bin/env python3
"""D1（分割リンクの接続間隔と左半分の消費電流）の実測を図にする。

    .venv/bin/python3 tools/gen_d1_interval.py

--------------------------------------------------------------------------
測ったもの（2026-08-10）
--------------------------------------------------------------------------
左（セントラル）を C4 の治具に載せ、電池 ＋ テスター（mA 直列）で読む。
右（ペリフェラル）はタクトのボード。**c・d が打てることを確かめてから**
読んでいる（繋がっていないペリフェラルを測る間違いを避けるため）。

**触っていないのに 2 つの値を行き来した。**片方だけを「その条件の値」と
すると比較にならないので、**低い側・高い側の両方**を記録してある。

--------------------------------------------------------------------------
**SVG を手で編集しない。**この生成器を直して実行する。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/hardware/img/d1-split-interval.svg"

# ==========================================================================
# 実測。**唯一の出どころ。**
#   間隔[ms]: (低い側, 高い側)   None は未観測
# ==========================================================================
MEASURED = {
    7.5: (0.49, 0.66),
    15.0: (0.30, 0.47),
    30.0: (0.29, 0.38),
}

# 高い側の 2 点（7.5 と 15）から当てはめた。30ms は当てはめに使っていない
# ので、そこが合うかどうかが検証になる。
K = 2.850          # 分割リンク: K / 間隔[ms]  [mA]
B_HIGH = 0.280     # 間隔に依存しない部分（高い側）
B_LOW = 0.110      # 同（低い側）。差 0.17mA

CAPACITY_MAH = 2000        # アルカリ単3
HOURS_PER_MONTH = 24 * 30.4
DEBOUNCE_MS = 3.0
HOST_WAIT_MS = 7.5         # ホストリンク 15ms の平均待ち。**触れない**

BLUE, RED, GREY = "#2b4a97", "#c0392b", "#8c959d"
ORA, GREEN = "#d35400", "#1e8449"

# 描画域
X0, X1, Y0, Y1 = 118, 560, 116, 424      # 左の図（電流 vs 間隔）
IMIN, IMAX = 0.0, 0.72                   # 電流の軸
LMIN, LMAX = 5.0, 33.0                   # 間隔の軸

o = []
a = o.append


def months(ma):
    return CAPACITY_MAH / ma / HOURS_PER_MONTH


def latency(interval):
    """押してからホストに届くまでの平均。分割リンクは間隔の半分。"""
    return DEBOUNCE_MS + interval / 2 + HOST_WAIT_MS


def model(interval, base):
    return base + K / interval


def px(interval):
    return X0 + (interval - LMIN) / (LMAX - LMIN) * (X1 - X0)


def py(ma):
    return Y1 - (ma - IMIN) / (IMAX - IMIN) * (Y1 - Y0)


def txt(x, y, s, color="#111", size=11.5, anchor="middle", bold=True):
    w = ' font-weight="bold"' if bold else ""
    a(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"{w} '
      f'fill="{color}">{s}</text>')


a('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1180 700" width="1180" '
  'height="700" font-family="Helvetica, Arial, sans-serif">')
a('<rect width="1180" height="700" fill="#ffffff"/>')

txt(24, 34, "D1 — 分割リンクの接続間隔を変えると、左半分の電流はどう変わるか",
    "#111", 18, "start")
txt(24, 56, "2026-08-10 実測。左＝セントラル（C4 の治具・電池 ＋ テスター直列）／右＝ペリフェラル。"
            "c・d が打てることを確かめてから読んだ。",
    "#666", 12, "start", bold=False)

# ======================= 左: 電流 vs 間隔 =======================
txt(X0, 96, "① 実測と当てはめ", "#111", 14, "start")

# 枠と目盛
a(f'<rect x="{X0}" y="{Y0}" width="{X1-X0}" height="{Y1-Y0}" fill="#fbfcfd" '
  'stroke="#d5dae0" stroke-width="1.5"/>')
for v in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
    y = py(v)
    a(f'<line x1="{X0}" y1="{y:.1f}" x2="{X1}" y2="{y:.1f}" stroke="#e8ecef" '
      'stroke-width="1"/>')
    txt(X0 - 10, y + 4, f"{v:.1f}", GREY, 10.5, "end", bold=False)
txt(X0 - 46, (Y0 + Y1) / 2, "mA", GREY, 11, "middle", bold=False)

for iv in (7.5, 15, 30):
    x = px(iv)
    a(f'<line x1="{x:.1f}" y1="{Y0}" x2="{x:.1f}" y2="{Y1}" stroke="#e8ecef" '
      'stroke-width="1"/>')
    txt(x, Y1 + 20, f"{iv:g}ms", "#111", 11.5)
txt((X0 + X1) / 2, Y1 + 42, "分割リンクの接続間隔", "#666", 11.5, bold=False)

# 当てはめの曲線（2 本）
for base, color, dash in ((B_HIGH, RED, None), (B_LOW, BLUE, "5 4")):
    pts = []
    iv = 7.0          # 枠から出ないよう、測った範囲の少し手前から
    while iv <= LMAX:
        pts.append(f"{px(iv):.1f} {py(model(iv, base)):.1f}")
        iv += 0.25
    d = "M " + " L ".join(pts)
    a(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" '
      + (f'stroke-dasharray="{dash}" ' if dash else "") + 'opacity="0.55"/>')

# 実測点
for iv, (lo, hi) in MEASURED.items():
    x = px(iv)
    a(f'<line x1="{x:.1f}" y1="{py(lo):.1f}" x2="{x:.1f}" y2="{py(hi):.1f}" '
      f'stroke="#9aa1a8" stroke-width="1.4" stroke-dasharray="3 3"/>')
    a(f'<circle cx="{x:.1f}" cy="{py(hi):.1f}" r="6" fill="{RED}"/>')
    txt(x + 14, py(hi) - 8, f"{hi:.2f}", RED, 11.5, "start")
    a(f'<circle cx="{x:.1f}" cy="{py(lo):.1f}" r="6" fill="{BLUE}"/>')
    txt(x + 14, py(lo) + 16, f"{lo:.2f}", BLUE, 11.5, "start")

# 30ms の低い側が外れていることを名指しする
_x, _y = px(30), py(MEASURED[30.0][0])
_yp = py(model(30, B_LOW))
a(f'<circle cx="{_x:.1f}" cy="{_yp:.1f}" r="5" fill="none" stroke="{BLUE}" '
  'stroke-width="2" stroke-dasharray="3 2"/>')
a(f'<line x1="{_x:.1f}" y1="{_yp:.1f}" x2="{_x-26:.1f}" y2="{_yp+40:.1f}" '
  f'stroke="{RED}" stroke-width="1.4"/>')
txt(_x - 30, _yp + 48, "予測 0.21 ⇄ 実測 0.29。ここだけ合わない", RED, 10.5, "end")

# 凡例
_LX, _LY = X1 - 242, Y0 + 12
a(f'<rect x="{_LX}" y="{_LY}" width="230" height="62" rx="5" fill="#ffffff" '
  'stroke="#d5dae0"/>')
a(f'<circle cx="{_LX+18}" cy="{_LY+20}" r="5" fill="{RED}"/>')
txt(_LX + 32, _LY + 24, "高い側の値", "#111", 11, "start")
a(f'<circle cx="{_LX+18}" cy="{_LY+44}" r="5" fill="{BLUE}"/>')
txt(_LX + 32, _LY + 48, "低い側（待つと出る）", "#111", 11, "start")

# ======================= 右: 分解 =======================
RX = 640
txt(RX, 96, "② 何がその電流を作っているか", "#111", 14, "start")

a(f'<rect x="{RX}" y="{Y0}" width="480" height="{Y1-Y0}" rx="8" fill="#fbfcfd" '
  'stroke="#d5dae0" stroke-width="1.5"/>')

txt(RX + 20, Y0 + 34, "測った 3 点は、この式にきれいに乗る", "#111", 12.5, "start")
a(f'<rect x="{RX+20}" y="{Y0+48}" width="440" height="46" rx="6" fill="#ffffff" '
  f'stroke="{ORA}" stroke-width="2"/>')
txt(RX + 240, Y0 + 78, f"電流 ＝ {B_HIGH:.2f}mA ＋ {K:.2f} ÷ 間隔[ms]", "#111", 15)

txt(RX + 20, Y0 + 124, "内訳（7.5ms のとき）", "#111", 12.5, "start")

# 積み上げ棒
BX, BY, BW = RX + 20, Y0 + 140, 440
split75 = K / 7.5
tot = B_HIGH + split75
w_split = BW * split75 / tot
a(f'<rect x="{BX}" y="{BY}" width="{w_split:.1f}" height="34" fill="{ORA}" '
  'stroke="#a04000"/>')
a(f'<rect x="{BX+w_split:.1f}" y="{BY}" width="{BW-w_split:.1f}" height="34" '
  'fill="#8fa3bf" stroke="#5f7391"/>')
txt(BX + w_split / 2, BY + 22, f"分割リンク {split75:.2f}mA", "#ffffff", 12)
txt(BX + w_split + (BW - w_split) / 2, BY + 22, f"それ以外 {B_HIGH:.2f}mA",
    "#ffffff", 12)
txt(BX, BY + 52, "← 間隔に反比例して減らせる", ORA, 11, "start")
txt(BX + BW, BY + 52, "触れない →", "#5f7391", 11, "end")

_gaps = " ／ ".join(f"{iv:g}ms {hi-lo:.2f}" for iv, (lo, hi) in MEASURED.items())
txt(RX + 20, BY + 92, f"高い側と低い側の差： {_gaps}  [mA]", "#111", 12, "start")
txt(RX + 20, BY + 110,
    "7.5 と 15 は 0.17mA でそろうが、30ms だけ 0.09mA。そろわない。",
    RED, 11.5, "start")
txt(RX + 20, BY + 128,
    "30ms の低い側が出きっていないのか、状態が 2 つではないのか、未解明。",
    "#666", 11.5, "start", bold=False)

# ======================= 下: 交換レート =======================
TY = 512
txt(24, TY - 16, "③ 交換レート — 何を払って何を得るか", "#111", 14, "start")

cols = [(60, "接続間隔"), (200, "電流（高い側）"), (390, "寿命"),
        (560, "合計遅延"), (730, "既定からの差"), (960, "評価")]
for x, name in cols:
    txt(x, TY + 6, name, "#666", 11.5, "start", bold=False)
a(f'<line x1="50" y1="{TY+14}" x2="1140" y2="{TY+14}" stroke="#d5dae0" '
  'stroke-width="1.5"/>')

rows = []
for iv in (7.5, 15.0, 30.0):
    hi = MEASURED[iv][1]
    rows.append((iv, hi, months(hi), latency(iv)))

base_m, base_l = rows[0][2], rows[0][3]
for i, (iv, ma, mo, lat) in enumerate(rows):
    y = TY + 46 + i * 42
    hl = i == 1
    if hl:
        a(f'<rect x="50" y="{y-26}" width="1090" height="38" rx="5" '
          f'fill="#fef6ec" stroke="{ORA}" stroke-width="1.5"/>')
    label = f"{iv:g}ms" + ("（ZMK の既定）" if i == 0 else "")
    txt(60, y, label, "#111", 12.5, "start")
    txt(200, y, f"{ma:.2f}mA", "#111", 12.5, "start")
    txt(390, y, f"{mo:.1f} ヶ月", "#111", 12.5, "start")
    txt(560, y, f"{lat:.2f}ms", "#111", 12.5, "start")
    if i == 0:
        txt(730, y, "—", GREY, 12.5, "start")
        txt(960, y, "いま", GREY, 12, "start", bold=False)
    else:
        txt(730, y, f"＋{mo-base_m:.1f} ヶ月 ／ 遅延 ＋{lat-base_l:.2f}ms",
            "#111", 12.5, "start")
        gain = (mo - base_m) / (lat - base_l)
        txt(960, y, f"1ms あたり {gain:.2f} ヶ月", GREEN if i == 1 else GREY,
            12, "start")

y = TY + 46 + 3 * 42 + 10
txt(60, y, "⚠️ 打鍵の体感は、この治具では判定できない。"
           "タクトスイッチ 2 個をつつくのと、キーキャップを付けて文章を打つのは別物。",
    RED, 12, "start")
txt(60, y + 20, "15ms・30ms とも「違和感なし」との報告はあるが、"
                "完成品で目隠しにして測り直す（D2）。",
    "#666", 11.5, "start", bold=False)

a("</svg>")
OUT.write_text("\n".join(o), encoding="utf-8")

# --- 当てはめが実測に合っているかを、書き出すたびに確かめる ------------
for _iv, (_lo, _hi) in MEASURED.items():
    assert abs(model(_iv, B_HIGH) - _hi) < 0.02, ("高い側が合わない", _iv)
assert abs(model(7.5, B_LOW) - MEASURED[7.5][0]) < 0.02
assert abs(model(15.0, B_LOW) - MEASURED[15.0][0]) < 0.02
# **30ms の低い側は合わない。**合わないことを、ここで固定しておく。
assert abs(model(30.0, B_LOW) - MEASURED[30.0][0]) > 0.05, \
    "30ms の低い側がモデルに合うようになった。図の注記を見直すこと"

print(f"wrote {OUT.relative_to(ROOT)}")
for _iv in (7.5, 15.0, 30.0):
    print(f"  {_iv:>4g}ms  {MEASURED[_iv][1]:.2f}mA  "
          f"{months(MEASURED[_iv][1]):.1f} ヶ月  遅延 {latency(_iv):.2f}ms")
