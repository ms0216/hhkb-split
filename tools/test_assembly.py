"""組み上げた状態で部品どうしが食い込まないことを守る。

**この検査はこれまで pytest から呼ばれていなかった。**
tools/gen_assembly.py を手で叩いたときにしか動かず、その結果
「単体のテストは全部通るのに、組み上げると食い込む」状態を何度も作った。
実際にこのファイルを足した時点でも、電池と仕切り壁で 2 件見つかっている。

部品を 1 つ足したら、必ず gen_assembly.build_assembly の parts へも足すこと。
**検査対象に入っていない部品は、検査されていないのと同じ。**
"""

import sys
from pathlib import Path

import pytest

CLEARANCE_HALF = 0.1   # gen_case.CLEARANCE / 2（空所は片側 0.1mm 広い）

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_assembly import build_assembly, check  # noqa: E402
from gen_plate import halves  # noqa: E402

HALVES = halves()


def _github_actions_only(what):
    """**重い検査は GitHub Actions だけで走らせる。**（利用者の方針・2026-08-10）

    実形状の全組み合わせは片側 5 分以上かかる。手元の `pytest tools` が
    40 分になると誰も回さなくなり、**回さない検査は無いのと同じ**。
    バッチはビルドサーバに任せ、手元は速いままにする。
    REQUIRE_KICAD=1（あのジョブだけが立てる）のときだけ走る。
    """
    import os

    if os.environ.get("REQUIRE_KICAD") != "1":
        pytest.skip(f"{what}: 重いので GitHub Actions で走らせる")


def _require_kicad(what):
    """kicad-cli が無ければ飛ばす。**ただし REQUIRE_KICAD=1 なら失敗にする。**

    GitHub Actions の実形状ジョブはこれを 1 にして走らせる。**飛んだ検査は
    無いのと同じ**で、KiCad のインストールに失敗しても緑になってしまう
    ——この案件で実際に起きた（build/ が無くて電源スイッチの検査が
    毎回飛んでいた）。
    """
    import os
    import pcb_parts

    if Path(pcb_parts.KICAD_CLI).exists():
        return
    if os.environ.get("REQUIRE_KICAD") == "1":
        pytest.fail(f"{what}: kicad-cli が見つからない（{pcb_parts.KICAD_CLI}）。"
                    "このジョブは飛ばしてはいけない")
    pytest.skip(f"{what}: kicad-cli が無い環境")

# 組み立てに含まれていなければならない部品。
# 名前を書いておくことで、あとから足した部品が検査から漏れるのを防ぐ。
REQUIRED = {"case", "plate", "pcb", "lid", "batt", "db", "topcase",
            "foot0", "foot1", "xiao",
            # open-gaps #29: 製品として存在する実物
            "sockets", "pcb_parts", "db_parts", "switches", "keycaps",
            "stabs", "sw_pwr", "usb_plug", "ffc", "inserts", "screws",
            "nut", "rubber"}


@pytest.mark.parametrize("half", ["left", "right"])
def test_nothing_bites_into_anything_else(half):
    problems, _ = check(HALVES[half], half)[:2]
    assert not problems, f"{half}:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("half", ["left", "right"])
def test_every_part_is_in_the_check(half):
    """検査対象から部品が漏れていないこと。

    子基板を足したとき、ケースには造作を入れたのに検査には入れ忘れていた。
    そうすると「通った」が「調べていない」の同義語になる。
    """
    parts, _ = build_assembly(HALVES[half], half)
    missing = REQUIRED - set(parts)
    assert not missing, f"{half}: 検査に入っていない部品 {sorted(missing)}"


@pytest.mark.parametrize("half", ["left", "right"])
def test_every_part_has_a_colour(half):
    """色の定義から部品が漏れていないこと。

    色は PyVista の絵と Blender の .blend の両方が使う。漏れると
    **灰色になるだけで落ちない。**見分けがつかない絵は見ていないのと同じ。
    色は種類ごと（style_for が末尾の番号を落として引く）。
    #29 で部品を足すときは、種類の色を STYLE に 1 行足せば通る。
    """
    from export_assembly import style_for

    parts, _ = build_assembly(HALVES[half], half)
    missing = [n for n in parts if style_for(n) is None]
    assert not missing, f"{half}: 色が無い部品 {sorted(missing)}"


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_check_actually_detects_a_collision(half):
    """**検査そのものが効いていることを確かめる。**

    通ったことは、調べた証拠にならない。故意に壊して検出できることを
    毎回確かめる。この案件では、誤った並び順どうしを突き合わせて
    テストが全部通ってしまった前科がある。
    """
    import envelopes

    original = envelopes.DB_STACK_H
    try:
        envelopes.DB_STACK_H = original + 15.0     # 子基板の部品を背高にする
        problems, _ = check(HALVES[half], half)[:2]
        assert any("db" in p for p in problems), \
            "子基板を 15mm 背高にしても検出できない。検査が効いていない"
    finally:
        envelopes.DB_STACK_H = original


