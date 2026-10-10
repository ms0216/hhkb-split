"""工作手順書（GUIDE.md）の図を描く。

  .venv/bin/python3 docs/hardware/joystick/guide/guide_figs.py

帯の図は pod_layout.py / left_layout.py の配置データ（回路と突き合わせ済み）から描く。手で写さない。
部品の足の図は、図面から起こした座標（scripts/joystick_rkjxv.py と同じ値。下の check_coords が突き合わせる）。
"""
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle

HERE = Path(__file__).resolve().parent
JOY = HERE.parent
sys.path.insert(0, str(JOY / "pod_layout"))
import pod_layout as L  # noqa: E402

for f in ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
    if Path(f).exists():
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
        break

# ---- 部品の足（図面の座標・上＝軸の側から見た向き） ----
STICK_VR2 = [(-2.5, 8.73), (0.0, 8.73), (2.5, 8.73)]
STICK_VR1 = [(8.73, -2.5), (8.73, 0.0), (8.73, 2.5)]
STICK_SW = [(-3.25, -5.75), (3.25, -5.75), (-3.25, -10.25), (3.25, -10.25)]
STICK_LUGS = [(-6.325, 5.0), (6.325, 5.0), (-6.325, -5.0), (6.325, -5.0)]
STICK_A, STICK_B = (-7.3, 10.9), (-10.8, 10.9)
ENC_ABC = [(-2.5, -7.5), (0.0, -7.5), (2.5, -7.5)]
ENC_SW = [(-3.0, 7.0), (-1.0, 7.0), (1.0, 7.0), (3.0, 7.0)]
ENC_LUGS = [(-6.6, 0.0), (6.6, 0.0)]

NET_COL = {"GND": "#444444", "VDD": "#d62728", "VIN": "#ff7f0e", "TOP": "#9467bd", "SDA": "#1f77b4", "SDA線": "#1f77b4",
           "SCL": "#2ca02c", "SCL線": "#2ca02c", "X": "#8c564b", "X線": "#8c564b", "Y": "#e377c2", "Y線": "#e377c2",
           "SW": "#17becf", "SW線": "#17becf", "3V3": "#d62728", "A": "#1f77b4", "B": "#2ca02c", "ROW4": "#9467bd"}


def check_coords():
    """上の座標が scripts/joystick_rkjxv.py と同じこと（写し間違いを検出）。"""
    src = (JOY / "scripts/joystick_rkjxv.py").read_text()
    for token in ("(-2.5, 0, 2.5)] + [(8.73, b)", "[(-3.25, -5.75), (3.25, -5.75), (-3.25, -10.25), (3.25, -10.25)]",
                  "[(-6.325, 5.0), (6.325, 5.0), (-6.325, -5.0), (6.325, -5.0)]", "[(-2.5, -7.5), (0.0, -7.5), (2.5, -7.5)]",
                  "[(-3.0, 7.0), (-1.0, 7.0), (1.0, 7.0), (3.0, 7.0)]", "[(-6.6, 0.0), (6.6, 0.0)]"):
        assert token in src, f"scripts/joystick_rkjxv.py の座標と食い違う: {token}"


def save(fig, name):
    fig.savefig(HERE / name, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  ", name)


def box(ax, x, y, w, h, text, fc="#eef3ff", ec="#335", fs=12, **kw):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1.8, **kw))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, linespacing=1.4)


def arrow(ax, p, q, text="", col="#333", fs=9.5, off=(0, 0.12), lw=2.2):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-", color=col, lw=lw, zorder=1))
    if text:
        ax.text((p[0] + q[0]) / 2 + off[0], (p[1] + q[1]) / 2 + off[1], text, ha="center", va="bottom", fontsize=fs, color=col, linespacing=1.3)


