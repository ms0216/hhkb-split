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
ROOT = Path(__file__).resolve().parent.parent
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
REQUIRED = {"case", "plate", "pcb", "rear_lid", "batt", "db", "topcase",
            "foot0", "foot1", "xiao",
            # open-gaps #29: 製品として存在する実物
            "sockets", "pcb_parts", "db_parts", "switches", "keycaps",
            "stabs", "sw_pwr", "usb_plug", "ffc", "inserts", "screws",
            "nut", "rubber"}


@pytest.mark.parametrize("half", ["left", "right"])
def test_nothing_bites_into_anything_else(half):
    """干渉 0。**実形状＋予約の箱の 1 パス**（#31 案 A・利用者の決定
    2026-08-11）。1 回の総当たりで 2 つの質問に答える:

      1. **実物どうしがぶつからないか**（実形状）
      2. **予約が守られているか**（条件 1・2 の箱 × ケース等）

    - CI の checks ジョブ: **干渉検査を置かない**（skip）。KiCad は 42 秒で
      入るが、real-shape ジョブと同じ 43 分の検査を二重にやるだけ
      （「全組み合わせを・重複なく 1 回・正確に」）。両側の実形状は
      real-shape ジョブが、形に関わる push のたびに見る（gate の filter が
      形の入力を覆っていることは test_ci_gate.py が見張る）
    - kicad-cli の無いローカル: **skip ではなく落とす。**「検査が飛んで緑」が
      この案件で 4 回起きた。「できなかった」を緑で素通りさせない
    """
    import os

    import pcb_parts

    if (os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("REQUIRE_KICAD") != "1"):
        pytest.skip("checks ジョブには干渉検査を置かない"
                    "（real-shape ジョブが唯一の干渉検査。利用者の決定）")
    assert pcb_parts.kicad_available(), (
        f"kicad-cli が無い（{pcb_parts.KICAD_CLI}）。実形状の干渉検査が"
        "できない環境を緑にしない（利用者の決定 2026-08-11）")
    problems, _, parts = check(HALVES[half], half, real=True)
    # **実形状と予約の箱の両方が組に入っていることを、緑の条件にする。**
    # どちらかが黙って抜けても総当たりは緑になれてしまう。
    for need in ("pcb_real", "db_real", "sockets", "stabs", "db", "xiao"):
        assert need in parts, f"{need} が組に入っていない（1 パスが欠けている）"
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


