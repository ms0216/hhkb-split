"""HHKB の使い勝手を規定する値が変わっていないことを守る。

これらは実機の調査から得た値で、**設計の都合で動かしてはならない**。
部品が収まらないときに傾斜や高さを妥協するのが最も起きやすい失敗なので、
機械的に止める。

出典はすべて docs/hardware/dimensions.md。値を変えたくなったら、まず
そこの根拠を更新すること。根拠なしにこのファイルを緩めない。
"""

import re
from pathlib import Path

import pytest
from layout import UNIT, bounds_mm, load_layout, split_halves

ORIGINAL = "layout/hhkb_original.json"
SPLIT = "layout/hhkb_split.json"


# --------------------------------------------------------------------------
# 指が触れる面の形（最優先。これが崩れたら別のキーボードになる）
# --------------------------------------------------------------------------

def test_key_pitch_is_19_05mm():
    """業界標準かつ実機の公称値。"""
    assert UNIT == 19.05


def test_typing_plane_tilt_is_7_3deg():
    """topre_key の実機ノギス実測値（"Angle measured on the HHKB"）。

    ケースに部品が収まらないからといって寝かせたり立てたりしない。
    """
    from gen_case import TILT_DEG
    assert TILT_DEG == 7.3


def test_front_edge_height():
    """手首が当たる手前端の高さ。

    **このテストは以前 PLATE_TOP_FRONT == 17.5 を固定していた。**
    実機の手前端 17mm は**ベゼル（リム）の上面**で、プレート面はその 5.2mm 下の
    14.00mm。二つを混同したまま固定していたため、全段のキートップが 3.5mm
    高いまま誰も気づかなかった。**要求を守っているように見えて、
    守っていない値を固定していた。**

    いまの設計にはベゼルが無く、手前端＝プレート面。実機との差は
    docs/hardware/open-gaps.md に記録し、忘れられないようにしてある。
    """
    from gen_case import PLATE_TOP_FRONT
    import re
    doc = (Path(__file__).resolve().parent.parent
           / "docs/hardware/open-gaps.md").read_text()
    m = re.search(r"手前端の高さ\s*\|\s*\*{0,2}([\d.]+)mm\*{0,2}\s*\|\s*\*{0,2}([\d.]+)mm", doc)
    assert m, "open-gaps.md に手前端の行が無い"
    designed, real = float(m.group(1)), float(m.group(2))
    assert designed == PLATE_TOP_FRONT, \
        f"設計値 {PLATE_TOP_FRONT} と文書 {designed} が食い違っている"
    assert designed < real, "差が無くなったなら、この行を open-gaps.md から消すこと"


def test_keytop_heights_match_the_real_machine():
    """各列のキートップ高さ（机上面から）。

    公称全高 40mm と各列のキャップ高さから導いた値で、
    cap_lift の不確かさに依存しない。ホーム段 31.6mm が最重要。
    """
    from reference_hhkb import solve
    got = [round(z, 1) for z in solve(4.0).rows_cap_top_z]
    assert got == [26.7, 29.2, 31.6, 35.6, 40.0]


def test_tilt_steps_are_0_3_6_deg():
    """実機は 0/3/6° の3段階。**達成できる角度**で判定する。

    当初 TILT_STEPS == [3.0, 6.0]（0° は脚なし）と書いていたが、脚を後ろの隅へ
    移し「0° 用の短い脚も差す」方式に変えたため [0.0, 3.0, 6.0] になった。
    段数も角度も変わっていないので、実装の表現ではなく意味を検査する。
    """
    from gen_case import TILT_STEPS
    assert set(TILT_STEPS) | {0.0} == {0.0, 3.0, 6.0}, "0/3/6° の3段階から外れた"


# --------------------------------------------------------------------------
# 配列（HHKB そのもの）
# --------------------------------------------------------------------------

def test_split_keeps_61_keys():
    """原機 60 キー ＋ 分割で増えるスペース 1 つ。増やさない。"""
    assert len(load_layout(SPLIT)) == 61