# ------------------------------------------------------------------ 1. 全体
def fig_overview():
    fig, axes = plt.subplots(2, 1, figsize=(13, 8.6))
    ax = axes[0]
    ax.set_title("右手: ジョイスティック（線は全部で 13 本）", fontsize=14, loc="left")
    box(ax, 0.2, 0.5, 2.6, 1.6, "スティック\n（受け皿に載せて\nプレートのくり抜きへ）", fc="#e8e8e8")
    box(ax, 5.2, 0.5, 3.2, 1.6, "マイコンの帯\n（13×7 穴・底板に貼る）", fc="#fff3d6")
    box(ax, 10.8, 0.5, 2.2, 1.6, "右の XIAO\n（ピンの頭に\nはんだ付け）", fc="#dfeeff")
    arrow(ax, (2.8, 1.3), (5.2, 1.3), "9 本（足 1 本に線 1 本）\n上端 ×2・中点 ×2・下端 ×2\nスイッチ ×2・金属の枠 ×1", off=(0, 0.2))
    arrow(ax, (8.4, 1.3), (10.8, 1.3), "4 本\n3V3・GND\nD4・D9", off=(0, 0.2))
    ax.set_xlim(0, 13.4); ax.set_ylim(0, 3.4); ax.axis("off")
    ax = axes[1]
    ax.set_title("左手: ロータリーエンコーダ（線は全部で 10 本）", fontsize=14, loc="left")
    box(ax, 0.2, 1.0, 2.6, 1.6, "エンコーダ\n（受け皿に載せて\nプレートのくり抜きへ）", fc="#e8e8e8")
    box(ax, 5.2, 1.0, 3.2, 1.6, "小さな帯\n（6×4 穴・底板に貼る）", fc="#fff3d6")
    box(ax, 10.8, 1.0, 2.2, 1.6, "左の XIAO\n（ピンの頭に\nはんだ付け）", fc="#dfeeff")
    box(ax, 5.2, -0.9, 3.2, 1.1, "「5」のキーのソケット\n（主基板の裏のパッド）", fc="#e6f5e6", fs=11)
    arrow(ax, (2.8, 1.8), (5.2, 1.8), "4 本\na・b・C（3 本の側）\n押し込みの片方", off=(0, 0.2))
    arrow(ax, (8.4, 1.8), (10.8, 1.8), "5 本\n3V3・GND\nD4・D9・D5", off=(0, 0.2))
    arrow(ax, (1.5, 1.0), (1.5, -0.35), "")
    arrow(ax, (1.5, -0.35), (5.2, -0.35), "1 本（押し込みのもう片方）", off=(0, 0.05))
    ax.set_xlim(0, 13.4); ax.set_ylim(-1.2, 3.9); ax.axis("off")
    save(fig, "01_overview.png")


# ------------------------------------------------------------------ 2. 部品の足
def fig_stick_pins():
    """足の側（裏）から見た図。上から見た座標の a を反転する。"""
    fig, ax = plt.subplots(figsize=(8.2, 8.6))
    M = lambda p: (-p[0], p[1])   # noqa: E731  裏から見るので左右を返す
    a0, a1 = -STICK_A[1], -STICK_A[0]
    ax.add_patch(Rectangle((a0, STICK_B[0]), a1 - a0, STICK_B[1] - STICK_B[0], fc="#ececec", ec="#444", lw=2))
    ax.add_patch(Rectangle((-4.0, -11.6), 8.0, 6.6, fc="#d5d5d5", ec="#666", lw=1.2))
    ax.text(0, -12.4, "押し込みスイッチの足 4 本がある側（こちらが目印）", ha="center", fontsize=11, color="#444")
    for i, p in enumerate(STICK_VR2):
        x, y = M(p); ax.add_patch(Circle((x, y), 0.55, fc="#ffb000", ec="#333", lw=1.3))
        ax.text(x, y + 1.25, f"P{3 - i}", ha="center", fontsize=13, fontweight="bold")
    for i, p in enumerate(STICK_VR1):
        x, y = M(p); ax.add_patch(Circle((x, y), 0.55, fc="#ffb000", ec="#333", lw=1.3))
        ax.text(x - 1.5, y - 0.3, f"Q{i + 1}", ha="center", fontsize=13, fontweight="bold")
    for i, p in enumerate(STICK_SW):
        x, y = M(p); ax.add_patch(Circle((x, y), 0.5, fc="#17becf", ec="#333", lw=1.3))
        ax.text(x + (1.5 if x > 0 else -1.5), y - 0.3, f"S{i + 1}", ha="center", fontsize=13, fontweight="bold")
    for p in STICK_LUGS:
        x, y = M(p); ax.add_patch(Rectangle((x - 0.25, y - 0.7), 0.5, 1.4, fc="#666", ec="#222"))
    ax.text(M(STICK_LUGS[0])[0], 6.6, "爪", ha="center", fontsize=10, color="#444"); ax.text(M(STICK_LUGS[1])[0], 6.6, "爪", ha="center", fontsize=10, color="#444")
    ax.text(0, 2.0, "（軸はこの裏側）", ha="center", fontsize=11, color="#777")
    ax.text(-13.2, 12.6, "ジョイスティックを裏返して、足の側から見た図", fontsize=14)
    ax.text(-13.2, -15.0, "橙 = 抵抗の足（3 本組が 2 つ: P1〜P3 と Q1〜Q3）\n水色 = 押し込みスイッチの足（S1〜S4）　灰 = 金属の枠の爪（4 本）\n"
            "名前は、この手順書の中だけの呼び名。どれが「上端・中点・下端」かは 0 章で測って決める", fontsize=11, va="top", linespacing=1.5)
    ax.set_xlim(-13.5, 10); ax.set_ylim(-18.5, 13.6); ax.set_aspect("equal"); ax.axis("off")
    save(fig, "02_stick_pins.png")


