"""生成した基板が、プレート・ケースと同じ寸法で作られていることを検査する。

**基板・プレート・ケースは別々に生成される。** 同じ設計値から導いていても、
座標変換を間違えれば静かにずれる。ずれたまま発注すると数万円が無駄になるので、
生成物そのものを読み返して突き合わせる。

.kicad_pcb はテキスト（S 式）なので、pcbnew を入れなくても読める。
そのため通常の pytest（プロジェクトの venv）から実行できる。
"""

import math
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
    # **参照名で絞る。**フットプリント名で "SW_" を見ていたが、電源の
    # スライドスイッチ（SW_DIP_SPSTx01_Slide_...）も一致してしまう。
    got = {ref: (x, y) for lib, ref, x, y in footprints(name)
           if re.fullmatch(r"SW\d+", ref)}
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
    """**上ケースのボスが基板に当たらない**ことと、取付穴が正しい数あること。

    上ケースのネジは基板の外側（y=±51.5、基板の縁 48.7 より外）のボスへ
    入るので、**ボスは基板に触れてはいけない。**

    ⚠️ **「基板に取付穴が無いこと」を見ていたが、2026-08-12 に逆転した**
    （open-gaps #36）。基板はプレートとスイッチで保持される——という理屈
    だったが、測ったら**固定具が 1 つも無く**、スイッチを抜くとソケットの
    はんだに剥離力がかかる状態だった。**プレート裏の柱へ下から締める**
    ようにしたので、基板には穴が要る。**数が合っているか**を見る。
    """
    import re

    from interface import M2_BOSS_D, boss_positions, pcb_mount_positions
    txt = (ROOT / f"pcb/hhkb_split_{name}.kicad_pcb").read_text()
    n_hole = len(re.findall(r'footprint "MountingHole', txt))
    want = len(pcb_mount_positions(name))
    assert n_hole == want, (
        f"{name}: 基板の取付穴が {n_hole} 個。設計は {want} 個"
        "（interface.PCB_MOUNT_POSITIONS）")
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
        # **キーのダイオードだけを見る。**電源部の D_PWR も "D" で始まるので、
        # 接頭辞だけで拾うと巻き込む（実際に巻き込んだ）。
        if not re.fullmatch(r"D\d+", ref):
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
    """マトリクスのネットが過不足なくあること。

    **電源部のネットは別に数える。**部品を載せたので全体の本数は増えるが、
    マトリクスの本数は変わってはいけない。
    """
    txt = (ROOT / f"pcb/hhkb_split_{name}.kicad_pcb").read_text()
    nets = {n for n in re.findall(r'\(net (?:\d+ )?"([^"]*)"\)', txt) if n}
    matrix = {n for n in nets if re.fullmatch(r"(ROW|COL)\d+|SW\d+_D", n)}
    assert len(matrix) == rows + cols + len(HALVES[name]), \
        f"{name}: マトリクスのネットが {len(matrix)} 本"
    # 電源・通信のネットも載っていること
    for n in ("GND", "V3V3", "VBATT_RAW", "VBATT_SW", "VBATT_SENSE",
              "SPI_SCK", "SPI_MOSI", "CS"):
        assert n in nets, f"{name}: ネット {n} が無い"


@pytest.mark.parametrize("name", NAMES)
def test_every_key_has_its_own_diode(name):
    """キー 1 つにダイオード 1 つ。使い回すとゴーストが出る。"""
    pads = pads_with_nets(name)
    n_sw = sum(1 for r in pads if re.fullmatch(r"SW\d+", r))
    n_d = sum(1 for r in pads if re.fullmatch(r"D\d+", r))
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

@pytest.mark.parametrize("half", ["left", "right", "daughterboard"])
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


# **まだ配線が終わっていない基板。**ここに名前がある間は発注できない。
# **空 = 3 基板すべて DRC 違反 0・未配線 0。**
WIP_BOARDS = set()


def test_the_unfinished_boards_are_declared():
    """未完の基板が明示されていること。

    **偽の緑を出さないため。**DRC の検査から外すなら、外していることが
    見えていなければならない。open-gaps #16 と対応する。
    """
    import json
    for half in WIP_BOARDS:
        rec = json.loads((ROOT / f"pcb/drc_{half}.json").read_text())
        assert rec["violations"] or rec["unconnected"], \
            f"{half}: もう綺麗なので WIP_BOARDS から外すこと"


