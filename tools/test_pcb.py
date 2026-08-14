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


# **基板の解析はキャッシュする**（2026-08-15・利用者「検査が想定より
# 大幅に長い。原因を突き止め、削減できるなら削減して」）。
#
# ⚠️ **同じファイルを検査ごとに読み直して正規表現をかけていた。**
# 配線済みの右基板は 37,000 行あり、`.*?` を挟んだ `re.S` の走査が
# **1 回で 400 秒**かかる。中身の違う 4 つの検査が揃って 400 秒だった
# ことが手がかりになった（＝検査本体ではなく共通の前処理が重い）。
#
# 実測（`--durations`・実形状の門を入れた後の 48 分の内訳）:
#   test_stabilizers_are_on_the_wide_keys[right]            401.55s
#   test_switch_positions_match_the_plate[right]            401.52s
#   test_switch_footprint_size_matches_the_key_width[right] 401.39s
#   test_every_footprint_is_inside_the_outline[right]       400.02s
#   （左は各 195s）→ **上位 8 件だけで約 39 分**
#
# ⚠️ **キャッシュしてよいのは「検査の実行中にファイルが変わらない」から。**
# CLAUDE.md にも「検査の実行中にファイルを編集しない」と書いてある
# （編集途中を読んで偽の赤／偽の緑が出た事故が 2 回）。
_CACHE = {}


def _pcb_text(name):
    """基板ファイルの中身。**1 回だけ読む。**"""
    key = ("text", name)
    if key not in _CACHE:
        _CACHE[key] = (PCB / f"hhkb_split_{name}.kicad_pcb").read_text()
    return _CACHE[key]


def footprints(name):
    """(ライブラリ名, 参照, x, y) の一覧をレイアウト座標（Y 上向き）で返す。

    ⚠️ **`.*?` でフットプリントを跨がないこと**（2026-08-15）。
    以前は 1 つの正規表現で `(footprint ...` から `(at ...` と
    `(property "Reference" ...` を一度に拾っていたが、**`.*?` が
    フットプリントの境界を越えて 200 万文字を走査**し、
    カタストロフィック・バックトラッキングを起こしていた。

    **実測: 右基板 1 回で 403 秒。**しかも**取りこぼしていた**——
    44 件しか返らず、正しくは 83 件（`pads_with_nets` が返す数と一致）。
    `.*?` が境界を越えるので `(at` と `Reference` の対応がずれ、
    **部品の約半分がこの関数を使う検査から漏れていた。**
    footprints() を使う検査（スイッチ位置・外形内・スタビ・幅）は
    **半分の部品しか見ていなかった**ことになる。
    直したら 83 件すべてを見て、そのうえで緑だった（実害は無かった）。

    `pads_with_nets` と同じく**フットプリント単位で切ってから中を見る**。
    実測 0.01 秒（4 万倍）で、件数も正しくなる。
    """
    key = ("footprints", name)
    if key in _CACHE:
        return _CACHE[key]
    out = []
    for fp in re.finditer(r'\n\t\(footprint "([^"]+)"(.*?)\n\t\)',
                          _pcb_text(name), re.S):
        lib, body = fp.group(1), fp.group(2)
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+)", body)
        ref = re.search(r'\(property "Reference" "([^"]+)"', body)
        if not at or not ref:
            continue
        x, y = float(at.group(1)), float(at.group(2))
        out.append((lib, ref.group(1), x - ORIGIN[0], ORIGIN[1] - y))
    _CACHE[key] = out
    return out