def fig_encoder_pins():
    fig, ax = plt.subplots(figsize=(7.6, 7.2))
    ax.add_patch(FancyBboxPatch((-6.2, -6.6), 12.4, 13.2, boxstyle="round,pad=0.02,rounding_size=0.6", fc="#ececec", ec="#444", lw=2))
    for i, p in enumerate(ENC_ABC):
        ax.add_patch(Circle(p, 0.55, fc="#ffb000", ec="#333", lw=1.3))
        ax.text(p[0], p[1] - 1.6, ["外", "真ん中\n= C", "外"][i], ha="center", va="top", fontsize=12, fontweight="bold", linespacing=1.2)
    for i, p in enumerate(ENC_SW):
        end = i in (0, 3)
        ax.add_patch(Circle(p, 0.5, fc="#17becf" if end else "#ffffff", ec="#333", lw=1.3))
        ax.text(p[0], p[1] + 1.1, "端" if end else "×", ha="center", fontsize=12, fontweight="bold", color="#111" if end else "#999")
    for p in ENC_LUGS:
        ax.add_patch(Rectangle((p[0] - 0.2, p[1] - 1.0), 0.4, 2.0, fc="#666", ec="#222"))
        ax.text(p[0] + (1.0 if p[0] > 0 else -1.0), p[1] - 0.3, "爪", ha="center", fontsize=10, color="#444")
    ax.text(0, 0, "（軸はこの裏側）", ha="center", fontsize=11, color="#777")
    ax.text(-8.2, 11.6, "エンコーダを裏返して、足の側から見た図", fontsize=14)
    ax.text(-8.2, -12.6, "橙 = 回転の足（3 本の側）。真ん中が C（共通）、外の 2 本が 2 つの相\n"
            "水色 = 押し込みの足（4 本の側の両端）。内側の 2 本（×）は LED で、使わない\n"
            "外の 2 本のどちらを a・b と呼ぶかは、0 章で測って決める", fontsize=11, va="top", linespacing=1.5)
    ax.set_xlim(-8.6, 8.6); ax.set_ylim(-16.6, 12.6); ax.set_aspect("equal"); ax.axis("off")
    save(fig, "03_encoder_pins.png")