def test_split_halves_are_27_and_34():
    left, right = split_halves(load_layout(SPLIT))
    assert (len(left), len(right)) == (27, 34)


def test_rows_are_15u_and_stagger_is_preserved():
    """行ずれは HHKB と同一。格子配列にしない。"""
    keys = load_layout(ORIGINAL)
    for row in range(4):
        assert sum(k.w_u for k in keys if k.row == row) == pytest.approx(15.0)
    left, right = split_halves(load_layout(SPLIT))
    base = min(k.left_u for k in right if k.row == 0)
    for row, expect in enumerate([0.0, 0.5, 0.75, 1.25]):
        got = min(k.left_u for k in right if k.row == row) - base
        assert got == pytest.approx(expect)


def test_bottom_row_is_the_real_hhkb_arrangement():
    """外側 1u / スペース寄り 1.5u。左右の余白は 1.5u と 2.5u で非対称。"""
    bottom = sorted((k for k in load_layout(ORIGINAL) if k.row == 4),
                    key=lambda k: k.left_u)
    assert [k.w_u for k in bottom] == [1.0, 1.5, 6.0, 1.5, 1.0]
    assert min(k.left_u for k in bottom) == pytest.approx(1.5)
    assert max(k.right_u for k in bottom) == pytest.approx(12.5)


def test_both_spaces_are_3u():
    """6u を 3u+3u に割る。左右とも Space。"""
    spaces = [k for k in load_layout(SPLIT) if k.w_u == pytest.approx(3.0)]
    assert len(spaces) == 2


def test_key_field_depth_is_5u():
    """5 段。段を減らしたり足したりしない。"""
    _, y0, _, y1 = bounds_mm(load_layout(SPLIT))
    assert (y1 - y0) == pytest.approx(5 * UNIT)


# --------------------------------------------------------------------------
# 電源（実機と同じ思想）
# --------------------------------------------------------------------------

def test_power_is_two_aa_cells():
    """単3×2。リポに逃げない。"""
    from gen_case import AA_D, AA_L
    assert (AA_D, AA_L) == (14.5, 50.5)


def test_plate_margins_come_from_the_real_machine():
    """縁の余白は実機の外形から導いた値であること。左右と前後で違う。

    幅   294mm − キー 15u(285.75mm) → 片側 4.125mm
    奥行 108mm − キー  5u( 95.25mm) → 片側 6.375mm

    一律 4.0mm にしていたことがあり、前後が実機より 2.4mm 狭かった。
    そのせいで取付ネジを置く余地が無くなり、取付穴が基板の外形を
    0.3mm はみ出していた。**実機に合わせると設計上の詰まりも解けた。**
    """
    from interface import PLATE_MARGIN_X, PLATE_MARGIN_Y
    assert PLATE_MARGIN_X == pytest.approx((294.0 - 15 * UNIT) / 2, abs=0.01)
    assert PLATE_MARGIN_Y == pytest.approx((108.0 - 5 * UNIT) / 2, abs=0.01)


def test_plate_depth_matches_the_real_machine():
    """プレートの奥行が実機の本体奥行 108mm と一致すること。

    120mm は電池の出っ張り込み、108mm が本体部分。
    ここが変わると、机に置いたときの占有面積が実機とずれる。
    """
    from gen_plate import halves
    from interface import plate_size
    from layout import bounds_mm
    for keys in halves().values():
        x0, y0, x1, y1 = bounds_mm(keys)
        _, h = plate_size(x1 - x0, y1 - y0)
        assert h == pytest.approx(108.0, abs=0.01)


