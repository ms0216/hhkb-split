"""基板の実装部品の占有空間を、KiCad の STEP から取り出して記録する。

open-gaps #29。組み立て検査の `pcb` は「板＋キー下のソケット」の粗い箱で、
**実装部品（ダイオード 61・595・FFC コネクタ…）は 1 つも入っていなかった。**
KiCad が実物の 3D を持っているので、そこから取り出して検査に足す。

**KiCad は実体の無い 3D モデルを警告なしに飛ばす**（#29 で確認済み。
宣言 9 種のうち Kailh ソケットとスタビライザの 3 種は実体が無い）。だから
「STEP から持ってきた」だけでは検証にならない。**何が入ったかを数えて
JSON に記録し、検査が外部の事実（キー数・回路）と突き合わせる。**

流れ:
  1. `kicad-cli pcb export step` → build123d で読む（このファイルの --write）
  2. 部品ごとの bbox を tools/pcb_parts.json に記録（コミットする）
  3. gen_assembly が JSON から箱を組み立てて検査に入れる
     （毎回 STEP を読むと KiCad の無い環境で検査が黙って消えるため、
      JSON を経由する。鮮度は test_assembly が kicad-cli のある環境で見張る）

座標系（実測で確認・2026-08-09）:
  KiCad の STEP は X=KiCad x / Y=−KiCad y / 部品面の裏側が z<0。
  本体基板は ORIGIN (150,100) が板の中心なので、plate 座標へは
  (X−150, Y+100)。z は**板の上面を 0** に合わせる（envelopes.pcb_envelope と
  同じ基準）。STEP の板厚は 1.51mm（誘電体のみ。公称 1.6 との差 0.09 は
  外層の銅とレジスト）なので、上面合わせにすると部品の座面が
  envelope の下面 −1.6 とほぼ一致する。
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "pcb_parts.json"
KICAD_CLI = os.environ.get(
    "KICAD_CLI", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")

BOARDS = {
    "left": "pcb/hhkb_split_left.kicad_pcb",
    "right": "pcb/hhkb_split_right.kicad_pcb",
    "db": "pcb/hhkb_split_daughterboard.kicad_pcb",
}
ORIGIN = (150.0, 100.0)          # gen_pcb.ORIGIN（pcbnew が要るので直接読めない）


# kiswitch ライブラリの部品（ソケット・スタビ）。**基板を貫く**ので、
# 穴の無い板の占有空間と重ねると偽の干渉になる。組み立てでは専用の
# 保守的な箱（envelopes.socket_envelope / stab_envelope）が受け持ち、
# こちらは「数の確認」と「箱が保守側であることの突き合わせ」に使う。
KEYSWITCH_LABELS = {"kailh_socket", "kailh_socket_leg",
                    "stab_housing", "stab_insert", "stab_wire"}


# (長辺, 短辺) の見本。**完全一致で引かない。**回転した部品の bbox は
# ±0.1mm ほど揺れ、実際にソケット 27 個中 15 個が取りこぼされて
# ffc_conn に化けた。許容差 0.25mm で最も近い見本に寄せる。
_SHAPES = [
    ("diode_sod123", 3.8, 1.6),
    ("ic_tssop16", 6.4, 5.0),
    ("cap_1206", 3.2, 1.6),
    ("kailh_socket", 11.0, 6.0),
    ("kailh_socket_leg", 4.6, 2.0),
    ("stab_housing", 19.2, 6.8),
    ("stab_insert", 8.3, 4.4),
]


def _classify(sx, sy, sz):
    """bbox の寸法から部品の種類を推定する。数を数えるための札。"""
    a, b = sorted((round(sx, 2), round(sy, 2)), reverse=True)
    for label, ta, tb in _SHAPES:
        if abs(a - ta) <= 0.25 and abs(b - tb) <= 0.25:
            return label
    if abs(a - 2.0) <= 0.25 and abs(b - 1.2) <= 0.25:
        return "res_0805" if sz < 1.0 else "cap_0805"
    if a >= 20.0:                # スタビのワイヤ組立（2u 25.5 / 3u 39.7）
        return "stab_wire"
    if a >= 8.0:                 # FFC コネクタは 3 つの立体でできている
        return "ffc_conn"
    return f"unknown_{a}x{b}"


def extract(name):
    """kicad-cli で STEP を出し、板と部品の bbox を返す。"""
    from build123d import import_step

    src = ROOT / BOARDS[name]
    with tempfile.TemporaryDirectory() as td:
        step = Path(td) / f"{name}.step"
        # --subst-models: .wrl 宣言を同名の .stp に置き換える。kiswitch の
        # ソケット・スタビのモデルはこれが無いと STEP に出ない
        subprocess.run([KICAD_CLI, "pcb", "export", "step", "--force",
                        "--subst-models", "--output", str(step), str(src)],
                       check=True, capture_output=True)
        solids = import_step(str(step)).solids()

    board = max(solids, key=lambda s: s.volume)
    bb = board.bounding_box()
    # 本体基板は plate 座標（板の中心が原点・上面 z=0）。
    # 子基板は基板ローカル座標（外形中心が原点・**下面** z=0。
    # 組み立てでは下面の高さ FLOOR+DB_BOSS_H が基準になるため）。
    dx, dy = -ORIGIN[0], ORIGIN[1]          # X−150, Y+100
    dz = -bb.max.Z if name != "db" else 0.0

    def box(s):
        b = s.bounding_box()
        return [round(b.min.X + dx, 3), round(b.min.Y + dy, 3),
                round(b.min.Z + dz, 3), round(b.max.X + dx, 3),
                round(b.max.Y + dy, 3), round(b.max.Z + dz, 3)]

    comps = []
    counts = {}
    for s in solids:
        if s is board:
            continue
        x0, y0, z0, x1, y1, z1 = box(s)
        # 子基板の板の上に居る立体は全部 XIAO のモデル（84 個の細かい
        # 部品でできている）。個別に分類すると USB シェルが ffc_conn に
        # 化けるなどラベルが汚れるので、まとめて 1 つの札にする。
        if name == "db" and z0 > 1.4:
            label = "xiao_asm"
        else:
            label = _classify(x1 - x0, y1 - y0, z1 - z0)
        counts[label] = counts.get(label, 0) + 1
        comps.append({"label": label, "bbox": [x0, y0, z0, x1, y1, z1]})

    return {
        "source": BOARDS[name],
        "solids": len(solids),
        "board_bbox": box(board),
        "board_step_thickness": round(bb.size.Z, 2),
        "counts": counts,
        "components": comps,
    }


def real_compound(name):
    """STEP を出し直し、実形状（板＋全部品モデル）の Compound を返す。

    視覚確認用の STL 出力（export_assembly）と、基板上の実形状どうしの
    干渉検査（test_assembly）が使う。kicad-cli とモデルの入った環境が要る。
    """
    from build123d import import_step

    src = ROOT / BOARDS[name]
    with tempfile.TemporaryDirectory() as td:
        step = Path(td) / f"{name}.step"
        subprocess.run([KICAD_CLI, "pcb", "export", "step", "--force",
                        "--subst-models", "--output", str(step), str(src)],
                       check=True, capture_output=True)
        return import_step(str(step))


def load():
    return json.loads(DATA.read_text())


def component_boxes(name):
    """記録済みの部品 bbox を [(x0,y0,z0,x1,y1,z1), ...] で返す。

    **ソケット・スタビ（KEYSWITCH_LABELS）は除く。**基板を貫く部品なので、
    穴の無い板の占有空間と必ず重なる。組み立てでは専用の箱が受け持つ。
    """
    return [tuple(c["bbox"]) for c in load()[name]["components"]
            if c["label"] not in KEYSWITCH_LABELS]


def keyswitch_boxes(name, label):
    """kiswitch 由来の部品（label 指定）の bbox 一覧。突き合わせ検査用。"""
    return [tuple(c["bbox"]) for c in load()[name]["components"]
            if c["label"] == label]


def build_envelope(name):
    """部品の占有空間を 1 つの Part にする（本体基板は plate 座標・上面 z=0）。"""
    from build123d import Align, Box, BuildPart, Locations

    with BuildPart() as env:
        for x0, y0, z0, x1, y1, z1 in component_boxes(name):
            with Locations(((x0 + x1) / 2, (y0 + y1) / 2, z0)):
                Box(x1 - x0, y1 - y0, z1 - z0,
                    align=(Align.CENTER, Align.CENTER, Align.MIN))
    return env.part


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv != ["--write"]:
        print(__doc__.split("\n")[0])
        print("使い方: pcb_parts.py --write   （STEP を出し直して JSON を更新）")
        d = load() if DATA.exists() else {}
        for name, rec in d.items():
            print(f"  {name}: 立体 {rec['solids']} 個 {rec['counts']}")
        return 0
    data = {name: extract(name) for name in BOARDS}
    DATA.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    for name, rec in data.items():
        print(f"{name}: 立体 {rec['solids']} 個 {rec['counts']}")
    print(f"→ {DATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