def fig_kit_and_updi():
    fig, ax = plt.subplots(figsize=(13, 6.4))
    ax.add_patch(FancyBboxPatch((0.4, 1.2), 10.2, 3.6, boxstyle="round,pad=0.02,rounding_size=0.1", fc="#2e9e4f", ec="#1b5e2f", alpha=0.3, lw=2))
    top = ["GND", "A3", "A2", "A1", "RST", "C3", "C2", "C1", "C0", "B0"]
    bot = ["VDD", "A4", "A5", "A6", "A7", "B5", "B4", "B3", "B2", "B1"]
    for i, (t, b) in enumerate(zip(top, bot)):
        for y, n in ((4.4, t), (1.6, b)):
            hl = n in ("GND", "VDD", "RST")
            ax.add_patch(Circle((1 + i, y), 0.22, fc="#ffd400" if hl else "#ddd", ec="#222", lw=1.4))
            ax.text(1 + i, y + (0.42 if y > 3 else -0.42), n, ha="center", va="center", fontsize=11, fontweight="bold" if hl else "normal")
    ax.text(5.5, 3.0, "マイコンのキット（シルクの面を上に見た図）", ha="center", fontsize=12, color="#1b5e2f")
    # 変換器（線は直角に引き、キットの上を横切らせない）
    box(ax, 4.6, -3.6, 3.6, 2.6, "USB シリアル\n変換器\n（FT232R）", fc="#dfeeff")
    for n, x, y, ha in (("電源", 4.4, -1.6, "right"), ("GND", 4.4, -3.0, "right"), ("TX", 8.4, -1.6, "left"), ("RX", 8.4, -3.0, "left")):
        ax.text(x, y + 0.28, n, fontsize=11, va="bottom", ha=ha, fontweight="bold")
    ax.plot([4.6, 1.0, 1.0], [-1.6, -1.6, 1.38], color="#d62728", lw=2.4); ax.text(1.2, -0.3, "電源 → VDD", color="#d62728", fontsize=11)
    ax.plot([4.6, -0.6, -0.6, 1.0, 1.0], [-3.0, -3.0, 5.6, 5.6, 4.62], color="#444", lw=2.4); ax.text(-0.4, 5.85, "GND → GND", color="#444", fontsize=11)
    ax.plot([8.2, 11.6, 11.6, 5.0, 5.0], [-3.0, -3.0, 5.6, 5.6, 4.62], color="#1f77b4", lw=2.4); ax.text(6.0, 5.85, "RX → RST（これが書き込みの線）", color="#1f77b4", fontsize=11)
    ax.plot([8.2, 9.3], [-1.6, -1.6], color="#2ca02c", lw=2.4); ax.plot([10.3, 11.6], [-1.6, -1.6], color="#2ca02c", lw=2.4)
    ax.add_patch(Rectangle((9.3, -1.9), 1.0, 0.6, fc="#d9d9d9", ec="#111", lw=1.3)); ax.add_patch(Rectangle((9.3, -1.9), 0.22, 0.6, fc="#111"))
    ax.plot(11.6, -1.6, "o", ms=7, color="#1f77b4")
    ax.text(9.8, -0.9, "BAT43（黒い帯を TX の側へ）", ha="center", fontsize=10.5, color="#2ca02c")
    ax.text(9.8, -4.0, "TX はダイオードを通って\nRX の線に合流する", ha="center", va="top", fontsize=10.5, color="#2ca02c", linespacing=1.35)
    ax.set_xlim(-1.2, 13); ax.set_ylim(-5.4, 6.8); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("マイコンへの書き込みのつなぎ方（ブレッドボードの上で。線は 4 本＋ダイオード 1 本）", fontsize=13, loc="left")
    save(fig, "04_kit_updi.png")


# ------------------------------------------------------------------ 3. 帯
def nets_and_reps():
    errs, _, find = L.check()
    assert not errs, errs
    reps = {}

    def label(h):
        items = {L.PINS.get(h)} | {f"{p}.{i + 1}" for p, (_, legs, _) in L.PARTS.items() for i, lg in enumerate(legs) if lg == h}
        if h in L.WIRES: items.add(f"線:{L.WIRES[h][0]}:{L.WIRES[h][1]}")
        for n, want in L.EXPECT.items():
            if items & want: return n
        return None
    for r in range(L.ROWS):
        for c in range(L.COLS):
            n = label((r, c))
            if n: reps[find((r, c))] = n
    return find, reps


