"""右手のマイコンの帯（ユニバーサル基板 13×7 穴）の穴ごとの配置。データ → 検査 → 図。

  .venv/bin/python3 build/joystick/pod_layout/pod_layout.py          # 検査して図を出す
  .venv/bin/python3 build/joystick/pod_layout/pod_layout.py --break  # 検査が壊れた配置に気づくか（自己試験）

穴は (行, 列)。行 0〜6・列 0〜12。**部品面から見た向き**で書く。
キット（ATtiny1616 DIP 化・秋月 g130229）は列 1〜10、ピンの列は 行 0（GND の側）と 行 3（VDD の側）。
決まり: 穴 1 つに足 1 本。つなぎは「隣どうしのはんだブリッジ」だけ（例外は VDD のジャンパ線 1 本）。
"""
import sys
from itertools import combinations

ROWS, COLS = 7, 13
ROW_B = ["GND", "PA3", "PA2", "PA1", "PA0", "PC3", "PC2", "PC1", "PC0", "PB0"]   # 行 0・列 1〜10（キットのシルク [写真]）
ROW_A = ["VDD", "PA4", "PA5", "PA6", "PA7", "PB5", "PB4", "PB3", "PB2", "PB1"]   # 行 3・列 1〜10
PINS = {(0, c + 1): n for c, n in enumerate(ROW_B)} | {(3, c + 1): n for c, n in enumerate(ROW_A)}

# 部品: 名前 → (値, 足の穴 2 つ, 置き方)。hair=折って立てる（隣の穴）、flat=寝かせる
PARTS = {
    "C1":      ("10µF",  ((6, 1), (6, 0)), "cap"),      # 秋月 g116018 は足 5mm・幅 5.5×厚み 3.15×高さ 4。足を内へ曲げて 2.54 に挿す。
                                                    # **板の端の行に置く**: 行 4 だとキットの縁（ピンの外 約 1.3mm）に 0.3mm 当たる（粗探しで発覚）
    "C2":      ("0.1µF", ((4, 1), (4, 0)), "cap"),      # 小さい方（厚み 2.5）をキットの側へ
    "R1":      ("33Ω",   ((5, 1), (5, 2)), "hair"),     # **小型の品 g108517（3.3×φ1.8）**。1/4W の g103941 は胴 6.3mm で立てると背が高すぎる
    "Rw_X":    ("1kΩ",   ((4, 3), (5, 3)), "hair"),
    "Rk":      ("1kΩ",   ((4, 4), (5, 4)), "hair"),
    "Rw_Y":    ("1kΩ",   ((4, 5), (5, 5)), "hair"),
    "Rs_SDA":  ("330Ω",  ((4, 10), (4, 9)), "hair"),
    "Rpu_SDA": ("6.8kΩ", ((5, 10), (5, 11)), "hair"),
    "Cf_SDA":  ("100pF", ((6, 10), (6, 11)), "cap"),
    "Rs_SCL":  ("330Ω",  ((0, 12), (2, 12)), "flat"),
    "Rpu_SCL": ("6.8kΩ", ((3, 12), (3, 11)), "hair"),
    "Cf_SCL":  ("100pF", ((4, 12), (4, 11)), "cap"),
}
# 外へ出る線: 穴 → (行き先, 名前)
WIRES = {
    (6, 2): ("XIAO", "3V3"), (1, 0): ("XIAO", "GND"), (5, 9): ("XIAO", "D9 (SDA)"), (5, 12): ("XIAO", "D4 (SCL)"),
    # **スティックの足 1 本につき線 1 本**（足どうしを先に渡り線でつなぐと、受け皿の長穴を通せない）。
    # 同じ行き先の線は、帯の上で同じ網の別の穴に挿す。計 9 本
    (6, 6): ("スティック", "X の抵抗の上端"), (5, 6): ("スティック", "Y の抵抗の上端"),
    (6, 3): ("スティック", "X の中点"), (6, 5): ("スティック", "Y の中点"), (6, 4): ("スティック", "スイッチ"),
    (5, 0): ("スティック", "X の抵抗の下端"), (3, 0): ("スティック", "Y の抵抗の下端"),
    (2, 0): ("スティック", "スイッチの片側"), (0, 0): ("スティック", "金属の枠（爪）"),
}
# はんだブリッジ（隣の穴どうし）。鎖は順に書く
CHAINS = [
    [(0, 1), (0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0)],      # GND: ピン → 列 0 を端から端まで
    [(2, 1), (3, 1), (4, 1), (5, 1), (6, 1)],                               # VDD: ピンの上下
    [(5, 2), (6, 2)],                                                       # 3V3 の入口（R1 の手前）
    [(3, 3), (4, 3)], [(5, 3), (6, 3)],                                     # X: ピン―Rw―線
    [(3, 4), (4, 4)], [(5, 4), (6, 4)],                                     # スイッチ
    [(3, 5), (4, 5)], [(5, 5), (6, 5)],                                     # Y
    [(3, 6), (4, 6), (5, 6), (6, 6)], [(3, 7), (4, 7), (4, 6)],             # 上端: PB5 と PB4 を束ねて線へ
    [(3, 10), (4, 10)],                                                     # SDA のピン
    [(4, 9), (5, 9), (5, 10), (6, 10)],                                     # SDA の線の側
    [(0, 10), (0, 11), (0, 12)],                                            # SCL のピン
    [(2, 12), (3, 12), (4, 12), (5, 12)],                                   # SCL の線の側
    [(2, 11), (3, 11), (4, 11), (5, 11), (6, 11)],                          # VDD（奥の端）
]
JUMPERS = [((2, 1), (2, 11))]            # 被覆線 1 本。部品面・キットの下をくぐる（行 2）