def outline_extent(name):
    """Edge.Cuts に引いた線分と円弧から、外形の外接矩形を出す。"""
    key = ("outline", name)
    if key in _CACHE:
        return _CACHE[key]
    s = _pcb_text(name)
    xs, ys = [], []
    for blk in re.finditer(r"\(gr_(?:line|arc)\b(.*?)\n\t\)", s, re.S):
        b = blk.group(1)
        if '"Edge.Cuts"' not in b:
            continue
        for m in re.finditer(r"\((?:start|end|mid) ([-\d.]+) ([-\d.]+)\)", b):
            xs.append(float(m.group(1)) - ORIGIN[0])
            ys.append(ORIGIN[1] - float(m.group(2)))
    _CACHE[key] = (min(xs), min(ys), max(xs), max(ys))
    return _CACHE[key]


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
    key = ("pads", name)
    if key in _CACHE:
        return _CACHE[key]
    s = _pcb_text(name)
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
    _CACHE[key] = out
    return out


@pytest.mark.parametrize("name", NAMES)
def test_matrix_wiring_matches_the_firmware(name):
    """基板の配線が、ファームウェアの行列対応表と一致すること。

    **ここがずれるとキーが入れ替わる。** 基板とファームで別々に表を持つと
    いつか片方だけ直して破綻するので、同じ出所（hhkb_split.dtsi の
    matrix-transform）から導いていることを毎回確かめる。
    """
    from matrix import assignments, row_nets
    rc = assignments(name)
    # 行 r のネット名は**行番号ではなくケーブル上の位置**（2026-08-15）。
    # 左右で違う行を同じレーンに載せるので、行番号の名前は片側で嘘になる。
    rows = row_nets(name)
    pads = pads_with_nets(name)
    for i, (r, c) in enumerate(rc, start=1):
        assert pads[f"SW{i}"]["1"] == f"COL{c}", \
            f"{name}: SW{i} が COL{c} につながっていない"
        assert pads[f"D{i}"]["1"] == rows[r], \
            f"{name}: D{i} のカソードが {rows[r]}（行 {r}）につながっていない"
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
        assert p["1"].startswith("ROW_"), f"{ref}: カソードが行側にない"
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
    # ⚠️ **行のネット名は ROW_A..E**（2026-08-15）。行番号ではなく
    # ケーブル上の位置。左右で違う行を同じレーンに載せるため。
    matrix = {n for n in nets if re.fullmatch(r"ROW_[A-E]|COL\d+|SW\d+_D", n)}
    assert len(matrix) == rows + cols + len(HALVES[name]), \
        f"{name}: マトリクスのネットが {len(matrix)} 本"
    # 電源・通信のネットも載っていること。
    #
    # ⚠️ **VBATT_SW / VBATT_SENSE は主基板に無い**（2026-08-14・#41）。
    # 電池・スイッチ・ショットキー・分圧は**全部 子基板へ移した**ので、
    # 主基板が受け取るのは V3V3 と GND だけ。**この検査は移設のときに
    # 追随しておらず、それから赤のまま残っていた**（2026-08-15 に気づいた）。
    for n in ("GND", "V3V3", "SPI_SCK", "SPI_MOSI", "CS"):
        assert n in nets, f"{name}: ネット {n} が無い"
    for n in ("VBATT_SW", "VBATT_SENSE"):
        assert n not in nets, (
            f"{name}: **{n} が主基板に戻っている。**電源部は子基板にある"
            "（#41。FFC を渡るのは V3V3 と GND だけ）")
    assert "VBATT_RAW" not in nets, (
        f"{name}: **VBATT_RAW が復活している。**電池の + は基板を通さず"
        "スイッチへ直結する（open-gaps #41）")


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
def test_the_main_board_is_two_layers_with_ground_poured_on_both(facts, half):
    """本体基板が 2 層で、**両面とも** GND のベタが塗られていること。

    2026-08-12 に 4 層から 2 層へ落とした（指摘 2）。4 層にした当時の
    根拠「行の引き回しが 2 層では通らない」は、その後 Freerouting に
    切り替えて配線をやり直したときに崩れていた——**信号は実際には
    In2.Cu と B.Cu の 2 層に収まり、F.Cu は配線 0 本で空いていた**（実測）。

    2 層になると GND 専用層が無くなるので、**両面に敷く**（指摘 3）。

    **「層を 2 に設定した」「ゾーンを足した」だけでは足りない。**
    それぞれの面でベタが実際に塗られていることまで見る。
    この案件では「足した」と「塗られた」を 2 回取り違えている。
    """
    f = facts[half]
    assert f["layers"] == ["F.Cu", "B.Cu"], f"{half}: 層構成が {f['layers']}"
    poured = {lay for lay, net, filled in f["zones"] if net == "GND" and filled}
    assert poured == {"F.Cu", "B.Cu"}, (
        f"{half}: GND ベタが塗られている面が {sorted(poured)}。"
        "両面（F.Cu と B.Cu）に要る")