def test_our_design_actually_reaches_the_real_keytop_heights():
    """**私たちの設計＋私たちが買うキーキャップ**の高さが、実機とどれだけ違うか。

    すぐ上の test_keytop_heights_match_the_real_machine は、参照モデルが
    実機と合っているかを見ているだけで、**設計そのものは検査していなかった**。
    最重要要求を守っているように見えて、守っていないテストだった。

    そのせいで PLATE_TOP_FRONT を 17.5mm（実機のベゼル高さ）と取り違え、
    全段のキートップが 3.5mm 高いまま気づかなかった。

    **さらにその後、この検査は「実機の Topre キャップを履かせたら」を
    計算していた。**私たちが実際に買うのは MX 用のキャップで、段ごとの
    高さが違う。DSA を入れたとき、実態と違う一律 −0.9mm という数字で
    落ちて発覚した。いまは gen_case.OUR_CAPS（買うキャップ）で計算する。

    差そのものは open-gaps.md の表と突き合わせる。**差があること自体は
    悪くない。気づけないことが悪い。**表と設計がずれたらここで落ちる。
    """
    import re
    from math import radians, tan

    from gen_case import CAP_LIFT, OUR_CAPS, PLATE_TOP_FRONT, TILT_DEG
    from reference_hhkb import ROWS, solve

    target = [round(z, 1) for z in solve(4.0).rows_cap_top_z]
    t = tan(radians(TILT_DEG))
    got, names = [], []
    for i, (name, _cap_h, _) in enumerate(ROWS):
        y = 6.375 + (i + 0.5) * 19.05                  # 手前からのキー中心
        got.append(round(PLATE_TOP_FRONT + y * t + CAP_LIFT + OUR_CAPS[name], 1))
        names.append(name)
    diffs = {n: round(g - r, 1) for n, g, r in zip(names, got, target)}

    doc = (Path(__file__).resolve().parent.parent
           / "docs/hardware/open-gaps.md").read_text()
    rows = dict(re.findall(
        r"^\|\s*(bottom|ZXCV|home|QWERTY|number)\s*\|[^|]*\|[^|]*\|\s*"
        r"\*{0,2}([-+][\d.]+)mm\*{0,2}\s*\|", doc, re.M))
    assert len(rows) == 5, (
        "open-gaps.md にキートップ高さの差の表が無い（5 段ぶん要る）。"
        f"読めたのは {sorted(rows)}")
    documented = {k: float(v) for k, v in rows.items()}
    assert diffs == documented, (
        "設計のキートップ高さの差が、文書に書いてある差と食い違っている\n"
        + "\n".join(f"    {n:8s} 設計 {diffs[n]:+.1f}mm  文書 {documented[n]:+.1f}mm"
                    for n in names if diffs[n] != documented[n])
        + "\n  どちらかを直すこと。差が無くなったなら表から行を消す")



def test_the_case_is_no_deeper_than_it_has_to_be():
    """奥行が、実機（本体 108 ＋ コブ 12 ＝ 120mm）から離れすぎないこと。

    コブは電池のために要るが、無制限に伸ばしてよいものではない。
    分割キーボードなので机の占有面積に効く。
    """
    from gen_case import BUMP_DEPTH
    from reference_hhkb import DEPTH_BODY, DEPTH_FULL
    total = 107.12 + BUMP_DEPTH
    assert total <= DEPTH_FULL + 6.0, (
        f"奥行 {total:.1f}mm が実機 {DEPTH_FULL}mm より "
        f"{total - DEPTH_FULL:.1f}mm 深い。コブを見直すこと")


def test_the_antenna_record_cannot_be_silently_deleted():
    """アンテナの件の記録が、測らないまま消されていないこと。

    子基板の XIAO のアンテナは、上 4.09mm に本体基板の GND ベタ、
    下 1.6mm に子基板の GND ベタ、横 0.5mm に FFC コネクタがある。
    チップアンテナの指針（全層 5〜10mm の禁止域）を満たしていない。
    **有効な対策が見つからず、実測で判断すると決めた。**

    この検査が守るのは「**測る前に記録だけ消える**」こと。
    消してよいのは Task C3 の §6-6 で実測し、結果を書いたときだけ。
    """
    doc = (Path(__file__).resolve().parent.parent
           / "docs/hardware/open-gaps.md").read_text()
    open_marker = "## 23. ★未解決★ アンテナが地板に挟まれている" in doc
    measured = "アンテナの実測結果" in doc
    assert open_marker or measured, (
        "アンテナの件（open-gaps #23）の記録が消えている。\n"
        "  実測して結果を書いたなら、見出しに「アンテナの実測結果」を\n"
        "  含む節を残すこと。測っていないなら #23 を戻すこと")