# --------------------------------------------------------------------------
# 電源スイッチが背面パネルに収まるか
# --------------------------------------------------------------------------

def _case_stl(half):
    """ケースの STL のパス。**無ければその場で作る**（約 10 秒）。

    飛ばすと「通った」が「調べていない」の同義語になる。
    """
    stl = Path(__file__).resolve().parent.parent / f"build/case_{half}.stl"
    if not stl.exists():
        import gen_case
        gen_case.main()
    assert stl.exists(), f"{stl} を作れなかった"
    return stl


def rear_panel_gaps(half):
    """背面パネルぞいの、障害物が無い x 区間と、使える奥行を返す。

    コブの中には電池と子基板が入っていて、どちらも背面壁の 1〜2mm 手前まで
    来ている。**スイッチを置けるのは、その左右の隙間だけ。**
    """
    from gen_case import (BUMP_DEPTH, DB_W, WALL, battery_x_center,
                          daughterboard_x_center)
    from gen_case import BATT_X
    from gen_plate import halves
    from interface import plate_positions
    from matrix import keymap_order
    _, (w, _h) = plate_positions(keymap_order(halves()[half]))
    bx, dx = battery_x_center(half, w), daughterboard_x_center(half, w)
    obstacles = sorted([(bx - BATT_X / 2, bx + BATT_X / 2),
                        (dx - DB_W / 2, dx + DB_W / 2)])
    gaps, cur = [], -w / 2 + WALL
    for a, b in obstacles:
        if a > cur:
            gaps.append((cur, a))
        cur = max(cur, b)
    if w / 2 - WALL > cur:
        gaps.append((cur, w / 2 - WALL))
    return gaps, BUMP_DEPTH - WALL


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_power_switch_fits_on_the_rear_panel(half):
    """電源スイッチが背面パネルの空きに収まること。

    **これは目で見て判断してはいけない。**左半分は電池と子基板の間に
    10.6mm しか無く、電池は左端まで 0.2mm・子基板は右端まで 0.8mm しか
    余っていないので、どちらもずらせない。買ってから入らないと分かると、
    リードタイムがもう一往復する（open-gaps #17 / #18）。

    買う製品を変えたら envelopes.py の SW_PWR_W / _D / _H を差し替える。
    それだけでここが判定し直す。
    """
    from envelopes import SW_PWR_D, SW_PWR_H, SW_PWR_W
    from gen_case import BATT_H
    gaps, depth = rear_panel_gaps(half)
    widest = max(b - a for a, b in gaps)
    assert SW_PWR_W <= widest, (
        f"{half}: スイッチの幅 {SW_PWR_W}mm が背面の空き {widest:.1f}mm に入らない\n"
        f"  空き区間: {[f'{a:+.1f}..{b:+.1f}' for a, b in gaps]}")
    assert SW_PWR_D <= depth, (
        f"{half}: スイッチの奥行 {SW_PWR_D}mm がコブの内寸 {depth:.1f}mm を超える")
    # 高さはコブの内部（電池が入る高さ）に収まること
    assert SW_PWR_H <= BATT_H, (
        f"{half}: スイッチの高さ {SW_PWR_H}mm がコブの内部 {BATT_H}mm を超える")


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_power_switch_holder_exists_and_is_hollow(half):
    """スイッチの受けが「足されて」いて、中身が空いていること。

    **奥の壁の内側は電池室の空洞で、もともと材料が無い。**座ぐりを掘る
    設計にしていたが、それは空気を削るだけでスイッチを受ける面ができない。
    **故意に「彫るのをやめる」実験をしたら検査が落ちなかった**ことで
    見つかった（壊しても落ちない＝検査していない）。

    そこで見るのは 3 つ。
      1. 空所の**まわりに壁がある**（受けの箱が足されている）
      2. 空所そのものは**空いている**（スイッチが入る）
      3. 操作部のスロットが**壁を貫いている**
    """
    import numpy as np
    import trimesh
    from envelopes import SW_PWR_D, SW_PWR_H, SW_PWR_W
    from gen_case import (BUMP_DEPTH, SW_RIB, WALL, power_switch_center_z,
                          power_switch_x_center)
    from interface import plate_positions
    from matrix import keymap_order

    # **無ければ自分で作る。飛ばさない。**
    # ここは「彫るのをやめても落ちなかった」ことで足した検査なのに、
    # `build/` は .gitignore なので **CI では毎回黙って飛んでいた**
    # （2026-08-10 に発覚）。10 秒で作れるものを、無いからと飛ばしていた。
    stl = _case_stl(half)
    _, (w, hb) = plate_positions(keymap_order(halves()[half]))
    mesh = trimesh.load(stl)
    x, z = power_switch_x_center(half, w), power_switch_center_z()
    y_out = hb / 2 + BUMP_DEPTH
    y_mid = y_out - WALL - SW_PWR_D / 2          # 空所の中心 y

    def solid(pts):
        return float(np.mean(mesh.contains(np.array(pts))))

    cavity = [(x + dx, y_mid + dy, z + dz)
              for dx in np.linspace(-SW_PWR_W * 0.35, SW_PWR_W * 0.35, 5)
              for dy in np.linspace(-SW_PWR_D * 0.3, SW_PWR_D * 0.3, 5)
              for dz in np.linspace(-SW_PWR_H * 0.35, SW_PWR_H * 0.35, 3)]
    # 受けの箱の壁（左右と上下）。**ここに材料が無ければスイッチは宙に浮く。**
    off_w = SW_PWR_W / 2 + CLEARANCE_HALF + SW_RIB / 2
    off_h = SW_PWR_H / 2 + CLEARANCE_HALF + SW_RIB / 2
    walls = ([(x + s_ * off_w, y_mid, z) for s_ in (-1, 1)]
             + [(x, y_mid, z + s_ * off_h) for s_ in (-1, 1)])
    slot = [(x + dx, y_out - WALL / 2, z + dz)
            for dx in np.linspace(-0.6, 0.6, 3)
            for dz in np.linspace(-1.0, 1.0, 3)]

    assert solid(walls) == 1.0, (
        f"{half}: スイッチの受けの壁が無い（材料 {solid(walls):.0%}）。"
        "空所を彫っただけでは、奥の壁の内側は元から空洞なので受けにならない")
    assert solid(cavity) == 0.0, \
        f"{half}: スイッチの空所に材料が残っている"
    assert solid(slot) == 0.0, \
        f"{half}: 操作部のスロットが壁を貫通していない"


