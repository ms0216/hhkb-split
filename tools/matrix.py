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


# **子基板のレーン（物理）↔ ケーブルのネット名。**
#
# 子基板は 1 種類しか作らないので、**XIAO のどのピンが FFC の何番に
# 繋がるかは固定**（`gen_daughterboard` の OUTER/INNER_LANE_PADS）。
# ここはその写しではなく、**同じ事実をネット名の側から見た表**。
#
# ⚠️ **名前は行番号ではなく「ケーブル上の位置」**（2026-08-15・利用者
# 「DB の ROWx というピン名前付は不適切になるかもしれません」）。
# **どの行を載せるかは左右で違う**ので、ROW2 のような名前を付けると
# 左では行 2、右では行 4 を運ぶ嘘の名前になる。
ROW_LANES = {                    # XIAO のピン → ケーブルのネット名
    "D5": "ROW_A",               # FFC 8  … 列の内側・内
    "D6": "ROW_B",               # FFC 9  … 列の内側・垂直
    "D3": "ROW_C",               # FFC 10 … 列の外・最も内側
    "D2": "ROW_D",               # FFC 11 … 列の外・真ん中
    "D1": "ROW_E",               # FFC 12 … 列の外・最も板端
}


def row_pins(half):
    """その半分の `row-gpios` を ["D6", "D5", ...] で返す。**並び順が行番号。**

    ⚠️ **出所は左右の overlay**（2026-08-15）。以前は共通の dtsi に
    1 つだけ書いていたが、**行がどの GPIO に来るかは左右で物理的に違う**
    （J_DB が左は板の右端・右は左端にあり、同じ FFC のピンでも行バスへ
    近づく向きが逆）。共通に書くと、どちらかの基板で必ず交差が出る。
    """
    path = ROOT / f"config/boards/shields/hhkb_split/hhkb_split_{half}.overlay"
    m = re.search(r"row-gpios\s*(.*?);", _strip(path.read_text()), re.S)
    if not m:
        raise RuntimeError(
            f"{half}: overlay に row-gpios が無い。**共通の dtsi ではなく"
            "左右の overlay が持つ**（片方だけ直すと行がずれる）")
    pins = [f"D{n}" for n in re.findall(r"&xiao_d\s+(\d+)", m.group(1))]
    if len(pins) != 5:
        raise RuntimeError(f"{half}: row-gpios が {len(pins)} 本（期待 5）")
    return pins


def row_nets(half):
    """行番号 → ケーブルのネット名。**基板の配線はこれを見る。**"""
    return [ROW_LANES[p] for p in row_pins(half)]


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




def keymap_order(keys):
    """キーをキーマップの並び順（行順）に並べ替える。

    **layout.split_halves は x 順（列方向）で返す。** キーマップと
    matrix-transform は行順（上段の左から右へ、次の段へ）を前提にしているので、
    突き合わせる前に必ずここを通す。

    これを忘れて基板を生成し、61 キー全部の行列割り当てを取り違えた。
    しかも「基板の割り当て」と「期待値」の両方に同じ誤った並びを使っていたため、
    テストが通ってしまった。**自分自身との一致は検証ではない。**
    発覚したのは DRC が「同じ行のはずのキーが物理的に離れている」ことによる
    異常な長さの配線を検出したため。

    layout.py の y_mm は Y 下向き（上の段ほど小さい）なので、y の昇順 → x の昇順。
    """
    return sorted(keys, key=lambda k: (k.y_mm, k.x_mm))


def computed_assignments(keys):
    """キー配置から行列の割り当てを計算する（行順に並べたキーを渡す）。

    **列は「段の中で何番目か」ではなく、物理的な x で決める。**
    番号で割り当てると、最下段（Space・Meta・Alt）のように段によって
    キー数が違うところで、論理的に同じ列のキーが物理的に大きく離れる。
    実際にそうなり、基板に 38mm の横断配線が生まれて DRC が交差を検出した。

    最上段（最も列数が多い段）を基準の列とし、各段のキーを x の順に
    単調増加で最も近い列へ割り当てる。単調にするのは、交差を避けるため。
    """
    rows = {}
    for k in keys:
        rows.setdefault(round(k.y_mm, 2), []).append(k)
    ys = sorted(rows)
    ref = sorted(rows[ys[0]], key=lambda k: k.x_mm)      # 最上段
    out = {}
    for r, y in enumerate(ys):
        row = sorted(rows[y], key=lambda k: k.x_mm)
        c_prev = -1
        for k in row:
            best, bestd = None, None
            for c in range(c_prev + 1, len(ref) - (len(row) - row.index(k) - 1)):
                d = abs(ref[c].x_mm - k.x_mm)
                if bestd is None or d < bestd:
                    best, bestd = c, d
            out[id(k)] = (r, best)
            c_prev = best
    return [out[id(k)] for k in keys]


if __name__ == "__main__":
    main()