def strip(ax, find, reps, show, solder=False, title=""):
    R, C = L.ROWS, L.COLS
    X = (lambda c: C - 1 - c) if solder else (lambda c: c)
    ax.add_patch(Rectangle((-0.6, -0.6), C + 0.2, R + 0.2, fc="#f3e2b8", ec="#8a6d2f", lw=2))
    used = set(L.PINS) | set(L.WIRES) | {h for p in L.PARTS.values() for h in p[1]} | {h for ch in L.CHAINS for h in ch} | {h for j in L.JUMPERS for h in j}
    if "kit" in show and L.PINS and not solder:
        ax.add_patch(FancyBboxPatch((0.55, -0.45), 9.9, 3.9, boxstyle="round,pad=0.02", fc="#2e9e4f", ec="#1b5e2f", alpha=0.3, lw=2))
        ax.text(5.5, 1.5, "キット", ha="center", va="center", fontsize=13, color="#1b5e2f")
    if "bridges" in show:
        for ch in L.CHAINS:
            for a, b in zip(ch, ch[1:]):
                ax.plot([X(a[1]), X(b[1])], [a[0], b[0]], color=NET_COL.get(reps.get(find(a), ""), "#999"), lw=10, alpha=0.6, solid_capstyle="round", zorder=2)
    if "jumper" in show:
        for a, b in L.JUMPERS:
            ax.plot([X(a[1]), X(b[1])], [a[0], b[0]], color="#d62728", lw=3.2, ls=(0, (6, 3)), zorder=3)
            if "kit" not in show:
                ax.text((X(a[1]) + X(b[1])) / 2, a[0] + 0.36, "被覆のジャンパ線", ha="center", fontsize=10, color="#d62728")
    for r in range(R):
        for c in range(C):
            h = (r, c); n = reps.get(find(h)) if h in used else None
            ring = "nets" in show and n
            ax.plot(X(c), r, "o", ms=12, mfc="white", mec=NET_COL.get(n, "#b89b5a") if ring else "#b89b5a", mew=2.6 if ring else 1.1, zorder=4)
            if h in L.PINS and ("kit" in show or "pins" in show):
                ax.plot(X(c), r, "s", ms=5.5, color="#222", zorder=5)
                if "pinnames" in show:
                    ax.text(X(c), r - 0.36, "RST" if L.PINS[h] == "PA0" else L.PINS[h].replace("P", "", 1) if L.PINS[h] not in ("GND", "VDD") else L.PINS[h], ha="center", va="bottom", fontsize=8, zorder=6)
    if "parts" in show and not solder:
        for name, (val, (a, b), kind) in L.PARTS.items():
            if kind == "cap" and "caps_optional" in show and name in ("Ca", "Cb"):
                continue
            xa, xb = X(a[1]), X(b[1]); mx, my = (xa + xb) / 2, (a[0] + b[0]) / 2
            ax.plot([xa, xb], [a[0], b[0]], color="#111", lw=2.2, zorder=7)
            w, hh = (0.66, 0.36) if a[0] == b[0] else (0.36, 0.66)
            if kind == "flat": w, hh = (0.36, 1.25) if a[1] == b[1] else (1.25, 0.36)
            fc = {"hair": "#ffd27f", "flat": "#ffd27f", "cap": "#9fd3ff", "diode": "#c8c8c8"}[kind]
            ax.add_patch(FancyBboxPatch((mx - w / 2, my - hh / 2), w, hh, boxstyle="round,pad=0.03", fc=fc, ec="#111", lw=1.2, zorder=8))
            ax.text(mx, my, val.replace("※", ""), ha="center", va="center", fontsize=6.4, zorder=9)
            if kind == "diode":
                bx = xb - 0.12 if xb > xa else xb + 0.02
                ax.add_patch(Rectangle((mx + (0.2 if xb > xa else -0.3), my - hh / 2), 0.1, hh, fc="#111", zorder=10))
    if "wires" in show:
        for h, (to, n) in L.WIRES.items():
            ax.plot(X(h[1]), h[0], "o", ms=9, color="#ffeb3b" if to.startswith("XIAO") else "#00c853", mec="#111", zorder=11)
    for c in range(C): ax.text(X(c), -0.95, str(c), ha="center", fontsize=10, color="#666")
    for r in range(R): ax.text(-1.0 if not solder else C, r, str(r), va="center", ha="center", fontsize=10, color="#666")
    ax.set_xlim(-1.5, C + 0.6); ax.set_ylim(R + 0.2, -1.4); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title(title, fontsize=12.5, loc="left")


def wire_table(ax, to_prefix, title, col):
    rows = [(h, n) for h, (to, n) in sorted(L.WIRES.items(), key=lambda kv: (kv[0][0], kv[0][1])) if to.startswith(to_prefix)]
    ax.axis("off"); ax.set_title(title, fontsize=12.5, loc="left")
    for i, (h, n) in enumerate(rows):
        ax.plot(0.02, 1 - 0.1 - i * 0.1, "o", ms=9, color=col, mec="#111", transform=ax.transAxes, clip_on=False)
        ax.text(0.07, 1 - 0.1 - i * 0.1, f"穴（行 {h[0]}, 列 {h[1]}）  ←  {n}", fontsize=11.5, va="center", transform=ax.transAxes)