def test_every_real_part_has_a_colour():
    """**実形状のときに増える部品にも色があること。**

    箱の組み立てにしか無い名前（`switches_real` など）は、下の
    `test_every_part_has_a_colour` では見えない。**色が無いと灰色になる
    だけで落ちない**ので、絵の中で見分けがつかないまま気づけない
    （2026-08-11 に利用者が 3D で気づいた）。
    """
    _github_actions_only("実形状の色")
    _require_kicad("実形状の色")
    from export_assembly import style_for

    parts, _ = build_assembly(HALVES["left"], "left", real=True)
    missing = [n for n in parts if style_for(n) is None]
    assert not missing, f"実形状で色が無い部品 {sorted(missing)}"


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

    **壊す摘みは `DB_XIAO_LIFT`（ソケットの浮き）**（2026-08-12 に変更）。
    それまでは `DB_STACK_H` を壊していたが、子基板の予約が
    **記録（実物の XIAO）＋浮き**から段付きで作られるようになり、
    **`DB_STACK_H` は導かれる値になった**（＝それだけ動かしても柱は動かない）。
    **この検査がその変更を捕まえた**——摘みが空回りしていることを、
    「検査が効いているか」の検査が教えた形。
    """
    import envelopes

    original = envelopes.DB_XIAO_LIFT
    try:
        envelopes.DB_XIAO_LIFT = original + 15.0   # ソケットを 15mm 高くする
        problems, _ = check(HALVES[half], half)[:2]
        assert any("db" in p for p in problems), \
            "ソケットを 15mm 高くしても検出できない。検査が効いていない"
    finally:
        envelopes.DB_XIAO_LIFT = original


# --------------------------------------------------------------------------
# 電源スイッチが背面パネルに収まるか
# --------------------------------------------------------------------------

def _case_stl(half):
    """ケースの STL のパス。**無ければ・古ければ、その場で作る**（約 10 秒）。

    飛ばすと「通った」が「調べていない」の同義語になる。

    ⚠️ **「無ければ作る」だけでは足りなかった**（2026-08-12）。CAD を
    変えても STL は残っているので、**古いまま読んで偽の結果を出す。**
    電源スイッチの受けを作り替えたとき、リブを足したのに検査は
    「リブが無い」と言った——読んでいたのは前の形の STL だった。
    `blend_assembly._refuse_if_stale` と同じ型。**こちらは止めずに作り直す**
    （検査は人の操作を待てない）。
    """
    root = Path(__file__).resolve().parent.parent
    stl = root / f"build/case_{half}.stl"
    newest = max((q.stat().st_mtime for q in (root / "tools").glob("*.py")
                  if not q.name.startswith("test_")), default=0.0)
    if not stl.exists() or stl.stat().st_mtime < newest:
        import gen_case
        gen_case.main()
    assert stl.exists(), f"{stl} を作れなかった"
    assert stl.stat().st_mtime >= newest, (
        f"{stl} が tools/*.py より古いまま。作り直しが効いていない")
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
    """スイッチの受けが「足されて」いて、**入れられて、押し込めない**こと。

    **奥の壁の内側は電池室の空洞で、もともと材料が無い。**座ぐりを掘る
    設計にしていたが、それは空気を削るだけでスイッチを受ける面ができない。
    **故意に「彫るのをやめる」実験をしたら検査が落ちなかった**ことで
    見つかった（壊しても落ちない＝検査していない）。

    2026-08-12 に**上から落とし込む溝**へ作り替えた（#18 の抜け止め）。
    見るのは 5 つ:
      1. 空所の**まわりに壁がある**（受けが足されている）
      2. 本体の空所は**空いている**
      3. 操作部のスロットが**壁を貫いている**
      4. **奥がリブで塞がっている**——押し込む向きの抜け止め。
         **ここが無いと、指で押し込んだスイッチがケースの中へ落ちる**
      5. **上が開いている**——入れられる。**#35 と同じ型**（留まることだけ
         見て、入れられるかを見ない）を繰り返さないために一緒に見る
    """
    import numpy as np
    import trimesh
    from envelopes import SW_PWR_BODY_D, SW_PWR_H, SW_PWR_PIN_W, SW_PWR_W
    from gen_case import (BUMP_DEPTH, CLEARANCE, SW_HOLD_H, SW_RIB, WALL,
                          plan_depth, power_switch_center_z,
                          power_switch_x_center)
    from interface import plate_positions
    from matrix import keymap_order

    # **無ければ自分で作る。飛ばさない。**
    # ここは「彫るのをやめても落ちなかった」ことで足した検査なのに、
    # `build/` は .gitignore なので **CI では毎回黙って飛んでいた**
    # （2026-08-10 に発覚）。10 秒で作れるものを、無いからと飛ばしていた。
    stl = _case_stl(half)
    _, (w, h_plate) = plate_positions(keymap_order(halves()[half]))
    mesh = trimesh.load(stl)
    x, z = power_switch_x_center(half, w), power_switch_center_z()
    # **plan_depth を通す。**plate_positions が返すのはプレートの奥行で、
    # ケースは傾けたぶん縮んだ値を使う（0.44mm ずれる）。
    y_out = plan_depth(h_plate) / 2 + BUMP_DEPTH
    y_in = y_out - WALL
    depth = SW_PWR_BODY_D + CLEARANCE          # 本体の空所の奥行
    y_mid = y_in - depth / 2

    def solid(pts):
        return float(np.mean(mesh.contains(np.array(pts))))

    cavity = [(x + dx, y_mid + dy, z + dz)
              for dx in np.linspace(-SW_PWR_W * 0.35, SW_PWR_W * 0.35, 5)
              for dy in np.linspace(-depth * 0.3, depth * 0.3, 3)
              for dz in np.linspace(-SW_PWR_H * 0.35, SW_PWR_H * 0.35, 3)]
    # 受けの箱の壁（左右と上下）。**ここに材料が無ければスイッチは宙に浮く。**
    off_w = SW_PWR_W / 2 + CLEARANCE_HALF + SW_RIB / 2
    off_h = SW_PWR_H / 2 + CLEARANCE_HALF + SW_RIB / 2
    walls = ([(x + s_ * off_w, y_mid, z) for s_ in (-1, 1)]
             + [(x, y_mid, z - off_h)])          # 下は溝の底（座る面）
    slot = [(x + dx, y_out - WALL / 2, z + dz)
            for dx in np.linspace(-0.6, 0.6, 3)
            for dz in np.linspace(-1.0, 1.0, 3)]
    # 奥のリブ。**端子のスリットを外して**左右の残りを見る。
    rib_y = y_in - depth - SW_RIB / 2
    # **リブの高さの中だけを見る。**受けは本体より低い（SW_HOLD_H。
    # 高くすると入れられなくなる。test_every_part_can_be_put_in_from_outside）。
    z_bot = z - SW_PWR_H / 2 - CLEARANCE / 2
    zs_rib = np.linspace(z_bot + 0.6, z_bot + SW_HOLD_H - 0.6, 3)
    rib = [(x + s_ * (SW_PWR_PIN_W + CLEARANCE + SW_PWR_W) / 4, rib_y, zz)
           for s_ in (-1, 1) for zz in zs_rib]
    # 端子のスリット（真ん中）。ここは抜けていなければ端子が入らない。
    slit = [(x, rib_y, zz) for zz in zs_rib]
    # 入れ口（溝の上）。
    mouth = [(x + dx, y_mid, z + SW_PWR_H / 2 + CLEARANCE_HALF + 1.0)
             for dx in np.linspace(-SW_PWR_W * 0.35, SW_PWR_W * 0.35, 3)]

    assert solid(walls) == 1.0, (
        f"{half}: スイッチの受けの壁が無い（材料 {solid(walls):.0%}）。"
        "空所を彫っただけでは、奥の壁の内側は元から空洞なので受けにならない")
    assert solid(cavity) == 0.0, \
        f"{half}: スイッチの空所に材料が残っている"
    assert solid(slot) == 0.0, \
        f"{half}: 操作部のスロットが壁を貫通していない"
    assert solid(rib) == 1.0, (
        f"{half}: 奥のリブが無い（材料 {solid(rib):.0%}）。"
        "**押し込む向きの抜け止めが効かない**——指で押し込むと"
        "スイッチがケースの中へ落ちる（#18）")
    assert solid(slit) == 0.0, (
        f"{half}: 奥のリブに端子のスリットが無い（材料 {solid(slit):.0%}）。"
        "端子 3 本が通らない＝**スイッチが奥まで入らない**")
    assert solid(mouth) == 0.0, (
        f"{half}: 溝の上が塞がっている（材料 {solid(mouth):.0%}）。"
        "**上から落とし込めない＝スイッチを入れられない**")


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
    # 余白を広げると隣の実物（スイッチ下部・基板部品）に届く
    ("stabs",    "envelopes", "STAB_PAD", +12.0),
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


def test_the_recorded_product_groups_are_fresh():
    """pcb_product_groups.json が、いまの基板から出た記録であること。

    組分け（どの立体とどの立体が 1 つの製品か）の実測は片側 139 秒かかるので
    記録して使い回す（#31）。記録が現物と合わないとき product_groups は
    **黙って実測に落ちる**（正しいが遅い）。落ちたまま誰も気づかないと
    記録が腐るので、鮮度はここで見張る。kicad は要らない。
    """
    import json as _json

    import pcb_parts

    data = _json.loads(pcb_parts.GROUPS_DATA.read_text())
    for name in pcb_parts.BOARDS:
        rec = data[name]
        assert rec["board_sha256"] == pcb_parts.board_sha256(name), (
            f"{name}: 組分けの記録が古い基板のもの。"
            "tools/pcb_parts.py --write-groups で記録し直すこと")
        assert len(rec["fingerprints"]) == pcb_parts.load()[name]["solids"], (
            f"{name}: 組分けの立体数が pcb_parts.json と合わない")
        # 板以外の全立体が、どれか 1 つの製品にちょうど 1 回ずつ入っている
        covered = sorted([i for g in rec["groups"] for i in g]
                         + [rec["board_index"]])
        assert covered == list(range(len(rec["fingerprints"]))), (
            f"{name}: 組分けに漏れか重複がある")


def test_the_product_group_record_gatekeeper_actually_works(tmp_path, monkeypatch):
    """組分けの記録の門番を、**わざと壊して**確かめる。

    - 記録が現物（盤面のハッシュ・立体の指紋）と合えば、記録が使われる
    - 指紋が 1 つでも合わなければ、記録を捨てて実測に落ちる

    前者が壊れていると記録が永久に使われず 139 秒が戻る。後者が壊れていると
    **並び順の変わった立体に古い組分けを当てて、嘘の融合を黙って作る**。
    """
    import json as _json

    import pcb_parts
    from build123d import Box, Location

    def _box(size, at):
        return Box(*size).solids()[0].moved(Location(at))

    solids = [_box((50, 50, 2), (0, 0, 0)),      # 板（いちばん大きい）
              _box((2, 2, 2), (0, 0, 5)),
              _box((2, 2, 2), (1, 0, 5)),        # 1 と食い込む＝同じ製品
              _box((2, 2, 2), (10, 0, 5))]       # 離れている＝別の製品
    assert pcb_parts.compute_product_groups(solids) == (0, [[1, 2], [3]])

    rec = {"left": {
        "board_sha256": pcb_parts.board_sha256("left"),
        "board_index": 0,
        "fingerprints": [[round(v, 3) for v in f]
                         for f in pcb_parts._fingerprints(solids)],
        # 実測とは違う組分けにしておく＝これが返ったら「記録が使われた」証拠
        "groups": [[1], [2], [3]],
    }}
    fake = tmp_path / "groups.json"
    fake.write_text(_json.dumps(rec))
    monkeypatch.setattr(pcb_parts, "GROUPS_DATA", fake)
    assert pcb_parts.product_groups("left", solids)[1] == [[1], [2], [3]], \
        "記録が現物と合っているのに使われていない（毎回 139 秒の実測に戻る）"

    rec["left"]["fingerprints"][1][0] += 1.0     # 指紋を 1 つ壊す
    fake.write_text(_json.dumps(rec))
    assert pcb_parts.product_groups("left", solids)[1] == [[1, 2], [3]], \
        "指紋が合わないのに記録が使われた（嘘の組分けを黙って作る）"


def test_the_reservation_exclusions_all_have_a_containment_guard():
    """`RESERVATION_CONTAINS`（見ない宣言）の**すべての組に、代わりの
    「箱 ⊇ 実物」の検査が実在する**こと。

    除外だけ足して代わりを忘れると、穴を開けたのと同じ。組を足すときは
    ここの対応表にも 1 行足す（検査関数が消えたら落ちて教える）。
    """
    import test_assembly as ta
    from gen_assembly import RESERVATION_CONTAINS

    guards = {
        ("sockets", "pcb_real"): "test_the_socket_box_contains_the_third_party_model",
        ("stabs", "pcb_real"): "test_the_stab_box_contains_the_third_party_model",
        ("db", "db_real"): "test_the_db_reservation_contains_the_real_parts",
        ("xiao", "db_real"): "test_the_db_reservation_contains_the_real_parts",
        ("sockets", "switches_real"): "test_the_switch_boxes_match_the_real_switch",
    }
    assert set(guards) == RESERVATION_CONTAINS, (
        "除外の組と対応表がずれている。除外を増減したら、代わりの検査と"
        "この表を揃えること")
    missing = [name for name in guards.values() if not hasattr(ta, name)]
    assert not missing, f"代わりの検査が存在しない: {missing}"


def test_the_stab_box_contains_the_third_party_model():
    """スタビの予約の箱が、**実物のハウジング（記録の bbox）を xy で
    包んでいる**こと。`stabs × pcb_real` を総当たりから外した
    （RESERVATION_CONTAINS）代わり。

    この検査を最初にブーリアンで書いたら、**予約の方が実物より小さい**
    ことが出てきた（手決めの前後 7.0 vs 実物 19.2。ハウジング後部が
    4.7mm はみ出していた）。箱を記録から作るよう直した
    （envelopes.stab_reservation）。その上でここが守るのは:
      - 箱が**記録のハウジングを包み続けている**こと（STAB_PAD を負に
        するなど、箱を実物より小さくする変更で落ちる）
      - 母数（各側 4 個）が揃っていること
    ワイヤと、帯の外（開口を貫く上部・板の穴の足）は予約しない。理由は
    stab_reservation の注記（ワイヤを箱にするとダイオードと偽衝突する。
    実測 0.2mm）。
    """
    from gen_assembly import plate_placement
    from interface import plate_positions

    import pcb_parts

    for half in ("left", "right"):
        rec = pcb_parts.keyswitch_boxes(half, "stab_housing")
        # 母数: スタビは各側 2 本 × ハウジング 2 個 = 4（右は 2u+3u、左も）
        assert len(rec) == 4, f"{half}: ハウジングが {len(rec)} 個（4 のはず）"
        parts, _ = build_assembly(HALVES[half], half)
        _, (w, h_plate) = plate_positions(HALVES[half])
        inv = plate_placement(w, h_plate).inverse()
        boxes = [b.moved(inv).bounding_box() for b in parts["stabs"].solids()]
        missing = []
        for x0, y0, _z0, x1, y1, _z1 in rec:
            hit = any(bb.min.X <= x0 + 1e-6 and x1 <= bb.max.X + 1e-6
                      and bb.min.Y <= y0 + 1e-6 and y1 <= bb.max.Y + 1e-6
                      for bb in boxes)
            if not hit:
                missing.append(f"x[{x0:.1f},{x1:.1f}] y[{y0:.1f},{y1:.1f}]")
        assert not missing, (
            f"{half}: 実物のハウジングを包む予約の箱が無い:\n  "
            + "\n  ".join(missing))


def test_the_db_reservation_contains_the_real_parts():
    """子基板の予約（db の箱＋xiao の箱）が、**記録上の実物を全部
    包んでいる**こと。

    `db × db_real` / `xiao × db_real` を総当たりから外した代わり。
    kicad は要らない（記録の算術）。DB_STACK_H を 0.1mm 削るだけで
    落ちる（実物の頭 5.97 に対して予約の天井 6.01。余裕 0.04mm）。
    """
    import pcb_parts
    from envelopes import DB_STACK_H

    rec = pcb_parts.load()["db"]
    bx0, by0, _, bx1, by1, _ = rec["board_bbox"]
    top = rec["board_step_thickness"] + DB_STACK_H
    rx0, _, _, rx1, ry1, _ = pcb_parts.usb_receptacle()
    # 張り出し帯の奥端＝XIAO の基板（xiao_asm で xy 最大の立体）の奥端。
    # envelopes.xiao_overhang_envelope と同じ導き方（出所は同じ記録）。
    xa = [c2["bbox"] for c2 in rec["components"] if c2["label"] == "xiao_asm"]
    xb = max(xa, key=lambda b: (b[3] - b[0]) * (b[4] - b[1]))
    overhang_end = xb[4]                  # 実測 17.53（板の奥端 16.0 + 1.528）
    over = []
    for c in rec["components"]:
        x0, y0, z0, x1, y1, z1 = c["bbox"]
        if z1 <= 0.05:                    # 裏面の部品は箱の受け持ちの外
            continue                      # （実物どうしの総当たりが見る）
        ok = (z1 <= top + 1e-6            # 予約の天井
              and bx0 - 1e-6 <= x0 and x1 <= bx1 + 1e-6
              and by0 - 1e-6 <= y0)
        if y1 > overhang_end + 1e-6:      # 張り出し帯より奥＝メスだけの帯
            ok = ok and (x0 >= rx0 - 1e-6 and x1 <= rx1 + 1e-6
                         and y1 <= ry1 + 1e-6)
        if not ok:
            over.append(f"{c['label']} {c['bbox']}")
    assert not over, ("子基板の実物が予約からはみ出している。"
                      "DB_STACK_H か配置が実物とずれた:\n  "
                      + "\n  ".join(over))


def test_the_xiao_envelope_rejects_a_wrong_record(monkeypatch):
    """XIAO の箱の出所を記録に替えた（#31）ので、**記録の取り違えで
    黙って進まない**ことを故意に壊して確かめる。

    箱の寸法は「xiao_asm のうち xy がいちばん大きい立体＝XIAO の基板」から
    取る。基板の立体が記録から消えると、2 位（USB シェル 12.6x10.6）を
    基板と取り違えて小さい箱を作りかねない。そのときは ValueError で止まる。
    """
    import copy

    import envelopes
    import pcb_parts

    d = copy.deepcopy(pcb_parts.load())
    d["db"]["components"] = [
        c for c in d["db"]["components"]
        if not (c["label"] == "xiao_asm" and c["bbox"][3] - c["bbox"][0] > 15)]
    monkeypatch.setattr(pcb_parts, "load", lambda: d)
    with pytest.raises(ValueError):
        envelopes.xiao_overhang_envelope(0, 16, 3)


def test_the_interference_memo_gatekeeper_actually_works():
    """結果の記憶（#31）の門番を、**わざと壊して**確かめる。

    - 記憶が合えば使われる（毒入りの値がそのまま返る＝読んでいる証拠。
      これが壊れていると毎回の実測に戻り、記憶が腐っても気づけない）
    - 0.001mm でも動かすと鍵（BRep のハッシュ）が変わり、記憶を使わず
      実測する（これが壊れていると**嘘の緑**を作る。こちらが本丸）
    """
    from build123d import Box, Location

    import verify

    a = Box(10, 10, 10).solids()[0]
    b = a.moved(Location((20, 0, 0)))           # 離れている: 実測は 0
    memo, touched = {}, set()
    assert verify.memoized_intersection_volume(a, b, memo, touched) == 0.0
    assert len(memo) == 1
    memo[next(iter(memo))] = 123.0              # 毒を入れる
    assert verify.memoized_intersection_volume(a, b, memo, touched) == 123.0, \
        "記憶が使われていない（毎回の実測に戻る）"
    b2 = a.moved(Location((20, 0, 0.001)))      # 1/1000mm 動かす
    assert verify.memoized_intersection_volume(a, b2, memo, touched) == 0.0, \
        "形が違うのに記憶が使われた（嘘の緑を作る）"


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

    ⚠️ **この検査は、2026-08-10 まで間違った理由で通っていた。**
    以前は `NUT_BOSS_H` を 8mm 高くして「何か出るか」を見ていたが、

      1. ナットの座は `cutter_under_pcb` で削られる。**高くしても何も
         当たらない**（`gen_case`: `nut_boss = _n.part - cutter_under_pcb`）
      2. それでも通っていたのは、**素の状態で指摘が 4 件残っていた**から。
         変異とは無関係に非空だった

    実形状の指摘を 0 にした瞬間に落ちて発覚した。**掃除しないと、
    自己確認が嘘をついていることにも気づけない。**

    いまは 2 つ直した:
      - 動かす対象を、**当たる相手がすぐ隣にあるもの**にした。子基板を
        奥の壁へ 8mm 押し込む（壁は 2.4mm 先にある）
      - `focus="db_real"` で**その部品が絡む組だけ**を見る。無関係な指摘が
        残っていても、それで通ることは無い

    ⚠️ **focus を狭めるときは、当たる相手を取り違えないこと。**
    最初に選んだ変異（座を 8mm 高くする）は実際には検出できていたが、
    出ていたのは `screws x pcb_real`（ネジが伸びて本体基板を突いた）で、
    `focus="db_real"` では見えなかった。**変異が効いていないのか、
    focus が外しているのかは、必ず focus=None で確かめてから狭める。**
    """
    _github_actions_only("実形状の自己確認")
    _require_kicad("実形状の自己確認")
    import gen_case

    original = gen_case.DB_FROM_REAR
    try:
        gen_case.DB_FROM_REAR = original - 8.0    # 子基板を奥の壁へ押し込む
        found = check(HALVES["left"], "left", focus="db_real", real=True)[0]
        assert found, \
            "子基板を奥の壁へ 8mm 押し込んでも何も検出されない。検査が効いていない"
    finally:
        gen_case.DB_FROM_REAR = original


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


