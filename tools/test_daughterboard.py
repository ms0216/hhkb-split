"""子基板へ渡すケーブルの信号一覧が、ファームウェアの使うピンと一致することを守る。

XIAO を子基板へ載せると、**ファームウェアが使うピンは全部ケーブルを渡る**。
あとからピンを 1 本増やしたのにケーブルが 12 本のままだと、基板を発注してから
「その信号が届かない」と分かる。ここは目視では守れないので機械で守る。

決定の経緯は docs/hardware/decisions/2026-08-07-daughterboard.md。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIELD = ROOT / "config/boards/shields/hhkb_split"
DOC = ROOT / "docs/hardware/decisions/2026-08-07-daughterboard.md"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import daughterboard_netlist  # noqa: E402

# xiao_spi (= SPI2) が固定で使うピン。デバイスツリーには現れないので、
# ボード定義（seeed_xiao_ble）の事実としてここに書く。
SPI_PINS = {"D8", "D10"}       # SCK, MOSI。MISO(D9) は pinctrl から外して
                               # ROW4 の GPIO に転用した（open-gaps #23・D9 移設）


def _strip(text):
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def firmware_pins():
    """シールドが使う XIAO のピンを集める。"""
    pins = set(SPI_PINS)
    for path in SHIELD.glob("*.dtsi"):
        text = _strip(path.read_text())
        # row-gpios / cs-gpios など、実際の &xiao_d 参照だけを見る
        for prop in ("row-gpios", "cs-gpios"):
            m = re.search(rf"\b{prop}\s*=?\s*(.*?);", text, re.S)
            if m:
                pins |= {f"D{n}" for n in re.findall(r"&xiao_d\s+(\d+)", m.group(1))}
    return pins


def _mcu_pins():
    """XIAO のピン名 → ネット名。"""
    return next(p for r, _, p in daughterboard_netlist() if r == "U_MCU")


def cable_signals():
    """ケーブルに通す信号。番号 → ネット名。

    **出所は circuit.py。**以前はここが決定文書の表を読んでいた。
    文書は自己完結して正しく見えるので、**この 4 件は誤った表を相手に
    通り続けていた**（表は 12 本すべてが旧い並び順のままだった）。
    文書とファームを突き合わせても、基板を作っているのは circuit.py なので
    何も守っていなかった。文書と circuit.py の照合は
    test_circuit.test_the_cable_pinout_table_matches_the_circuit が見る。
    """
    j = next(p for r, _, p in daughterboard_netlist() if r == "J_MAIN")
    return {int(n): net for n, net in j.items()}


def firmware_nets():
    """ファームが使う XIAO のピンが載っているネット名。"""
    mcu = _mcu_pins()
    return {mcu[p] for p in firmware_pins() if p in mcu}


def test_the_cable_carries_every_pin_the_firmware_uses():
    """ファームが使うピンが 1 本残らずケーブルに載っていること。

    **これを外すと、そのキーの行が届かず 1 段まるごと反応しない。**
    """
    mcu = _mcu_pins()
    unknown = firmware_pins() - set(mcu)
    assert not unknown, f"回路が知らないピンをファームが使っている: {sorted(unknown)}"
    missing = firmware_nets() - set(cable_signals().values())
    assert not missing, f"ケーブルに無い信号: {sorted(missing)}"


def test_the_cable_carries_power_and_a_ground():
    """電源と GND がケーブルに載っていること。

    ⚠️ **2026-08-14 に GND が 2 本から 1 本へ減った。**利用者の指示で
    XIAO の左右の列を鏡像に配線し、**GND はレーンに載せず地板で受ける**
    と決めたため（レーンに載せると FFC まで 1 本の細線で運ぶ形になる）。

    **「2 本」を数えるのをやめ、下の `test_how_far_the_return_path_is`
    で距離そのものを見る。**本数は手段で、目的は戻り経路の短さ。
    """
    sigs = cable_signals()
    assert "V3V3" in sigs.values(), "電源が無い"
    assert "GND" in sigs.values(), "GND が 1 本も無い"


# **SCK から最寄りの GND までの、許せる距離（ピン数）。**
#
# 実測（2026-08-14）: GND 2 本のとき SCK の隣が GND で 1 ピン（0.5mm）。
# 鏡像化して GND が 1 本になり **4 ピン（2.0mm）** に伸びた。
#
# ⚠️ **この 4 は「測って許容と判断した値」ではない。**いまの設計を
# 記録し、**それ以上悪化したら気づく**ための上限。0.5mm でどれだけ
# 改善するかは実測していない（利用者と確認済み）。
#
# **問題が出たときの逃げ道は決めてある**（利用者・2026-08-14）:
# D9(SPARE2) を両基板で GND へジャンパすると、SCK の隣が GND に戻る。
# そのために SPARE2 は用途未定のまま配線だけ通してある。
SCK_TO_GROUND_MAX_PINS = 4


def test_how_far_the_return_path_is():
    """**SCK から最寄りの GND までの距離**を見る（ループ面積の代理）。

    ケーブルを渡る信号の戻り電流は、最も近い GND を通ろうとする。
    行きと戻りが囲む面積は「GND までの距離 × ケーブル長 100mm」で、
    面積が大きいほど放射も受信も増える。

    **見るのは SCK だけでよい。**ROW は走査のたびにゆっくり変わる
    だけで、遷移が速く連続的なのは SPI クロックだから。
    """
    sigs = cable_signals()
    n = next((k for k, v in sigs.items() if v == "SPI_SCK"), None)
    assert n is not None, "SCK がケーブルに無い"
    gnd = [k for k, v in sigs.items() if v == "GND"]
    assert gnd, "GND がケーブルに無い"
    d = min(abs(n - k) for k in gnd)
    assert d <= SCK_TO_GROUND_MAX_PINS, (
        f"SCK({n} 番) から最寄りの GND まで {d} ピン"
        f"（上限 {SCK_TO_GROUND_MAX_PINS}）。**戻り経路が伸びた。**"
        "並びを変えたなら、なぜ許せるかを書いてから上限を動かすこと")


def test_the_pin_count_matches_the_connector():
    """本数がコネクタのピン数と一致すること。"""
    sigs = cable_signals()
    assert sorted(sigs) == list(range(1, 13)), f"番号が飛んでいる: {sorted(sigs)}"
    assert "12 ピン" in DOC.read_text(), "文書のコネクタ指定と本数が食い違う"


def test_the_battery_never_reaches_the_bat_pin_on_the_daughterboard():
    """BAT 端子がケーブルに載っていないこと。

    **XIAO の BAT 端子はリポ用充電回路に直結している。**乾電池をつなぐと
    USB 接続時に一次電池を充電しようとして液漏れ・破裂の危険がある。
    """
    bat = _mcu_pins()["BAT"]
    assert bat == "NC", f"BAT 端子に {bat} が繋がっている"
    # ⚠️ **`NC` はネット名ではなく「繋がっていない」という印。**
    # 以前ここは `bat not in cable_signals().values()` と書いていたが、
    # bat == "NC" なので、**ケーブルに 1 本でも予備ピン（NC）があると
    # 落ちる**（2026-08-14 に FFC の 6 番を予備にして実際に落ちた）。
    # BAT が載っていないことは上の行で言えている。ここで見るべきは
    # 「BAT に繋がる実ネットがケーブルに載っていないこと」だが、
    # BAT は NC なのでそんなネットは存在しない。**この検査は上の 1 行で
    # 足りる。**残すなら、実ネットのときだけ見る。
    if bat != "NC":
        assert bat not in cable_signals().values(), \
            "BAT の信号がケーブルに載っている"


def test_the_connector_spec_matches_the_board():
    """文書に書いたコネクタの仕様が、実基板のフットプリントと一致すること。

    **文書は「1.0mm ピッチ・12 本が 12mm」と書いていたが、実基板は
    最初から 0.5mm ピッチだった。**それまでの検査は本数（`"12 ピン"` と
    いう文字列）しか見ていなかったので通っていた。

    ピッチを間違えたままケーブルを買うと、届いてから挿さらないと分かる。
    """
    doc = DOC.read_text()
    m = re.search(r"\*\*(\d+) ピン・([\d.]+)mm ピッチ", doc)
    assert m, "文書のコネクタ指定（**N ピン・X.Xmm ピッチ**）が読めない"
    pins, pitch = int(m.group(1)), float(m.group(2))

    # 実基板から読む。**両方の基板を見る。**片方だけだと食い違いに気づかない。
    found = {}
    for half in ("hhkb_split_left", "hhkb_split_right", "hhkb_split_daughterboard"):
        text = (ROOT / f"pcb/{half}.kicad_pcb").read_text()
        for blk in re.split(r"\n\t\(footprint ", text)[1:]:
            ref = re.search(r'\(property "Reference" "(J_[A-Z]+)"', blk)
            if ref:
                found[f"{half}/{ref.group(1)}"] = blk.split('"')[1]
    assert len(found) == 3, f"FFC コネクタが 3 個見つからない: {sorted(found)}"

    for where, fp in found.items():
        n = re.search(r"1x(\d+)", fp)
        p = re.search(r"P([\d.]+)mm", fp)
        assert n and p, f"{where}: フットプリント名から本数とピッチが読めない ({fp})"
        assert int(n.group(1)) == pins, \
            f"{where}: 実基板は {n.group(1)} ピン、文書は {pins} ピン"
        assert float(p.group(1)) == pitch, \
            f"{where}: 実基板は {p.group(1)}mm ピッチ、文書は {pitch}mm ピッチ"


def test_the_firmware_and_the_circuit_agree_on_the_battery_divider():
    """ファームの分圧宣言が、回路の抵抗値と一致すること。

    残量計は `output-ohms` と `full-ohms` から実電圧を復元する。
    **回路とファームで別々に書かれていて、一致を見る検査が無かった。**
    片方だけ変えても DRC も検査も通り、**残量表示だけが静かに狂う。**
    電池が空なのに 60% と出る、あるいはその逆になる。

    変異検査で `DIVIDER_R_HIGH` を 1MΩ → 1.1MΩ にしても 271 件が全部通った。

    **compatible は見ない。**2026-08-11 に乾電池用へ差し替えた
    （`zmk,battery-voltage-divider` → `hhkb,battery-alkaline`）とき、
    ここが品名で引っ掛けていたので落ちた。この検査が守りたいのは
    **抵抗値の一致**であって、どの driver を使うかではない
    （それは tools/test_firmware.py が見る）。
    """
    dtsi = _strip((SHIELD / "hhkb_split.dtsi").read_text())
    m = re.search(r"output-ohms\s*=\s*<(\d+)>"
                  r"[\s\S]*?full-ohms\s*=\s*<(\d+)>", dtsi)
    assert m, "ファームに分圧（output-ohms / full-ohms）の宣言が見つからない"
    output_ohms, full_ohms = int(m.group(1)), int(m.group(2))

    from circuit import DIVIDER_R_HIGH, DIVIDER_R_LOW

    assert output_ohms == DIVIDER_R_LOW, (
        f"ファームの output-ohms={output_ohms} が、回路の下側抵抗 "
        f"{DIVIDER_R_LOW} と違う")
    assert full_ohms == DIVIDER_R_HIGH + DIVIDER_R_LOW, (
        f"ファームの full-ohms={full_ohms} が、回路の合計 "
        f"{DIVIDER_R_HIGH + DIVIDER_R_LOW} と違う")


# **ケーブルの界面（凍結）。**
#
# アンテナの件（open-gaps #23）は発注前に直せないので、駄目だったときに
# **子基板 1 枚だけを作り直せば済む**ようにしておく。そのために、本体基板と
# ケーブルに触れる部分をここで凍結する。ここが動くと、子基板の作り直しが
# 本体基板 2 枚（発注済み）とケーブル（購入済み）まで巻き込む。
FROZEN_FOOTPRINT = "Hirose_FH12-12S-0.5SH_1x12-1MP_P0.50mm_Horizontal"
FROZEN_LAYER = "B.Cu"
FROZEN_ROTATION = 180.0
FROZEN_FROM_FRONT_EDGE = 5.0     # 子基板の前端からコネクタ中心まで（mm）


def test_the_cable_interface_is_frozen():
    """ケーブルの界面が凍結どおりであること。

    **これが手戻りの範囲を決める。**アンテナが駄目だったとき、ここが
    動いていなければ作り直すのは子基板 1 枚（21x32mm）だけで済む。
    動いていると、本体基板 2 枚とケーブルまで巻き込む。

    凍結するのは「相手がある」ものだけ。子基板の中の配置や外形は
    自由に変えてよい（ケースは 3D プリントなので作り直せる）。
    """
    import re as _re

    found = {}
    for name in ("hhkb_split_left", "hhkb_split_right", "hhkb_split_daughterboard"):
        text = (ROOT / f"pcb/{name}.kicad_pcb").read_text()
        for blk in _re.split(r"\n\t\(footprint ", text)[1:]:
            ref = _re.search(r'\(property "Reference" "(J_[A-Z]+)"', blk)
            if not ref:
                continue
            at = _re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", blk)
            lay = _re.search(r'\(layer "([^"]+)"\)', blk)
            found[f"{name}/{ref.group(1)}"] = {
                "fp": blk.split('"')[1],
                "x": float(at.group(1)), "y": float(at.group(2)),
                "rot": float(at.group(3) or 0), "layer": lay.group(1)}
    assert len(found) == 3, f"FFC コネクタが 3 個見つからない: {sorted(found)}"

    for where, d in sorted(found.items()):
        assert d["fp"] == FROZEN_FOOTPRINT, \
            f"{where}: コネクタが {d['fp']}。凍結は {FROZEN_FOOTPRINT}"
        # **面と回転はケーブルの向き（同面/対向）を決める。**買う部品が変わる。
        assert d["layer"] == FROZEN_LAYER, \
            f"{where}: {d['layer']} 面にある。凍結は {FROZEN_LAYER}"
        assert d["rot"] == FROZEN_ROTATION, \
            f"{where}: 回転 {d['rot']}。凍結は {FROZEN_ROTATION}"

    # 子基板の前端からの距離。**ケーブルの必要長がここで決まる。**
    text = (ROOT / "pcb/hhkb_split_daughterboard.kicad_pcb").read_text()
    ys = [float(b) for _a, b in
          _re.findall(r"\(gr_line[\s\S]{0,120}?\(start ([-\d.]+) ([-\d.]+)\)", text)]
    front = max(ys)                      # KiCad は Y 下向き。手前＝大きい y
    got = front - found["hhkb_split_daughterboard/J_MAIN"]["y"]
    assert abs(got - FROZEN_FROM_FRONT_EDGE) < 0.01, (
        f"子基板の前端からコネクタまで {got:.2f}mm。"
        f"凍結は {FROZEN_FROM_FRONT_EDGE}mm。ケーブルの必要長が変わる")

    # 2 つのコネクタのピン割り当てが一致すること（向きの取り違え防止）
    main = next(p for r, _k, p in _import_netlist("left") if r == "J_DB")
    db = next(p for r, _k, p in daughterboard_netlist() if r == "J_MAIN")
    assert main == db, "本体基板と子基板でケーブルのピン割り当てが違う"


def _import_netlist(half):
    from circuit import netlist
    return netlist(half)


def test_the_mcu_sits_where_the_case_expects_it():
    """**実基板の XIAO の位置**が、ケースが空けたポケットと合っていること。

    XIAO は子基板の奥端から `XIAO_OVERHANG` だけ外へ出る（open-gaps #28）。
    ケース側は、その端を受けるポケットを奥の壁に掘っている。
    **片方だけ動かすと、XIAO の端が壁を突き破るか、逆にメスが届かなくなる。**

    ここは「自分の生成物どうしの一致」ではなく、**実基板のファイルから
    読んだ座標**を、基板の外形そのものを基準にして測り、ケースが使う式と
    突き合わせている。
    """
    from interface import XIAO_OUTLINE_L, XIAO_PAD_INSET, xiao_y_offset
    from gen_case import DB_D

    text = (ROOT / "pcb/hhkb_split_daughterboard.kicad_pcb").read_text()

    # 基板の外形（Edge.Cuts）から、板の中心を出す。**式ではなく実ファイルから。**
    ys = []
    for blk_ in re.split(r"\n\t\(gr_", text)[1:]:
        if '"Edge.Cuts"' not in blk_.split("(gr_")[0][:400]:
            continue
        ys += [float(v) for v in re.findall(r"\((?:start|end|center) [-\d.]+ ([-\d.]+)\)",
                                            blk_.split("(stroke")[0])]
    assert ys, "基板の外形（Edge.Cuts）が読めない"
    y_center_kicad = (min(ys) + max(ys)) / 2

    blk = [b for b in re.split(r"\n\t\(footprint ", text)[1:]
           if '(property "Reference" "U_MCU"' in b]
    assert len(blk) == 1, "子基板に U_MCU が 1 個見つからない"
    m = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)", blk[0])
    assert m, "U_MCU の座標が読めない"

    y_cad = y_center_kicad - float(m.group(2))     # KiCad は Y 下向き
    want = xiao_y_offset(DB_D)
    assert abs(y_cad - want) < 0.05, (
        f"実基板の XIAO は板の中心から y={y_cad:.2f}、"
        f"ケースが期待するのは y={want:.2f}")

    pad_edge = y_cad + XIAO_OUTLINE_L / 2 - XIAO_PAD_INSET
    assert pad_edge <= DB_D / 2 - 0.5, (
        f"いちばん奥のパッド y={pad_edge:.2f} が板の端 {DB_D/2:.1f} に近すぎる")


def test_the_ground_pour_is_actually_absent_under_the_antenna():
    """子基板の地板が、アンテナの真下から**本当に**消えていること。

    **設定しただけでは効いていない。**ルール領域を置いても、塗り直しが
    走らなければベタは残る。本体基板では Freerouting が禁止域を無視した
    前例がある（open-gaps #23）。宣言ではなく、塗られた多角形で見る。

    ここは**ベタだけを禁止し、配線は通している。**FFC から XIAO への
    12 本は、アンテナが XIAO の先端にある以上、必ずこの帯を横切る
    （迂回路が無い）。面積の大きい地板と 0.25mm の線 12 本では桁が違う。
    **「完全な禁止域」ではない。**
    """
    text = (ROOT / "pcb/hhkb_split_daughterboard.kicad_pcb").read_text()

    # ⚠️ **正規表現でゾーンを跨がないこと**（2026-08-14 に踏んだ）。
    # 以前は `\(zone[\s\S]*?\(keepout[\s\S]*?\)\s*\(polygon...` と
    # 書いていたが、`[\s\S]*?` が最初のゾーン（GND のベタ）を越えて
    # 次の keepout まで走り、**ベタ自身の polygon を禁止域として読んで
    # いた**。結果「アンテナの下にベタが 3297 点ある」と言い続けた
    # （実際には 0 点。pcbnew で数え直して分かった）。
    # **ゾーンの塊を先に切り出してから、その中だけを見る。**
    zones = re.findall(r"\n\t\(zone[\s\S]*?\n\t\)", text)
    ka = None
    for z in zones:
        if "(keepout" not in z:
            continue
        poly = re.search(r"\(polygon[\s\S]*?\n\t\t\)", z)
        if poly:
            ka = [(float(a), float(b)) for a, b in
                  re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", poly.group(0))]
            break
    assert ka, "子基板にアンテナのルール領域（キープアウト）が無い"
    x_lo, x_hi = min(p[0] for p in ka), max(p[0] for p in ka)
    y_lo, y_hi = min(p[1] for p in ka), max(p[1] for p in ka)
    # **大きさはアンテナに合わせる。**2026-08-14 まで `> 15.0mm` を
    # 要求していたが、それは XIAO の全幅（18.3mm）を使っていた頃の
    # 数字で、**アンテナは 3.5mm 角**。広すぎる禁止域は地板を無駄に
    # 削るだけだったので、`interface.antenna_x_band()` の幅に直した。
    from interface import ANTENNA_L, ANTENNA_W, antenna_x_band
    want_w = antenna_x_band()[1] - antenna_x_band()[0]
    assert abs((x_hi - x_lo) - want_w) < 0.1, (
        f"キープアウトの幅 {x_hi-x_lo:.2f}mm がアンテナの帯 {want_w:.2f}mm と違う")
    assert (y_hi - y_lo) >= ANTENNA_L - 0.01, (
        f"キープアウトの高さ {y_hi-y_lo:.2f}mm がアンテナ {ANTENNA_L}mm を覆わない")

    EPS = 0.01      # 境界ちょうどはベタの回り込みの頂点が載るので内側で見る
    n = 0
    for zp in re.findall(r"\(filled_polygon[\s\S]*?\n\t\t\)", text):
        for xs, ys in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", zp):
            x, y = float(xs), float(ys)
            if x_lo + EPS <= x <= x_hi - EPS and y_lo + EPS <= y <= y_hi - EPS:
                n += 1
    assert n == 0, f"アンテナの真下にベタの頂点が {n} 点ある"


def test_no_copper_on_the_near_layer_under_the_antenna():
    """**アンテナに近いほうの層（F.Cu）**に、真下の銅が 1 つも無いこと。

    アンテナは XIAO の上面にあり、子基板の表面（F.Cu）まで 1.6mm、
    裏面（B.Cu）まで 3.2mm（open-gaps #23）。FFC から XIAO への 12 本は
    アンテナの y 帯を必ず横切るが、**x は選べる**。アンテナの実測位置
    （TX 側の縁から 7.0mm）で計算すると、6 本のうち 2 本がどうしても
    真下に入る。

    **消せないので、遠いほうの層へ逃がしてある。**距離が倍になる。
    ここは**基板が届いてからでは直せない**（配線は XIAO の下に隠れる）。

    ⚠️ この検査が守るのは「近い層に無いこと」だけ。**B.Cu には 2 本ある。**
    それが何 dB 効くかは測っていない（#23 の「実機で無線がおかしいとき」）。
    """
    from interface import ANTENNA_W, ANTENNA_X, antenna_y_span
    from gen_case import DB_D

    text = (ROOT / "pcb/hhkb_split_daughterboard.kicad_pcb").read_text()
    ys, xs = [], []
    for blk in re.split(r"\n\t\(gr_", text)[1:]:
        if '"Edge.Cuts"' not in blk:
            continue
        for m in re.finditer(r"\((?:start|end) ([-\d.]+) ([-\d.]+)\)",
                             blk.split("(stroke")[0]):
            xs.append(float(m.group(1)))
            ys.append(float(m.group(2)))
    assert xs, "基板の外形が読めない"
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    y_lo, y_hi = antenna_y_span(DB_D / 2)          # 板の中心を原点とした CAD 座標
    x_lo, x_hi = ANTENNA_X - ANTENNA_W / 2, ANTENNA_X + ANTENNA_W / 2

    def inside(x_abs, y_abs):
        x, y = x_abs - cx, cy - y_abs              # KiCad は Y 下向き
        return x_lo <= x <= x_hi and y_lo <= y <= y_hi

    bad = []
    for seg in re.findall(r"\n\t\(segment[\s\S]*?\n\t\)", text):
        lay = re.search(r'\(layer "([^"]+)"\)', seg)
        if not lay or lay.group(1) != "F.Cu":
            continue
        a = re.search(r"\(start ([-\d.]+) ([-\d.]+)\)", seg)
        b = re.search(r"\(end ([-\d.]+) ([-\d.]+)\)", seg)
        if not (a and b):
            continue
        x1, y1 = float(a.group(1)), float(a.group(2))
        x2, y2 = float(b.group(1)), float(b.group(2))
        if any(inside(x1 + (x2 - x1) * i / 40, y1 + (y2 - y1) * i / 40)
               for i in range(41)):
            bad.append(f"配線({x1:.1f},{y1:.1f})-({x2:.1f},{y2:.1f})")
    for via in re.findall(r"\n\t\(via[\s\S]*?\n\t\)", text):
        a = re.search(r"\(at ([-\d.]+) ([-\d.]+)\)", via)
        if a and inside(float(a.group(1)), float(a.group(2))):
            bad.append("ビア")

    assert not bad, (
        f"アンテナの真下（近いほうの層）に銅がある: {bad[:4]}"
        f"{' ほか' if len(bad) > 4 else ''}")


def test_the_row_order_matches_between_firmware_and_circuit():
    """**ファームの行の並びと、子基板のレーンが 1 対 1 で対応すること。**

    ⚠️ **2026-08-15 に構造が変わった。**それまで `row-gpios` は共通の
    dtsi に 1 つだけあり、この検査は「行 N が ROW{N} に載っているか」を
    見ていた。いまは:

      - `row-gpios` は**左右の overlay**が別々に持つ（並び順が行番号）
      - ケーブルのネット名は**行番号ではなくレーンの位置**（ROW_A..E）
      - 対応は `matrix.ROW_LANES`（XIAO のピン → レーン）が唯一の出所

    なぜ分けたか: **行がどの GPIO に来るかは左右で物理的に違う**
    （J_DB が左は板の右端・右は左端にあり、同じ FFC のピンでも行バスへ
    近づく向きが逆）。共通に書くと、どちらかの基板で必ず交差が出る。
    """
    import matrix

    mcu = _mcu_pins()
    for half in ("left", "right"):
        pins = matrix.row_pins(half)
        assert len(pins) == 5, f"{half}: 行が {len(pins)} 本（期待 5）"
        assert len(set(pins)) == 5, f"{half}: 同じピンを 2 回使っている: {pins}"
        for pin in pins:
            assert pin in matrix.ROW_LANES, (
                f"{half}: {pin} は行のレーンではない。"
                f"使えるのは {sorted(matrix.ROW_LANES)}"
                "（子基板のレーンは物理で固定・gen_daughterboard を見ること）")
            net = matrix.ROW_LANES[pin]
            assert mcu.get(pin) == net, (
                f"{half}: {pin} は circuit.py で {mcu.get(pin)} だが、"
                f"matrix.ROW_LANES は {net} と言っている。**片方だけ直すと"
                "押したキーと違う行が読まれる**")
        nets = matrix.row_nets(half)
        assert sorted(nets) == sorted(matrix.ROW_LANES.values()), (
            f"{half}: レーンを使い切っていない: {nets}")


def test_the_two_halves_may_order_their_rows_differently():
    """**左右で行の並びが違ってよい**ことの記録（2026-08-15・利用者）。

    「左右で ROW の順番を変えてもいい（左右で違う FW になるのは確定
    している）」という判断があった。**揃っていることを要求する検査を
    書かない**ための歯止め。要求すると、どちらかの基板で交差が出る
    並びを強いることになる。

    使うピンの集合は同じ（子基板は 1 種類しか作らない）が、順序は自由。
    """
    import matrix

    left, right = matrix.row_pins("left"), matrix.row_pins("right")
    assert set(left) == set(right), (
        "左右で使うピンの集合は同じはず（子基板は 1 種類）。"
        f"左 {left} / 右 {right}")
