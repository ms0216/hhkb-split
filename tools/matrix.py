"""キーが行列のどこに割り当てられているかを、ファームウェアの定義から読む。

**基板の配線とファームウェアの行列対応表が食い違うと、キーが入れ替わる。**
両方に同じ表を書くと、いつか片方だけ直して破綻する。そこで
config/boards/shields/hhkb_split/hhkb_split.dtsi の matrix-transform を
唯一の出所とし、基板生成はそれを読む。

transform の map は「キーマップの並び順 → RC(row, col)」の対応表で、
並び順は「左 27 を上段左から、続いて右 34 を上段左から」。
これは layout.split_halves が返すキーの順序と一致する（テストで検査する）。

右半分は基板上の列 0..7 が全体では列 6..13 に当たる（overlay の col-offset）。
基板を作るときは基板上の番号が要るので、ここで戻す。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DTSI = ROOT / "config/boards/shields/hhkb_split/hhkb_split.dtsi"
RIGHT_OVERLAY = ROOT / "config/boards/shields/hhkb_split/hhkb_split_right.overlay"

LEFT_KEYS = 27
RIGHT_KEYS = 34


def _strip(text):
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def col_offset(half):
    """右半分が全体の行列へ写るときのずらし量。左は 0。"""
    if half == "left":
        return 0
    m = re.search(r"&default_transform\s*\{[^}]*col-offset\s*=\s*<(\d+)>",
                  _strip(RIGHT_OVERLAY.read_text()), re.S)
    if not m:
        raise RuntimeError("右半分の col-offset を読めない")
    return int(m.group(1))


def transform_map():
    """transform の map を [(row, col), ...] で返す（キーマップの並び順）。"""
    body = re.search(r"map\s*=\s*<(.*?)>\s*;", DTSI.read_text(), re.S).group(1)
    rc = [(int(r), int(c))
          for r, c in re.findall(r"RC\(\s*(\d+)\s*,\s*(\d+)\s*\)", _strip(body))]
    if len(rc) != LEFT_KEYS + RIGHT_KEYS:
        raise RuntimeError(f"map の要素が {len(rc)} 個（期待 {LEFT_KEYS + RIGHT_KEYS}）")
    return rc


def assignments(half):
    """その半分のキーについて、基板上の (row, col) を並び順で返す。"""
    rc = transform_map()
    part = rc[:LEFT_KEYS] if half == "left" else rc[LEFT_KEYS:]
    off = col_offset(half)
    return [(r, c - off) for r, c in part]


def shape(half):
    """行数・列数を返す。"""
    a = assignments(half)
    return max(r for r, _ in a) + 1, max(c for _, c in a) + 1


def main():
    for half in ("left", "right"):
        a = assignments(half)
        rows, cols = shape(half)
        print(f"=== {half} ===  {rows} 行 × {cols} 列 / キー {len(a)} 個")
        grid = {}
        for i, (r, c) in enumerate(a):
            grid[(r, c)] = i
        for r in range(rows):
            line = "".join(f"{grid.get((r, c), '  '):>4}" if (r, c) in grid else "   ."
                           for c in range(cols))
            print(f"  行{r}: {line}")
        print()


if __name__ == "__main__":
    main()