def fig_right_strip():
    find, reps = nets_and_reps()
    fig, ax = plt.subplots(figsize=(11, 6.2))
    strip(ax, find, reps, {"jumper", "pins"}, title="手順 1: 13×7 穴に切り、被覆のジャンパ線を付ける（穴 行 2・列 1 → 行 2・列 11）。■ はあとでキットの足が入る穴")
    save(fig, "05_right_strip_1_jumper.png")
    fig, ax = plt.subplots(figsize=(11, 6.2))
    strip(ax, find, reps, {"jumper", "pins", "parts"}, title="手順 2: 抵抗（橙）とコンデンサ（水色）を挿す。抵抗は折って立てる。縦長の 330Ω だけ寝かせる")
    save(fig, "06_right_strip_2_parts.png")
    fig, ax = plt.subplots(figsize=(11, 6.2))
    strip(ax, find, reps, {"bridges", "pins", "nets"}, solder=True, title="手順 3: 裏返して（はんだ面）、色の帯のとおりに隣の穴どうしをはんだでつなぐ。★ 左右が逆。列の番号を見て数える")
    ax.text(-1.2, L.ROWS + 0.5, "灰 = GND　赤 = VDD　橙 = 3V3 の入口　紫 = 抵抗の上端　青 = SDA　緑 = SCL　茶 = X　桃 = Y　水色 = スイッチ\n"
            "⚠ 列 0（灰）と列 1（赤）の間には、はんだを流さない（電源のショートになる）", fontsize=10.5, va="top", linespacing=1.5)
    ax.set_ylim(L.ROWS + 1.6, -1.4)
    save(fig, "07_right_strip_3_bridges.png")
    fig, axes = plt.subplots(1, 2, figsize=(15.5, 6.2), gridspec_kw={"width_ratios": [1.5, 1]})
    strip(axes[0], find, reps, {"jumper", "kit", "pinnames", "parts", "wires"}, title="手順 4〜5: キットを載せ、線を挿す（黄 = XIAO へ 4 本　緑 = スティックへ 9 本）")
    ax = axes[1]; ax.axis("off")
    a1 = fig.add_axes([0.63, 0.50, 0.35, 0.36]); wire_table(a1, "XIAO", "XIAO へ行く線（黄）", "#ffeb3b")
    a2 = fig.add_axes([0.63, 0.02, 0.35, 0.44]); a2.axis("off")
    a2.set_title("スティックへ行く線（緑）", fontsize=12.5, loc="left")
    rows = [(h, n) for h, (to, n) in sorted(L.WIRES.items(), key=lambda kv: (kv[0][0], kv[0][1])) if not to.startswith("XIAO")]
    for i, (h, n) in enumerate(rows):
        a2.plot(0.02, 0.93 - i * 0.105, "o", ms=9, color="#00c853", mec="#111", transform=a2.transAxes, clip_on=False)
        a2.text(0.07, 0.93 - i * 0.105, f"穴（行 {h[0]}, 列 {h[1]}）  ←  {n}", fontsize=11, va="center", transform=a2.transAxes)
    save(fig, "08_right_strip_4_wires.png")


def fig_left_strip():
    import left_layout  # noqa: F401  （L の中身を左の帯に差し替える。副作用で left_layout_*.png も描く）
    find, reps = nets_and_reps()
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 5.0), gridspec_kw={"width_ratios": [1, 1, 1.15]})
    strip(axes[0], find, reps, {"parts", "wires", "caps_optional"}, title="部品面（黒い帯を列 5 の側へ）")
    strip(axes[1], find, reps, {"bridges", "nets"}, solder=True, title="はんだ面（左右が逆）")
    ax = axes[2]; ax.axis("off"); ax.set_title("線を挿す穴", fontsize=12.5, loc="left")
    rows = sorted(L.WIRES.items(), key=lambda kv: (not kv[1][0].startswith("XIAO"), kv[0]))
    for i, (h, (to, n)) in enumerate(rows):
        ax.plot(0.02, 0.92 - i * 0.1, "o", ms=9, color="#ffeb3b" if to.startswith("XIAO") else "#00c853", mec="#111", transform=ax.transAxes, clip_on=False)
        n2 = {"A": "a（いつも開いている相）", "B": "b（もう片方の相）", "C": "C（真ん中）", "スイッチの端子 1": "押し込みの片方"}.get(n, n)
        ax.text(0.07, 0.92 - i * 0.1, f"穴（行 {h[0]}, 列 {h[1]}）  ←  {to}: {n2}", fontsize=11, va="center", transform=ax.transAxes)
    ax.text(0.0, -0.02, "黄 = XIAO へ　緑 = エンコーダへ　橙 = 100kΩ　灰 = BAT43\nコンデンサ 2 個（行 2〜3 の列 0 と列 3）は、最初は付けない", fontsize=10.5, transform=ax.transAxes, color="#555")
    save(fig, "09_left_strip.png")


