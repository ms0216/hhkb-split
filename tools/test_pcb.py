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
from matrix import keymap_order
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

# **キーマップ順に並べ替えたものを使う。** 生成側と同じ並びにしないと
# 比較にならないが、その並びが正しいことは
# test_keymap_order_matches_the_keymap が別途担保する。
HALVES = {k: keymap_order(v) for k, v in halves().items()}

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
    """**基板に取付穴が無いこと**と、ボスが基板に当たらないこと。

    上ケース方式では、基板はプレートとスイッチで一体になり、上下ケースに
    挟まれて保持される。ネジは上ケースから基板の外側のボスへ入る。
    穴が要らないぶん配線の自由度も上がる。

    以前は「穴がボスと同じ位置にあること」を見ていた。構造が変わったので、
    **穴が無いこと**と**当たらないこと**の two 方向で見る。
    """
    from interface import M2_BOSS_D, boss_positions
    txt = (ROOT / f"pcb/hhkb_split_{name}.kicad_pcb").read_text()
    assert "MountingHole" not in txt, f"{name}: 基板に取付穴が残っている"
    x0, y0, x1, y1 = outline_extent(name)
    half_h = (y1 - y0) / 2
    for bx, by in boss_positions(name):
        assert abs(by) - M2_BOSS_D / 2 >= half_h - 1e-6, \
            f"{name}: ボス({bx},{by}) が基板（半深 {half_h:.2f}）に掛かる"


@pytest.mark.parametrize("name", NAMES)

def test_outline_is_the_plate_inset_by_pcb_inset(name):
    """基板の外形が、ケースの外形から所定だけ小さいこと。

    **左右と前後で詰め方が違う。** 前後は取付ボス（y=±51.5, φ5 → 内端 49.0）を
    基板の外へ出すため深く詰める。左右を同じだけ詰めると、キー領域が
    基板からはみ出す。
    """
    from interface import PCB_INSET_Y, plate_positions
    x0, y0, x1, y1 = outline_extent(name)
    _, (case_w, case_h) = plate_positions(HALVES[name])
    assert x1 - x0 == pytest.approx(case_w - PCB_INSET * 2, abs=0.05)
    assert y1 - y0 == pytest.approx(case_h - PCB_INSET_Y * 2, abs=0.05)


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
    # 前後は取付ボスを基板の外へ出すため、左右より深く詰めてある。
    from interface import PCB_INSET_Y
    assert y1 - y0 == pytest.approx(108.0 - PCB_INSET_Y * 2, abs=0.05)


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


@pytest.mark.parametrize("name,rows,cols", [("left", 5, 6), ("right", 5, 9)])
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


# --------------------------------------------------------------------------
# 並び順そのものの正しさ
# --------------------------------------------------------------------------

# キーマップ（hhkb_split.keymap）の先頭に並ぶキー。ここが検証の基準点になる。
EXPECTED_HEAD = {
    "left": ["Esc", "1", "2", "3", "4", "5", "Tab", "Q", "W", "E", "R", "T",
             "Ctrl", "A", "S", "D", "F", "G"],
    "right": ["6", "7", "8", "9", "0", "-", "=", "\\", "`",
              "Y", "U", "I", "O", "P", "[", "]", "Del"],
}


@pytest.mark.parametrize("name", NAMES)
def test_keymap_order_matches_the_keymap(name):
    """並べ替えの結果が、キーマップに書かれた並びと一致すること。

    **これが全ての比較の基準点。** 他のテストは「生成側と期待値が同じ並びを
    使っているか」しか見ておらず、その並び自体が間違っていれば揃って通る。
    実際に一度そうなった（layout.split_halves は x 順で返すのに、行順だと
    思い込んで突き合わせ、61 キー全部の割り当てを取り違えた）。
    **自分自身との一致は検証ではない。**

    ここだけは外部の事実（キーマップに書かれたキー名の並び）と照合する。
    """
    got = [k.label for k in HALVES[name]][:len(EXPECTED_HEAD[name])]
    assert got == EXPECTED_HEAD[name], f"{name}: 並び順が違う\n  got  {got}"


@pytest.mark.parametrize("name", NAMES)
def test_matrix_columns_follow_physical_position(name):
    """同じ列のキーが物理的にも近いこと。

    列を「段の中で何番目か」で決めると、最下段のようにキー数が違う段で
    論理的に同じ列のキーが大きく離れる。基板に 38mm の横断配線が生まれ、
    DRC が交差を検出した。
    """
    from matrix import assignments
    rc = assignments(name)
    keys = HALVES[name]
    cols = {}
    for k, (_, c) in zip(keys, rc):
        cols.setdefault(c, []).append(k.x_mm)
    for c, xs in cols.items():
        spread = max(xs) - min(xs)
        assert spread <= 19.05 * 1.5, \
            f"{name}: 列 {c} のキーが x 方向に {spread:.1f}mm 散らばっている"


# --------------------------------------------------------------------------
# DRC の記録が最新かどうか
#
# DRC は kicad-cli が要るので CI では走らせられない。代わりに
# 「記録が現在の基板から作られたものか」を検査する。**基板を直したのに
# DRC をかけ直していない状態**を、これが捕まえる。
# 記録を更新するには python3 tools/drc.py を走らせる。
# --------------------------------------------------------------------------

