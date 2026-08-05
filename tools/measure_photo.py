"""実機写真から HHKB のキー位置を計測する。

手法:
  1. 本体の左右端を検出し、公称全幅 294mm でピクセル→mm を較正する
  2. 英数キー列の隣接ピッチが 19.05mm になるかで較正を検証する（二重較正）
  3. 最下段のキー境界を検出し、各キーの幅と左右の余白を u 単位で出す

キーキャップは実際のキーピッチより一回り小さい（1u=19.05mm に対し
キャップ幅は約 18.2mm）。したがって「キャップの幅」ではなく
「キャップ中心の間隔」を基準にする。中心間隔ならピッチと一致する。

出力は build/measure_annotated.png に描画され、目視で検証できる。
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

BOARD_WIDTH_MM = 294.0
UNIT_MM = 19.05
UNITS_PER_ROW = 15.0

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"


def load_gray(path):
    im = Image.open(path).convert("L")
    return np.asarray(im, dtype=np.float32), im


def find_board_edges(gray, y_frac=0.5, margin_frac=0.02):
    """本体（暗い塊）の左右端を検出する。背景は本体より明るい前提。"""
    h, w = gray.shape
    band = gray[int(h * (y_frac - 0.05)) : int(h * (y_frac + 0.05)), :].mean(axis=0)
    thresh = (band.max() + band.min()) / 2.0
    dark = band < thresh
    idx = np.flatnonzero(dark)
    return int(idx[0]), int(idx[-1])


def column_profile(gray, y0, y1):
    """行範囲の輝度を縦に平均した横方向プロファイル。キー間の溝が谷になる。"""
    return gray[y0:y1, :].mean(axis=0)


def smooth(a, k=9):
    return np.convolve(a, np.ones(k) / k, mode="same")


def find_key_centers(profile, x0, x1, expect_n, min_gap_px):
    """プロファイルの山（キーキャップ）の中心を検出する。

    キャップは周囲の溝より明るいので、閾値を超える連続区間の中心を取る。
    """
    seg = smooth(profile[x0:x1])
    thresh = (seg.max() + seg.min()) / 2.0
    above = seg > thresh
    runs = []
    start = None
    for i, v in enumerate(above):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_gap_px:
                runs.append((start + x0, i + x0))
            start = None
    if start is not None and len(above) - start >= min_gap_px:
        runs.append((start + x0, len(above) + x0))
    return runs


def main(path):
    gray, im = load_gray(path)
    h, w = gray.shape
    print(f"画像: {w} x {h} px  ({path})")

    left, right = find_board_edges(gray)
    board_px = right - left
    mm_per_px = BOARD_WIDTH_MM / board_px
    u_per_px = UNITS_PER_ROW / board_px
    print(f"本体左右端: x={left} .. {right}  (幅 {board_px}px)")
    print(f"較正: {mm_per_px:.5f} mm/px, 1u = {1 / u_per_px:.2f}px")

    print("\n各行のキーキャップ検出（y はキャップの中心付近を指定する）:")
    # 行ごとの帯。画像の縦方向でキーキャップの中心にあたる位置を割合で指定。
    rows = {
        "row0 (数字段)": (0.20, 0.24),
        "row1 (QWERTY)": (0.36, 0.40),
        "row2 (ASDF)":   (0.51, 0.55),
        "row3 (ZXCV)":   (0.66, 0.70),
        "row4 (最下段)": (0.81, 0.85),
    }
    results = {}
    for name, (a, b) in rows.items():
        prof = column_profile(gray, int(h * a), int(h * b))
        runs = find_key_centers(prof, left, right, None, min_gap_px=int(0.4 / u_per_px))
        centers = [(s + e) / 2 for s, e in runs]
        widths_u = [(e - s) * u_per_px for s, e in runs]
        results[name] = (runs, centers, widths_u)
        print(f"  {name}: {len(runs)} 個検出")
        if len(centers) >= 3:
            pitches = np.diff(centers) * u_per_px
            near1 = pitches[(pitches > 0.85) & (pitches < 1.15)]
            if len(near1):
                print(
                    f"     1u ピッチ: 平均 {near1.mean():.4f}u "
                    f"({near1.mean() * UNIT_MM:.3f}mm), "
                    f"標準偏差 {near1.std() * UNIT_MM:.3f}mm, n={len(near1)}"
                )

    # 最下段の詳細
    name = "row4 (最下段)"
    runs, centers, widths_u = results[name]
    print(f"\n{name} の詳細（キャップ幅と位置、u 単位）:")
    print(f"  本体左端からの余白: {(runs[0][0] - left) * u_per_px:.3f}u")
    for i, ((s, e), wu) in enumerate(zip(runs, widths_u)):
        print(
            f"  key{i}: x={(s - left) * u_per_px:7.3f}u .. "
            f"{(e - left) * u_per_px:7.3f}u   キャップ幅 {wu:.3f}u"
        )
    print(f"  本体右端までの余白: {(right - runs[-1][1]) * u_per_px:.3f}u")

    annotate(im, left, right, results, BUILD / "measure_annotated.png")
    print(f"\n注釈付き画像: {BUILD / 'measure_annotated.png'}")


def annotate(im, left, right, results, out_png):
    """検出結果を画像に描いて、目視で検証できるようにする。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    BUILD.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(20, 9), dpi=110)
    ax.imshow(im, cmap="gray")
    h = im.size[1]
    ax.axvline(left, color="lime", linewidth=1.2)
    ax.axvline(right, color="lime", linewidth=1.2)
    colors = ["#ff4040", "#ffa500", "#40ff40", "#40a0ff", "#ff40ff"]
    for (name, (runs, centers, _)), c in zip(results.items(), colors):
        for s, e in runs:
            ax.axvspan(s, e, ymin=0, ymax=1, color=c, alpha=0.10)
        for cx in centers:
            ax.axvline(cx, color=c, linewidth=0.6, alpha=0.8)
    ax.set_axis_off()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(BUILD / "photos" / "HHKB_Pro_Hybrid_Type-S.jpg"))