# ------------------------------------------------------------------ 4. XIAO・受け皿・隙間
def fig_xiao():
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 7.2))
    left = ["D0", "D1", "D2", "D3", "D4", "D5", "D6"]; right = ["5V", "GND", "3V3", "D10", "D9", "D8", "D7"]
    for ax, title, use in ((axes[0], "右の XIAO（スティック）", {"3V3": "帯の 3V3", "GND": "帯の GND", "D4": "帯の SCL", "D9": "帯の SDA", "D1": "（任意）押し込みを\nキーにする線"}),
                           (axes[1], "左の XIAO（エンコーダ）", {"3V3": "帯の 3V3", "GND": "帯の GND", "D4": "帯の a", "D9": "帯の b", "D5": "帯の「行 4」"})):
        ax.add_patch(FancyBboxPatch((0, 0), 6, 7.6, boxstyle="round,pad=0.02,rounding_size=0.25", fc="#1b2a44", ec="#000", lw=2))
        ax.add_patch(Rectangle((2.0, 7.0), 2.0, 1.2, fc="#bbb", ec="#333", lw=1.5)); ax.text(3, 8.5, "USB の口（こちらが奥）", ha="center", fontsize=11)
        ax.add_patch(Rectangle((1.4, 1.0), 3.2, 3.6, fc="#888", ec="#333")); ax.text(3, 2.8, "金属の\nふた", ha="center", va="center", fontsize=10, color="#fff")
        for i, (l, r) in enumerate(zip(left, right)):
            y = 6.4 - i * 0.9
            for x, n, ha, tx in ((0.35, l, "right", -0.3), (5.65, r, "left", 6.3)):
                hot = n in use
                ax.add_patch(Circle((x, y), 0.27, fc="#ffd400" if hot else "#cfcfcf", ec="#222", lw=1.6 if hot else 1))
                ax.text(tx, y, n + ("  ← " + use[n] if hot and ha == "left" else ""), ha=ha, va="center", fontsize=12 if hot else 10.5,
                        fontweight="bold" if hot else "normal", color="#000" if hot else "#777", linespacing=1.2)
                if hot and ha == "right":
                    ax.text(tx - 1.0, y, use[n] + " →", ha="right", va="center", fontsize=11, linespacing=1.2)
        ax.set_xlim(-4.2, 10.2); ax.set_ylim(-0.6, 9.2); ax.set_aspect("equal"); ax.axis("off"); ax.set_title(title, fontsize=13)
    fig.suptitle("XIAO を部品の面を上・USB を奥にして見た図。黄色のピンの頭（はんだの山）に線を付ける\n⚠ 裏のシルク（D0〜D10）で、左右の列を必ず確かめる", fontsize=12.5, y=0.86)
    save(fig, "10_xiao_pins.png")


def fig_tray_section():
    fig, ax = plt.subplots(figsize=(12.5, 5.6))
    ax.add_patch(Rectangle((-14, 0), 9.5, 1.5, fc="#c9c9c9", ec="#333")); ax.add_patch(Rectangle((4.5, 0), 9.5, 1.5, fc="#c9c9c9", ec="#333"))
    ax.text(-9.3, 0.75, "プレート", ha="center", va="center", fontsize=11); ax.text(9.3, 0.75, "プレート", ha="center", va="center", fontsize=11)
    ax.add_patch(Rectangle((-4.2, 0), 8.4, 1.5, fc="#e2c16b", ec="#333"))                      # 床
    ax.add_patch(Rectangle((-6.0, -1.0), 1.8 + 1.5, 1.0, fc="#e2c16b", ec="#333")); ax.add_patch(Rectangle((2.7, -1.0), 3.3, 1.0, fc="#e2c16b", ec="#333"))   # つば
    ax.add_patch(Rectangle((-6.0, -3.4), 1.4, 2.4, fc="#e2c16b", ec="#333")); ax.add_patch(Rectangle((4.6, -3.4), 1.4, 2.4, fc="#e2c16b", ec="#333"))       # 脚
    ax.add_patch(Rectangle((-14, -5.1), 28, 1.6, fc="#3f9a4c", ec="#333")); ax.text(-10, -4.3, "主基板", ha="center", va="center", fontsize=11, color="#fff")
    ax.add_patch(Rectangle((-3.6, 1.5), 7.2, 5.0, fc="#555", ec="#222")); ax.text(0, 4.0, "スティック\n／エンコーダ", ha="center", va="center", color="#fff", fontsize=11)
    ax.add_patch(Rectangle((-0.6, 6.5), 1.2, 3.0, fc="#555", ec="#222"))
    for x in (-2.2, 2.2):                                                                     # 足と線
        ax.add_patch(Rectangle((x - 0.12, -1.4), 0.24, 2.9, fc="#ffb000", ec="#333"))
        ax.plot([x, x, x + (1.6 if x > 0 else -1.6)], [-0.8, -2.2, -2.2], color="#d62728", lw=2.4)
    ax.add_patch(Rectangle((-1.2, -0.3), 0.9, 0.22, fc="#666", ec="#222")); ax.add_patch(Rectangle((-0.35, -0.3), 0.22, 1.8, fc="#666", ec="#222"))
    ax.annotate("受け皿の床\n（プレートのくり抜きの中）", (3.4, 0.75), (10.5, 3.6), fontsize=10.5, arrowprops=dict(arrowstyle="->"), ha="center")
    ax.annotate("つば: プレートの下に掛かる\n→ 上へ抜けない", (5.2, -0.5), (11.2, -2.2), fontsize=10.5, arrowprops=dict(arrowstyle="->"), ha="center")
    ax.annotate("脚: 主基板に乗る\n→ 下へも動かない", (-5.3, -2.6), (-11.0, -2.0), fontsize=10.5, arrowprops=dict(arrowstyle="->"), ha="center")
    ax.annotate("爪は床の下で\n内側へ倒す", (-0.8, -0.2), (-8.5, 3.6), fontsize=10.5, arrowprops=dict(arrowstyle="->"), ha="center")
    ax.annotate("線は、足にはんだ付けしてから\n長穴に通す（赤）。脚の間から外へ出す", (2.2, -2.2), (0.5, -6.6), fontsize=10.5, arrowprops=dict(arrowstyle="->"), ha="center")
    ax.set_xlim(-15, 15); ax.set_ylim(-7.6, 10); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("受け皿の留まり方（横から切った模式図・寸法は正確ではない）。プレートと主基板に挟まれて動かない", fontsize=13, loc="left")
    save(fig, "11_tray_section.png")