@pytest.mark.parametrize("half", ["left", "right", "daughterboard"])
def test_the_board_has_no_drc_violations(half):
    if half in WIP_BOARDS:
        pytest.skip(f"{half}: 配線が未完（open-gaps #16 / WIP_BOARDS）")
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


@pytest.mark.parametrize("half", NAMES)
def test_the_board_declares_the_netclass_used_for_routing(half):
    """配線に使われるネットクラスが、意図した値で書かれていること。

    **最小値（min_track_width ほか）とは別物。** 最小値は「これを下回るな」
    であって、実際に何 mm で引くかはネットクラスが決める。

    以前ここは設定されておらず、KiCad の既定値が入っていた。たまたま
    意図と同じ 0.2mm だったので誰も気づかなかった。手書きルータは
    TRACK_W を直接読んでいたが、**自動配線器はネットクラスしか見ない。**
    既定値が変われば、黙って別の線幅で配線される。
    """
    import json
    pro = json.loads((PCB / f"hhkb_split_{half}.kicad_pro").read_text())
    cls = pro["net_settings"]["classes"][0]
    assert cls["name"] == "Default"
    for key, mm in (("track_width", 0.2), ("clearance", 0.2),
                    ("via_diameter", 0.6), ("via_drill", 0.3)):
        assert cls[key] == pytest.approx(mm, abs=1e-6), \
            f"{half}: ネットクラスの {key} が {cls[key]}（期待 {mm}）"


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


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_main_board_is_four_layers_with_a_ground_plane(half):
    """本体基板が 4 層で、内層 1 に GND のベタがあること。

    2 層では行の引き回しが通らない（通路が 1.65mm しかない）。
    連続した GND 面は、分割の左右で 2.4GHz を至近距離で動かすこの設計では
    配線の都合以上に効く。

    **「層を 4 に設定した」だけでは足りない。**ベタが実際に塗られている
    （filled_polygon がある）ことまで見る。
    """
    txt = (ROOT / f"pcb/hhkb_split_{half}.kicad_pcb").read_text()
    m = re.search(r"\(layers\s*\n(.*?)\n\t\)", txt, re.S)
    assert m, f"{half}: 層の定義が読めない"
    cu = re.findall(r'"(\w+\.Cu)"', m.group(1))
    assert cu == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], f"{half}: 層構成が {cu}"
    zone = re.search(r"\(zone\b[\s\S]{0,400}?\(layer \"In1\.Cu\"", txt)
    assert zone, f"{half}: 内層 1 に GND のベタが無い"
    assert "filled_polygon" in txt, f"{half}: ベタが塗られていない"


# --------------------------------------------------------------------------
# 電子部品が帯に収まっているか
#
# **「寄っている」と「入っていない」は別の問題。**
# SOIC-16 はコートヤード 10.49mm で、帯 9.25mm にそもそも入らない。
# 位置を微調整しても 0 にはならない。算数で入らないものを、機械が言う。
# --------------------------------------------------------------------------