def test_the_hotswap_cups_fit_the_drilled_holes():
    """**ソケットのカップが、基板に開けた穴に入ること。**寸法で見る。

    実形状の総当たりでは「板 × その板に載る部品」を見ないことにした
    （`gen_assembly.check` の注記）。**外した検査をここへ移す。**

    見るのは 2 つ。どちらも外の事実どうしの突き合わせで、
    自分の生成物どうしの一致ではない:
      - 穴の径 … KiCad のフットプリント（`np_thru_hole` の drill）
      - カップの径 … kiswitch の STEP（第三者モデル）

    **モデルの置き位置は最大 0.13mm ずれている**（2026-08-10 実測。これが
    総当たりに残っていた 0.136mm^3 の正体）。ずれは記録するが、合否は
    「カップが穴に入るか」で決める。**径が穴を超えたら、実物が入らない。**
    """
    import re

    import pcb_parts
    from build123d import Align, Box, Location, import_step

    model = pcb_parts.third_party_model("SW_Hotswap_Kailh_MX")
    if model is None:
        import os

        if os.environ.get("REQUIRE_KICAD") == "1":
            pytest.fail("kiswitch のモデルが見つからない。このジョブは飛ばせない")
        pytest.skip("kiswitch のモデルが無い環境")

    fp = (ROOT / "pcb/lib/keyswitch.pretty/SW_Hotswap_Kailh_MX_1.00u.kicad_mod"
          ).read_text()
    holes = [(float(x), float(y), float(d)) for x, y, d in re.findall(
        r'np_thru_hole circle \(at (-?[\d.]+) (-?[\d.]+)\).*?\(drill ([\d.]+)\)',
        fp)]
    assert len(holes) >= 2, "フットプリントに非メッキ穴が見当たらない"

    body = max(import_step(str(model)).solids(), key=lambda s: s.volume)
    bb = body.bounding_box()
    # 板を貫く部分＝板の下面（z=0 の下）より上。板厚の真ん中で切る。
    z = (bb.max.Z + max(bb.max.Z - 0.5, bb.min.Z)) / 2
    slab = Location((0, 0, z)) * Box(60, 60, 0.02,
                                     align=(Align.CENTER, Align.CENTER,
                                            Align.CENTER))
    cups = []
    for s in body.intersect(slab).solids():
        c = s.bounding_box()
        cups.append((c.center().X, c.center().Y, max(c.size.X, c.size.Y)))
    assert cups, "モデルに板を貫く部分が無い。ソケットの向きが変わった可能性"

    bad, drift = [], []
    for cx, cy, cd in cups:
        # モデルは裏面部品なので Y が反転している。近いほうの穴と組む。
        hx, hy, hd = min(holes, key=lambda h: (h[0] - cx) ** 2 + (-h[1] - cy) ** 2)
        off = ((hx - cx) ** 2 + (-hy - cy) ** 2) ** 0.5
        drift.append(f"({cx:+.2f},{cy:+.2f}) カップ φ{cd:.2f} / 穴 φ{hd:.2f} "
                     f"ずれ {off:.3f}mm")
        if cd > hd + 1e-6:
            bad.append(f"({cx:+.2f},{cy:+.2f}) カップ φ{cd:.2f} > 穴 φ{hd:.2f}")
    assert not bad, ("ソケットのカップが穴に入らない\n  " + "\n  ".join(bad)
                     + "\n  実測: " + " / ".join(drift))