def fig_slot():
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.6))
    for ax, title, edge_from, lo, hi, xi in ((axes[0], "右手の基板（上から見た図・手前が自分）", "左の端", 19.5, 21.4, (1.8, 19.5)),
                                              (axes[1], "左手の基板（上から見た図・手前が自分）", "右の端", 19.6, 21.4, (1.8, 19.6))):
        mirror = edge_from == "右の端"
        X = (lambda v: 60 - v) if mirror else (lambda v: v)
        ax.add_patch(Rectangle((0, 0), 60, 14, fc="#3f9a4c", ec="#222")); ax.text(30, 6, "主基板（奥の縁のあたり）", ha="center", color="#fff", fontsize=12)
        x0, x1 = sorted((X(xi[0]), X(xi[1])))
        ax.add_patch(Rectangle((x0, 14.4), x1 - x0, 9, fc="#5b84c4", ec="#222")); ax.text((x0 + x1) / 2, 19, "XIAO と\nソケット", ha="center", va="center", color="#fff", fontsize=11)
        w0, w1 = sorted((X(hi), X(60)))
        ax.add_patch(Rectangle((w0, 14.4), w1 - w0, 2.0, fc="#bdbdbd", ec="#222")); ax.text((w0 + w1) / 2, 15.4, "受けの壁（ここは線が通らない）", ha="center", va="center", fontsize=9.5)
        s0, s1 = sorted((X(lo), X(hi)))
        ax.add_patch(Rectangle((s0, 14.0), s1 - s0, 2.6, fc="#ff3b30", ec="#900")); ax.annotate("ここだけ線が下へ降りられる\n（幅 約 1.8mm・縦に 1 列に並べる）", ((s0 + s1) / 2, 16.2), ((s0 + s1) / 2 + (20 if not mirror else -20), 30),
                                                                                            fontsize=11, ha="center", arrowprops=dict(arrowstyle="->", color="#900"), color="#900")
        e = X(0); ax.annotate("", (e, -2.2), ((s0 + s1) / 2, -2.2), arrowprops=dict(arrowstyle="<->"))
        ax.text((e + (s0 + s1) / 2) / 2, -4.4, f"{edge_from}から 約 {lo}〜{hi}mm", ha="center", fontsize=11)
        ax.text(30, -8, "↓ 手前（キーの側）", ha="center", fontsize=10, color="#555")
        ax.set_xlim(-3, 63); ax.set_ylim(-10, 36); ax.set_aspect("equal"); ax.axis("off"); ax.set_title(title + "（模式図）", fontsize=12.5)
    save(fig, "12_slot.png")


if __name__ == "__main__":
    check_coords()
    print("図:")
    fig_overview(); fig_stick_pins(); fig_encoder_pins(); fig_kit_and_updi()
    fig_right_strip(); fig_xiao(); fig_tray_section(); fig_slot()
    fig_left_strip()          # 最後（L の中身を左に差し替えるため）
