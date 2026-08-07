"""生成した基板が、プレート・ケースと同じ寸法で作られていることを検査する。

**基板・プレート・ケースは別々に生成される。** 同じ設計値から導いていても、
座標変換を間違えれば静かにずれる。ずれたまま発注すると数万円が無駄になるので、
生成物そのものを読み返して突き合わせる。

.kicad_pcb はテキスト（S 式）なので、pcbnew を入れなくても読める。
そのため通常の pytest（プロジェクトの venv）から実行できる。
"""

import re
from pathlib import Path

import pytest

from gen_plate import halves
from interface import (
    CORNER_R,
    PCB_INSET,
    boss_positions,
    plate_positions,
    stab_offset_for,
)

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "pcb"
NAMES = ["left", "right"]
ORIGIN = (150.0, 100.0)          # gen_pcb.ORIGIN と同じ

HALVES = halves()

pytestmark = pytest.mark.skipif(
    not (PCB / "hhkb_split_left.kicad_pcb").exists(),
    reason="基板がまだ生成されていない（KiCad の Python で tools/gen_pcb.py を実行する）",
)


def footprints(name):
    """(ライブラリ名, 参照, x, y) の一覧をレイアウト座標（Y 上向き）で返す。"""
    s = (PCB / f"hhkb_split_{name}.kicad_pcb").read_text()
    out = []
    for m in re.finditer(
        r'\(footprint "([^"]+)".*?\(at ([-\d.]+) ([-\d.]+)\).*?'
        r'\(property "Reference" "([^"]+)"', s, re.S):
        lib, x, y, ref = m.group(1), float(m.group(2)), float(m.group(3)), m.group(4)
        out.append((lib, ref, x - ORIGIN[0], ORIGIN[1] - y))
    return out


def outline_extent(name):
    """Edge.Cuts に引いた線分と円弧から、外形の外接矩形を出す。"""
    s = (PCB / f"hhkb_split_{name}.kicad_pcb").read_text()
    xs, ys = [], []
    for blk in re.finditer(r"\(gr_(?:line|arc)\b(.*?)\n\t\)", s, re.S):
        b = blk.group(1)
        if '"Edge.Cuts"' not in b:
            continue
        for m in re.finditer(r"\((?:start|end|mid) ([-\d.]+) ([-\d.]+)\)", b):
            xs.append(float(m.group(1)) - ORIGIN[0])
            ys.append(ORIGIN[1] - float(m.group(2)))
    return min(xs), min(ys), max(xs), max(ys)


# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", NAMES)
def test_switch_positions_match_the_plate(name):
    """スイッチの位置がプレートの開口と 1 対 1 で一致すること。

    ここがずれると、プレートの穴とスイッチの軸が合わず組み立てられない。
    """
    keys = HALVES[name]
    want, _ = plate_positions(keys)
    got = {ref: (x, y) for lib, ref, x, y in footprints(name) if lib.startswith("SW_")}
    assert len(got) == len(keys), f"{name}: スイッチ数が {len(got)}（期待 {len(keys)}）"
    for i, (wx, wy) in enumerate(want, start=1):
        gx, gy = got[f"SW{i}"]
        assert gx == pytest.approx(wx, abs=0.01), f"{name}: SW{i} の X がずれている"
        assert gy == pytest.approx(wy, abs=0.01), f"{name}: SW{i} の Y がずれている"


@pytest.mark.parametrize("name", NAMES)
def test_switch_footprint_size_matches_the_key_width(name):
    """キーの幅に対応するフットプリントが使われていること。

    1.00u のフットプリントを 3u のキーに置くと、スタビの穴が開かず
    キーが傾く。見た目では気づきにくい。
    """
    keys = HALVES[name]
    got = {ref: lib for lib, ref, _, _ in footprints(name) if lib.startswith("SW_")}
    for i, k in enumerate(keys, start=1):
        assert got[f"SW{i}"].endswith(f"{k.w_u:.2f}u"), \
            f"{name}: SW{i}（{k.w_u}u）に {got[f'SW{i}']} が使われている"


