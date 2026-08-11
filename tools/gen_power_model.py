#!/usr/bin/env python3
"""左（セントラル）の消費電流を、部品ごとに分けて図にする。

    .venv/bin/python3 tools/gen_power_model.py

--------------------------------------------------------------------------
何の図か
--------------------------------------------------------------------------
**2026-08-10〜11 に測った 3 つの実験を 1 枚にまとめたもの。**

  D1        分割リンクの間隔を 8 点振った     → Ksplit
  ホスト側  ホストリンクの間隔を 3 点振った   → Khost（**弱い。下を読む**）
  床        走査・SPI・595 の上乗せを測った   → 0（分解能以下）

**「どの設定を変えると、どれだけ効くか」を、理屈と実データの両方で読める
ようにするのが目的。**採否は決めない。

--------------------------------------------------------------------------
式
--------------------------------------------------------------------------
    I = 床 ＋ スタック ＋ Ksplit ÷ 分割間隔 ＋ Khost ÷ (ホスト間隔 × (latency+1))

**無線イベント 1 回あたりの費用が一定**という前提。Ksplit と Khost が
近い値（2.59 と 2.73）になったことが、この前提の傍証になっている。

--------------------------------------------------------------------------
**SVG を手で編集しない。**この生成器を直して実行する。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/hardware/img/power-model.svg"

# ==========================================================================
# 実測。**唯一の出どころ。**
# ==========================================================================
CPU = 0.030          # CONFIG_ZMK_BLE=n の直接実測
STACK = 0.060        # 底 0.090 − CPU。latency 0 の掃引から（推論なし）
K_SPLIT = 2.591      # 分割リンクを 8 点振った当てはめ I = 0.287 + K/間隔
K_HOST = 2.725       # ホストリンクを 3 点振った当てはめ。**実質 2 点。弱い**
# 送信電力を 0dBm → +8dBm にしたときの上乗せ。**1 イベントあたりの追加費用。**
# Nordic のデータシート（DC/DC 3V）TX 0dBm 4.9mA / +8dBm 14.1mA、
# 空パケット 80µs（1M PHY）から 9.2mA × 80µs = 0.736 mA·ms。
# **分割 7.5ms で実測 +0.10mA（0.44 → 0.54）。計算 +0.098 と一致した。**
K_TX8 = 0.736

FLOOR_JIG = CPU + STACK           # 治具の床（595 は載っていない）
SHIFTER_IQ = 0.020                # 74LVC595 ×2 の静止電流。**データシート**

# 床の実測（BLE 無し・電池を入れ直して測った）
FLOOR_MEASURED = {"proto_direct": 0.03, "proto_matrix": 0.02, "proto_shift": 0.03}

CAPACITY_MAH, HOURS_PER_MONTH = 2000, 24 * 30.4

# 並べる構成: (名前, 分割間隔[ms], ホスト間隔[ms], latency, TX+8dBm, 実測 or None, 注)
# **5 つとも実測済み。**すべて UART の宣言を外したファームで測っている。
CONFIGS = (
    ("既定（ZMK のまま）", 7.5, 15.0, 0, False, 0.63, "latency 30 を要求していたが Apple の規則違反で捨てられていた"),
    ("候補 A", 7.5, 15.0, 30, False, 0.43, "遅延も左右差も動かない。Mac・Windows とも同じ値"),
    ("候補 A ＋ 分割 15ms", 15.0, 15.0, 30, False, 0.27, "右手だけ平均 +3.75ms。打鍵の違和感は無かった（目隠しではない）"),
    ("候補 A ＋ 分割 30ms", 30.0, 15.0, 30, False, 0.18, "右手だけ平均 +7.5ms。実測は 0.14〜0.21 で振れた"),
    ("候補 A ＋ TX +8dBm", 7.5, 15.0, 30, True, 0.54, "電波の余裕を買う。**寿命を 1.1 ヶ月払う**"),
)


def split_ma(interval):
    return K_SPLIT / interval


def host_ma(interval, latency):
    return K_HOST / (interval * (latency + 1))


def tx8_ma(split_iv, host_iv, latency):
    """送信電力を +8dBm にしたときの上乗せ。**送信 1 回ごとに乗る。**"""
    return K_TX8 / split_iv + K_TX8 / (host_iv * (latency + 1))


def total_ma(split_iv, host_iv, latency, tx8=False):
    i = FLOOR_JIG + split_ma(split_iv) + host_ma(host_iv, latency)
    return i + tx8_ma(split_iv, host_iv, latency) if tx8 else i


def months(ma):
    return CAPACITY_MAH / ma / HOURS_PER_MONTH


# ---- 書き出すたびに、当てはめが実測を当てることを確かめる ----------------
for _name, _s, _h, _l, _tx, _meas, _note in CONFIGS:
    if _meas is None:
        continue
    assert abs(total_ma(_s, _h, _l, _tx) - _meas) < 0.035, ("当てはめが実測から離れた", _name)
# 分割リンクの当てはめの定数項は「分割リンク以外の全部」なので、
# 床 ＋ ホストリンク(15ms・latency 0) と一致していなければならない
assert abs(0.287 - (FLOOR_JIG + host_ma(15.0, 0))) < 0.02, "2 つの当てはめが噛み合わない"
# 床の実測は 3 本とも分解能内で同じ
assert max(FLOOR_MEASURED.values()) - min(FLOOR_MEASURED.values()) <= 0.01

BLUE, RED, GREY = "#2b4a97", "#c0392b", "#8c959d"
ORA, GREEN, PUR, BLK = "#d35400", "#1e8449", "#6c3483", "#333333"

W, H = 1240, 1260
o = []
a = o.append


def txt(x, y, s, color="#111", size=11.5, anchor="middle", bold=True):
    # **強調** は Markdown の書き方。SVG では意味が無いので落とす
    # （2026-08-11 に生のまま図に出た）
    s = str(s).replace("**", "")
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    w = ' font-weight="bold"' if bold else ""
    a(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"{w} '
      f'fill="{color}">{s}</text>')


a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
  f'height="{H}" font-family="Helvetica, Arial, sans-serif">')
a(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

txt(24, 36, "左（セントラル）の消費電流 — 何が食っていて、どこを変えると効くか",
    "#111", 19, "start")
txt(24, 58, "2026-08-10〜11 の実測。電池 ＋ テスター（mA 直列）。"
            "**5 つとも実測。**UART の宣言を外し、電池を入れ直してから読んだ値。",
    "#666", 12, "start", bold=False)

# ==========================================================================
# ① 積み上げ
# ==========================================================================
BX0, BX1 = 300, 900
BY = 118
BH, BGAP = 46, 34
IMAX = 0.70

txt(24, BY - 44, "① 内訳と、設定を変えたときの姿（**5 つとも実測**）", "#111", 14.5, "start")


def bx(ma):
    return BX0 + ma / IMAX * (BX1 - BX0)


# 目盛
for v in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
    x = bx(v)
    a(f'<line x1="{x:.1f}" y1="{BY}" x2="{x:.1f}" y2="{BY + len(CONFIGS)*(BH+BGAP)}" '
      'stroke="#e8ecef"/>')
    txt(x, BY - 22, f"{v:.1f}", GREY, 10, bold=False)
txt(BX1 + 34, BY - 22, "mA", GREY, 10, "start", bold=False)

for i, (name, s_iv, h_iv, lat, tx8, meas, note) in enumerate(CONFIGS):
    y = BY + i * (BH + BGAP)
    parts = (
        ("CPU・DC/DC", CPU, "#9aa1a8"),
        ("BLE スタック", STACK, PUR),
        ("分割リンク", split_ma(s_iv), RED),
        ("ホストリンク", host_ma(h_iv, lat), BLUE),
        ("TX +8dBm の上乗せ", tx8_ma(s_iv, h_iv, lat) if tx8 else 0.0, ORA),
    )
    x = BX0
    for _pn, ma, color in parts:
        w = bx(ma) - BX0
        a(f'<rect x="{x:.1f}" y="{y}" width="{max(w,0.6):.1f}" height="{BH}" '
          f'fill="{color}" stroke="#ffffff" stroke-width="1"/>')
        if w > 42:
            txt(x + w / 2, y + BH / 2 + 4, f"{ma:.3f}", "#ffffff", 11)
        x += w
    tot = total_ma(s_iv, h_iv, lat, tx8)
    txt(24, y + BH / 2 - 2, name, "#111", 12.5, "start")
    txt(24, y + BH / 2 + 15,
        f"分割 {s_iv:g}ms ／ ホスト {h_iv:g}ms・latency {lat}"
        + ("／ TX +8dBm" if tx8 else ""), "#777", 10.5, "start", bold=False)
    txt(x + 12, y + BH / 2 - 3, f"{tot:.3f} mA", "#111", 12.5, "start")
    txt(x + 12, y + BH / 2 + 14, f"{months(tot):.1f} ヶ月", GREEN, 12, "start")
    if meas is not None:
        a(f'<circle cx="{bx(meas):.1f}" cy="{y - 7}" r="5" fill="#111"/>')
        txt(bx(meas) - 10, y - 3, f"実測 {meas:.2f}", "#111", 10.5, "end")
    else:
        txt(x + 12, y + BH / 2 + 30, "（未実測・式からの予測）", GREY, 9.5, "start",
            bold=False)
    txt(BX0, y + BH + 15, note.replace("**", ""), "#777", 10, "start", bold=False)

LY = BY + len(CONFIGS) * (BH + BGAP) + 18
for j, (pn, color) in enumerate((("CPU・DC/DC・分圧", "#9aa1a8"), ("BLE スタック", PUR),
                                 ("分割リンク（左 ↔ 右）", RED),
                                 ("ホストリンク（左 ↔ PC）", BLUE),
                                 ("TX +8dBm の上乗せ", ORA))):
    x = BX0 + j * 150
    a(f'<rect x="{x}" y="{LY}" width="13" height="13" fill="{color}"/>')
    txt(x + 18, LY + 11, pn, "#555", 10, "start", bold=False)
txt(24, LY + 11, "● ＝ 実測値", "#111", 10.5, "start")

# ==========================================================================
# ② 式
# ==========================================================================
FY = LY + 46
txt(24, FY, "② 使っている式と、その根拠", "#111", 14.5, "start")
a(f'<rect x="24" y="{FY+12}" width="{W-48}" height="132" rx="8" fill="#f7f9fb" '
  'stroke="#d5dae0"/>')
txt(44, FY + 40,
    "I  =  床 0.090  +  2.591 ÷ 分割間隔[ms]  +  2.725 ÷ ( ホスト間隔[ms] × (latency+1) )"
    "   [ +8dBm なら さらに 0.736 ÷ 同じ 2 つ ]",
    "#111", 13, "start")
txt(44, FY + 66,
    "前提: 無線イベント 1 回あたりの費用は、相手が右手でもホストでも同じ。"
    "→ 2 つの係数が近い値（2.591 と 2.725）になったことが傍証。",
    "#555", 11, "start", bold=False)
txt(44, FY + 88,
    "latency は「送るものが無いとき、何回まで聞き逃してよいか」。"
    "送るものがあれば次の機会に送るので、打鍵の遅延は増えない。",
    "#555", 11, "start", bold=False)
txt(44, FY + 110,
    "検算: 0.617/0.63・0.441/0.43・0.269/0.27・0.182/0.18・0.541/0.54。"
    "**5 点すべてで残差 0.01mA 以内。**予測してから測って当てた点が 3 つある。",
    GREEN, 11, "start", bold=False)
txt(44, FY + 130,
    f"⚠️ 本番はこれに 74LVC595 の静止電流 {SHIFTER_IQ:.2f}mA（データシート・右は 2 個）が乗る。",
    ORA, 11, "start", bold=False)

# ==========================================================================
# ③ レバー
# ==========================================================================
TY = FY + 176
txt(24, TY, "③ どのレバーが、どれだけ効くか", "#111", 14.5, "start")

LEVERS = (
    ("分割リンクを 7.5 → 30ms",
     f"−{split_ma(7.5)-split_ma(30):.3f}mA", f"＋{months(0.182)-months(0.441):.1f} ヶ月",
     "右手だけ平均 +7.5ms。左右差", "**実測 0.18mA**（0.14〜0.21 で振れる）", GREEN),
    ("分割リンクを 7.5 → 15ms",
     f"−{split_ma(7.5)-split_ma(15):.3f}mA", f"＋{months(0.269)-months(0.441):.1f} ヶ月",
     "右手だけ平均 +3.75ms。左右差", "**実測 0.27mA**。打鍵の違和感は無し（目隠しでない）", GREEN),
    ("ホストの latency を 0 → 30",
     f"−{host_ma(15,0)-host_ma(15,30):.3f}mA", f"＋{months(0.441)-months(0.617):.1f} ヶ月",
     "**なし**", "実測（Mac・Windows とも 0.43）＋ログで受理を確認", GREEN),
    ("送信電力を 0 → +8dBm",
     f"＋{tx8_ma(7.5,15,30):.3f}mA", f"−{months(0.441)-months(0.541):.1f} ヶ月".replace("−-", "−"),
     "電波の余裕を買う（左だけ強くなる）", "**実測 0.54mA**。ZMK の「無視できる」は当てはまらない", RED),
    ("ホストの間隔 15 → 60ms（latency 30 のまま）",
     f"−{host_ma(15,30)-host_ma(60,30):.3f}mA", "＋0.1 ヶ月",
     "両手に +22ms", "式。**分解能以下なので実測で確かめられない**", GREY),
    ("マトリクス走査・595 の駆動をやめる",
     "0.00mA", "±0",
     "—", "実測（direct 0.03 / matrix 0.02 / shift 0.03）", GREY),
)

COLS = (24, 400, 520, 650, 890)
HEADS = ("変えるもの", "電流の変化", "寿命の変化", "払う代償", "何で確かめたか")
for cx, h in zip(COLS, HEADS):
    txt(cx, TY + 26, h, "#555", 11, "start")
a(f'<line x1="24" y1="{TY+32}" x2="{W-24}" y2="{TY+32}" stroke="#ccd2d8"/>')
for i, (nm, dma, dmo, cost, ev, color) in enumerate(LEVERS):
    y = TY + 54 + i * 30
    txt(COLS[0], y, nm, "#111", 11.5, "start")
    txt(COLS[1], y, dma, color, 11.5, "start")
    txt(COLS[2], y, dmo, color, 11.5, "start")
    txt(COLS[3], y, cost, "#555", 11, "start", bold=False)
    txt(COLS[4], y, ev.replace("**", ""), "#777", 10.5, "start", bold=False)

# ==========================================================================
# ④ 確かさ
# ==========================================================================
CY = TY + 54 + len(LEVERS) * 30 + 26
txt(24, CY, "④ どこまで確かか", "#111", 14.5, "start")
CERT = (
    ("強い", GREEN,
     "分割リンクの係数 2.591 — 8 点の当てはめに加え、15ms と 30ms を**予測してから実測して当てた**"),
    ("強い", GREEN,
     "床が増えないこと — 3 本のファームで実測。差はすべて分解能以下"),
    ("強い", GREEN,
     "候補 A の 0.43mA — Mac・Windows・電池入れ直しで一致。macOS はログで受理を確認"),
    ("強い", GREEN,
     "TX +8dBm の +0.10mA — データシートから計算した +0.098 を、測って当てた"),
    ("弱い", RED,
     "ホストリンクの係数 2.725 — 3 点だが 45ms と 60ms が同値。実質 2 点・未知数 2 個で自由度 0"),
    ("未確認", GREY,
     "Windows の実際の interval / latency — 更新イベントを出さないので読めない。電流が同じことだけが分かっている"),
    ("未確認", GREY,
     "打鍵感（D2）— 15ms・30ms とも「違和感なし」だが、目隠しでなく右の 1 キーだけ。判断材料にはならない"),
    ("未確認", GREY,
     "本番基板の電波環境（アンテナ #23・左右の距離・人体）。再送が増えれば全部の値が上がる"),
)
for i, (tag, color, s) in enumerate(CERT):
    y = CY + 26 + i * 22
    a(f'<rect x="24" y="{y-12}" width="52" height="17" rx="3" fill="{color}" '
      'opacity="0.16"/>')
    txt(50, y, tag, color, 10.5)
    txt(88, y, s.replace("**", ""), "#444", 11, "start", bold=False)

txt(24, H - 22,
    "生成: tools/gen_power_model.py — SVG を手で編集しない",
    "#aab1b8", 10, "start", bold=False)

a("</svg>")
OUT.write_text("\n".join(o), encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}")
for name, s_iv, h_iv, lat, tx8, meas, _n in CONFIGS:
    t = total_ma(s_iv, h_iv, lat, tx8)
    m = f"  実測 {meas:.2f}" if meas is not None else ""
    print(f"  {name:24s} {t:.3f} mA  {months(t):5.1f} ヶ月{m}")