def _footprint_blocks(txt):
    """(参照名, フットプリントの S 式) を順に返す。括弧の対応で切り出す。"""
    for m in re.finditer(r"\n\t\(footprint ", txt):
        i = m.start() + 1
        depth, j = 0, i
        while True:
            if txt[j] == "(":
                depth += 1
            elif txt[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blk = txt[i:j + 1]
        r = re.search(r'\(property "Reference" "([^"]+)"', blk)
        if r:
            yield r.group(1), blk


def _courtyard_bbox(blk):
    """コートヤードの世界座標での (x0, y0, x1, y1)。無ければ None。"""
    import math
    at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", blk)
    ox, oy = float(at.group(1)), float(at.group(2))
    rot = math.radians(float(at.group(3) or 0))
    pts = []
    for m in re.finditer(
            r"\(fp_(line|rect|poly)\b([\s\S]*?)\(layer \"([^\"]+)\"\)", blk):
        if not m.group(3).endswith(".CrtYd"):
            continue
        pts += [(float(a), float(b)) for a, b in
                re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", m.group(2))]
        for tag in ("start", "end"):
            g = re.search(rf"\({tag} ([-\d.]+) ([-\d.]+)\)", m.group(2))
            if g:
                pts.append((float(g.group(1)), float(g.group(2))))
    if not pts:
        return None
    c, s = math.cos(rot), math.sin(rot)
    w = [(ox + x * c - y * s, oy + x * s + y * c) for x, y in pts]
    xs, ys = [p[0] for p in w], [p[1] for p in w]
    return min(xs), min(ys), max(xs), max(ys)


# 電子部品の参照名。**定義は circuit.py。**生成側と検査側で同じものを使う。
from circuit import ELEC_REF  # noqa: E402


def _expected_electronics(half):
    """回路の宣言から、帯に置かれる部品の参照名を導く。

    **走査の正解を、走査するコード自身から作らない。**
    circuit.py は基板の生成側も読んでいる宣言なので、部品が増えれば
    検査も自動で追従する。個数の下限を手で書くと、そこが嘘になる。
    """
    from circuit import board_refs, netlist
    refs = set()
    for ref, kind, pins in netlist(half):
        if kind in ("keyswitch", "diode"):
            continue          # マトリクスの 61 個は帯の外
        # **展開規則は circuit.board_refs に一本化してある。**ここに
        # 「battery_holder だけ 2 個」と書いていたため、電源スイッチを
        # ランドに変えたとき検査が追従できなかった。
        refs |= set(board_refs(ref, kind, pins))
    return refs


@pytest.mark.parametrize("half", NAMES)
def test_the_electronics_fit_inside_their_band(half):
    """電子部品のコートヤードが帯 9.25mm の内側にあること。

    はみ出していると、行のバスやソケットに当たる。**位置の微調整では
    直らない**（部品そのものが大きい）ので、フットプリントを選び直す
    必要がある。それを人の目に頼らない。
    """
    from bands import BAND_H, band_bounds_kicad
    txt = (PCB / f"hhkb_split_{half}.kicad_pcb").read_text()
    bad = []
    seen = set()
    for ref, blk in _footprint_blocks(txt):
        if not ELEC_REF.fullmatch(ref):
            continue
        bb = _courtyard_bbox(blk)
        assert bb is not None, f"{half}: {ref} にコートヤードが無い"
        seen.add(ref)
        # どの帯に属するかは、部品の中心がいちばん近い帯で決める。
        mid = (bb[1] + bb[3]) / 2
        i = min(range(4), key=lambda k: abs(sum(band_bounds_kicad(k)) / 2 - mid))
        lo, hi = band_bounds_kicad(i)
        if bb[1] < lo - 1e-6 or bb[3] > hi + 1e-6:
            bad.append(f"{ref}: y {bb[1]:.3f}..{bb[3]:.3f} "
                       f"(高さ {bb[3] - bb[1]:.3f}) が帯 {i} "
                       f"{lo:.3f}..{hi:.3f} からはみ出す")
    want = _expected_electronics(half)
    assert seen == want, (
        f"{half}: 走査できた部品が回路の宣言と一致しない。\n"
        f"  拾えなかった: {sorted(want - seen)}\n"
        f"  余計に拾った: {sorted(seen - want)}")
    assert not bad, f"{half}: 帯 {BAND_H}mm に収まっていない部品\n" + "\n".join(bad)


@pytest.mark.parametrize("half", NAMES)
def test_the_ground_plane_is_not_cut_by_routing(half):
    """In1.Cu に配線が 1 本も無いこと。

    **In1.Cu は GND のベタ専用。**ここに信号を通すと基準面が切れる。
    分割キーボードは左右で 2.4GHz を至近距離で動かすので、基準電位が
    連続していることの価値が大きい（4 層にしたのはそのため）。

    KiCad の DSN は 4 層すべてを (type signal) として書き出すので、
    そのまま渡すと自動配線器がここを使う。autoroute.py の
    _protect_the_ground_plane が (type power) に直している。
    **その細工が効いているかを、ここで確かめる。**DRC は面が切れていても
    何も言わない。
    """
    txt = (PCB / f"hhkb_split_{half}.kicad_pcb").read_text()
    # **セグメントの塊ごとに見る。**非貪欲でも `(segment ...` から
    # 次のゾーンの `(layer "In1.Cu")` まで食ってしまい、誤検出した。
    on_in1 = [b for b in re.findall(r"\(segment\n(?:\t\t\([^\n]*\)\n)+\t\)", txt)
              if '(layer "In1.Cu")' in b]
    assert not on_in1, (
        f"{half}: GND 基準面（In1.Cu）に配線が {len(on_in1)} 本ある。"
        "autoroute.py の _protect_the_ground_plane を確かめること")


@pytest.mark.parametrize("half", NAMES)
def test_every_ground_pad_reaches_the_plane(half):
    """電子部品の GND パッドの脇にビアが立っていること。

    GND ベタは In1.Cu の 1 層だけ、GND パッドは全部 B.Cu の SMD。
    間にビアが無いとベタに届かない。**ImportSpecctraSES は既存の配線を
    作り直すので、取り込みのたびにファンアウトが消える**（実測 7→0）。
    autoroute.py が立て直しているかを見る。
    """
    txt = (PCB / f"hhkb_split_{half}.kicad_pcb").read_text()
    vias = [(float(x), float(y)) for x, y in
            re.findall(r'\(via\s*\(at ([-\d.]+) ([-\d.]+)\)'
                       r'[\s\S]{0,200}?\(net (?:\d+ )?"GND"\)', txt)]
    pads = []
    for ref, blk in _footprint_blocks(txt):
        if not ELEC_REF.fullmatch(ref):
            continue
        # **フットプリントの回転をパッドにも掛ける。**掛け忘れると
        # 180 度回っている部品（J_DB など）のパッドが 3.7mm ずれる。
        at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", blk)
        ox, oy = float(at.group(1)), float(at.group(2))
        rot = math.radians(float(at.group(3) or 0))
        cos, sin = math.cos(rot), math.sin(rot)
        for m in re.finditer(r'\(pad "[^"]*"[\s\S]{0,400}?\(net (?:\d+ )?"GND"\)', blk):
            a = re.search(r"\(at ([-\d.]+) ([-\d.]+)", m.group(0))
            px, py = float(a.group(1)), float(a.group(2))
            pads.append((ref, ox + px * cos - py * sin, oy + px * sin + py * cos))
    assert pads, f"{half}: GND パッドを 1 つも拾えていない。走査が壊れている"
    far = [(r, x, y) for r, x, y in pads
           if not any(abs(vx - x) < 3.0 and abs(vy - y) < 3.0 for vx, vy in vias)]
    assert not far, (
        f"{half}: ベタに届いていない GND パッド\n" +
        "\n".join(f"  {r} ({x:.2f}, {y:.2f})" for r, x, y in far))


@pytest.mark.parametrize("half", NAMES)
def test_the_routing_was_made_from_the_current_placement(half):
    """配線が、いまの未配線基板から作られたものであること。

    **配置を変えたのに配線し直していない状態を検出する。**
    drc.py が「基板を変えたのに DRC をかけ直していない」を見るのと
    同じ型を、一段手前に置いたもの。

    **バイト列ではなく指紋で比べる。** KiCad は保存のたびに UUID と
    フットプリントの並び順を変えるので、バイトの sha256 だと
    「再生成しただけ」で落ちてしまい、何も変わっていないのに
    Freerouting（数分）を回し直すことになる（tools/boardhash.py）。
    """
    import json
    from boardhash import fingerprint
    rec_path = PCB / f"route_{half}.json"
    assert rec_path.exists(), \
        f"{half}: 配線の記録が無い。tools/autoroute.py を実行すること"
    rec = json.loads(rec_path.read_text())
    src = PCB / "unrouted" / f"hhkb_split_{half}.kicad_pcb"
    assert src.exists(), f"{half}: 未配線の基板が無い: {src}"
    assert rec["unrouted_fingerprint"] == fingerprint(src), (
        f"{half}: 配置が変わったのに配線し直していない。"
        'KiCad の Python で "tools/gen_pcb.py" のあと '
        '"tools/autoroute.py" を実行すること')


# --------------------------------------------------------------------------
# 本体基板と子基板をつなぐ FFC
# --------------------------------------------------------------------------

def ffc_span(half):
    """J_DB（本体）と J_MAIN（子基板）の平面距離 mm。

    **左右で別の値になる。**子基板の左右位置が半分ごとに違うため。
    """
    from gen_case import (BUMP_DEPTH, DB_D, DB_FROM_REAR, WALL,
                          daughterboard_x_center)
    from interface import plan_depth, plate_positions
    _, (w, h) = plate_positions(HALVES[half])
    # **footprints() を使わない。**あの正規表現は `.*?` で最初に見つかった
    # (at ...) を拾うため、部品によって別の座標を返す（J_DB では左が
    # 誤った値・右が空になった）。括弧の対応で切り出す方を使う。
    txt = (PCB / f"hhkb_split_{half}.kicad_pcb").read_text()
    blk = next(b for r, b in _footprint_blocks(txt) if r == "J_DB")
    at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)", blk)
    jx, jy = float(at.group(1)) - ORIGIN[0], ORIGIN[1] - float(at.group(2))
    # 子基板は奥の壁ぎわ。J_MAIN は子基板の中心から手前へ 11.0mm
    # （pcb/hhkb_split_daughterboard.kicad_pcb で実測。外形中心 y=100、
    #   J_MAIN は y=111 で KiCad は Y 下向きなので手前側）。
    dbx = daughterboard_x_center(half, w)
    # **plan_depth を通す**（plate_positions はプレートの奥行。0.44mm ずれる）
    dby = plan_depth(h) / 2 + BUMP_DEPTH - WALL - DB_FROM_REAR - DB_D / 2
    return math.hypot(dbx - jx, (dby - 11.0) - jy)


@pytest.mark.parametrize("half", NAMES)
def test_the_ffc_cable_reaches_the_daughterboard(half):
    """FFC が本体基板から子基板まで、余裕を持って届くこと。

    **部品を動かすと静かに届かなくなる。**実際、自動配線のために
    J_DB を左 9.1mm・右 8.5mm 動かしたとき、これを見る検査が無かった。
    ケーブルは発注品なので、合わないと分かるのが組み立て時になる。

    ケーブルを張った状態では使えないので、直線距離に FFC_SLACK
    （垂直の落差・両端の曲げ・抜け止めの遊び）を足して見る。
    **どちらも暫定値**（docs/hardware/provisional-values.md）。
    """
    from envelopes import FFC_LENGTH, FFC_SLACK
    need = ffc_span(half) + FFC_SLACK
    assert need <= FFC_LENGTH, (
        f"{half}: FFC が届かない。直線 {ffc_span(half):.1f}mm + 余裕 "
        f"{FFC_SLACK}mm = {need:.1f}mm > ケーブル {FFC_LENGTH}mm。"
        "J_DB か子基板を近づけるか、長いケーブルを選ぶこと")


def test_both_halves_can_use_the_same_ffc_cable():
    """左右で同じ長さの FFC が使えること。

    **違う長さが要ると、部品表と在庫が 2 種類になる。**組み立てで
    取り違えると、短い方が届かない。左右で子基板の位置が違うので、
    ここは黙って壊れうる。
    """
    from envelopes import FFC_LENGTH, FFC_SLACK
    need = {h: ffc_span(h) + FFC_SLACK for h in NAMES}
    assert max(need.values()) <= FFC_LENGTH, (
        f"1 種類のケーブルで足りない: "
        + " / ".join(f"{h} {v:.1f}mm" for h, v in need.items())
        + f" > {FFC_LENGTH}mm")


@pytest.mark.parametrize("half", NAMES)
def test_no_user_operated_part_is_sealed_inside(half):
    """使用者が操作する部品が、基板の上に載っていないこと。

    **DRC が 0 でも、手が届かない場所にある部品は検出されない。**
    電源スイッチを帯（段と段の間・基板の裏面）に置いていて、上は
    プレートとキーキャップ、下はケースの床という状態になっていた
    （open-gaps #17）。ケースを開けないと入切できない。

    基板の後端からケース背面までは 23.3mm あり、**基板の上のどこに
    置いても背面には出せない。**だから操作する部品は基板に載せず、
    ケースのパネルに付けて配線で繋ぐ（基板側はランド 2 個）。

    ここで見るのは「回路に宣言された操作部品が、基板上の実体を
    持っていないこと」。増えたときに気づけるようにしておく。
    """
    from circuit import netlist
    txt = (PCB / f"hhkb_split_{half}.kicad_pcb").read_text()
    refs = {r for r, _ in _footprint_blocks(txt)}
    # 使用者が指で触る部品。**キースイッチは除く**（触るのが仕事）。
    operated = {ref for ref, kind, _ in netlist(half)
                if kind in ("slide_switch", "push_button", "rotary_encoder")}
    on_board = sorted(operated & refs)
    assert not on_board, (
        f"{half}: 使用者が操作する部品が基板に載っている: {on_board}\n"
        "  基板の上には手が届かない（プレートとキーキャップの下）。\n"
        "  ケースのパネルに付けて配線で繋ぐこと（kind を wire_pads にする）")


@pytest.mark.parametrize("name", NAMES)
def test_the_declared_socket_envelope_contains_the_real_footprint(name):
    """`bands.SOCK_LO/HI` が、実フットプリントを本当に囲んでいること。

    帯の位置と高さは、この 2 つの数字から導いている。**手で書いた数字なので、
    外の事実に繋いでおかないと静かにずれる。**フットプリントのライブラリを
    別のものに差し替えたときが危ない。

    **これが無いと帯の検査は空回りする。**帯を広げれば「帯に収まっている」は
    通りやすくなるだけで、部品がソケットに乗ることは誰も見ない。実際、
    変異検査で `BAND_H` を 9.25 → 10.175 にしても 271 件が全部通った。
    """
    from bands import SOCK_HI, SOCK_LO, SOCK_X_HI, SOCK_X_LO

    text = (PCB / f"hhkb_split_{name}.kicad_pcb").read_text()
    worst_lo, worst_hi, worst_ref = 0.0, 0.0, None
    worst_x_lo, worst_x_hi = 0.0, 0.0
    seen = 0
    for blk in re.split(r"\n\t\(footprint ", text)[1:]:
        ref = re.search(r'\(property "Reference" "(SW\d+)"', blk)
        if not ref:
            continue
        seen += 1
        ys, xs = [], []
        # パッド（半田付けする実体）
        for seg in re.findall(r"\(pad [\s\S]*?\n\t\t\)", blk):
            at = re.search(r"\(at ([-\d.]+) ([-\d.]+)", seg)
            sz = re.search(r"\(size ([\d.]+) ([\d.]+)\)", seg)
            if at and sz:
                x, w = float(at.group(1)), float(sz.group(1))
                y, h = float(at.group(2)), float(sz.group(2))
                xs += [x - w / 2, x + w / 2]
                ys += [y - h / 2, y + h / 2]
        # 裏面のコートヤード（ソケット本体の占有）
        for seg in re.findall(r"\((?:fp_line|fp_arc)\b[\s\S]*?\n\t\t\)", blk):
            if '(layer "B.CrtYd")' in seg:
                for a, b in re.findall(
                        r"\((?:start|mid|end) ([-\d.]+) ([-\d.]+)\)", seg):
                    xs.append(float(a))
                    ys.append(float(b))
        if not ys:
            continue
        worst_x_lo = min(worst_x_lo, min(xs))
        worst_x_hi = max(worst_x_hi, max(xs))
        # KiCad は Y 下向き。レイアウト座標（Y 上向き）へ直す。
        lo, hi = -max(ys), -min(ys)
        if lo < worst_lo or worst_ref is None:
            worst_lo, worst_ref = lo, ref.group(1)
        worst_hi = max(worst_hi, hi)

    assert seen >= 27, f"{name}: スイッチが {seen} 個しか見つからない。走査が壊れている"
    assert SOCK_LO <= worst_lo, (
        f"{name}: 宣言 SOCK_LO={SOCK_LO} より実物が下へ出ている（{worst_lo:.2f}"
        f"・{worst_ref}）")
    assert worst_hi <= SOCK_HI, (
        f"{name}: 宣言 SOCK_HI={SOCK_HI} より実物が上へ出ている（{worst_hi:.2f}）")

    # **緩い方向も見る。**囲めているかだけを見ると、宣言を広げ放題になる。
    # 広げると帯 BAND_H が痩せるので発注前に気づく…とは限らない。実際、
    # 変異検査で SOCK_LO を -2.6 → -2.86 にしても検査が全部通った。
    # 左右方向も同じ要領で。**ここを見ないと SOCK_X_LO/HI が測られない。**
    # ボスとの干渉に効く数字なので、囲めているかは確かめる必要がある。
    assert SOCK_X_LO <= worst_x_lo, (
        f"{name}: 宣言 SOCK_X_LO={SOCK_X_LO} より実物が外へ出ている"
        f"（{worst_x_lo:.2f}）")
    assert worst_x_hi <= SOCK_X_HI, (
        f"{name}: 宣言 SOCK_X_HI={SOCK_X_HI} より実物が外へ出ている"
        f"（{worst_x_hi:.2f}）")

    SLACK = 1.0
    assert worst_lo - SOCK_LO <= SLACK, (
        f"{name}: SOCK_LO={SOCK_LO} が実物（{worst_lo:.2f}）より "
        f"{worst_lo - SOCK_LO:.2f}mm も余っている。帯を無駄に痩せさせている")
    assert SOCK_HI - worst_hi <= SLACK, (
        f"{name}: SOCK_HI={SOCK_HI} が実物（{worst_hi:.2f}）より "
        f"{SOCK_HI - worst_hi:.2f}mm も余っている。帯を無駄に痩せさせている")
    assert worst_x_lo - SOCK_X_LO <= SLACK, (
        f"{name}: SOCK_X_LO={SOCK_X_LO} が実物（{worst_x_lo:.2f}）より "
        f"{worst_x_lo - SOCK_X_LO:.2f}mm も余っている")
    assert SOCK_X_HI - worst_x_hi <= SLACK, (
        f"{name}: SOCK_X_HI={SOCK_X_HI} が実物（{worst_x_hi:.2f}）より "
        f"{SOCK_X_HI - worst_x_hi:.2f}mm も余っている")


@pytest.mark.parametrize("name", NAMES)
def test_the_antenna_keepout_is_actually_empty(name):
    """アンテナの禁止域に、銅が本当に 1 つも無いこと。

    **設定しただけでは効いていない。**Freerouting 2.3.0 は DSN に書いた
    禁止域を守らない（4 層とも正しく出ていることは確認済み）。宣言を
    信じると、実際は配線が通っているのに「対策した」と思い込む。

    右は入れられなかった（`ANTENNA_KEEPOUT["right"] is None`）。
    裏面を列のバス 9 本が横断しており、子基板の x を 0.5mm 刻みで
    全部試しても最良で 9 本掛かる。理由は interface.py に書いた。
    """
    from interface import ANTENNA_KEEPOUT

    spec = ANTENNA_KEEPOUT[name]
    if spec is None:
        return
    cx, cy, w, h = spec
    # レイアウト座標 → KiCad 座標（Y 下向き・原点 ORIGIN）
    x_lo, x_hi = ORIGIN[0] + cx - w / 2, ORIGIN[0] + cx + w / 2
    y_lo, y_hi = ORIGIN[1] - cy - h / 2, ORIGIN[1] - cy + h / 2
    text = (PCB / f"hhkb_split_{name}.kicad_pcb").read_text()

    # **境界ちょうどは中ではない。**ベタは禁止域を避けて回り込むので、
    # その輪郭の頂点が縁の上に載る。それを「銅がある」と数えると
    # 正しく効いているのに落ちる（実際に落ちた）。少し内側で見る。
    EPS = 0.01

    def inside(x, y):
        return (x_lo + EPS <= x <= x_hi - EPS
                and y_lo + EPS <= y <= y_hi - EPS)

    bad = []
    for seg in re.findall(r"\n\t\(segment[\s\S]*?\n\t\)", text):
        a = re.search(r"\(start ([-\d.]+) ([-\d.]+)\)", seg)
        b = re.search(r"\(end ([-\d.]+) ([-\d.]+)\)", seg)
        lay = re.search(r'\(layer "([^"]+)"\)', seg)
        if a and b and (inside(float(a.group(1)), float(a.group(2)))
                        or inside(float(b.group(1)), float(b.group(2)))):
            bad.append(f"配線({lay.group(1)})")
    for via in re.findall(r"\n\t\(via[\s\S]*?\n\t\)", text):
        a = re.search(r"\(at ([-\d.]+) ([-\d.]+)\)", via)
        if a and inside(float(a.group(1)), float(a.group(2))):
            bad.append("ビア")
    n_fill = 0
    for zp in re.findall(r"\(filled_polygon[\s\S]*?\n\t\t\)", text):
        for xs, ys in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", zp):
            if inside(float(xs), float(ys)):
                n_fill += 1
    assert not bad and n_fill == 0, (
        f"{name}: アンテナの禁止域に銅がある。"
        f"{bad[:5]}{'' if not bad else ' ほか'} / ベタの頂点 {n_fill} 点")


@pytest.mark.parametrize("name", NAMES)
def test_the_ground_plane_still_covers_the_board(name):
    """GND ベタが基板の大半を覆ったままであること。

    **禁止域を開けることの代償はここに出る。**地板は戻り電流の道なので、
    穴で分断すると、その向こうの部品の戻り電流が遠回りする。

    **数で見てはいけない。**最初「塗られた多角形が 1 個であること」と
    書いたが、地板を横断する帯を故意に入れても 1 個のままだった。
    KiCad は切り離された側を**孤島として黙って削除する**ので、
    多角形は 1 個のまま面積だけが半分になる（頂点 12246 → 6248 で気づいた）。
    面積で見る。

    いまの左の禁止域は基板の縁から入る**切り欠き**で、内部に穴を作って
    いない。切り欠きの向こうには部品もビアも無く、近くを通るのは
    SW6_D と ROW0 だけ。**どちらも走査の kHz** なので遠回りは効かない。
    """
    text = (PCB / f"hhkb_split_{name}.kicad_pcb").read_text()
    blk = re.search(r"\(filled_polygon[\s\S]*?\n\t\t\)", text)
    assert blk, f"{name}: GND ベタが 1 枚も塗られていない"
    pts = [(float(a), float(b)) for a, b in
           re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", blk.group(0))]
    area = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                   - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts)))) / 2
    xs = [(float(a), float(b)) for a, b in
          re.findall(r"\(gr_line[\s\S]{0,120}?\(start ([-\d.]+) ([-\d.]+)\)", text)]
    board = ((max(p[0] for p in xs) - min(p[0] for p in xs))
             * (max(p[1] for p in xs) - min(p[1] for p in xs)))
    ratio = area / board
    # いまは左 86.5% / 右 89.3%。地板を割ると 39.5% まで落ちる（実測）。
    assert ratio >= 0.80, (
        f"{name}: GND ベタが基板の {ratio * 100:.1f}% しか覆っていない。"
        "禁止域か配線が地板を割り、切り離された側が孤島として削除された"
        "可能性がある。戻り電流の道が切れるので、割らない形に直すこと")


