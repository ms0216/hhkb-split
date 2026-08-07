"""取付ネジを置ける場所を、キー配置とフットプリントの実寸から探す。

**なぜ要るか。**
当初はネジを外周（プレートの縁）に並べていたが、HHKB 実機と同じ 4mm の縁幅では
M2 のネジ穴・φ5 のボス・基板の縁が並ばないことが分かった。取付穴が基板の外形を
0.3mm はみ出していた。envelopes.py は矩形から円を引くだけなので、はみ出しても
黙ってクリップされ気づけなかった。

縁幅は実機由来（294mm − キー 285.75mm ＝ 片側 4.12mm）で動かせないので、
**ネジはキーとキーの隙間に置く**。その空き場所を機械的に探すのがこの道具。

占有範囲は推測せず、実際のフットプリントファイルから測る。
"""

import re
from pathlib import Path

from interface import CASE_WALL, M2_BOSS_D, M2_CLEAR_D, plate_size, stab_offset_for
from layout import bounds_mm, load_layout, split_halves  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "pcb/lib/keyswitch.pretty"

# 基板をケース内壁からどれだけ逃がすか
PCB_WALL_GAP = 0.2
# 取付穴の縁から基板外形までに確保する余裕
HOLE_EDGE_MARGIN = 1.5
# ボスの外周と、キーの占有範囲との間に確保する余裕
BOSS_KEEPOUT_GAP = 0.5

SWITCH_CUTOUT_HALF = 7.0     # プレートの開口 14mm


def _footprint_extent(name):
    """フットプリントの占有範囲を実ファイルから測る（KiCad 座標・Y 下向き）。"""
    s = (LIB / f"{name}.kicad_mod").read_text()
    xs, ys = [], []
    pat = r"\(pad [^()]*?\(at ([-\d.]+) ([-\d.]+)[^)]*\) \(size ([\d.]+) ([\d.]+)\)"
    for m in re.finditer(pat, s):
        x, y, w, h = map(float, m.groups())
        xs += [x - w / 2, x + w / 2]
        ys += [y - h / 2, y + h / 2]
    return min(xs), max(xs), min(ys), max(ys)


def keepout_boxes(keys):
    """各キーが占有する矩形を、レイアウト座標（原点中心・Y 上向き）で返す。

    スイッチのフットプリントとプレート開口の和に、スタビライザーがあれば
    それも足す。KiCad は Y 下向きなので符号を反転して取り込む。
    """
    from gen_plate import stab_polygon        # プレートの開口の定義
    from interface import plate_positions     # 座標変換

    positions, _ = plate_positions(keys)
    sw = _footprint_extent("SW_Hotswap_Kailh_MX_1.00u")
    boxes = []
    for (kx, ky), k in zip(positions, keys):
        # スイッチ本体（フットプリント ∪ プレート開口）
        bx0 = min(sw[0], -SWITCH_CUTOUT_HALF)
        bx1 = max(sw[1], SWITCH_CUTOUT_HALF)
        by0 = min(-sw[3], -SWITCH_CUTOUT_HALF)   # Y 反転
        by1 = max(-sw[2], SWITCH_CUTOUT_HALF)
        boxes.append((kx + bx0, ky + by0, kx + bx1, ky + by1))
        # スタビライザー。基板のフットプリントと、プレートの開口の**両方**を見る。
        # プレートの開口（stab_polygon）はフットプリントより広い（±16.14 対 ±13.93）。
        # 狭い方だけで判定して、ネジ穴を Enter の開口に重ねかけた。
        s = stab_offset_for(k.w_u)
        if s is not None:
            name = "Stabilizer_Cherry_MX_3.00u" if s > 15 else "Stabilizer_Cherry_MX_2.00u"
            e = _footprint_extent(name)
            poly = stab_polygon(s)                 # プレート側の開口（Y 上向き）
            px = [q[0] for q in poly]
            py = [q[1] for q in poly]
            boxes.append((kx + min(e[0], min(px)), ky + min(-e[3], min(py)),
                          kx + max(e[1], max(px)), ky + max(-e[2], max(py))))
    return boxes


def _clear_of(px, py, boxes, r):
    """点 (px,py) を中心とする半径 r の円が、どの矩形とも重ならないか。"""
    for bx0, by0, bx1, by1 in boxes:
        dx = max(bx0 - px, 0.0, px - bx1)
        dy = max(by0 - py, 0.0, py - by1)
        if dx * dx + dy * dy < r * r:
            return False
    return True