def test_the_switch_boxes_match_the_real_switch():
    """**キースイッチの箱が、実物のモデルと寸法で一致していること。**

    `switches` は箱のまま置いている（open-gaps #29 の表）。**足さない理由:**

      - **箱は近似ではない。**実物モデルの断面を測ると、プレートを通る部分は
        きっちり 14.00 角、プレートの上は 15.60 角で、`SW_UNDER_W` /
        `SW_BODY_W` と一致する（下でそれを毎回確かめる）
      - 実形状に替えて増えるのは**ステム・ピン・LED 窓**だけで、どれも
        設計上ほかの部品の**内側**にある。ステムはキャップの空洞、
        ピンはソケットの中
      - しかも**嵌合なので必ず重なる。**ソケットのカップと同じで、
        例外を 2 つ増やすことになる（ピン↔ソケット、爪↔プレート）
      - 総当たりは立体数の 2 乗で効く。61 個 × 7 立体を足すと、
        いまでも 43 分の実形状ジョブが実用外になる

    **その代わり、箱が実物からずれたら落ちるようにする。**
    ここが無いと「箱で十分」という判断の根拠が消える。

    ついでに**箱では見えないもの**も 1 つ見る: 実物のステムの頭が、
    キーキャップの空洞に収まっていること（`CAP_TOP_T` を厚くしすぎると
    天井がステムに当たる）。
    """
    _require_kicad("スイッチの箱と実物の突き合わせ")
    import re

    import pcb_parts
    from build123d import Align, Box, Location, import_step
    from envelopes import (CAP_TOP_T, PLATE_TO_PCB, SW_BODY_W, SW_UNDER_W)
    from gen_case import CAP_LIFT, OUR_CAPS
    from interface import PLATE_T, SWITCH_CUTOUT

    model = pcb_parts.third_party_model("SW_Cherry_MX_Plate")
    if model is None:
        import os

        if os.environ.get("REQUIRE_KICAD") == "1":
            pytest.fail("SW_Cherry_MX_Plate.stp が無い。このジョブは飛ばせない")
        pytest.skip("kiswitch のスイッチモデルが無い環境")

    sw = import_step(str(model))          # z=0 が基板の上面

    def widest(z):
        """高さ z での、いちばん大きい断面の一辺。"""
        slab = Location((0, 0, z)) * Box(60, 60, 0.02,
                                         align=(Align.CENTER,) * 3)
        best = 0.0
        for s in sw.solids():
            r = s.intersect(slab)
            if r is None:
                continue
            for t in r.solids():
                b = t.bounding_box()
                best = max(best, b.size.X, b.size.Y)
        return best

    # プレートの中（開口 SWITCH_CUTOUT を通る部分）
    through = widest(PLATE_TO_PCB + PLATE_T / 2)
    assert through == pytest.approx(SW_UNDER_W, abs=0.05), (
        f"プレートを通る部分が {through:.2f}mm。SW_UNDER_W={SW_UNDER_W} と違う")
    # **胴が開口に入ること。**ここは総当たりから外した組
    # （`plate × switches_real`）の代わりの検査。
    # ⚠️ 爪はわざと当たる（スナップフィット）。**逃げを入れてはいけない。**
    # 入れた瞬間にスイッチが保持されなくなる（スタビ #30 とは逆の判断）。
    assert through <= SWITCH_CUTOUT + 1e-6, (
        f"スイッチの胴 {through:.2f}mm がプレート開口 {SWITCH_CUTOUT}mm に入らない")

    # **ピンが基板の穴に入ること。**同じく総当たりから外した組
    # （`pcb_real × switches_real`）の代わり。板の下（z<0）の断面を、
    # フットプリントの非メッキ穴と突き合わせる。
    holes = [(float(hx), float(hy), float(hd)) for hx, hy, hd in re.findall(
        r'np_thru_hole circle \(at (-?[\d.]+) (-?[\d.]+)\).*?\(drill ([\d.]+)\)',
        (ROOT / "pcb/lib/keyswitch.pretty/SW_Hotswap_Kailh_MX_1.00u.kicad_mod"
         ).read_text())]
    assert holes, "フットプリントに非メッキ穴が見当たらない"
    slab = Location((0, 0, -0.4)) * Box(60, 60, 0.02,
                                        align=(Align.CENTER,) * 3)
    tight = []
    for so in sw.solids():
        r = so.intersect(slab)
        if r is None:
            continue
        for t in r.solids():
            b = t.bounding_box()
            d = max(b.size.X, b.size.Y)
            hx, hy, hd = min(holes, key=lambda h: (h[0] - b.center().X) ** 2
                             + (h[1] - b.center().Y) ** 2)
            if d > hd + 1e-6:
                tight.append(f"({b.center().X:+.2f},{b.center().Y:+.2f}) "
                             f"φ{d:.2f} > 穴 φ{hd:.2f}")
    assert not tight, ("スイッチのピンが基板の穴に入らない\n  "
                       + "\n  ".join(tight))

    # プレートのすぐ上（つばが載る部分）
    flange = widest(PLATE_TO_PCB + PLATE_T + 0.3)
    assert flange == pytest.approx(SW_BODY_W, abs=0.05), (
        f"プレートの上のつばが {flange:.2f}mm。SW_BODY_W={SW_BODY_W} と違う")

    # **箱では見えないもの。**ステムの頭がキャップの空洞に収まるか。
    plate_top = PLATE_TO_PCB + PLATE_T
    stem_top = sw.bounding_box().max.Z - plate_top       # プレート上面から
    ceiling = CAP_LIFT + OUR_CAPS["home"] - CAP_TOP_T    # 空洞の天井
    assert stem_top < ceiling, (
        f"実物のステムの頭 {stem_top:.2f}mm が、キャップの空洞の天井 "
        f"{ceiling:.2f}mm に当たる（CAP_TOP_T={CAP_TOP_T} が厚すぎる）")