# --------------------------------------------------------------------------
# フットプリントを**メーカーのデータシート**と突き合わせる（2026-08-10）
# --------------------------------------------------------------------------
# 実形状の検査で、Kailh ソケットのモデルが基板に 0.13mm^3 食い込んでいた。
# **どちらが間違っているのかを、第三者のモデルどうしでは決められない。**
# 決めるのはメーカーの図面。突き合わせた結果「基板は正しく、モデルが
# 実物より大きい」と分かったので、その組は比べないことにした。
#
# **その判断の根拠をここに残す。**根拠が検査になっていないと、
# 「モデルが大きいだけ」は次の人にとってただの言い訳になる。
#
# 出典: Kailh PG151101S11 製品規格書 KH-PS1607-10 Rev.B の
#       「9. Recommended PCB Layout」（φ3.00 の穴 2 つ・間隔 6.35 と 2.54、
#        パッド 2.5 x 2.55mm）。

def test_the_hotswap_footprint_matches_the_kailh_datasheet():
    """ホットスワップソケットのフットプリントが、データシートどおりであること。"""
    import re

    fp = (ROOT / "pcb/lib/keyswitch.pretty/SW_Hotswap_Kailh_MX_1.00u.kicad_mod").read_text()
    # **1 行ごとに at / size / drill を別々に拾う。**まとめて 1 つの正規表現で
    # 取ろうとすると、SMD パッドの (layers ...) を挟んだ形に当たらず、
    # 「パッド 0 枚」と誤って報告した（2026-08-10）。
    pads = []
    for line in fp.splitlines():
        if "(pad " not in line:
            continue
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+)", line)
        size = re.search(r"\(size ([\d.]+) ([\d.]+)\)", line)
        drill = re.search(r"\(drill ([\d.]+)", line)
        if at and size:
            pads.append((float(at.group(1)), float(at.group(2)),
                         float(size.group(1)), float(size.group(2)),
                         float(drill.group(1)) if drill else None))
    holes = [(x, y, d) for x, y, _w, _h, d in pads if d]
    # ソケットの端子が入る穴（φ3.05）。MX 軸の穴（φ4 / φ1.75）とは別。
    sock = sorted((h for h in holes if 2.9 <= h[2] <= 3.2), key=lambda h: h[0])
    assert len(sock) == 2, f"ソケットの穴が {len(sock)} 個（2 個のはず）"
    (x0, y0, d0), (x1, y1, d1) = sock
    assert 3.00 <= d0 <= 3.15 and 3.00 <= d1 <= 3.15, (
        f"穴径 {d0}/{d1}mm。データシートは φ3.00（実物が入る側に少しだけ大きく）")
    assert abs(x1 - x0) == pytest.approx(6.35, abs=0.01), (
        f"穴の左右間隔 {abs(x1 - x0):.3f}mm。データシートは 6.35mm")
    assert abs(y1 - y0) == pytest.approx(2.54, abs=0.01), (
        f"穴の前後のずれ {abs(y1 - y0):.3f}mm。データシートは 2.54mm")
    # はんだ付けするパッド 2.5 x 2.55mm
    solder = [(w, h) for _x, _y, w, h, d in pads if d is None and 2.0 < w < 3.5]
    assert len(solder) == 2, f"はんだパッドが {len(solder)} 枚（2 枚のはず）"
    for w, h in solder:
        assert {round(w, 2), round(h, 2)} == {2.55, 2.5}, (
            f"パッド {w}x{h}mm。データシートは 2.5 x 2.55mm")