# --------------------------------------------------------------------------
# 電子部品が帯に収まっているか
#
# **「寄っている」と「入っていない」は別の問題。**
# SOIC-16 はコートヤード 10.49mm で、帯 9.25mm にそもそも入らない。
# 位置を微調整しても 0 にはならない。算数で入らないものを、機械が言う。
# --------------------------------------------------------------------------

def _sexpr_blocks(txt, head):
    """トップレベルの `(head ...)` を括弧の対応で切り出して順に返す。

    **正規表現で切らない。**非貪欲でも次の塊まで食ってしまい、
    誤検出したことがある（GND 基準面の検査で実際に起きた）。
    """
    for m in re.finditer(r"\n\t\(" + head + r"\b", txt):
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
        yield txt[i:j + 1]


def _zone_blocks(txt):
    """ゾーン（ベタ・禁止域）の S 式を順に返す。"""
    return _sexpr_blocks(txt, "zone")


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


# `test_the_ground_stays_one_island_after_routing` は削除した（2026-08-12）。
#
# 4 層のときは GND 専用層があり「その層に配線が 0 本か」で面の連続を
# 保証できた。**2 層では信号層と兼ねるので、面が割れるのは避けられない。**
# 「島が 1 つ」は達成し得ない条件になった。
# 代わりに `test_few_pieces_of_ground_copper_are_left_floating` が
# **浮いている（GND のどこにも触れていない）区画の数**を見る。
# 割れていても、ビアで繋がっていれば問題ない。