# --------------------------------------------------------------------------
# open-gaps #29 で足した実物の検査
# --------------------------------------------------------------------------
# **足した検査は、故意に壊して落ちることを確かめる**（検証の作法 2）。
# 部品ごとに「その部品を実際より大きく／深くしたら、組み立て検査が
# その部品の名前を挙げて落ちる」ことを見る。挙がらなければ、その部品は
# 置いてあるだけで検査されていない。
#
# (部品名, モジュール, 定数, 加算量)。定数は組み立て時に読み直されるので、
# 書き換えてから check() を呼べば効く。focus でその部品の組だけ見る（速度）。
MUTATIONS = [
    ("sockets",  "envelopes", "SOCKET_DROP", +15.0),
    ("switches", "envelopes", "SW_BODY_W", +12.0),
    # キャップの裾はベゼルの頂より 0.3〜0.4mm 低く、開口の**中**に入る
    # （「上に浮く」は誤りだった。実測 2026-08-09）。守られているのは
    # 開口の縁との水平の余白（約 1.8mm）なので、幅を広げて壊す
    ("keycaps",  "envelopes", "CAP_GAP", -6.0),
    # 奥行(+y)はプレートと基板の間の空き地で、+15 でも何にも届かない。
    # 幅を広げると自分のキーのスイッチ下部に届く（実測 1327mm^3）
    ("stabs",    "envelopes", "STAB_BODY_XPAD", +25.0),
    ("sw_pwr",   "envelopes", "SW_PWR_W", +15.0),
    ("usb_plug", "envelopes", "USB_MATE_DEPTH", +3.0),
    ("ffc",      "envelopes", "FFC_RIBBON_W", +20.0),
    ("inserts",  "envelopes", "M2_INSERT_L", +10.0),
    ("screws",   "envelopes", "SCREW_L_MAIN", +10.0),
    ("nut",      "envelopes", "NUT_QUARTER_AF", +2.0),
    # **ゴム足は変異検査にかけられない。**寸法も位置も座ぐり（ケース側）から
    # 導かれるので、定数を動かすと座ぐりも一緒に動いて自己整合してしまう
    # （RUBBER_D / RUBBER_T / RUBBER_RECESS / RUBBER_INSET の 4 つで確認）。
    # 干渉の観点では絵のための部品。**代わりに効く制約**は下の
    # test_the_rubber_feet_actually_touch_the_desk が見る。
]


