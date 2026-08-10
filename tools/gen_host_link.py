#!/usr/bin/env python3
"""ホストリンク（左 ↔ Mac）の消費電流を図にする。

    .venv/bin/python3 tools/gen_host_link.py

--------------------------------------------------------------------------
測ったもの（2026-08-10）
--------------------------------------------------------------------------
左（セントラル）を C4 の治具に載せ、電池 ＋ テスター（mA 直列）で読む。
右（ペリフェラル）は基準のまま。**分割リンクは既定の 7.5ms で固定**なので、
動いているのはホストリンクだけ。

**latency 0 に固定して間隔を振った。**そうするとホストリンクが大きいまま
測れるので、「小さすぎて測れないものを 0 と置く」推論を使わずに済む。

--------------------------------------------------------------------------
**SVG を手で編集しない。**この生成器を直して実行する。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/hardware/img/host-link.svg"

# ==========================================================================
# 実測。**唯一の出どころ。**
# ==========================================================================
# latency 0 で間隔を振ったもの: 間隔[ms] → 電流[mA]
LAT0 = {15.0: 0.63, 45.0: 0.50, 60.0: 0.50}

# 候補 A（15ms・latency 30）。4 回測った
CAND_A = [0.43, 0.44, 0.43, 0.43]

# 分割リンク（7.5ms のとき）。8 点の当てはめから
SPLIT = 0.345
# 無線を全部止めたときの実測（CONFIG_ZMK_BLE=n）
CPU = 0.030

# 3 点の最小二乗（この式で描く）
K_HOST = 2.725
C_FIT = 0.447
BASE = C_FIT - SPLIT          # 底 ＝ CPU ＋ BLE スタック
STACK = BASE - CPU
HOST_15_LAT0 = K_HOST / 15
HOST_CAND_A = K_HOST / (15 * 31)

# 当てはめが実測に合っていることを、書き出すたびに確かめる
for _iv, _ma in LAT0.items():
    assert abs((C_FIT + K_HOST / _iv) - _ma) < 0.02, ("当てはめが合わない", _iv)
# そして latency 30 で測った候補 A を、この式が当てること
_pred_a = BASE + SPLIT + HOST_CAND_A
assert abs(_pred_a - sum(CAND_A) / len(CAND_A)) < 0.03, "候補 A を当てられない"

CAPACITY_MAH, HOURS_PER_MONTH = 2000, 24 * 30.4

BLUE, RED, GREY = "#2b4a97", "#c0392b", "#8c959d"
ORA, GREEN, PUR = "#d35400", "#1e8449", "#6c3483"

X0, X1, Y0, Y1 = 118, 470, 116, 400
IMIN, IMAX = 0.0, 0.70
LMIN, LMAX = 13.0, 66.0

o = []
a = o.append


def months(ma):
    return CAPACITY_MAH / ma / HOURS_PER_MONTH


def px(iv):
    from math import log
    return X0 + (log(iv) - log(LMIN)) / (log(LMAX) - log(LMIN)) * (X1 - X0)


def py(ma):
    return Y1 - (ma - IMIN) / (IMAX - IMIN) * (Y1 - Y0)


def txt(x, y, s, color="#111", size=11.5, anchor="middle", bold=True):
    s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    w = ' font-weight="bold"' if bold else ""
    a(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"{w} '
      f'fill="{color}">{s}</text>')


a('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1180 860" width="1180" '
  'height="860" font-family="Helvetica, Arial, sans-serif">')
a('<rect width="1180" height="860" fill="#ffffff"/>')

txt(24, 34, "ホストリンク（左 ↔ Mac）— 遅延を払わずに 32% 減らせた", "#111", 18, "start")
txt(24, 56, "2026-08-10 実測。分割リンクは既定の 7.5ms で固定し、ホスト側だけを動かした。",
    "#666", 12, "start", bold=False)

# ======================= ① 実測と当てはめ =======================
txt(X0, 96, "① latency 0 で間隔を振る（ホストリンクを大きいまま測る）",
    "#111", 13.5, "start")
a(f'<rect x="{X0}" y="{Y0}" width="{X1-X0}" height="{Y1-Y0}" fill="#fbfcfd" '
  'stroke="#d5dae0" stroke-width="1.5"/>')
for v in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
    y = py(v)
    a(f'<line x1="{X0}" y1="{y:.1f}" x2="{X1}" y2="{y:.1f}" stroke="#e8ecef"/>')
    txt(X0 - 10, y + 4, f"{v:.1f}", GREY, 10, "end", bold=False)
txt(X0 - 44, (Y0 + Y1) / 2, "mA", GREY, 11, bold=False)
for iv in (15, 30, 45, 60):
    x = px(iv)
    a(f'<line x1="{x:.1f}" y1="{Y0}" x2="{x:.1f}" y2="{Y1}" stroke="#e8ecef"/>')
    txt(x, Y1 + 20, f"{iv}ms", "#111", 11)
txt((X0 + X1) / 2, Y1 + 42, "ホストリンクの接続間隔", "#666", 11.5, bold=False)

pts = []
iv = LMIN
while iv <= LMAX:
    pts.append(f"{px(iv):.1f} {py(C_FIT + K_HOST / iv):.1f}")
    iv += 0.25
a('<path d="M ' + " L ".join(pts) + f'" fill="none" stroke="{RED}" '
  'stroke-width="2" opacity="0.55"/>')
for iv, ma in LAT0.items():
    a(f'<circle cx="{px(iv):.1f}" cy="{py(ma):.1f}" r="6" fill="{RED}"/>')
    txt(px(iv) + 13, py(ma) - 9, f"{ma:.2f}", RED, 11, "start")

# 候補 A（latency 30）は別の点として置く
_ay = py(sum(CAND_A) / len(CAND_A))
a(f'<circle cx="{px(15):.1f}" cy="{_ay:.1f}" r="7" fill="{GREEN}"/>')
txt(px(15) + 14, _ay + 5, "候補 A 0.43mA（15ms・latency 30）", GREEN, 11, "start")
a(f'<line x1="{px(15):.1f}" y1="{py(LAT0[15.0]):.1f}" x2="{px(15):.1f}" '
  f'y2="{_ay:.1f}" stroke="{GREEN}" stroke-width="1.6" stroke-dasharray="4 3"/>')
txt(X0 + 10, py(0.05), f"式: {C_FIT:.3f} ＋ {K_HOST:.3f} ÷ 間隔[ms]（残差 0.008 以内）",
    "#111", 11, "start")

# ======================= ② 内訳 =======================
RX = 540
txt(RX, 96, "② 0.63mA の内訳（推論を使わずに割れた）", "#111", 13.5, "start")
a(f'<rect x="{RX}" y="{Y0}" width="600" height="{Y1-Y0}" rx="8" fill="#fbfcfd" '
  'stroke="#d5dae0" stroke-width="1.5"/>')

BW = 540
for i, (label, parts) in enumerate((
        ("いま（ZMK の既定・latency 0）",
         [("CPU・DC/DC", CPU, "#8fa3bf"), ("BLE スタック", STACK, "#5f7391"),
          ("分割リンク 7.5ms", SPLIT, ORA), ("ホストリンク 15ms", HOST_15_LAT0, RED)]),
        ("候補 A（15ms・latency 30）",
         [("CPU・DC/DC", CPU, "#8fa3bf"), ("BLE スタック", STACK, "#5f7391"),
          ("分割リンク 7.5ms", SPLIT, ORA), ("ホスト", HOST_CAND_A, GREEN)]))):
    tot = sum(v for _n, v, _c in parts)
    by = Y0 + 46 + i * 108
    txt(RX + 20, by - 10, label, "#111", 12, "start")
    x = RX + 20
    for nm, v, c in parts:
        w = BW * v / 0.63
        a(f'<rect x="{x:.1f}" y="{by}" width="{w:.1f}" height="34" fill="{c}" '
          'stroke="#ffffff" stroke-width="1"/>')
        if w > 54:
            txt(x + w / 2, by + 22, f"{v:.3f}", "#ffffff", 11)
        x += w
    _lbl = (f"式から {tot:.2f}mA ／ 実測 {sum(CAND_A)/len(CAND_A):.2f}mA"
            if i == 1 else f"合計 {tot:.2f}mA（実測 {LAT0[15.0]:.2f}）")
    txt(RX + 20 + BW * tot / 0.63 + 10, by + 22, _lbl, "#111", 11.5, "start")
    # 凡例
    lx = RX + 20
    for nm, v, c in parts:
        a(f'<rect x="{lx}" y="{by+42}" width="11" height="11" fill="{c}"/>')
        txt(lx + 16, by + 52, nm, "#444", 10, "start", bold=False)
        lx += 26 + len(nm) * 10

txt(RX + 20, Y0 + 262, "latency を効かせると、ホストリンクが 30 分の 1 になる。打鍵の遅延は 1ms も増えない。", "#111", 12, "start")
txt(RX + 20, Y0 + 282, "latency は「送るものが無ければ聞かなくてよい」仕組み。"
                       "押せば次の接続イベントで送れる。", "#666", 11, "start", bold=False)

# ======================= ③ 何が起きていたか =======================
TY = 470
txt(24, TY, "③ なぜ今まで効いていなかったか — ZMK の既定が Apple の規則に違反していた",
    "#111", 13.5, "start")
a(f'<rect x="24" y="{TY+14}" width="1132" height="132" rx="8" fill="#fef6ec" '
  f'stroke="{ORA}" stroke-width="1.5"/>')
txt(44, TY + 40, "Apple Accessory Design Guidelines（2026-06-08 版）§58.6 より",
    "#111", 12, "start")
for i, (rule, ours, ok) in enumerate((
        ("Interval Min ≥ 15 ms・15 ms の倍数", "ZMK の既定は 7.5 ms", False),
        ("Peripheral Latency ≤ 30", "30", True),
        ("Supervision Timeout ＞ Interval Max ×(Latency+1)×3", "6,000 ＞ 1,395", True))):
    y = TY + 62 + i * 24
    txt(44, y, ("✕ " if not ok else "◯ ") + rule, RED if not ok else "#111",
        11.5, "start")
    txt(700, y, ours, RED if not ok else "#444", 11.5, "start", bold=not ok)
txt(44, TY + 136, "→ 要求ごと捨てられ、macOS の初期値（15ms・latency 0）のまま動いていた。latency 30 は一度も効いていなかった。", RED, 12, "start")

# ======================= ④ 交換レート =======================
TY2 = 640
txt(24, TY2, "④ 何を払って何を得るか", "#111", 13.5, "start")
cols = [(44, "設定"), (300, "電流"), (450, "打鍵の遅延（左/右）"), (700, "寿命"), (850, "左右差")]
for x, nm in cols:
    txt(x, TY2 + 22, nm, "#666", 11, "start", bold=False)
a(f'<line x1="34" y1="{TY2+30}" x2="1150" y2="{TY2+30}" stroke="#d5dae0" stroke-width="1.5"/>')
rows = [("いま（ZMK の既定）", LAT0[15.0], "10.5 / 14.25ms", "3.75ms", False),
        ("候補 A（15ms・latency 30）", sum(CAND_A) / len(CAND_A), "10.5 / 14.25ms",
         "3.75ms", True)]
for i, (nm, ma, lat, asym, hl) in enumerate(rows):
    y = TY2 + 58 + i * 40
    if hl:
        a(f'<rect x="34" y="{y-24}" width="1116" height="36" rx="5" fill="#eafaf1" '
          f'stroke="{GREEN}" stroke-width="1.5"/>')
    txt(44, y, nm, "#111", 12.5, "start")
    txt(300, y, f"{ma:.2f}mA", "#111", 12.5, "start")
    txt(450, y, lat, "#111", 12.5, "start")
    txt(700, y, f"{months(ma):.1f} ヶ月", "#111", 12.5, "start")
    txt(850, y, asym, "#111", 12.5, "start")
txt(44, TY2 + 150, "分割リンクには一切触っていない。遅延も左右差も変わらない。",
    GREEN, 12.5, "start")
txt(44, TY2 + 172, "⚠️ 未解決: 60ms を要求したとき、電流が 0.50 ⇄ 0.65mA を行き来した。"
                   "0.65 は macOS の初期値の電流と同じ。", RED, 12, "start")
txt(44, TY2 + 192, "→ 接続パラメータが行き来している疑い。ログで確かめる。"
                   "今日ずっと追ってきた「低い側」の謎と繋がるかもしれない。",
    "#666", 11.5, "start", bold=False)

a("</svg>")
OUT.write_text("\n".join(o), encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}")
print(f"  底 {BASE:.3f}（CPU {CPU:.3f} ＋ スタック {STACK:.3f}）")
print(f"  ホストリンク 15ms・latency 0  {HOST_15_LAT0:.3f}mA")
print(f"  ホストリンク 候補 A            {HOST_CAND_A:.4f}mA")
print(f"  候補 A の予測 {_pred_a:.3f} / 実測 {sum(CAND_A)/len(CAND_A):.3f}")