@pytest.mark.parametrize("half", NAMES)
def test_every_ground_pad_reaches_the_plane(half):
    """電子部品の GND パッドの脇にビアが立っていること。

    GND パッドは全部 B.Cu の SMD。ベタは F.Cu・B.Cu の両面にあるが、
    B.Cu 側のパッドから F.Cu 側のベタへ電位を渡すにはビアが要る
    （2026-08-13 訂正：4 層時代は In1.Cu が GND 専用層だったが、
    2 層化で両面ベタに変わった。判定条件自体は層数に依存しない）。
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


def test_the_antenna_clears_the_main_board():
    """**アンテナが本体基板と平面で重ならないこと。**（2026-08-14）

    ここは open-gaps #23——発注を止めている門——の中身そのもの。

    以前は「アンテナの真上の銅を抜く」禁止域（30x15mm）を左基板に
    開けていた。**測ったらアンテナを覆っていなかった。**

        禁止域        y 30.60 .. 45.60
        本体基板の後端 y 48.70
        アンテナ      y 49.50 .. 53.00   ← 禁止域の 3.90mm 奥

    アンテナは本体基板の後端より**奥**にいる（`XIAO_OVERHANG` 1.8mm を
    入れた効果）。平面的に基板の外なので、地板に覆われていない。
    禁止域は的を外したまま 450mm² の銅を捨て、左基板の配線を
    圧迫していた（実害: 電源ブロックが置けず DRC 5 件）。

    **前の検査は「禁止域の中が空か」しか見ておらず、位置が合っているかを
    誰も確かめていなかった。**`interface.py` には
    `test_the_antenna_keepout_actually_covers_the_antenna` が照合すると
    書いてあったが、**その検査は存在しなかった。**これはその穴を塞ぐもの。

    ⚠️ **余裕は 0.80mm しかない。**製造公差と組み立てのばらつきで
    簡単に入れ替わる薄さなので、ここが縮んだら気づけるようにしておく。
    足りるかどうかは **#23 の手 0（アルミ箔で RSSI・¥0・1 日）** で測る。
    """
    import interface as I
    import gen_case as G
    from gen_plate import plate_positions, halves

    H = halves()
    for half in NAMES:
        if half == "daughterboard":
            continue
        _, (_w, h) = plate_positions(H[half])
        # 子基板の中心 y。**gen_case が実際に使っている式をそのまま使う**
        # （ここで別の式を書くと、片方だけ直って静かにずれる）。
        db_y = (h / 2 + G.BUMP_DEPTH) - G.WALL - G.DB_FROM_REAR - G.DB_D / 2
        lo, hi = I.antenna_y_span(G.DB_D / 2)
        antenna_front = db_y + lo
        pcb_rear = h / 2 - I.PCB_INSET_Y
        gap = antenna_front - pcb_rear
        assert gap > 0, (
            f"{half}: **アンテナが本体基板の下に入っている**"
            f"（アンテナ前端 y={antenna_front:.2f} < 基板後端 y={pcb_rear:.2f}・"
            f"{-gap:.2f}mm 潜っている）。\n"
            "両面 GND ベタが真上に来るので 2.4GHz が塞がれる。"
            "open-gaps #23 を読むこと")


@pytest.mark.parametrize("name", NAMES)
def test_the_ground_plane_still_covers_the_board(name):
    """GND ベタが基板の大半を覆ったままであること。

    **禁止域を開けることの代償はここに出る。**地板は戻り電流の道なので、
    大きく削れるとその向こうの部品の戻り電流が遠回りする。

    ⚠️ **2026-08-13 に測り方を直した。**以前は正規表現で**最初に見つけた
    多角形 1 個**の面積を測っていた。4 層のときはベタが 1 枚の連続した
    面だったので、それで用が足りていた。**2 層ではベタが配線で細かく
    分かれる**ので、最初の 1 個は全体の 0.24% しかなく、嘘の赤が出た。

    面ごとに**塗られた多角形すべての合計**で測る。

    しきい値について
    ----------------
    実測（2026-08-13）は **左 B.Cu 76.4% / F.Cu 82.4%、
    右 B.Cu 79.8% / F.Cu 84.4%、子基板 B.Cu 62.4%**。
    一方、**地板を故意に割ったときは 39.5% まで落ちる**（4 層時代の実測）。

    55% はその 2 つを分ける値であって、**現在値に合わせて置いた数字では
    ない**。「正常なら 60% 以上、割れたら 40% 前後」という 2 つの実測の
    間を取っている。
    """
    facts = _board_facts(name) if name in NAMES else None
    if facts is None:
        pytest.skip(f"{name} は対象外")
    per = facts["gnd_coverage"]
    assert per, f"{name}: GND ベタが 1 枚も塗られていない"
    thin = {k: v for k, v in per.items() if v < 0.55}
    assert not thin, (
        f"{name}: GND ベタの被覆率が低い面がある "
        + " / ".join(f"{k} {v*100:.1f}%" for k, v in sorted(thin.items()))
        + "\n  禁止域か配線が地板を大きく削っている可能性がある。"
        "戻り電流の道が遠回りになるので、削らない形に直すこと")


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


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_mounting_holes_are_isolated_from_ground(half):
    """取付穴が **GND につながっていない**こと（electrical-design 3-3）。

    ケースが樹脂なので落とす意味が無く、**ネジ頭が他所に触れたときの
    経路になる。**規則は 2026-08-09 から書いてあったが、**穴そのものが
    無かったので誰も見張っていなかった。**2026-08-12 に穴を足したので、
    ここで初めて意味を持つ。

    非メッキ穴（`MountingHole_2.2mm_M2`）ならネットは付かない。
    `MountingHole_Pad` 系に差し替えるとパッドが出て GND に落ちうる。
    """
    import re

    txt = (PCB / f"hhkb_split_{half}.kicad_pcb").read_text()
    blocks = re.findall(r'\(footprint "MountingHole[^"]*"(.*?)\n\t\)\n', txt, re.S)
    assert blocks, f"{half}: 取付穴が 1 つも無い"
    nets = set()
    for b in blocks:
        nets |= {m.group(1) for m in re.finditer(r'\(net \d+ "([^"]*)"', b)}
    assert not nets, (
        f"{half}: 取付穴にネットが付いている: {sorted(nets)}。"
        "**絶縁のままにすること**（electrical-design 3-3）")


# ======================================================================
# 2026-08-12 の回路レビュー（熟練エンジニアの指摘 4・6・7・8）
#
# **どれも「配置」ではなく「出来上がった銅」を測る。**
# 設定しただけ・置いただけでは効いていない、というのがこの案件で
# 何度も踏んだ型なので、判定は配線後の実物に対して行う。
# ======================================================================

# pcbnew を持つ Python の場所は pcb_parts に一本化してある
# （KICAD_PYTHON で差し替えられる）。


def _board_facts(half):
    """基板の中身を **pcbnew から**取り出す。

    ⚠️ **S 式を正規表現で読まない。**KiCad 10 はビアのネットを
    `(net "COL0")` と**名前**で書く（番号ではない）。番号を期待した
    正規表現が 1 件も拾えず、「GND のビアが 0 個」という嘘の赤を出した
    （2026-08-12）。書式は版で変わるので、KiCad 自身に読ませる。
    """
    import subprocess

    import pcb_parts
    from conftest import require_kicad_python

    require_kicad_python("配線後の実物から銅を測る検査")
    script = r"""