@pytest.mark.parametrize("name", NAMES)
def test_stabilizers_are_on_the_wide_keys(name):
    """2u 以上のキーにだけスタビライザーが置かれていること。"""
    keys = HALVES[name]
    wide = {i for i, k in enumerate(keys, start=1) if stab_offset_for(k.w_u) is not None}
    got = {ref for lib, ref, _, _ in footprints(name) if lib.startswith("Stabilizer")}
    assert got == {f"ST{i}" for i in wide}, f"{name}: スタビの付くキーが違う"


@pytest.mark.parametrize("name", NAMES)
def test_mounting_holes_match_the_case_bosses(name):
    """取付穴がケース側のボスと同じ位置にあること。

    プレート・ケース・基板の 3 つが同じ位置を持つ必要がある。
    以前プレートとケースで別々に計算していてずれた前科がある。
    """
    want = boss_positions(name)
    got = [(x, y) for lib, ref, x, y in footprints(name) if lib.startswith("MountingHole")]
    assert len(got) == len(want)
    for wx, wy in want:
        assert any(gx == pytest.approx(wx, abs=0.01) and gy == pytest.approx(wy, abs=0.01)
                   for gx, gy in got), f"{name}: ({wx}, {wy}) に取付穴が無い"


@pytest.mark.parametrize("name", NAMES)
def test_outline_is_the_plate_inset_by_pcb_inset(name):
    """基板の外形が、プレートより片側 PCB_INSET だけ小さいこと。

    大きいとケースの側壁と当たる（1.0mm にしていて 17,000mm^3 衝突した）。
    """
    keys = HALVES[name]
    _, (plate_w, plate_h) = plate_positions(keys)
    x0, y0, x1, y1 = outline_extent(name)
    assert x1 - x0 == pytest.approx(plate_w - PCB_INSET * 2, abs=0.05)
    assert y1 - y0 == pytest.approx(plate_h - PCB_INSET * 2, abs=0.05)
    assert abs(x0 + x1) < 0.05, f"{name}: 外形が左右方向で原点中心になっていない"
    assert abs(y0 + y1) < 0.05, f"{name}: 外形が前後方向で原点中心になっていない"


@pytest.mark.parametrize("name", NAMES)
def test_every_footprint_is_inside_the_outline(name):
    """すべての部品が外形の内側にあること。角丸ぶんの余裕も見る。"""
    x0, y0, x1, y1 = outline_extent(name)
    for lib, ref, x, y in footprints(name):
        assert x0 < x < x1 and y0 < y < y1, f"{name}: {ref} が外形の外にある"


@pytest.mark.parametrize("name", NAMES)
def test_board_depth_matches_the_real_machine(name):
    """基板の奥行が、実機の本体奥行から導いた値になっていること。"""
    _, y0, _, y1 = outline_extent(name)
    assert y1 - y0 == pytest.approx(108.0 - PCB_INSET * 2, abs=0.05)


def test_corner_radius_is_applied():
    """角が丸められていること（円弧が 4 つ）。"""
    s = (PCB / "hhkb_split_left.kicad_pcb").read_text()
    arcs = [b for b in re.findall(r"\(gr_arc\b(.*?)\n\t\)", s, re.S) if '"Edge.Cuts"' in b]
    assert len(arcs) == 4, f"外形の円弧が {len(arcs)} 個（期待 4）"
    assert CORNER_R > 0


# --------------------------------------------------------------------------
# ネット（配線の接続情報）
# --------------------------------------------------------------------------