# --------------------------------------------------------------------------
# アンテナと本体基板の地板の距離（open-gaps #23・#27）
# --------------------------------------------------------------------------
ANTENNA_MIN_CLEARANCE = 5.0     # チップアンテナの指針「全層で 5〜10mm」の下限
# 指針を割ることを承知したときに、open-gaps.md へ書く見出し。
# **この文字列があるかどうかで、「黙って割った」と「承知で割った」を区別する。**
ACCEPTED_HEADING = "### 承知でソケットを挟む（プロトタイプ限定）"


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_antenna_keeps_its_distance_from_the_main_board(half):
    """XIAO のアンテナが、本体基板（4 層・全面 GND ベタ）から離れていること。

    **この検査が無かったせいで、危うくアンテナを潰すところだった。**
    2026-08-12、XIAO をピンソケットで 10.5mm 浮かせる設計に作り直し、
    **干渉検査は左右とも 0 で通った。**ところがアンテナは XIAO と一緒に
    上がるので、本体基板の後端と同じ高さまで来てしまい、
    **地板までの距離が 7.22mm → 0.72mm になっていた**（指針は 5〜10mm）。
    #23 が案 C（XIAO を奥端へ寄せる）で稼いだ距離を、そっくり失う変更を、
    **形の検査は全部緑で通した。**

    → **電波の条件は、ぶつかるかどうかの検査には映らない。**
      浮き（DB_XIAO_LIFT）を触るときは必ずここを見る。上限は 2.24mm。

    距離は**箱どうしの最短距離**で測る（アンテナの占有空間 × 基板の外形）。
    実際に効くのは銅なので、外形で測るのは**保守側**（銅は外形より内側）。
    """
    from build123d import Align, Box, Location

    import pcb_parts
    from gen_case import (BUMP_DEPTH, DB_BOSS_H, DB_FROM_REAR, FLOOR, WALL,
                          daughterboard_x_center)
    from envelopes import DB_XIAO_LIFT
    from interface import antenna_x_band, antenna_y_span

    parts, (w, h_case) = build_assembly(HALVES[half], half)
    db_x = daughterboard_x_center(half, w)
    lo, hi = antenna_y_span(h_case / 2 + BUMP_DEPTH - WALL - DB_FROM_REAR)
    x0, x1 = antenna_x_band()
    # アンテナが載る面＝XIAO 自身の基板の上面（記録から。手写しの高さを置かない）
    xa = [c["bbox"] for c in pcb_parts.load()["db"]["components"]
          if c["label"] == "xiao_asm"]
    xiao_pcb = max(xa, key=lambda b: (b[3] - b[0]) * (b[4] - b[1]))
    z = FLOOR + DB_BOSS_H + xiao_pcb[5] + DB_XIAO_LIFT
    ant = Location((db_x + (x0 + x1) / 2, (lo + hi) / 2, z)) * Box(
        x1 - x0, hi - lo, 1.0, align=(Align.CENTER, Align.CENTER, Align.MIN))

    d = ant.distance_to(parts["pcb"])
    if d >= ANTENNA_MIN_CLEARANCE:
        return

    # **指針を割っているときは、承知の記録が無ければ落とす。**
    # export_fab.py の `_gate_antenna()`（「### 承知して発注する」が無ければ
    # ガーバーを出さない）と同じ形。**黙って割るのを許さない**のが目的で、
    # 利用者が承知して割るのを止めるのが目的ではない。
    doc = (ROOT / "docs/hardware/open-gaps.md").read_text(encoding="utf-8")
    assert ACCEPTED_HEADING in doc, (
        f"アンテナと本体基板が {d:.2f}mm しか離れていない"
        f"（指針 {ANTENNA_MIN_CLEARANCE}〜10mm）。"
        f"XIAO の浮き DB_XIAO_LIFT={DB_XIAO_LIFT}mm が大きすぎる。\n"
        f"  承知で割るなら open-gaps.md に見出し「{ACCEPTED_HEADING}」の節を"
        "書くこと（誰が・いつ・何を承知したか）。\n"
        "  直すなら DB_SOCKET_SEAT を 0 に戻すか、アンテナの置き方から"
        "見直すこと（open-gaps #23）")


def test_the_socket_build_is_not_used_to_judge_the_antenna():
    """ソケットで割っている間は、**#23 の測定に使ってはいけない**と書いてあること。

    **これがこの逸脱の本当の代償。**発注をせき止めている唯一の課題（#23）は
    「劣化が何 dB か」の実測で、**ソケットを挟んだ機体で測った数字は、
    出荷構成（直付け）について何も語らない。**悪い結果が出ても、原因が
    ソケットなのか元の配置なのか切り分けられない。
    """
    from envelopes import DB_SOCKET_SEAT

    if DB_SOCKET_SEAT <= 0:
        return
    doc = (ROOT / "docs/hardware/open-gaps.md").read_text(encoding="utf-8")
    assert "この構成で #23 を測ってはいけない" in doc, (
        "ソケットを挟んでいるのに、「この構成で #23 を測ってはいけない」が"
        "open-gaps.md に書かれていない。**測ってしまうと、その数字は"
        "出荷構成について何も語らない**")


# --------------------------------------------------------------------------
# テンティング用ナットの抜け止め（2026-08-12・利用者の「固定が弱いところ」から）
# --------------------------------------------------------------------------
def test_the_tenting_nut_is_captured():
    """1/4-20 ナットが、押し込んだあと自重で落ちないこと。

    **ポケットは底面に開いている。**逃げ 0.30mm では、キーボードを
    持ち上げるとナットが落ちる（2026-08-12 に発見）。締めれば天井に
    当たるので機能はするが、使わないときに落ちるのは製品にならない。

    → 入口の帯だけ二面幅を狭めて噛ませた。**噛んでいることを寸法で見る**
    （#12 の「舌と溝を試したが噛まなかった」を、当たらないことしか見ない
    干渉検査が見逃した反省。**噛み合いは直接見る**）。
    """
    from gen_case import NUT_AF, NUT_LIP_H, NUT_LIP_UNDER, NUT_T
    from envelopes import NUT_QUARTER_AF, NUT_QUARTER_T

    lip = NUT_AF - NUT_LIP_UNDER
    assert lip < NUT_QUARTER_AF, (
        f"入口の二面幅 {lip:.2f} がナットの {NUT_QUARTER_AF} 以上。**噛まない**"
        "（このままでは持ち上げると落ちる）")
    bite = (NUT_QUARTER_AF - lip) / 2
    assert bite <= 0.25, (
        f"片側の食い込みが {bite:.2f}mm。**PLA が割れるか入らない。**"
        "0.25mm 以下に抑えること")
    assert NUT_AF > NUT_QUARTER_AF, (
        f"ポケットの二面幅 {NUT_AF} がナット {NUT_QUARTER_AF} 以下。入らない")
    # **唇を越えた先に、ナットが丸ごと収まる深さがあること。**
    # ここが足りないと、ナットが唇に跨がったまま止まる＝押し込めない。
    assert NUT_T >= NUT_LIP_H + NUT_QUARTER_T, (
        f"ポケットの深さ {NUT_T} が、唇 {NUT_LIP_H} ＋ ナット厚 "
        f"{NUT_QUARTER_T} = {NUT_LIP_H + NUT_QUARTER_T} に足りない")


@pytest.mark.parametrize("half", ["left", "right"])
def test_every_part_declares_how_it_is_held(half):
    """組み立てに入っている部品が、**何で留まっているか**を宣言していること。

    **干渉検査は「ぶつからないこと」しか見ない。**組んだ瞬間に成立して
    いても、**持ち上げた・裏返した・打鍵した**ときに落ちる／浮くものは
    別の話で、それを見る仕組みが無かった。2026-08-12 に利用者の
    「固定が弱いところは無いか」で 2 つ出た——**電池蓋が外から開かない**
    （#35）／**テンティング用ナットが落ちる**。

    **留め方が書かれていない部品は、留まっていないのと同じ。**
    部品を足したら `gen_assembly.HELD_BY` にも書く。
    """
    from gen_assembly import HELD_BY

    parts, _ = build_assembly(HALVES[half], half)
    missing = sorted(n for n in parts
                     if n not in HELD_BY
                     and n.rstrip("0123456789").rstrip("_") not in HELD_BY)
    assert not missing, (
        f"留め方が宣言されていない部品: {missing}\n"
        "  gen_assembly.HELD_BY に「何で留まっているか」を書くこと"
        "（弱いなら ⚠️ を付けて、open-gaps に項目を立てる）")


def test_the_tilt_foot_is_captured():
    """チルト脚が、差したあと自重や持ち上げで抜けないこと。

    **ピンを伸ばす道は塞がっている**（真上に J_MAIN コネクタが 4.31mm まで
    下がるため、#29 で 4.0 → 2.4mm に短縮した）。摩擦だけでは裏返すたびに
    抜けるので、**先端の返しと穴の奥の溝**で噛ませた（2026-08-12）。

    **噛み合いは直接見る。**#12 の「舌と溝を試したが噛まなかった」は、
    当たらないことしか見ない干渉検査では見つからなかった。
    """
    from gen_case import (CLEARANCE, FOOT_BARB_D, FOOT_BARB_H, FOOT_GROOVE_D,
                          FOOT_PEG_D, FOOT_PEG_H)

    hole = FOOT_PEG_D + CLEARANCE
    assert FOOT_BARB_D > hole, (
        f"返し φ{FOOT_BARB_D} が穴 φ{hole:.2f} 以下。**噛まない**（抜ける）")
    bite = (FOOT_BARB_D - hole) / 2
    assert bite <= 0.25, (
        f"片側の食い込みが {bite:.2f}mm。**押し込めないか、返しが折れる**")
    assert FOOT_GROOVE_D > FOOT_BARB_D, (
        f"溝 φ{FOOT_GROOVE_D} が返し φ{FOOT_BARB_D} 以下。返しが開けない")
    assert FOOT_BARB_H < FOOT_PEG_H, (
        f"返しの高さ {FOOT_BARB_H} がピン全長 {FOOT_PEG_H} 以上")
    # 返しを飲み込んでも、案内として効く胴の長さが残っていること
    assert FOOT_PEG_H - FOOT_BARB_H >= 1.5, (
        f"返しを除いた胴が {FOOT_PEG_H - FOOT_BARB_H:.1f}mm しかない。"
        "差すときに傾いて入る")