import json, pcbnew, sys
sys.path.insert(0, %r)
import gnd_fanout
b = pcbnew.LoadBoard(%r)
tracks, vias = [], []
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        p = t.GetPosition()
        vias.append([pcbnew.ToMM(p.x), pcbnew.ToMM(p.y), t.GetNetname()])
    else:
        s, e = t.GetStart(), t.GetEnd()
        tracks.append([b.GetLayerName(t.GetLayer()), t.GetNetname(),
                       pcbnew.ToMM(t.GetWidth()),
                       pcbnew.ToMM(s.x), pcbnew.ToMM(s.y),
                       pcbnew.ToMM(e.x), pcbnew.ToMM(e.y)])
pads = {}
for fp in b.GetFootprints():
    for pad in fp.Pads():
        q = pad.GetPosition()
        pads["%%s/%%s" %% (fp.GetReference(), pad.GetNumber())] = [
            pcbnew.ToMM(q.x), pcbnew.ToMM(q.y), pad.GetNetname()]
zones = []
for z in b.Zones():
    if z.GetIsRuleArea():
        continue
    for lay in z.GetLayerSet().CuStack():
        zones.append([b.GetLayerName(lay), z.GetNetname(),
                      z.HasFilledPolysForLayer(lay)])
floating = sum(1 for _z, _l, _p, f in gnd_fanout._islands(b) if f)
bb = b.GetBoardEdgesBoundingBox()
board_mm2 = pcbnew.ToMM(bb.GetWidth()) * pcbnew.ToMM(bb.GetHeight())
cov = {}
for z in b.Zones():
    if z.GetIsRuleArea() or z.GetNetname() != "GND":
        continue
    for lay in z.GetLayerSet().CuStack():
        if not z.HasFilledPolysForLayer(lay):
            continue
        ps = z.GetFilledPolysList(lay)
        a = sum(abs(ps.Outline(i).Area()) for i in range(ps.OutlineCount())) / 1e12
        nm = b.GetLayerName(lay)
        cov[nm] = cov.get(nm, 0.0) + a / board_mm2
print(json.dumps({"tracks": tracks, "vias": vias, "pads": pads,
                  "zones": zones, "floating": floating,
                  "gnd_coverage": cov,
                  "layers": [b.GetLayerName(l)
                             for l in b.GetEnabledLayers().CuStack()]}))