def pads_with_nets(name):
    """{参照: {パッド番号: ネット名}} を返す。"""
    s = (PCB / f"hhkb_split_{name}.kicad_pcb").read_text()
    out = {}
    for fp in re.finditer(r'\n\t\(footprint "[^"]+"(.*?)\n\t\)', s, re.S):
        body = fp.group(1)
        m = re.search(r'\(property "Reference" "([^"]+)"', body)
        if not m:
            continue
        ref = m.group(1)
        pads = {}
        for pm in re.finditer(r'\(pad "([^"]+)"(.*?)\n\t\t\)', body, re.S):
            nm = re.search(r'\(net "([^"]+)"\)', pm.group(2))
            if nm:
                pads[pm.group(1)] = nm.group(1)
        out[ref] = pads
    return out


@pytest.mark.parametrize("name", NAMES)
def test_matrix_wiring_matches_the_firmware(name):
    """基板の配線が、ファームウェアの行列対応表と一致すること。

    **ここがずれるとキーが入れ替わる。** 基板とファームで別々に表を持つと
    いつか片方だけ直して破綻するので、同じ出所（hhkb_split.dtsi の
    matrix-transform）から導いていることを毎回確かめる。
    """
    from matrix import assignments
    rc = assignments(name)
    pads = pads_with_nets(name)
    for i, (r, c) in enumerate(rc, start=1):
        assert pads[f"SW{i}"]["1"] == f"COL{c}", \
            f"{name}: SW{i} が COL{c} につながっていない"
        assert pads[f"D{i}"]["1"] == f"ROW{r}", \
            f"{name}: D{i} のカソードが ROW{r} につながっていない"
        # スイッチとダイオードは同じ中間ノードで繋がる
        assert pads[f"SW{i}"]["2"] == pads[f"D{i}"]["2"] == f"SW{i}_D", \
            f"{name}: SW{i} とダイオードが繋がっていない"


@pytest.mark.parametrize("name", NAMES)
def test_diode_direction_is_col2row(name):
    """ダイオードの向きが col2row（アノードが列側・カソードが行側）であること。

    KiCad の D_SOD-123 は pad 1 がカソード、pad 2 がアノード。
    逆にすると 1 つも反応しない。
    """
    pads = pads_with_nets(name)
    for ref, p in pads.items():
        if not ref.startswith("D"):
            continue
        assert p["1"].startswith("ROW"), f"{ref}: カソードが行側にない"
        assert p["2"].startswith("SW"), f"{ref}: アノードがスイッチ側にない"


@pytest.mark.parametrize("name", NAMES)
def test_diodes_are_on_the_back(name):
    """ダイオードがソケットと同じ裏面にあること。

    表面に置くとキーキャップと干渉する。JLCPCB の実装も片面に揃えたい。
    """
    s = (PCB / f"hhkb_split_{name}.kicad_pcb").read_text()
    for fp in re.finditer(r'\n\t\(footprint "D_SOD-123"(.*?)\n\t\)', s, re.S):
        body = fp.group(1)
        ref = re.search(r'\(property "Reference" "([^"]+)"', body).group(1)
        assert '(layer "B.Cu")' in body, f"{ref} が裏面にない"


@pytest.mark.parametrize("name,rows,cols", [("left", 5, 6), ("right", 5, 8)])
def test_net_count_is_exactly_rows_plus_cols_plus_keys(name, rows, cols):
    """ネットの本数が 行 + 列 + キー数 と一致すること。

    余計なネットがあれば配線ミス、足りなければ繋ぎ忘れ。
    """
    keys = len(HALVES[name])
    names = {n for p in pads_with_nets(name).values() for n in p.values()}
    assert len(names) == rows + cols + keys
    assert {n for n in names if n.startswith("ROW")} == {f"ROW{i}" for i in range(rows)}
    assert {n for n in names if n.startswith("COL")} == {f"COL{i}" for i in range(cols)}


@pytest.mark.parametrize("name", NAMES)
def test_every_key_has_its_own_diode(name):
    """キー 1 つにダイオード 1 つ。使い回すとゴーストが出る。"""
    pads = pads_with_nets(name)
    n_sw = sum(1 for r in pads if r.startswith("SW"))
    n_d = sum(1 for r in pads if r.startswith("D"))
    assert n_sw == n_d == len(HALVES[name])