# 期待する回路: 網の名前 → そこに居るべきもの（ピン名・部品の足「名前.番号」・線）
EXPECT = {
    "GND":   {"GND", "C1.2", "C2.2", "線:XIAO:GND", "線:スティック:X の抵抗の下端", "線:スティック:Y の抵抗の下端",
              "線:スティック:スイッチの片側", "線:スティック:金属の枠（爪）"},
    "VDD":   {"VDD", "C1.1", "C2.1", "R1.1", "Rpu_SDA.2", "Cf_SDA.2", "Rpu_SCL.2", "Cf_SCL.2"},
    "VIN":   {"R1.2", "線:XIAO:3V3"},
    "X":     {"PA5", "Rw_X.1"}, "X線": {"Rw_X.2", "線:スティック:X の中点"},
    "SW":    {"PA6", "Rk.1"},   "SW線": {"Rk.2", "線:スティック:スイッチ"},
    "Y":     {"PA7", "Rw_Y.1"}, "Y線": {"Rw_Y.2", "線:スティック:Y の中点"},
    "TOP":   {"PB5", "PB4", "線:スティック:X の抵抗の上端", "線:スティック:Y の抵抗の上端"},
    "SDA":   {"PB1", "Rs_SDA.1"}, "SDA線": {"Rs_SDA.2", "Rpu_SDA.1", "Cf_SDA.1", "線:XIAO:D9 (SDA)"},
    "SCL":   {"PB0", "Rs_SCL.1"}, "SCL線": {"Rs_SCL.2", "Rpu_SCL.1", "Cf_SCL.1", "線:XIAO:D4 (SCL)"},
}
COLORS = None
TITLE = "右手のマイコンの帯（ユニバーサル基板 13×7 穴・33.0×17.8mm）"
KEY = "● 黄 = XIAO へ行く線   ● 緑 = スティックへ行く線   ■ = キットのピン   太い色帯 = はんだブリッジ（はんだ面）   橙 = 抵抗  水色 = コンデンサ"
LEGEND = "網の色: 灰 GND／赤 VDD／橙 3V3 の入口／紫 抵抗の上端／青 SDA／緑 SCL／茶 X／桃 Y／水色 スイッチ"
UNUSED_PINS = {"PA3", "PA2", "PA1", "PA0", "PC3", "PC2", "PC1", "PC0", "PA4", "PB3", "PB2"}   # PA0 は UPDI（上からクリップ）