""" % (str(ROOT / "tools"), str(PCB / f"hhkb_split_{half}.kicad_pcb"))
    out = subprocess.run([pcb_parts.KICAD_PYTHON, "-c", script],
                         capture_output=True, text=True, check=True)
    import json as _json
    return _json.loads(out.stdout.strip().splitlines()[-1])


# パスコンと IC の電源ピンの間に許す距離（mm）。
#
# **物理から一意に決まる値ではない。**0805 のパッドと TSSOP-16 の
# 寸法から、隣に置いたときに構造的に決まるのが 2.64mm なので、
# 配置の揺れを見て 6mm を上限に置く。
# **17mm だった状態を二度と作らないための番人**であって、
# 「6mm なら十分」という主張ではない。
MAX_DECOUPLE_MM = 6.0

# GND ビアの下限（実測 左 732 / 右 913 の 75%）。
# **「これだけあれば十分」ではなく、静かな後退を見つけるための番人。**
# DRC は「判定が厳しすぎてビアが減った」を検出しないので、数で見る。
MIN_GND_VIAS = {"left": 550, "right": 700}

# 浮いた（GND のどこにも触れていない）区画の上限。**0 が必達。**
#
# 一時は「現実に 0 にできないので増加を検出する」としていたが、**誤り**
# だった（2026-08-13・利用者の指摘）。取り得る手は常に 2 つあり、
# どちらかは必ず選べる。
#
#   1. 繋ぐ  ビアが入るなら（gnd_fanout.stitch_islands）
#   2. 消す  ビアが入らないなら、その銅を残す理由が無い
#
# 浮いた銅は**電位が定義されておらず GND ではない**。遮蔽の役に立たず、
# 囲んでいる配線どうしを容量結合させ、2.4GHz では再放射する。
# 残す利益がゼロなので、**番人ではなく必達条件**として 0 を要求する。
MAX_FLOATING_ISLANDS = 0


@pytest.fixture(scope="module")
def facts():
    return {h: _board_facts(h) for h in NAMES}


@pytest.mark.parametrize("half", NAMES)
def test_power_nets_can_carry_the_current_they_actually_see(facts, half):
    """**電源の配線が、実際に流れる電流を流せる幅であること**（指摘 8）。

    ⚠️ **「規定幅の何割か」で見るのをやめた**（2026-08-13）。
    それは代理指標で、しかも**実測値を見てから閾値を置いていた**
    （96.5% を見てから 90% と書いた）。データに閾値を合わせる行為で、
    現状が悪くてもその悪さを固定してしまう。

    本当に問うべきは「**その幅で、実際に流れる電流を流せるか**」で、
    これは計算できる。閾値を置く必要がない。

      必要な幅 = 実際に流れる電流 ÷ 経験則（1A あたり 1mm）

    電流の出どころは `circuit.BLE_TX_CURRENT`（送信中の消費電流。
    この系で最大の電流）。**この検査は数字を持たない**——回路の宣言と
    経験則から毎回導く。電流の見積もりを直せば、ここも自動で追随する。

    利用者の指摘は「1A あたり 1mm 程度」「今回は 1A も流さないので現在の
    幅でも十分な可能性は高いが、**電源ラインから疑うという初歩的な疑いを
    無くしたい**」。だから求めるのは「足りていること」であって、
    「太いこと」ではない。余裕がどれだけあるかも表示する。
    """
    import math
    from circuit import BLE_TX_CURRENT
    from pcb_rules import JLC, POWER_CLASSES

    # 経験則: 1A あたり 1mm（利用者の指摘。外皮温度上昇を抑える目安）
    MM_PER_AMP = 1.0
    need_mm = BLE_TX_CURRENT * MM_PER_AMP

    power_nets = {n for _w, nets in POWER_CLASSES.values() for n in nets}
    worst = None
    bad = []
    for layer, net, w, x1, y1, x2, y2 in facts[half]["tracks"]:
        if net not in power_nets:
            continue
        if w < JLC["track_min"] - 1e-6:
            bad.append(f"{net} {w}mm ({layer}) — 製造の最小 {JLC['track_min']}mm 未満")
        elif w < need_mm - 1e-9:
            bad.append(f"{net} {w}mm ({layer}) — {BLE_TX_CURRENT*1000:.0f}mA には "
                       f"{need_mm:.3f}mm 要る")
        if worst is None or w < worst[0]:
            worst = (w, net, layer)

    assert worst is not None, f"{half}: 電源の配線が 1 本も無い"
    assert not bad, (
        f"{half}: 電流を流せない幅の配線がある\n  " + "\n  ".join(sorted(set(bad))))

    # 余裕を記録に残す（落とすためではなく、後から読む人のため）
    print(f"\n  {half}: 最も細い電源配線 {worst[0]}mm（{worst[1]} / {worst[2]}）"
          f" — {BLE_TX_CURRENT*1000:.0f}mA に必要な {need_mm:.3f}mm の "
          f"{worst[0]/need_mm:.0f} 倍")


@pytest.mark.parametrize("half", NAMES)
def test_there_are_enough_ground_vias_to_tie_the_two_planes(facts, half):
    """**GND のビアが十分な数あること**（指摘 4）。

    理屈の上ではビアが 1 個でも表と裏の GND は繋がる。しかし電流が流れると
    その 1 個に集中し、抵抗とインダクタンスが電位差として現れる。
    **多いほど電位が揃う。**
    """
    n = sum(1 for _x, _y, net in facts[half]["vias"] if net == "GND")
    assert n >= MIN_GND_VIAS[half], (
        f"{half}: GND のビアが {n} 個しかない（下限 {MIN_GND_VIAS[half]}）")


@pytest.mark.parametrize("half", NAMES)
def test_decoupling_caps_are_close_to_their_ic_in_copper(facts, half):
    """**パスコンと IC の電源ピンが近いこと**（指摘 6）。

    利用者の指摘のとおり、効くのは配置上の直線距離ではなく
    **IC の電源ピン → パスコン → GND → 地板 → IC の GND ピン**と
    一周する経路の配線長（ループのインダクタンス）。
    GND 側の復路は両面のベタと、各 GND パッド脇のビアが受け持つ
    （別の検査が見ている）ので、ここでは往路のパッド間を測る。

    2026-08-12 の実測では **17.0mm** あった。パスコンとして働かない距離。
    """
    import math
    import pinmap
    from pcb_rules import DECOUPLE_BESIDE
    pads = facts[half]["pads"]
    far = []
    for cap_ref, ic_ref in DECOUPLE_BESIDE.items():
        a = pads.get(f"{ic_ref}/{pinmap.resolve('74LVC595', 'VCC')}")
        b = pads.get(f"{cap_ref}/{pinmap.resolve('cap_100n', '1')}")
        if a is None or b is None:
            continue
        d = math.dist(a[:2], b[:2])
        if d > MAX_DECOUPLE_MM:
            far.append(f"{cap_ref}→{ic_ref}: {d:.2f}mm")
    assert not far, (
        f"{half}: パスコンが IC から遠い（上限 {MAX_DECOUPLE_MM}mm）\n  "
        + "\n  ".join(far))


@pytest.mark.parametrize("half", NAMES)
def test_few_pieces_of_ground_copper_are_left_floating(facts, half):
    """**浮いた GND の区画が増えていないこと**（指摘 5 の番人）。

    配線に囲まれて GND のどこにも触れていない銅は、電位が決まって
    おらず **GND ではない**。遮蔽の役に立たず、囲んでいる配線どうしを
    容量結合させ、2.4GHz では寸法次第でアンテナになる。

    **DRC はこれを何も言わない。**
    """
    n = facts[half]["floating"]
    assert n <= MAX_FLOATING_ISLANDS, (
        f"{half}: 浮いた GND の区画が {n} 箇所ある（**0 でなければならない**）。\n"
        "  繋ぐ（gnd_fanout.stitch_islands）か、消す（ゾーンの島削除）かの\n"
        "  どちらかが効かなくなっている。**浮いた銅を残す理由は無い。**")


@pytest.mark.parametrize("half", NAMES)
def test_there_is_exactly_one_bulk_capacitor_shared_by_the_board(half):
    """**バルクコンデンサは 1 個で、その基板の IC 全部で共用していること**
    （指摘 7）。

    指摘は「可能な範囲で数を減らし、複数の IC で共用できるように」。
    調べた結果、**すでに 1 枚あたり 1 個で、これ以上減らせない**。
    レール（V3V3）に付いているので、その基板の IC は全部これを共用している。

    バルクは「電池の内部抵抗が上がったときに BLE 送信のパルスを支える」
    ためのもの。パスコン（0.1µF）とは役割が違うので**統合できない**——
    パスコンは IC ごとに直近へ置くことに意味がある。

    **この検査は「減らせ」ではなく「増えたら気づく」ために置く。**
    後から不用意にバルクが増えたら落ちる。

    ⚠️ **2026-08-14 にバルクは子基板へ移った**（open-gaps #41）。守る相手が
    XIAO の µs 級の電流変動なので、FFC を挟まない側に置くのが筋だった。
    **主基板にバルクは無いのが正しい状態。**この検査は移設のときに
    追随しておらず、**それから赤のまま残っていた**（2026-08-15 に気づいた）。

    見るものを 2 つにする:
      - 主基板には**無い**こと（戻ってきたら気づく）
      - 子基板に**ちょうど 1 個**あり、レールに付いていること
    """
    from circuit import daughterboard_netlist, netlist

    on_main = [p for p in netlist(half) if p[1] == "cap_100u"]
    assert not on_main, (
        f"{half}: 主基板にバルクがある: {[p[0] for p in on_main]}。"
        "**バルクは子基板にある**（#41。守る相手は XIAO の電流変動で、"
        "FFC を挟まない側に置く）")

    bulk = [p for p in daughterboard_netlist() if p[1] == "cap_100u"]
    assert len(bulk) == 1, (
        f"子基板のバルクが {len(bulk)} 個ある: "
        f"{[p[0] for p in bulk]}。1 個で足りるはず"
        "（レールに付いていて全 IC が共用する）")
    assert set(bulk[0][2].values()) == {"V3V3", "GND"}, (
        f"バルクがレール（V3V3-GND）に付いていない: {bulk[0][2]}")


# ======================================================================
# **「判定が厳しすぎる」ことを検出するための検査**
#
# DRC は「緩すぎ」だけを見る。規則より厳しく置いても DRC は緑のままで、
# **ビアが減っているのに誰も気づけない。**実際 2026-08-12 に、
# ビアの半径を二重に数えていたせいで格子点の 8 割を無言で捨てていた。
#
# だから**結果の量**を測る。減ったら落ちる。
# ここの数字は「これだけあれば十分」という物理的主張ではなく、
# **静かな後退を見つけるための番人。**
# ======================================================================

# 実測値（2026-08-12・2 層化と判定の修正後）
#   左  ファンアウト 9 + スティッチング 175 + フェンス 121 = 305
#   右  ファンアウト 12 + スティッチング 210 + フェンス 174 = 396
# 下限はその 8 割。配線のやり直しで多少ぶれるため。
MIN_GND_VIAS = {"left": 240, "right": 310}

# **`MAX_FLOATING_ISLANDS = 12` はここにあった（2026-08-14 に削除）。**
# 2026-08-13 に「番人ではなく必達条件」へ方針を変えて 1165 行に `= 0` を
# 書いたとき、**古いこの定義を消さなかった。**Python は後の代入が勝つので
# **効いていたのは 12 のほう**で、検査の文言が「0 でなければならない」と
# 言いながら、浮いた区画が 12 個まで黙って通っていた。
# CLAUDE.md #8「置き換えたら、置き換えられた方を消す」の実例。