@pytest.mark.parametrize("half", ["left", "right"])
def test_the_drc_report_matches_the_current_board(half):
    import hashlib
    import json
    report = ROOT / f"pcb/drc_{half}.json"
    board = ROOT / f"pcb/hhkb_split_{half}.kicad_pcb"
    assert report.exists(), f"{half}: DRC の記録が無い。python3 tools/drc.py を実行すること"
    rec = json.loads(report.read_text())
    now = hashlib.sha256(board.read_bytes()).hexdigest()
    assert rec["sha256"] == now, (
        f"{half}: 基板が変わったのに DRC をかけ直していない。"
        f"python3 tools/drc.py を実行すること")


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_board_has_no_drc_violations(half):
    import json
    rec = json.loads((ROOT / f"pcb/drc_{half}.json").read_text())
    assert rec["violations"] == 0, f"{half}: DRC 違反 {rec['violations']} 件\n" + \
        "\n".join(rec.get("details", []))
    assert rec["unconnected"] == 0, f"{half}: 未配線 {rec['unconnected']} 件"


# --------------------------------------------------------------------------
# 製造能力
# --------------------------------------------------------------------------

@pytest.mark.parametrize("half", ["left", "right"])
def test_the_board_declares_the_manufacturer_rules(half):
    """基板に JLCPCB の製造能力が設計規則として書き込まれていること。

    **これが無い間、DRC は KiCad の既定値で通していただけだった。**
    「違反 0 件」は「JLCPCB で製造できる」を意味していなかった。
    規則が消えると、また同じ状態に戻る。
    """
    # **設計規則は .kicad_pcb ではなく .kicad_pro に入る。**
    # 最初 .kicad_pcb を見ていて「書かれていない」と誤検出した。
    import json
    pro = json.loads((ROOT / f"pcb/hhkb_split_{half}.kicad_pro").read_text())
    rules = pro["board"]["design_settings"]["rules"]
    for key, mm in (("min_track_width", 0.127), ("min_clearance", 0.127),
                    ("min_via_diameter", 0.45), ("min_through_hole_diameter", 0.2),
                    ("min_hole_to_hole", 0.5), ("min_copper_edge_clearance", 0.3),
                    ("min_via_annular_width", 0.13)):
        assert key in rules, f"{half}: 設計規則 {key} が無い"
        assert rules[key] == pytest.approx(mm, abs=1e-6), \
            f"{half}: {key} が {rules[key]}（期待 {mm}）"


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_actual_geometry_is_inside_the_manufacturer_limits(half):
    """実際の線幅・ビアが能力の内側にあること。

    規則を書いただけでは足りない。**規則を緩めれば通ってしまう**ので、
    実物の寸法も直接見る。
    """
    txt = (ROOT / f"pcb/hhkb_split_{half}.kicad_pcb").read_text()
    # **銅箔の配線だけを見る。** 単に (width ...) を拾うと、フットプリントの
    # シルクや図形（0.05〜0.12mm）まで混ざって誤検出する。
    widths = {float(w) for w in
              re.findall(r"\(segment[\s\S]{0,200}?\(width ([\d.]+)\)", txt)}
    assert widths and min(widths) >= 0.127, f"{half}: 線幅 {sorted(widths)[:3]}"
    for size, drill in re.findall(r"\(size ([\d.]+)\)\s*\n\s*\(drill ([\d.]+)\)", txt):
        ring = (float(size) - float(drill)) / 2
        assert float(drill) >= 0.20, f"{half}: ビアのドリル {drill} が小さすぎる"
        assert ring >= 0.13, f"{half}: アニュラリング {ring:.3f}mm が薄すぎる"


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_silkscreen_is_thick_enough_to_print(half):
    """シルクの線幅が JLCPCB の最小 0.15mm 以上であること。

    KiCad の標準フットプリントは 0.12mm で描かれており、そのままだと
    かすれるか印字されない。**DRC はシルクの線幅を見ないので、
    自分で担保するしかない。**
    """
    txt = (ROOT / f"pcb/hhkb_split_{half}.kicad_pcb").read_text()
    thin = set()
    for m in re.finditer(r'\(fp_(?:line|arc|circle|poly)[\s\S]{0,300}?'
                         r'\(width ([\d.]+)\)[\s\S]{0,120}?\(layer "([^"]+)"', txt):
        if "SilkS" in m.group(2) and float(m.group(1)) < 0.15:
            thin.add(float(m.group(1)))
    assert not thin, f"{half}: シルクが細すぎる線がある {sorted(thin)}"


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_board_says_which_half_it_is(half):
    """基板に左右の識別が印字されていること。

    2 種類が届いて見分けがつかないと、組み立ても修理も取り違える。
    """
    txt = (ROOT / f"pcb/hhkb_split_{half}.kicad_pcb").read_text()
    assert f"HHKB Split  {half.upper()}" in txt, f"{half}: 左右の識別表示が無い"