# --------------------------------------------------------------------------
# 本体基板をプレートへ締める柱（open-gaps #36・2026-08-12）
# --------------------------------------------------------------------------
@pytest.mark.parametrize("half", ["left", "right"])
def test_the_pcb_is_actually_fastened_to_the_plate(half):
    """本体基板が、プレートの柱で締められていること。

    **それまで本体基板には固定具が 1 つも無かった。**上ケースのネジ 3 本は
    y=−51.5 で基板の縁（−48.7）より外にあり、**基板に触れてもいない。**
    保持はスイッチ 54 本のピンの摩擦だけで、**スイッチを抜くとソケットの
    はんだに剥離力**がかかる（ホットスワップ基板でいちばん多い壊れ方）。

    ここが見ているのは 3 つ:
      1. 柱が**基板の内側**にあること（縁から出ていたら締まらない）
      2. 柱が**キーやスタビと当たらない**こと
      3. 柱が**実装部品と当たらない**こと（記録から）
    """
    import math

    import pcb_parts
    from find_mounts import keepout_boxes, _clear_of
    from interface import PCB_POST_D, pcb_mount_positions, plate_positions

    pts = pcb_mount_positions(half)
    assert pts, f"{half} の柱が 0 本。基板が固定されない"

    rec = pcb_parts.load()[half]
    bb = rec["board_bbox"]
    r = PCB_POST_D / 2
    for px, py in pts:
        assert abs(px) + r <= bb[3] - 1.0 and abs(py) + r <= bb[4] - 1.0, (
            f"柱 ({px}, {py}) が基板の縁からはみ出す"
            f"（基板 ±{bb[3]:.1f} × ±{bb[4]:.1f}）")

    boxes = list(keepout_boxes(HALVES[half]))          # スイッチ＋スタビ
    for c in rec["components"]:
        x0, y0, _z0, x1, y1, _z1 = c["bbox"]
        boxes.append((x0, y0, x1, y1))
    # **1 本目で止めない。**assert をループの中に置くと最初の 1 本しか
    # 出ず、直すたびに次が出てくる（2026-08-12 に 3 往復した）。
    biting = [p for p in pts if not _clear_of(p[0], p[1], boxes, r)]
    assert not biting, (
        f"キーか実装部品に当たる柱が {len(biting)}/{len(pts)} 本: {biting}")

    # **どのキーからも遠すぎないこと。**遠いほど、そのキーを抜くときに
    # 基板が撓んでソケットに力がかかる。
    kpos, _ = plate_positions(HALVES[half])
    worst = max(min(math.dist(k, q) for q in pts) for k in kpos)
    assert worst <= 40.0, (
        f"最寄りの柱まで {worst:.1f}mm のキーがある。40mm 以下に収めること")


# --------------------------------------------------------------------------
# 電池蓋（コブの奥面）の着脱（open-gaps #35・2026-08-12）
# --------------------------------------------------------------------------
@pytest.mark.parametrize("half", ["left", "right"])
def test_the_rear_battery_lid_can_be_taken_off(half):
    """奥面の電池蓋が、**外から着脱でき、かつ勝手に外れない**こと。

    **底面の蓋は外から開かなかった**（座ぐりが床の内側にあり、蓋は貫通穴より
    3.8mm 大きい。#35）。**同じ失敗を繰り返さないために、最初から入れる。**

    方式は**下へスライドして庇の裏へ差し込む**。動作を 4 つとも見る:

      1. 据わった位置で**干渉が無い**（嵌まる）
      2. そのまま手前へ引くと**引っ掛かる**（勝手に外れない）
      3. **上へ SLIDE ずらすと**、引っ掛かりが消える（外せる）
      4. 上へずらす途中で**ビードに当たる**（勝手に上がらない）

    ⚠️ **片持ちばね案は 2 と 3 を同時に満たせず不成立だった。**腕が壁の裏に
    立っていて、どう撓ませても抜けない。**「留まる」だけを見る検査では
    通ってしまった**ので、3 を必ず一緒に見る。
    """
    from build123d import Location
    from gen_case import REAR_LID_SLIDE

    parts, _ = build_assembly(HALVES[half], half)
    lid, case = parts["rear_lid"], parts["case"]

    def hit(dy, dz):
        v = 0.0
        for a in (Location((0, dy, dz)) * lid).solids():
            for b in case.solids():
                s = a & b
                if s is not None and s.volume > 1e-6:
                    v += s.volume
        return v

    assert hit(0.0, 0.0) < 1e-6, f"据わった位置で {hit(0.0, 0.0):.2f}mm³ 当たる"
    assert hit(2.0, 0.0) > 1.0, (
        "手前へ 2mm 引いても何も引っ掛からない。**抜け止めが効いていない**"
        "（蓋が自重で落ちる）")
    assert hit(2.0, REAR_LID_SLIDE) < 1e-6, (
        f"上へ {REAR_LID_SLIDE}mm ずらしてから手前へ引くと "
        f"{hit(2.0, REAR_LID_SLIDE):.2f}mm³ 当たる。**外せない蓋**")
    assert hit(0.0, REAR_LID_SLIDE) > 1.0, (
        "上へずらす途中で何にも当たらない。**抜け止めのビードが効いていない**"
        "（振動で勝手に上がって外れる）")


def test_the_rear_lid_slide_survives_pla():
    """電池蓋を外すときの**板の反り**が、PLA で割れない量であること。

    片持ち爪をやめたので撓むのは**板そのもの**。上端をビード（0.4mm）へ
    乗り上げさせるとき、板は下端を支点に反る。

        ε = 1.5 · t · y / L²        …… PLA は繰り返し使用なら ε ≤ 1.0%

    **爪案は ε = 0.94% で綱渡りだった**（L=9・t=1.0・y=0.6）。板で受けると
    L が桁で大きくなるので、同じ掛かり量でもひずみが桁で小さい。
    """
    from gen_case import (REAR_LID_DETENT, REAR_LID_LIP_ENG, REAR_LID_SLIDE,
                          REAR_LID_T, rear_lid_plate_z, rear_lid_rebate)
    from gen_plate import halves, plate_positions

    _pos, (w, _h) = plate_positions(halves()["left"])
    z_bot, z_top = rear_lid_plate_z("left", w)
    L = z_top - z_bot                            # 反る長さ＝板の高さ
    eps = 1.5 * REAR_LID_T * (REAR_LID_DETENT + 0.1) / L ** 2
    assert eps <= 0.010, (
        f"板の反りのひずみが {eps*100:.2f}%。**PLA は 1.0% まで。**"
        f"L={L:.1f} t={REAR_LID_T} 反り={REAR_LID_DETENT + 0.1:.1f}mm。"
        "ビードを浅くするか、板を薄くすること")

    # 差し込みしろは掛かり代より大きくなければ、ずらしても抜けない。
    assert REAR_LID_SLIDE > REAR_LID_LIP_ENG, (
        f"差し込みしろ {REAR_LID_SLIDE} が掛かり代 {REAR_LID_LIP_ENG} 以下。"
        "**ずらしきっても舌が庇から抜けない＝外せない**")
    # 上に残る隙間は**差し込みしろ**（蓋が上へ逃げる場所）。
    # **ここは指掛かりではない。**蓋を上へずらすには蓋の下向きの面を
    # 押す必要があるが、隙間は蓋の上にあるので押せるのは下向きだけ。
    # （2026-08-12・利用者の指摘。それまで指掛かりだと書いていた）
    _rx0, _rz0, _rx1, rz1 = rear_lid_rebate("left", w)
    assert rz1 - z_top >= REAR_LID_SLIDE, (
        f"上に残る隙間が {rz1 - z_top:.1f}mm。差し込みしろ "
        f"{REAR_LID_SLIDE}mm に足りない＝**ずらしきれない**")

    # **手を掛けるところは蓋の表面の溝。**親指で押して滑らせる。
    from gen_case import (REAR_LID_GRIP_D, REAR_LID_GRIP_N, REAR_LID_GRIP_P,
                          REAR_LID_GRIP_W, build_rear_battery_lid)
    from gen_plate import halves as _halves

    assert REAR_LID_GRIP_N >= 3 and REAR_LID_GRIP_W >= 20.0, (
        f"滑り止めが {REAR_LID_GRIP_N} 本 × {REAR_LID_GRIP_W}mm。"
        "親指の腹が掛からない")
    assert 0.3 <= REAR_LID_GRIP_D <= REAR_LID_T / 3, (
        f"溝の深さ {REAR_LID_GRIP_D}mm。浅いと滑り、深いと板が薄くなる"
        f"（板 {REAR_LID_T}mm の 1/3 まで）")

    # **溝が本当に彫られていること。**定数だけ足して彫り忘れる型を塞ぐ。
    # 溝の高さで蓋の外面を薄く切り取り、**溝の無い高さより体積が減る**
    # ことを見る。深さも一緒に測れる。
    from build123d import Align, Box, Location

    from gen_case import REAR_LID_GRIP_H, REAR_LID_GRIP_P

    lid_part, _ = build_rear_battery_lid("left", _halves()["left"])
    _b = lid_part.bounding_box()
    y_out = _b.max.Y
    cx = (_b.min.X + _b.max.X) / 2          # **蓋の中心は原点ではない**
    z_g0 = z_bot + 3.0                      # gen_case と同じ起点

    def skin(zc):
        # z=zc で、外面から GRIP_D ぶんの薄皮に残っている体積
        probe = Location((cx, y_out - REAR_LID_GRIP_D / 2, zc)) * Box(
            REAR_LID_GRIP_W, REAR_LID_GRIP_D, REAR_LID_GRIP_H * 0.6,
            align=(Align.CENTER, Align.CENTER, Align.CENTER))
        r = lid_part.intersect(probe)
        return 0.0 if r is None else sum(x.volume for x in r.solids())

    on = skin(z_g0)                                    # 溝のところ
    off = skin(z_g0 + REAR_LID_GRIP_P / 2)             # 溝と溝のあいだ
    assert off > 0, "溝と溝のあいだに板が無い。溝が繋がっている"
    assert on < off * 0.05, (
        f"溝の高さで外面が {on:.2f}mm³ 残っている（溝の無いところは "
        f"{off:.2f}mm³）。**溝が彫られていない**")
    assert REAR_LID_GRIP_N * REAR_LID_GRIP_P < z_top - z_bot - 4.0, (
        "溝の並びが蓋の高さに収まらない")