def test_fabrication_output_requires_an_accepted_antenna_risk():
    """**アンテナの risk を承知したと書いてから、製造ファイルを出すこと。**

    もとは「測るまで本体基板のガーバーを出させない」形だった。
    **基板を 1 回でまとめて発注すると決めたので、それでは成立しない。**
    測るには子基板の実物が要り、実物を得るには発注が要る。

    発注前に直す手は無い（3 つとも数字で潰した。open-gaps #23 の表）。
    残るのは「承知して出す」だけで、**それを黙ってやらせないのがここ。**

    文書に書くだけでは埋もれる。実際この案件では、電源スイッチが
    「ケースを開けないと操作できない場所」にあるまま、DRC 0 件・
    検査 264 件すべて緑で進んでいた。
    """
    root = Path(__file__).resolve().parent.parent
    doc = (root / "docs/hardware/open-gaps.md").read_text()
    if "## 23. ★未解決★ アンテナが地板に挟まれている" not in doc:
        return                      # 解決済み。何も止めない

    fab = sorted(
        str(q.relative_to(root))
        for pat in ("**/*.gbr", "**/*.gtl", "**/*.gbl", "**/*.drl", "**/*.gm1")
        for q in root.glob(pat)
        if ".superpowers" not in str(q))
    if not fab:
        return                      # まだ出していない。何も言うことはない

    assert "### 承知して発注する" in doc, (
        "\n"
        "  ★ アンテナの risk を承知した記録が無いまま製造ファイルが出ている ★\n"
        f"  {fab[:5]}\n"
        "\n"
        "  子基板のアンテナは上下を地板に挟まれており、チップアンテナの\n"
        "  指針を満たしていない（open-gaps #23）。**発注前に直す手は無い。**\n"
        "  基板を 1 回でまとめて発注する以上、測れるのは組み上げた後になる。\n"
        "\n"
        "  出す前にやること:\n"
        "    1. open-gaps #23 に「### 承知して発注する」の節を作り、\n"
        "       **誰がいつ承知したか**と、駄目だったときに何を作り直すかを書く\n"
        "    2. FFC の界面（12 ピン・0.5mm ピッチ・ピン配置・コネクタ位置）が\n"
        "       凍結されていることを確かめる。ここが動くと子基板の作り直しが\n"
        "       本体基板まで巻き込む\n"
        "    3. 届いたら Task C3 の §6-6 で RSSI を測る\n"
        "       （①単体 →②＋子基板 →③＋ケーブル →④＋組み立て を\n"
        "         **同じ日に続けて**。日を分けると比較にならない）\n"
        "\n"
        "  **この検査を消して通すこと。それは記録を消すのと同じ。**\n")


def test_the_prototype_shield_uses_the_production_spi_speed():
    """**試作シールドの SPI 転送速度が本番と揃っていること。**

    Task C2-b で確かめたいのは「速い打鍵で列を取りこぼさないか」で、
    取りこぼしは転送速度で決まる。試作だけ遅くしておくと、
    **通っても本番の保証にならない。**

    実際に食い違っていた（試作 200kHz / 本番 4MHz）。C2-b を走らせる
    直前に見つかった。
    """
    shields = Path(__file__).resolve().parent.parent / "config/boards/shields"
    found = {}
    for f in sorted(shields.rglob("*.overlay")) + sorted(shields.rglob("*.dtsi")):
        for hit in re.findall(r"spi-max-frequency\s*=\s*<(\d+)>", f.read_text()):
            found[str(f.relative_to(shields))] = int(hit)
    assert found, "spi-max-frequency がどこにも無い。検査が空回りしている"
    assert len(set(found.values())) == 1, (
        "試作と本番で SPI の転送速度が違う。C2-b の結果を本番へ持ち越せない:\n"
        + "\n".join(f"  {k}: {v / 1e6:g}MHz" for k, v in sorted(found.items())))