@pytest.mark.parametrize("part,module,attr,delta",
                         MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_each_added_part_is_actually_checked(part, module, attr, delta):
    """#29 で足した部品を 1 つずつ故意に壊し、検出されることを確かめる。"""
    import importlib

    mod = importlib.import_module(module)
    original = getattr(mod, attr)
    try:
        setattr(mod, attr, original + delta)
        # 例外も「検出」に数える。電源スイッチは幅を広げると、組み立てる
        # 前に power_switch_x_center が「背面の空きに入らない」と例外を
        # 投げる（それ自体が守り）。黙って通ることだけが失敗。
        try:
            problems, _ = check(HALVES["left"], "left", focus=part)[:2]
        except Exception:
            return
        assert any(part in p for p in problems), (
            f"{attr} を {delta:+} しても {part} の干渉が検出されない。"
            "置いてあるだけで検査されていない")
    finally:
        setattr(mod, attr, original)


def test_board_components_are_actually_checked():
    """基板の実装部品（STEP 由来）を故意に沈め、検出されることを確かめる。

    定数ではなく記録（pcb_parts.json）から作る部品なので、
    読み出しを差し替えて「全部品が 8mm 背高だったら」を作る。
    """
    import pcb_parts

    original = pcb_parts.component_boxes

    def sunken(name):
        return [(x0, y0, z0 - 8.0, x1, y1, z1)
                for x0, y0, z0, x1, y1, z1 in original(name)]

    try:
        pcb_parts.component_boxes = sunken
        problems, _ = check(HALVES["left"], "left", focus="pcb_parts")[:2]
        assert any("pcb_parts" in p for p in problems), \
            "本体基板の部品を 8mm 沈めても検出されない"
        problems, _ = check(HALVES["left"], "left", focus="db_parts")[:2]
        assert any("db_parts" in p for p in problems), \
            "子基板の裏面部品を 8mm 沈めても検出されない"
    finally:
        pcb_parts.component_boxes = original


# --------------------------------------------------------------------------
# 記録（pcb_parts.json）と外部の事実の突き合わせ
# --------------------------------------------------------------------------
# **「KiCad から持ってきた」は検証ではない。**KiCad は実体の無い 3D モデルを
# 警告なしに飛ばす（#29 で確認。ソケット 27・スタビ 2・XIAO が消えている）。
# だから STEP に「何が入ったか」を数え、回路とレイアウトから導ける数と
# 突き合わせる。数が合わなくなったら、モデルの増減を確認してから記録を直す。

def test_step_component_counts_match_the_circuit():
    import pcb_parts

    data = pcb_parts.load()
    for half in ("left", "right"):
        n_keys = len(HALVES[half])
        c = data[half]["counts"]
        # マトリクスのダイオードはキーごとに 1、電源のショットキーが 1
        assert c["diode_sod123"] == n_keys + 1, (
            f"{half}: ダイオード {c['diode_sod123']} 個 ≠ キー {n_keys} + 1。"
            "STEP のモデルが増減した（黙って消えるので数えるしかない）")
        # FFC コネクタは 3 立体で 1 個
        assert c["ffc_conn"] == 3, f"{half}: FFC コネクタの立体が {c['ffc_conn']}"
        # kiswitch のモデル（decisions/2026-08-09-third-party-3d-models.md）。
        # ソケットはキーごとに本体 1＋端子 2。スタビは 2 基で 10 立体。
        # **数が減ったら、ライブラリが未インストールの環境で --write した**
        # （再インストール手順は decisions の文書にある）
        assert c["kailh_socket"] == n_keys, (
            f"{half}: ソケットのモデル {c.get('kailh_socket', 0)} ≠ キー {n_keys}")
        assert c["kailh_socket_leg"] == 2 * n_keys
        assert (c["stab_housing"], c["stab_insert"], c["stab_wire"]) == (4, 4, 2)
    # 74LVC595 は左右合計 3 個
    total_ic = sum(data[h]["counts"]["ic_tssop16"] for h in ("left", "right"))
    assert total_ic == 3, f"74LVC595 が合計 {total_ic} 個（回路は 3 個）"
    # 子基板: 裏面に C 1 個 + FFC コネクタ（3 立体）、板の上に XIAO の
    # 公式モデル（Seeed 配布・84 立体をまとめて xiao_asm）。
    # xiao_asm が消えたら、モデル未設置の環境で --write した。
    dbc = data["db"]["counts"]
    assert dbc["cap_0805"] == 1 and dbc["ffc_conn"] == 3, f"子基板の裏面が変わった: {dbc}"
    assert dbc.get("xiao_asm", 0) >= 50, (
        f"XIAO のモデルが STEP に出ていない（xiao_asm={dbc.get('xiao_asm', 0)}）。"
        "pcb/lib/hhkb_split.3dshapes/XIAO_nRF52840.step を確認")
    # モデルの高さが、占有空間の積み上げ（DB_STACK_H）に収まっていること
    from envelopes import DB_STACK_H
    top = max(c["bbox"][5] for c in data["db"]["components"]
              if c["label"] == "xiao_asm")
    thick = data["db"]["board_step_thickness"]
    assert top - thick <= DB_STACK_H + 1e-6, (
        f"XIAO モデルの高さ {top - thick:.2f} が DB_STACK_H {DB_STACK_H} を超える")
    # **XIAO の向き。**USB シェル（4.2×7.3×8.94）が奥半分（+y）に居ること。
    # モデル導入時に 180° 逆に置き、利用者が Blender の絵で見つけた。
    # 数値の検査はどれも通ってしまっていた（高さも数も向きに依らない）。
    usb = next(c["bbox"] for c in data["db"]["components"]
               if c["label"] == "xiao_asm"
               and sorted((round(c["bbox"][3] - c["bbox"][0], 1),
                           round(c["bbox"][4] - c["bbox"][1], 1),
                           round(c["bbox"][5] - c["bbox"][2], 1))) == [4.2, 7.3, 8.9])
    y_mid = (usb[1] + usb[4]) / 2
    assert y_mid > 8.0, (
        f"XIAO の USB が手前（y中心 {y_mid:.1f}）を向いている。"
        "フットプリントの (model (rotate ...)) を確認")


def test_step_board_outline_matches_the_envelope():
    """STEP の板の外形と、占有空間の板が矛盾しないこと。

    幅は一致する。奥行は**占有空間のほうが 4.6mm 深い**（保守側なので可。
    実基板の奥行 97.4 に対し envelope は 102.0）。保守側で
    なくなったら（実基板が占有空間からはみ出したら）落とす。
    """
    import pcb_parts
    from envelopes import PCB_T, pcb_envelope
    from interface import plate_positions

    data = pcb_parts.load()
    for half in ("left", "right"):
        _, (w, h_plate) = plate_positions(HALVES[half])
        env = pcb_envelope(w, h_plate, half, HALVES[half]).bounding_box()
        x0, y0, _z0, x1, y1, _z1 = data[half]["board_bbox"]
        assert abs((x1 - x0) - env.size.X) < 0.2, (
            f"{half}: 板の幅 STEP {x1 - x0:.2f} ≠ envelope {env.size.X:.2f}")
        assert env.min.Y - 0.05 <= y0 and y1 <= env.max.Y + 0.05, (
            f"{half}: 実基板 y[{y0:.1f},{y1:.1f}] が envelope "
            f"y[{env.min.Y:.1f},{env.max.Y:.1f}] をはみ出す（保守側でない）")
        # STEP の板厚は誘電体のみ（1.51）。公称 1.6 との差は外層の銅とレジスト
        assert abs(data[half]["board_step_thickness"] - PCB_T) < 0.15


def test_the_recorded_step_data_is_fresh():
    """pcb_parts.json が、いまの基板から出る STEP と一致すること。

    記録が古いまま基板だけ変わると、検査は**昔の部品**を検査し続ける。
    kicad-cli の無い環境（CI）では飛ばすが、手元では毎回突き合わせる。
    """
    import pcb_parts

    _require_kicad("記録の突き合わせ")
    fresh = pcb_parts.extract("left")
    rec = pcb_parts.load()["left"]
    assert fresh["counts"] == rec["counts"], (
        f"記録が古い: {rec['counts']} → いまは {fresh['counts']}。"
        "tools/pcb_parts.py --write で更新して差分を確認すること")
    assert fresh["board_bbox"] == rec["board_bbox"], \
        "板の外形が記録と違う。tools/pcb_parts.py --write で更新すること"


def test_the_socket_box_contains_the_third_party_model():
    """保守的なソケットの箱が、kiswitch のモデルを包含していること。

    箱（SOCKET_DROP 3.2mm・フットプリント実測の xy）は組み立ての予約地で、
    「実体より大きい」ことが前提。その前提を、第三者モデル（データシート
    PG151101S11 の板下厚 1.80 / ボス込み 3.05mm と一致することを確認済み）
    と機械で突き合わせる。**箱がモデルより小さくなったら、予約が実体を
    収められていない**ので落とす。確定は現物のノギス（provisional-values）。
    """
    import pcb_parts
    from bands import SOCK_HI, SOCK_LO, SOCK_X_HI, SOCK_X_LO
    from envelopes import SOCKET_DROP
    from interface import plate_positions

    for half in ("left", "right"):
        positions, _ = plate_positions(HALVES[half])
        thick = pcb_parts.load()[half]["board_step_thickness"]
        for x0, y0, z0, x1, y1, z1 in pcb_parts.keyswitch_boxes(half, "kailh_socket"):
            # 深さ: 板の下面からの出っ張りが箱の予約以下であること
            below = -(z0) - thick
            assert below <= SOCKET_DROP + 1e-6, (
                f"{half}: ソケットのモデルが板下 {below:.2f}mm 出ている"
                f"（箱の予約 SOCKET_DROP={SOCKET_DROP}）")
            # xy: いちばん近いキーの箱の範囲に収まっていること
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            kx, ky = min(positions, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
            assert (kx + SOCK_X_LO - 0.1 <= x0 and x1 <= kx + SOCK_X_HI + 0.1
                    and ky + SOCK_LO - 0.1 <= y0 and y1 <= ky + SOCK_HI + 0.1), (
                f"{half}: キー ({kx:.1f},{ky:.1f}) のソケットモデル "
                f"x[{x0:.1f},{x1:.1f}] y[{y0:.1f},{y1:.1f}] が箱の範囲を出ている")


def test_real_board_parts_do_not_collide_in_3d():
    """基板上の**実形状どうし**（板＋全部品モデル）が立体で当たらないこと。

    DRC のコートヤードは 2D の外形で、**高さを見ない**。背の高い部品どうしの
    立体干渉は、モデルが STEP に入った今、ここが唯一の検査。
    設計どおりの重なりだけを、実測値つきで許す:
      - 同じスタビの内部（ワイヤが自分のインサートに刺さる。実測 0.47）
      - J_DB の 3 立体どうし（アクチュエータがハウジングに入る。実測 7.81）
      - スタビのスナップ爪が板の穴の縁を掴む（実測 1.50）
      - ソケットの位置決めボスが板の穴に入る（実測 0.14 ＝ ほぼゼロ）
    """
    import pcb_parts
    from pcb_parts import _classify

    _require_kicad("実形状の総当たり")

    # **設計どおりの嵌合はブーリアン演算ごと省く**（全対を測ると 4 分かかる。
    # 内訳は上の docstring の実測値。ここで見たいのは「部品をまたぐ干渉」）。
    SKIP = {
        frozenset({"kailh_socket", "kailh_socket_leg"}),   # 端子は本体から生える
        frozenset({"kailh_socket", "board"}),              # 位置決めボスが穴に入る
        frozenset({"stab_housing", "board"}),              # スナップ爪が縁を掴む
        frozenset({"stab_insert", "board"}),
        frozenset({"stab_wire", "stab_insert"}),           # 同じスタビの内部
        frozenset({"stab_wire", "stab_housing"}),
        frozenset({"stab_insert", "stab_housing"}),
        frozenset({"ffc_conn"}),                           # J_DB の 3 立体どうし
    }
    for half in ("left", "right"):
        solids = pcb_parts.real_compound(half).solids()
        board = max(solids, key=lambda s: s.volume)
        info = []
        for s in solids:
            b = s.bounding_box()
            label = "board" if s is board else _classify(b.size.X, b.size.Y, b.size.Z)
            info.append((s, b, label))
        bad = []
        for i in range(len(info)):
            for j in range(i + 1, len(info)):
                si, bi, li = info[i]
                sj, bj, lj = info[j]
                if not (bi.min.X < bj.max.X and bj.min.X < bi.max.X
                        and bi.min.Y < bj.max.Y and bj.min.Y < bi.max.Y
                        and bi.min.Z < bj.max.Z and bj.min.Z < bi.max.Z):
                    continue
                if frozenset({li, lj}) in SKIP:
                    continue
                inter = si & sj
                v = 0.0 if inter is None else float(getattr(inter, "volume", 0.0))
                if v > 0.2:
                    bad.append(f"{li} x {lj}: {v:.2f}mm^3 "
                               f"(x~{(bi.min.X + bi.max.X) / 2 - 150:.1f})")
        assert not bad, f"{half}: 実形状の干渉\n  " + "\n  ".join(bad)


# --------------------------------------------------------------------------
# **KiCad が無い環境（CI）でも実形状を検査する**（2026-08-10・利用者の提案）
# --------------------------------------------------------------------------
# 厳密な B-rep の総当たり（test_real_board_parts_do_not_collide_in_3d）は
# kicad-cli が要るので **CI では黙って飛んでいた。**飛んだ検査は
# 「無い」のと同じなので、記録（pcb_parts.json）だけで走る版をここに置く。
#
#   手元  … 実形状を出し直して厳密に見る＋記録の中身が古くないか見る
#   CI    … 記録の**ハッシュ**が今の盤面と一致するか＋部品 bbox の総当たり
#
# ハッシュを見るので「古い記録を検査して通す」ことは起こらない。

def test_the_recorded_step_data_matches_the_current_board_files():
    """記録が、いまの基板ファイルから出たものであること（KiCad 不要）。

    **これが無いと、CI は古い記録を検査して緑を出す。**基板を変えたのに
    `pcb_parts.py --write` を忘れた、をここで止める。
    """
    import pcb_parts

    stale = []
    for name in pcb_parts.BOARDS:
        rec = pcb_parts.load()[name].get("board_sha256")
        now = pcb_parts.board_sha256(name)
        if rec != now:
            stale.append(f"{name}: 記録 {str(rec)[:12]} / いまの盤面 {now[:12]}")
    assert not stale, (
        "pcb_parts.json が今の基板と一致しない:\n  " + "\n  ".join(stale)
        + "\n  tools/pcb_parts.py --write で作り直すこと")


def test_real_component_boxes_do_not_collide():
    """基板に載る実部品どうしが、bbox の粒度で当たらないこと（KiCad 不要）。

    モデルの bbox は**占有空間の箱より遥かに実物に近い**ので、これだけでも
    「新しい部品が既存の部品に乗った」は捕まる。厳密な形状での判定は
    手元の test_real_board_parts_do_not_collide_in_3d が担当。
    """
    import pcb_parts

    # 設計どおりの嵌合（厳密版と同じ理由。あちらの SKIP を参照）
    SKIP = {
        frozenset({"kailh_socket", "kailh_socket_leg"}),
        frozenset({"kailh_socket", "board"}),
        frozenset({"stab_housing", "board"}), frozenset({"stab_insert", "board"}),
        frozenset({"stab_wire", "stab_insert"}), frozenset({"stab_wire", "stab_housing"}),
        frozenset({"stab_insert", "stab_housing"}),
        frozenset({"ffc_conn"}),
        # XIAO は 84 立体でできた**1 つの完成モジュール**。内部の部品どうしが
        # 入れ子になるのは当たり前で、ここで見るものではない。
        frozenset({"xiao_asm"}),
    }
    data = pcb_parts.load()
    for name in pcb_parts.BOARDS:
        comps = data[name]["components"]
        hits = []
        for i in range(len(comps)):
            for j in range(i + 1, len(comps)):
                a, b = comps[i], comps[j]
                if frozenset({a["label"], b["label"]}) in SKIP:
                    continue
                A, B = a["bbox"], b["bbox"]
                ov = [min(A[k + 3], B[k + 3]) - max(A[k], B[k]) for k in range(3)]
                if all(o > 0 for o in ov):
                    hits.append(f"{a['label']} x {b['label']} "
                                f"{ov[0] * ov[1] * ov[2]:.2f}mm^3 "
                                f"at x~{(A[0] + A[3]) / 2:.1f} y~{(A[1] + A[4]) / 2:.1f}")
        assert not hits, f"{name}: 実部品の bbox が重なる\n  " + "\n  ".join(hits[:10])


def test_the_rubber_feet_actually_touch_the_desk():
    """ゴム足が座ぐりより厚く、床から出ていること。

    **買う足が薄いと、足は座ぐりに沈んだままで接地しない。**ケースの底が
    机に当たり、前を支点にする傾斜も狂う。`RUBBER_T` を 0.5mm（座ぐり
    0.6mm より薄い）にしても、足と傾斜まわりの検査は **7 件とも通った**
    （2026-08-10 に確認）。買う製品を変えるときに効く検査が無かった。

    出っ張り = `RUBBER_T` − `RUBBER_RECESS` = `FOOT_BASE_H` で、これは
    **0° のチルト脚の高さでもある**（前後を同じ高さにするため）。
    """
    from gen_case import FOOT_BASE_H, RUBBER_RECESS, RUBBER_T

    stick_out = RUBBER_T - RUBBER_RECESS
    # **1.0mm は判断であって実測ではない。**印刷した底面のうねりより
    # 小さい出っ張りは足として働かない、という理由で置いている。
    # 実測でうねり量が分かったらこの数字を差し替えること。
    assert stick_out >= 1.0, (
        f"ゴム足 {RUBBER_T}mm − 座ぐり {RUBBER_RECESS}mm = {stick_out:.2f}mm しか"
        "床から出ない。接地せず、傾斜も狂う")
    assert abs(FOOT_BASE_H - stick_out) < 1e-9, (
        "0° のチルト脚の高さ（FOOT_BASE_H）とゴム足の出っ張りが違う。"
        "前後で高さが揃わず、傾斜が設計値からずれる")


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_screws_engage_enough_of_the_insert(half):
    """ネジがインサートに**十分な長さ噛み合っている**こと。

    インサートを筒にして「ネジが穴を通る」形にした（2026-08-10）。
    干渉の許容は 0 になったが、**それだけでは「ゆるくて効かないネジ」を
    止められない。**通っているかではなく、どれだけ噛んでいるかを見る。

    下限 3.0mm は **M2 の呼び径 2.0 × 1.5** という一般則で、実測では
    ない。インサートの製品を決めたら、メーカーの推奨噛み合い長さに
    差し替えること。
    """
    from envelopes import SCREW_SHAFT_D

    parts, _ = build_assembly(HALVES[half], half)
    need = SCREW_SHAFT_D * 1.5
    short = []
    for ins in parts["inserts"].solids():
        ib = ins.bounding_box()
        best = 0.0
        for scr in parts["screws"].solids():
            sb = scr.bounding_box()
            if (abs(sb.center().X - ib.center().X) > 1.0
                    or abs(sb.center().Y - ib.center().Y) > 1.0):
                continue
            best = max(best, min(sb.max.Z, ib.max.Z) - max(sb.min.Z, ib.min.Z))
        if best < need:
            short.append(f"({ib.center().X:+.1f},{ib.center().Y:+.1f}) 噛み合い {best:.2f}mm")
    assert not short, (
        f"{half}: ネジの噛み合いが {need}mm に足りない\n  " + "\n  ".join(short))


# --------------------------------------------------------------------------
# **全部品を実形状にして、全組み合わせを許容ゼロで見る**（GitHub Actions）
# --------------------------------------------------------------------------
# 箱（占有空間）は場所取りで、実物とは違う。基板が設計済みになった今、
# 正確に見るときは実物を置く。重い（片側 4〜5 分）ので GitHub Actions の
# 別ジョブに任せ、手元では走らせない。

# **判定は check() に任せる。**ここで自前に総当たりを書いたら、
# Compound どうしを直接交差させて**まったく嘘の数字**（9338mm^3 など）を
# 出した。check() は立体単位に展開してから測る。同じ判定を 2 つ持たない。


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_real_shapes_do_not_overlap_anywhere(half):
    """**実形状の全部品・全組み合わせで重なり 0。**許容値は無い。"""
    _github_actions_only("実形状の全組み合わせ")
    _require_kicad("実形状の全組み合わせ")
    problems = check(HALVES[half], half, real=True)[0]
    assert not problems, f"{half}: 実形状で重なっている\n  " + "\n  ".join(problems)


def test_the_real_shape_check_actually_detects_a_collision():
    """**この検査が生きていることを、毎回わざと壊して確かめる。**

    検査器が壊れて何も見ていなくても緑になる——それが一番危ない。
    緑の意味を「検査器が生きていて、そのうえで何も無かった」にする。
    """
    _github_actions_only("実形状の自己確認")
    _require_kicad("実形状の自己確認")
    import gen_case

    original = gen_case.NUT_BOSS_H
    try:
        gen_case.NUT_BOSS_H = original + 8.0      # 三脚ナットの座を突き上げる
        assert check(HALVES["left"], "left", real=True)[0], \
            "ナットの座を 8mm 高くしても何も検出されない。検査が効いていない"
    finally:
        gen_case.NUT_BOSS_H = original


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_stab_openings_clear_the_real_stabilizers_by_the_kerf(half):
    """**プレートのスタビ開口が、実物のスタビに対して全周 CLEARANCE/2 空いている。**

    重なり 0（上の検査）は「入る」ことを意味しない。プレートは 3D プリントで
    公差 ±0.2mm 前後なので、隙間 0 は運任せになる（open-gaps #30）。

    **面どうしの最短距離では測れない。**スタビの肩と胴には傾いた面があり、
    傾いた面への垂線は面内の隙間より短く出る（kerf 0.1 に対して 0.067、
    板厚の帯で切っても 0.073）。**2 度測って 2 度とも違った。**

    なので距離ではなく**入るかどうかそのもの**を見る。板を平らな座標へ
    戻し、面内の 8 方向へ CLEARANCE/2 だけずらしても、スタビとまだ
    重ならないこと。面の傾きに左右されないし、判定は体積なので曖昧さが無い。

    **要求するのは実物に対する隙間で、開口の広げ量（STAB_KERF）ではない。**
    swillkb の標準パスは実物より片側 0.027mm 狭く、両者は一致しない。
    ここで STAB_KERF を要求すると、その差を黙って見逃す
    （実際、逃げ 0.1 で 0.075 しか動かせなかった）。

    実物は KiCad（kiswitch）の STEP。**自分の生成物どうしの一致ではない。**
    """
    _github_actions_only("スタビ開口の逃げ")
    _require_kicad("スタビ開口の逃げ")
    import math

    from build123d import Location
    from gen_assembly import plate_placement
    from gen_plate import plate_positions
    from interface import CLEARANCE, stab_offset_for
    from verify import intersection_volume

    keys = HALVES[half]
    parts, _ = build_assembly(keys, half, real=True)
    _, (w, h_plate) = plate_positions(keys)
    flat = plate_placement(w, h_plate).inverse()
    flat_plate = parts["plate"].moved(flat)

    # **母数を数えてから測る。**選び方が空振りしても緑になる、を防ぐ。
    want = sum(1 for k in keys if stab_offset_for(k.w_u))
    stabs = [s.moved(flat) for s in parts["pcb_real"].solids()
             if s.bounding_box().size.Y > 18 and s.bounding_box().size.Z > 18]
    assert len(stabs) == want, (
        f"{half}: 実形状のスタビが {len(stabs)} 個。2u 以上のキーは {want} 個")

    # EPS は check() と同じ意味（ブーリアン演算の分解能）。ちょうど接する
    # 位置まで寄せるので、退化した接触の欠片が出る。
    EPS = 1e-6
    need = CLEARANCE / 2
    tight = []
    for s in stabs:
        c = s.bounding_box().center()
        for k in range(8):
            a = math.pi * k / 4
            moved = flat_plate.moved(
                Location((need * math.cos(a), need * math.sin(a), 0)))
            v = intersection_volume(moved, s)
            if v > EPS:
                tight.append(f"({c.X:+.1f},{c.Y:+.1f}) {k * 45}度へ "
                             f"{need}mm ずらすと {v:.4f}mm^3 当たる")
    assert not tight, (
        f"{half}: 実物のスタビとの隙間が全周 {need}mm に足りない\n  "
        + "\n  ".join(tight))