# --------------------------------------------------------------------------
# 奥の壁の穴（2026-08-12。**目で見て気づけなかったものを、数で捕まえる**）
# --------------------------------------------------------------------------
def test_every_part_declares_its_shape_kind():
    """組み立てのすべての部品が、実形状か箱かを申告していること。

    ⚠️ **この分類は blend_assembly.py に手書きで置いてあった。**部品を
    足すのは gen_assembly なのに、分類は別のファイル——**片方だけ直る。**
    2026-08-12 に `rear_lid` と `sw_pwr` で 2 回続けて踏んだ。実形状なのに
    「箱」のコレクションへ入り、**利用者が開いた実形状側に現れなかった。**
    """
    from gen_assembly import BOX_SHAPE, REAL_SHAPE

    both = REAL_SHAPE & BOX_SHAPE
    assert not both, f"実形状と箱の両方に入っている: {sorted(both)}"
    for half in ("left", "right"):
        parts, _ = build_assembly(HALVES[half], half)
        missing = sorted(k for k in parts if k not in REAL_SHAPE | BOX_SHAPE)
        assert not missing, (
            f"{half}: 形の種類を申告していない部品: {missing}\n"
            "  gen_assembly.REAL_SHAPE か BOX_SHAPE に足すこと。"
            "**書かないと Blender で間違ったコレクションに入る**")


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_rear_wall_has_no_undeclared_holes(half):
    """コブの奥の壁に、**申告していない貫通穴が無い**こと。

    ⚠️ **これは「目で見る」で 3 回落とした種類の欠陥。**2026-08-12 に、
    電源スイッチの端子スリットを切る箱を「奥へ 2 倍」にしたら、手前側が
    **奥の壁を突き抜けて外に出た**（外から本体が見えていた）。利用者が
    Blender で見つけた。**数で判定できるものを、目に頼っていた。**

    やり方: 奥の外面を格子で走査し、壁厚のどこにも材料が無い点を「穴」と
    する。穴はすべて**申告した窓の中**に無ければならない。
    """
    import numpy as np
    import trimesh
    from gen_case import (BUMP_DEPTH, SW_SLOT_W, USB_H, USB_W,
                          WALL, plan_depth, power_switch_slot_z,
                          daughterboard_x_center,
                          power_switch_center_z, power_switch_x_center,
                          rear_lid_opening, usb_center_z)
    from interface import plate_positions
    from matrix import keymap_order

    mesh = trimesh.load(_case_stl(half))
    _, (w, h_plate) = plate_positions(keymap_order(halves()[half]))
    y_out = plan_depth(h_plate) / 2 + BUMP_DEPTH   # **plan_depth を通す**

    # 申告した窓（x0, z0, x1, z1）。**余白 0.6mm を足して縁の量子化を吸収。**
    m = 0.6
    ox0, oz0, ox1, oz1 = rear_lid_opening(half, w)
    sx, sz = power_switch_x_center(half, w), power_switch_center_z()
    db_x = daughterboard_x_center(half, w)
    windows = [
        ("電池蓋の口", ox0 - m, oz0 - m, ox1 + m, oz1 + m),
        ("電源スイッチのスロット", sx - SW_SLOT_W / 2 - m,
         power_switch_slot_z(half, w)[0] - m, sx + SW_SLOT_W / 2 + m,
         power_switch_slot_z(half, w)[1] + m),
        ("USB-C の口", db_x - USB_W / 2 - m, usb_center_z() - USB_H / 2 - m,
         db_x + USB_W / 2 + m, usb_center_z() + USB_H / 2 + m),
    ]

    xs = np.arange(-w / 2 + 1.0, w / 2 - 1.0, 1.0)
    zs = np.arange(0.5, 30.0, 0.5)
    depths = y_out - np.linspace(0.15, WALL - 0.15, 6)
    gx, gz = np.meshgrid(xs, zs, indexing="ij")
    gx, gz = gx.ravel(), gz.ravel()
    solid = np.zeros(gx.shape, dtype=bool)
    for d in depths:
        pts = np.column_stack([gx, np.full_like(gx, d), gz])
        solid |= mesh.contains(pts)

    holes = [(x, z) for x, z, ok in zip(gx, gz, solid) if not ok]
    stray = [(x, z) for x, z in holes
             if not any(x0 <= x <= x1 and z0 <= z <= z1
                        for _n, x0, z0, x1, z1 in windows)]
    # 壁そのものが無い高さ（コブの外・角の丸み）は除く。**壁の帯だけ見る。**
    stray = [(x, z) for x, z in stray if 1.0 <= z <= 26.0]
    assert not stray, (
        f"{half}: 奥の壁に申告していない穴が {len(stray)} 点ある。"
        f"最初の 5 点 {[(round(x, 1), round(z, 1)) for x, z in stray[:5]]}\n"
        "  **外から中が見える。**切削の箱が壁を突き抜けていないか見ること")