def candidates(keys, step=0.5):
    """ボスを置ける点を総当たりで探す。"""
    x0, y0, x1, y1 = bounds_mm(keys)
    kw, kh = x1 - x0, y1 - y0
    plate_w, plate_h = plate_size(kw, kh)
    pcb_hw = plate_w / 2 - CASE_WALL - PCB_WALL_GAP
    pcb_hh = plate_h / 2 - CASE_WALL - PCB_WALL_GAP
    lim_x = pcb_hw - M2_CLEAR_D / 2 - HOLE_EDGE_MARGIN
    lim_y = pcb_hh - M2_CLEAR_D / 2 - HOLE_EDGE_MARGIN
    boxes = keepout_boxes(keys)
    r = M2_BOSS_D / 2 + BOSS_KEEPOUT_GAP
    pts = []
    n = int(lim_x / step)
    m = int(lim_y / step)
    for i in range(-n, n + 1):
        for j in range(-m, m + 1):
            px, py = i * step, j * step
            if _clear_of(px, py, boxes, r):
                pts.append((round(px, 2), round(py, 2)))
    return pts, (plate_w, plate_h), (pcb_hw, pcb_hh)


def main():
    keys_l, keys_r = split_halves(load_layout(str(ROOT / "layout/hhkb_split.json")))
    for name, keys in (("左", keys_l), ("右", keys_r)):
        pts, (pw, ph), (hw, hh) = candidates(keys)
        print(f"=== {name} ===")
        print(f"  プレート {pw:.2f} x {ph:.2f}   基板 {hw*2:.2f} x {hh*2:.2f}")
        print(f"  ボスを置ける点: {len(pts)} 箇所（0.5mm 刻み）")
        if not pts:
            print("  → 置ける場所が無い。設計の見直しが要る")
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        print(f"  範囲 X {min(xs):7.2f}〜{max(xs):6.2f}   Y {min(ys):7.2f}〜{max(ys):6.2f}")
        # 大まかな塊を見るため、5mm グリッドに丸めて数える
        from collections import Counter
        c = Counter((round(x / 5) * 5, round(y / 5) * 5) for x, y in pts)
        print(f"  まとまり（5mm 単位に丸めた区画）: {len(c)} 箇所")
        for (gx, gy), n in sorted(c.items(), key=lambda t: -t[1])[:12]:
            print(f"     ({gx:+7.1f}, {gy:+6.1f})  点数 {n}")
        print()




# --------------------------------------------------------------------------
# 選定
# --------------------------------------------------------------------------
# 電池は左右方向に 2 本寝かせるので幅 109mm を占める。後ろ側のボスはその外へ
# 出す必要がある（中に立てると電池室を貫く。実際に 231mm^3 の食い込みを出した）。
BATTERY_HALF_W = (50.5 * 2 + 8.0) / 2      # envelopes.AA_L / gen_case.BATT_X と同じ値
BATTERY_CLEAR = M2_BOSS_D / 2 + 0.5


def select(keys, n_corner_frac=0.92):
    """候補から取付位置を 7 箇所選ぶ。

    四隅・手前中央・後ろ 2 箇所。後ろは電池室の外側へ出す。
    プレートを支えるため、なるべく外周に近い点を選ぶ。
    """
    pts, (pw, ph), (hw, hh) = candidates(keys)
    if not pts:
        raise RuntimeError("ボスを置ける点が無い")
    f = n_corner_frac
    # 奥の中央にはボスを立てられない。電池室（幅 109mm）が横断しているため。
    # 電池を奥へ置いたのは傾いた基板の下へ収めるためで、これはその代償。
    # 代わりに長辺の中央を支える。
    targets = [
        (-hw * f, -hh * f), (hw * f, -hh * f),      # 手前の左右
        (-hw * f, hh * f), (hw * f, hh * f),        # 奥の左右
        (0.0, -hh * f),                             # 手前の中央
        (-hw * f, 0.0), (hw * f, 0.0),              # 長辺の中央
    ]
    chosen = []
    for i, (tx, ty) in enumerate(targets):
        rear = ty > 0
        best = None
        for px, py in pts:
            if (px, py) in chosen:
                continue
            if rear and abs(px) < BATTERY_HALF_W + BATTERY_CLEAR:
                continue                            # 電池室の上は避ける
            if any((px - cx) ** 2 + (py - cy) ** 2 < 15.0 ** 2 for cx, cy in chosen):
                continue                            # 近すぎる点は選ばない
            d = (px - tx) ** 2 + (py - ty) ** 2
            if best is None or d < best[0]:
                best = (d, px, py)
        if best is None:
            raise RuntimeError(f"{i} 番目の取付位置が見つからない")
        chosen.append((best[1], best[2]))
    return chosen, (pw, ph), (hw, hh)


def report():
    keys_l, keys_r = split_halves(load_layout(str(ROOT / "layout/hhkb_split.json")))
    result = {}
    for name, keys in (("left", keys_l), ("right", keys_r)):
        sel, (pw, ph), (hw, hh) = select(keys)
        result[name] = sel
        print(f'    "{name}": [')
        for x, y in sel:
            print(f"        ({x:7.2f}, {y:7.2f}),")
        print("    ],")
    return result


if __name__ == "__main__":
    import sys
    if "--select" in sys.argv:
        report()
    else:
        main()