def check(parts=None, chains=None):
    parts, chains = parts or PARTS, chains or CHAINS
    errs = []
    adj = lambda a, b: abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1   # noqa: E731
    inb = lambda h: 0 <= h[0] < ROWS and 0 <= h[1] < COLS         # noqa: E731
    used = {}
    for h, n in PINS.items():
        used[h] = "ピン " + n
    for name, (_, legs, kind) in parts.items():
        for h in legs:
            if not inb(h): errs.append(f"{name}: 穴 {h} は板の外")
            if h in used: errs.append(f"穴 {h} に 2 本: {used[h]} と {name}")
            used[h] = name
        d = abs(legs[0][0] - legs[1][0]) + abs(legs[0][1] - legs[1][1])
        straight = legs[0][0] == legs[1][0] or legs[0][1] == legs[1][1]
        if kind in ("hair", "cap", "diode") and d != 1: errs.append(f"{name}: 立てる部品は隣の穴どうし（いま {d}）")
        if kind == "flat":
            if not straight or d < 2: errs.append(f"{name}: 寝かせる抵抗は一直線で 2 穴以上あける")
            for k in range(1, d):       # 胴体の下の穴は使えない
                mid = (legs[0][0] + (legs[1][0] - legs[0][0]) * k // d, legs[0][1] + (legs[1][1] - legs[0][1]) * k // d)
                if mid in used and used[mid] != name: errs.append(f"{name}: 胴体の下の穴 {mid} を {used[mid]} が使っている")
                used.setdefault(mid, name + "（胴体の下）")
        # キットの下（行 1・2 の列 1〜10）に背の高い部品を置かない
        for h in legs:
            if PINS and h[0] in (1, 2) and 1 <= h[1] <= 10: errs.append(f"{name}: 穴 {h} はキットの下")
    for h, (to, n) in WIRES.items():
        if h in used: errs.append(f"穴 {h} に 2 本: {used[h]} と 線 {n}")
        if PINS and h[0] in (1, 2) and 1 <= h[1] <= 10: errs.append(f"線 {n}: 穴 {h} はキットの下")
        used[h] = "線 " + n
    for a, b in JUMPERS:
        for h in (a, b):
            if h in used: errs.append(f"穴 {h} に 2 本: {used[h]} と ジャンパ")
            used[h] = "ジャンパ"
    # 網を作る
    par = {}
    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for ch in chains:
        for a, b in zip(ch, ch[1:]):
            if not (inb(a) and inb(b) and adj(a, b)): errs.append(f"ブリッジ {a}-{b} は隣どうしでない")
            par[find(a)] = find(b)
    for a, b in JUMPERS:
        par[find(a)] = find(b)
    nets = {}
    for h, n in PINS.items(): nets.setdefault(find(h), set()).add(n)
    for name, (_, legs, _) in parts.items():
        for i, h in enumerate(legs): nets.setdefault(find(h), set()).add(f"{name}.{i + 1}")
    for h, (to, n) in WIRES.items(): nets.setdefault(find(h), set()).add(f"線:{to}:{n}")
    got = [s for s in nets.values() if not (len(s) == 1 and next(iter(s)) in UNUSED_PINS)]
    for name, want in EXPECT.items():
        if want not in got:
            near = max(got, key=lambda s: len(s & want))
            errs.append(f"網 {name}: 期待 {sorted(want)} ／ 実際 {sorted(near)}")
    for s in got:
        if s not in EXPECT.values(): errs.append(f"期待に無い網: {sorted(s)}")
    # ブリッジしていない隣どうしで、はんだが流れると電源を短絡する組を数える（注意書き用）
    risky = []
    pads = set(used) | {h for ch in chains for h in ch}      # **ブリッジだけの穴も数える**（used だけだと 2 組漏れた）
    for h, n in PINS.items(): nets.setdefault(find(h), set()).add(n)
    for a, b in combinations(sorted(pads), 2):
        if adj(a, b) and find(a) != find(b):
            na, nb = nets.get(find(a), set()), nets.get(find(b), set())
            if ("VDD" in na and "GND" in nb) or ("GND" in na and "VDD" in nb): risky.append((a, b))
    return errs, risky, find


def draw(find, path, solder_side=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import Rectangle, FancyBboxPatch
    for f in ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",):
        try:
            font_manager.fontManager.addfont(f); plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
        except Exception:
            pass
    name_of = {}
    for n, want in EXPECT.items():
        for h in list(PINS) + [l for p in PARTS.values() for l in p[1]] + list(WIRES):
            pass
    hole_net = {}
    def label(h):
        for n, want in EXPECT.items():
            items = {PINS.get(h)} | {f"{p}.{i + 1}" for p, (_, legs, _) in PARTS.items() for i, l in enumerate(legs) if l == h} | ({f"線:{WIRES[h][0]}:{WIRES[h][1]}"} if h in WIRES else set())
            if items & want: return n
        return None
    reps = {}
    for r in range(ROWS):
        for c in range(COLS):
            n = label((r, c))
            if n: reps[find((r, c))] = n
    col = COLORS or {"GND": "#444444", "VDD": "#d62728", "VIN": "#ff7f0e", "TOP": "#9467bd", "SDA": "#1f77b4", "SDA線": "#1f77b4",
           "SCL": "#2ca02c", "SCL線": "#2ca02c", "X": "#8c564b", "X線": "#8c564b", "Y": "#e377c2", "Y線": "#e377c2", "SW": "#17becf", "SW線": "#17becf"}
    X = (lambda c: COLS - 1 - c) if solder_side else (lambda c: c)
    fig, ax = plt.subplots(figsize=(15, 9.2))
    ax.add_patch(Rectangle((-0.6, -0.6), COLS + 0.2, ROWS + 0.2, fc="#f3e2b8", ec="#8a6d2f", lw=2))
    if not solder_side and PINS:
        ax.add_patch(FancyBboxPatch((0.55, -0.45), 9.9, 3.9, boxstyle="round,pad=0.02", fc="#2e9e4f", ec="#1b5e2f", alpha=0.28, lw=2))
        ax.text(5.5, 1.5, "ATtiny1616 DIP 化キット（ピンヘッダで浮かせて載せる）\nジャンパ線はこの下をくぐる", ha="center", va="center", fontsize=12, color="#1b5e2f")
    # ブリッジ
    for ch in CHAINS:
        for a, b in zip(ch, ch[1:]):
            n = reps.get(find(a), "")
            ax.plot([X(a[1]), X(b[1])], [a[0], b[0]], color=col.get(n, "#999"), lw=9, alpha=0.55, solid_capstyle="round", zorder=2)
    for a, b in JUMPERS:
        ax.plot([X(a[1]), X(b[1])], [a[0], b[0]], color="#d62728", lw=3, ls=(0, (6, 3)), zorder=3)
        ax.text((X(a[1]) + X(b[1])) / 2, a[0] - 0.3 if solder_side else a[0] + 0.33, "被覆のジャンパ線（部品面・VDD）", ha="center", fontsize=10, color="#d62728")
    # 穴
    for r in range(ROWS):
        for c in range(COLS):
            h = (r, c); n = reps.get(find(h)) if (h in PINS or h in WIRES or any(h in p[1] for p in PARTS.values()) or any(h in ch for ch in CHAINS) or any(h in j for j in JUMPERS)) else None
            ax.plot(X(c), r, "o", ms=13, mfc="white", mec=col.get(n, "#b89b5a"), mew=2.6 if n else 1.2, zorder=4)
            if h in PINS:
                ax.plot(X(c), r, "s", ms=6, color="#222", zorder=5)
                ax.text(X(c), r - 0.36, PINS[h], ha="center", va="bottom", fontsize=8.5, color="#222", zorder=6)
    # 部品
    if not solder_side:
        for name, (val, (a, b), kind) in PARTS.items():
            xa, xb = X(a[1]), X(b[1])
            ax.plot([xa, xb], [a[0], b[0]], color="#111", lw=2.2, zorder=7)
            mx, my = (xa + xb) / 2, (a[0] + b[0]) / 2
            w, hgt = (0.62, 0.34) if a[0] == b[0] else (0.34, 0.62)
            if kind == "flat": w, hgt = (0.36, 1.25) if a[1] == b[1] else (1.25, 0.36)
            fc = {"hair": "#ffd27f", "flat": "#ffd27f", "cap": "#9fd3ff", "diode": "#c8c8c8"}[kind]
            ax.add_patch(FancyBboxPatch((mx - w / 2, my - hgt / 2), w, hgt, boxstyle="round,pad=0.03", fc=fc, ec="#111", lw=1.3, zorder=8))
            off = 0.0
            ax.text(mx, my + off, f"{name}\n{val}", ha="center", va="center", fontsize=6.6, zorder=9, linespacing=0.95)
    # 線
    for h, (to, n) in WIRES.items():
        ax.plot(X(h[1]), h[0], "o", ms=8, color="#ffeb3b" if to.startswith("XIAO") else "#00c853", mec="#111", zorder=10)
    y0 = ROWS + 0.15
    ax.text(-0.5, y0, KEY, fontsize=10.5, va="top")
    lines = [f"({h[0]},{h[1]})  {to} ← {n}" for h, (to, n) in sorted(WIRES.items(), key=lambda kv: (kv[1][0], kv[0]))]
    xr = max(6.6, COLS + 1.0) if not PINS else 6.6
    ax.text(-0.5, y0 + 0.45, "線を挿す穴（行, 列）:\n" + "\n".join(lines), fontsize=10, va="top", linespacing=1.35)
    ax.text(xr, y0 + 0.45 if PINS else 0.0, LEGEND + "\n"
            + ("★ はんだ面から見た図（左右が逆）。列の番号を見て数える" if solder_side else "★ 部品面から見た図。ブリッジは裏（はんだ面）で作る"), fontsize=10.5, va="top", linespacing=1.5)
    for c in range(COLS): ax.text(X(c), -0.95, str(c), ha="center", fontsize=11, color="#555")
    for r in range(ROWS): ax.text(-1.0 if not solder_side else COLS, r, str(r), va="center", ha="center", fontsize=11, color="#555")
    ax.text(-1.0 if not solder_side else COLS, -0.95, "行\\列", ha="center", fontsize=9, color="#555")
    ax.set_xlim(-1.5, max(COLS + 0.5, 13.5)); ax.set_ylim(ROWS + 4.3, -1.4); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title(TITLE + ("— はんだ面" if solder_side else "— 部品面"), fontsize=14)
    fig.savefig(path, dpi=110, bbox_inches="tight"); plt.close(fig)


if __name__ == "__main__":
    from pathlib import Path
    if "--break" in sys.argv:       # 壊した配置を検査が見つけるか
        import copy
        bad = 0
        for name in PARTS:          # 部品を 1 つずつ、足を入れ替える／隣の列へずらす
            p = copy.deepcopy(PARTS); v, (a, b), k = p[name]; p[name] = (v, ((a[0], a[1] + 1), b), k)
            bad += bool(check(parts=p)[0])
        n_ch = 0
        for i in range(len(CHAINS)):          # 鎖を 1 本ずつ抜く
            n_ch += bool(check(chains=CHAINS[:i] + CHAINS[i + 1:])[0])
        extra = bool(check(chains=CHAINS + [[(4, 3), (4, 4)]])[0])      # 余計なブリッジ（X と スイッチの短絡）
        print(f"足をずらした {bad}/{len(PARTS)} 件・鎖を抜いた {n_ch}/{len(CHAINS)} 件・余計なブリッジ {'検出' if extra else '見逃し'}")
        sys.exit(0 if bad == len(PARTS) and n_ch == len(CHAINS) and extra else 1)
    errs, risky, find = check()
    for e in errs: print("NG", e)
    print("検査:", "問題なし" if not errs else f"{len(errs)} 件", "／ VDD と GND が隣り合う穴の組（はんだを流さない）:", risky)
    if errs: sys.exit(1)
    out = Path(__file__).parent
    draw(find, out / "pod_layout_parts_side.png"); draw(find, out / "pod_layout_solder_side.png", solder_side=True)
    print("図:", out / "pod_layout_parts_side.png", out / "pod_layout_solder_side.png")