def test_the_blender_script_only_imports_what_blender_has():
    """`blend_assembly.py` が、**Blender の Python に有る物しか import しない**こと。

    ⚠️ 2026-08-12。実形状／箱の分類を `gen_assembly.py` へ移したら、
    `blend_assembly.py` はそれを import するので **`build123d` を要求**し、
    Blender の Python には無いので `ModuleNotFoundError` で落ちた。
    **.blend が 1 つも作られなくなった。**しかも Blender は -P の
    スクリプトが落ちても 0 を返すので、シェルも通り、**古い .blend を
    「出し直した」と報告した。**

    分類は依存を持たない `part_kinds.py` に置く。ここはそれを見張る。
    """
    import ast

    root = Path(__file__).resolve().parent
    tree = ast.parse((root / "blend_assembly.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            imported.add(n.module.split(".")[0])
    allowed = {
        "json", "math", "sys", "pathlib", "os", "re", "collections",
        "bpy", "mathutils",          # Blender が持っているもの
        "part_kinds",                # 依存を持たない自前の一覧
    }
    extra = sorted(imported - allowed)
    assert not extra, (
        f"blend_assembly.py が {extra} を import している。\n"
        "  **Blender の Python には build123d も numpy も無い。**\n"
        "  ここが落ちると .blend が 1 つも作られず、しかも Blender は\n"
        "  0 を返すので気づけない。データは part_kinds.py へ置くこと")


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_power_switch_dish_is_not_covered_by_the_battery_lid(half):
    """電源スイッチの**指の窪みが、電池蓋に覆われていない**こと。

    ⚠️ 2026-08-12。電池蓋をコブの奥面へ移して座ぐりを広げたら、
    **窪み（幅 10mm）が座ぐりに 2.22mm 食い込んだ。**どちらも外面の造作
    なので、重なった部分は蓋の下に隠れる＝**指が入らない。**

    干渉検査では出ない（蓋は座ぐりの中、スイッチは壁の裏で、立体としては
    当たらない）。**「面の取り合い」は体積では見えない。**

    窪みは操作のためのもので、**狭いと部品選択の前提（突出量 1.4mm で
    足りる）が崩れる**——窪みが無ければ壁 2.4mm を貫く必要に戻る。
    """
    from gen_case import (power_switch_dish_w, power_switch_x_center,
                          rear_lid_rebate)
    from interface import plate_positions
    from matrix import keymap_order

    _, (w, _h) = plate_positions(keymap_order(halves()[half]))
    sx = power_switch_x_center(half, w)
    rx0, _rz0, rx1, _rz1 = rear_lid_rebate(half, w)
    dw = power_switch_dish_w(half, w)      # **上限 SW_DISH_W ではなく実寸**
    assert dw >= 5.0, (
        f"{half}: 指の窪みが {dw:.2f}mm しか取れない。指が入らない"
        "（蓋の座ぐりと子基板ポケットに挟まれている）")
    d0, d1 = sx - dw / 2, sx + dw / 2
    overlap = min(d1, rx1) - max(d0, rx0)
    assert overlap <= 0, (
        f"{half}: 指の窪み ({d0:.1f}..{d1:.1f}) が電池蓋の座ぐり "
        f"({rx0:.1f}..{rx1:.1f}) に {overlap:.2f}mm 重なる。"
        "**窪みの一部が蓋に覆われて指が入らない**")


@pytest.mark.parametrize("half", ["left", "right"])
def test_every_part_can_be_put_in_from_outside(half):
    """ケースに入る部品が、**外から入れられる**こと。

    ⚠️ **「留まるか」だけを見ていて「入れられるか」を見ていなかった。**
    2026-08-12 に電源スイッチで踏んだ——奥のリブで押し込みを止めたのは
    よかったが、**そのリブのせいで手前からは入らず、上からはツマミが
    スロットの上端に当たって入らなかった**（実形状で 12.6mm³）。
    #35 の電池蓋（外から開かない）と同じ型で、**3 度目**だった。

    gen_assembly.INSERT_PATH に書いた逃がし方を、**実形状でたどる。**
    途中で 1 点でも当たれば、その部品は入らない（＝組み立てできない）。
    """
    from build123d import Location
    from gen_assembly import INSERT_PATH

    parts, _ = build_assembly(HALVES[half], half)
    case = parts["case"]

    def hit(part, d):
        v = 0.0
        for a in (Location(d) * part).solids():
            for b in case.solids():
                s_ = a & b
                if s_ is not None and s_.volume > 1e-6:
                    v += s_.volume
        return v

    missing = sorted(k for k in INSERT_PATH if k not in parts)
    assert not missing, f"INSERT_PATH に居ない部品が書いてある: {missing}"

    for name, path in sorted(INSERT_PATH.items()):
        part = parts[name]
        assert hit(part, (0, 0, 0)) < 1e-6, (
            f"{half}: {name} が据わった位置で当たっている")
        for step, d in enumerate(path, start=1):
            v = hit(part, d)
            assert v < 1e-6, (
                f"{half}: {name} を {d} へ動かすと {v:.2f}mm³ 当たる"
                f"（{step}/{len(path)} 手目）。**入れられない＝組み立てできない**")
        # 最後は本当に外へ出ていること（当たらないだけでは中に居るかもしれない）
        b_case = case.bounding_box()
        b_end = (Location(path[-1]) * part).bounding_box()
        outside = (b_end.min.Z > b_case.max.Z - 1e-6
                   or b_end.min.Y > b_case.max.Y - 1e-6
                   or b_end.max.Y < b_case.min.Y + 1e-6)
        assert outside, (
            f"{half}: {name} は当たらないが、まだケースの中に居る"
            f"（最後の手 {path[-1]}）。**外まで出す経路を書くこと**")


# --------------------------------------------------------------------------
# 誰も見張っていなかった定数（2026-08-13）
#
# 今日足した定数 35 個のうち **17 個は検査が名前で見ていなかった。**
# 多くは形に効くので干渉検査が間接的に捕まえるが、**素通りしたときに
# 金が飛ぶもの**（ネジを買い直す・ケースを刷り直す）だけは関係式で見る。
# `mutate.py` を数時間回すより安くて確実。
# --------------------------------------------------------------------------
def test_the_pcb_screw_reaches_the_post_without_punching_through():
    """本体基板を締める M2 の長さが、**噛み代を満たし、突き抜けない**こと。

    短いと柱に噛まず、長いと柱を貫いて**プレートの表面（キーの座面）へ
    出る**。どちらも**ネジを買い直す**しかない（open-gaps #36）。
    """
    from envelopes import PCB_T, PLATE_TO_PCB, SCREW_L_PCB
    from interface import PLATE_T

    bite = SCREW_L_PCB - PCB_T                    # 柱へ入る長さ
    assert bite >= 2.0, (
        f"ネジ {SCREW_L_PCB}mm − 板 {PCB_T}mm = 噛み代 {bite:.1f}mm。"
        "**M2（ピッチ 0.4）で 5 山に満たない。**2.0mm 以上にすること")
    room = PLATE_TO_PCB + PLATE_T - 0.5           # 柱＋プレート厚（表面手前まで）
    assert bite <= room, (
        f"噛み代 {bite:.1f}mm が柱＋プレート {room:.1f}mm を超える。"
        "**プレートの表面へ突き抜ける**（キーの座面に頭が出る）")


def test_the_post_pilot_hole_taps_without_splitting():
    """柱の下穴が、**M2 がタップでき、かつ柱が割れない**径であること。

    太いとねじが効かず、細いと PLA の柱が割れる。**基板と一緒に組んでから
    でないと分からない**ので、寸法の関係で見る。
    """
    from interface import PCB_POST_D, PCB_POST_PILOT_D

    # PLA へのセルフタッピングは呼び径の 0.75〜0.85 が定石（M2 → 1.5〜1.7）
    assert 1.5 <= PCB_POST_PILOT_D <= 1.7, (
        f"下穴 φ{PCB_POST_PILOT_D}。M2 のセルフタッピングは φ1.5〜1.7"
        "（太いと効かず、細いと割れる）")
    wall = (PCB_POST_D - PCB_POST_PILOT_D) / 2
    assert wall >= 1.0, (
        f"柱の肉が片側 {wall:.2f}mm。1.0mm 未満は**タップで割れる**"
        f"（柱 φ{PCB_POST_D} / 下穴 φ{PCB_POST_PILOT_D}）")


def test_the_finger_dish_leaves_wall_and_still_exposes_the_knob():
    """指の窪みが、**壁を残しつつツマミを出す**深さであること。

    深いと壁が薄くなって割れ、浅いとツマミに指が届かない。**ケースを
    刷り直す**ことになる（open-gaps #18）。
    """
    from envelopes import SW_PWR_KNOB
    from gen_case import SW_DISH_D, WALL

    left = WALL - SW_DISH_D
    assert left >= 1.2, (
        f"窪みの底の壁が {left:.1f}mm。0.4mm ノズルで 3 本ぶん（1.2mm）は残す")
    out = SW_PWR_KNOB - left
    assert out >= 1.0, (
        f"ツマミが窪みの底から {out:.1f}mm しか出ない。**指が掛からない**"
        f"（ツマミ {SW_PWR_KNOB} − 貫く壁 {left:.1f}）")


def test_the_switch_reservation_covers_the_real_part_and_its_wires():
    """電源スイッチの**予約の奥行が、実物とリード線の曲げに足りる**こと。

    足りないとリード線がコブの内壁に押される。**組んでからでないと
    分からない**ので、内訳の関係で見る。
    """
    from envelopes import SW_PWR_D, SW_PWR_WIRE
    from gen_case import BUMP_DEPTH, WALL, plan_depth
    from interface import plate_positions
    from matrix import keymap_order

    # ⚠️ **`SW_PWR_D == 本体＋端子＋線` は書いてはいけない。**
    # SW_PWR_D はその合計として導出しているので**常に真**——中身が無い
    # （2026-08-13 に実際に書いて、故意に壊しても素通りした）。
    # **組み立てに置いた実物を測って**、予約に収まるかを見る。
    parts, _ = build_assembly(HALVES["left"], "left")
    # **plan_depth を通す。**plate_positions が返すのはプレートの奥行で、
    # ケースは傾けたぶん縮んだ値を使う（0.44mm ずれる）。
    _, (w, h_plate) = plate_positions(keymap_order(halves()["left"]))
    y_in = plan_depth(h_plate) / 2 + BUMP_DEPTH - WALL
    used = y_in - parts["sw_pwr"].bounding_box().min.Y     # 壁の内面から奥へ
    assert used <= SW_PWR_D - SW_PWR_WIRE + 1e-6, (
        f"実物が壁の内面から {used:.2f}mm 使っている。予約 {SW_PWR_D} から"
        f"リード線ぶん {SW_PWR_WIRE} を引いた {SW_PWR_D - SW_PWR_WIRE:.2f}mm "
        "に収まらない。**リード線を回す余地が無い**")
    # AWG26 のリード線の曲げ半径は約 1.5mm。端子の先で 1 回曲げる。
    assert SW_PWR_WIRE >= 1.5, (
        f"リード線の余裕が {SW_PWR_WIRE}mm。AWG26 の曲げ半径 1.5mm に足りない"
        "（端子の先で内壁へ押し付けられる）")

