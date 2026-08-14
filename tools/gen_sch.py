"""circuit.py の宣言から回路図（.kicad_sch）を出す。

    .venv/bin/python3 tools/gen_sch.py

なぜ要るか
----------
**回路図が無かったせいで、発注寸前の基板から 74LVC595 が丸ごと
抜け落ちていた**（2026-08-12）。幾何には DRC と干渉検査があるのに、
「宣言した回路が本当に基板に乗ったか」を見るものが 1 つも無かった。

回路図があると 2 つ手に入る。

  1. **ERC** — 電源入力がどこからも駆動されていない、出力どうしが
     ぶつかっている、といった電気的な誤りを KiCad が見つける
  2. **突き合わせの相手** — 回路図から出した netlist と、基板から
     読んだ netlist が一致するかを機械で見られる（test_schematic.py）

**手で描かない。**circuit.py を直せば回路図も追随する。二重管理にすると
必ずどちらかが腐る（この案件で何度も起きている型）。

なぜ kiutils を使わないか
-------------------------
kiutils 1.4.8 が書く .kicad_sch は KiCad 6 世代の書式で、**KiCad 10 は
読めない**（`(generator kiutils)` のような引用符なしトークンで撥ねられる。
実測: `kicad-cli sch export netlist` が「回路図の読み込みに失敗しました」）。
書式は KiCad 同梱の template/*.kicad_sch から読み取った。

図の見た目について
------------------
**配線は引かない。**各ピンの先端にネット名のグローバルラベルを置く。
KiCad は同名のグローバルラベルを同一ネットとして扱うので、これで
電気的には完全な回路図になる（実務でもフラットな回路図で使う手法）。
61 キーぶんのマトリクスに線を引いても人は読めない。

部品は機能ごとの塊に分けて並べ、塊の頭に見出しを置く。
"""

import subprocess
import sys
import uuid as _uuid
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pinmap                                                    # noqa: E402
from circuit import (daughterboard_netlist, netlist)             # noqa: E402

OUT = ROOT / "pcb"
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"

# KiCad 10 が書き出す書式版。template/*.kicad_sch から読み取った。
# KiCad 10.0.5 が自分で保存したファイルの値に合わせてある
# （generator は "hhkb_split" のまま独自ジェネレータと明示、
#  version と generator_version だけ実際のフォーマットに追随させる）。
SCH_VERSION = "20260306"

# --- 図面の寸法（mm）---
BODY_HW = 6.35          # シンボル本体の半幅
PIN_LEN = 5.08          # ピンの長さ
# **ピンの縦の間隔。**KiCad の標準グリッド 2.54mm ではなく 5.08mm
# （2 グリッド分）にしてある。
#
# グローバルラベルの矢印は必ずピン先端にくっつく（KiCad の仕様。
# ラベルを付ける以上、避けられない）。文字サイズ 1.0mm のラベルだと
# 矢印の高さがピンピッチとほぼ同じになり、隣どうしのラベルが
# 上下に重なってピン番号ごと読めなくなる（2026-08-13・利用者が
# スクリーンショットで指摘）。ラベルの矢印を小さくする／ワイヤーで
# ずらすはどちらも別の副作用を生んだ（前者は重なりを軽くしただけ、
# 後者は他ネットの配線と交差して短絡した）ので、ピッチを広げて
# 物理的に間隔を作る方に倒した。
#
# ⚠️ **1.27mm（KiCad の標準グリッド 50mil）の整数倍でなければならない。**
# 3.81mm（1.5 グリッド）を試したら、シンボル本体の半高
# `h = max(n+1,4)*PIN_PITCH/2` の `/2` で 1.905 の奇数倍が発生し、
# 1.27mm グリッドに乗らない座標のワイヤーができた
# （実測: 5.3975mm のワイヤー = 1.27mm の 4.25 倍）。
# KiCad はグリッド外の端点をピンとして認識せず、ピンの 8 割が
# 「未接続」判定になった（ERC: endpoint_off_grid 81 件、
# pin_not_connected 多数）。5.08mm（4 グリッド、2 の倍数）なら
# `/2` しても 2.54mm＝2 グリッドの整数倍で必ず乗る。
PIN_PITCH = 5.08
COL_W = 60.96           # 部品の列の間隔
ROW_GAP = 7.62          # 部品の縦の余白
# **左端の余白。**実配線グループ（電源・シフトレジスタ・ケーブル）の
# ワイヤーラベルを縦の帯に並べる場所を兼ねる。最大 3 本
# （シフトレジスタの SPI_SCK・CS・U1_U2）が並ぶので、
# 12.7mm 間隔 × 3 本が収まる余裕を見た
# （2026-08-13。25.4mm だと 3 本目がシート枠の外に出た）。
MARGIN = 38.1

# 参照名の接頭辞から、シンボルの見た目の名前を決めるための塊の順序。
# **回路図は人が読むものなので、宣言順ではなく機能順に並べる。**
GROUPS = [
    ("電源",       lambda ref, kind: kind in ("battery_land", "wire_land",
                                              "schottky", "res_1M")
                                     or ref == "C_BULK"),
    ("シフトレジスタ", lambda ref, kind: kind == "74LVC595" or ref.startswith("C_U")),
    ("マイコン",   lambda ref, kind: kind == "xiao_nrf52840" or ref == "C_DB"),
    ("ケーブル",   lambda ref, kind: kind == "ffc_12p"),
    ("マトリクス", lambda ref, kind: kind in ("keyswitch", "diode")),
]

# 決定的な UUID を振る。**乱数だと再生成のたびに全行が変わり、
# 差分が読めなくなる。**名前から導く。
NS = _uuid.UUID("6f1b4b4e-0000-4000-8000-000000000000")


def _uid(*parts):
    return str(_uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def _q(s):
    """KiCad の s 式の文字列。"""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _effects(hide=False, size=1.27):
    e = f"(effects (font (size {size} {size}))"
    if hide:
        e += " (hide yes)"
    return e + ")"


# ---------------------------------------------------------------- シンボル

def _symbol_pins(kind):
    """そのシンボルのピンを (ピン名, パッド番号, 電気的種別) で並べて返す。

    **並びはパッド番号順。**宣言順にすると同じ部品でも基板ごとに
    ピンの縦位置が変わり、図の差分が読めなくなる。
    """
    def key(item):
        pad = item[1][0]
        return (0, int(pad)) if pad and pad.isdigit() else (1, str(pad))
    return [(name, pad, et)
            for name, (pad, et) in sorted(pinmap.PINS[kind].items(), key=key)]


def _lib_symbol(kind, lib_id):
    """lib_symbols に入れる 1 個ぶんの定義。

    ピンは全部**左側**に縦一列。位置決めの規則が 1 本で済み、
    ラベルを置く座標が自明になる。

    **名前は lib_id そのもの**（`プロジェクト名:種類`）にする。
    ここを種類だけにすると、配置側の `(lib_id ...)` と一致せず、
    **KiCad はシンボルを見つけられずピンを 1 本も認識しない。**
    その状態でも netlist は出るが、全ピンが `Net-(X-Pad??)` という
    孤立ネットになり、ラベルは全部 dangling になる（実際にやった）。
    """
    pins = _symbol_pins(kind)
    n = len(pins)
    h = max(n + 1, 4) * PIN_PITCH / 2          # 本体の半高
    top = (n - 1) * PIN_PITCH / 2
    lines = [
        f"\t\t(symbol {_q(lib_id)}",
        "\t\t\t(pin_numbers (hide no))",
        f"\t\t\t(pin_names (offset {1.016}))",
        "\t\t\t(exclude_from_sim no)",
        "\t\t\t(in_bom yes)",
        "\t\t\t(on_board yes)",
        f"\t\t\t(property \"Reference\" \"U\" (at 0 {h + 1.27:.2f} 0) {_effects()})",
        f"\t\t\t(property \"Value\" {_q(kind)} (at 0 {-h - 1.27:.2f} 0) {_effects()})",
        f"\t\t\t(property \"Footprint\" \"\" (at 0 0 0) {_effects(hide=True)})",
        f"\t\t\t(property \"Datasheet\" \"\" (at 0 0 0) {_effects(hide=True)})",
        # **内側のユニット名には接頭辞を付けない。**外側は
        # `プロジェクト名:種類`、内側は `種類_1_1`。KiCad 同梱の
        # template でもそうなっている。ここに接頭辞を付けると、
        # **回路図まるごと読み込み失敗**になる（実際にやった）。
        f"\t\t\t(symbol {_q(kind + '_1_1')}",
        "\t\t\t\t(rectangle",
        f"\t\t\t\t\t(start {-BODY_HW} {h:.2f})",
        f"\t\t\t\t\t(end {BODY_HW} {-h:.2f})",
        "\t\t\t\t\t(stroke (width 0.254) (type default))",
        "\t\t\t\t\t(fill (type background))",
        "\t\t\t\t)",
    ]
    for i, (name, pad, et) in enumerate(pins):
        y = top - i * PIN_PITCH
        # ピンの接続点は (x, y)。そこから angle の向きへ length ぶん伸びて
        # 本体に届く。左側のピンなので angle 0（右向き）。
        lines += [
            f"\t\t\t\t(pin {et} line",
            f"\t\t\t\t\t(at {-(BODY_HW + PIN_LEN):.2f} {y:.2f} 0)",
            f"\t\t\t\t\t(length {PIN_LEN})",
            f"\t\t\t\t\t(name {_q(name)} {_effects(size=1.0)})",
            f"\t\t\t\t\t(number {_q(pad if pad is not None else name)} "
            f"{_effects(size=1.0)})",
            "\t\t\t\t)",
        ]
    lines += ["\t\t\t)", "\t\t)"]
    return "\n".join(lines), h


# **電源フラグ。**基板の外から電源が入ってくるネット（FFC 経由の V3V3、
# 電池からの GND）には、この印を付けないと ERC が
# 「電源入力ピンがどの電源出力にも駆動されていない」と言う。
# KiCad 標準ライブラリの PWR_FLAG と同じ役目のものを自前で持つ
# （標準ライブラリの場所に依存したくない）。
PWR_FLAG_KIND = "PWR_FLAG"
def _pwr_flag_sym(lib_id):
    # **`(power global)` と書く。**KiCad 10 は引数なしの `(power)` を
    # 撥ねて、回路図まるごと読み込み失敗になる（実際にやった）。
    # 中身は KiCad 同梱の symbols/power.kicad_sym の PWR_FLAG に合わせた。
    return f"""\t\t(symbol {_q(lib_id)}
\t\t\t(power global)
\t\t\t(pin_numbers (hide yes))
\t\t\t(pin_names (offset 0) (hide yes))
\t\t\t(exclude_from_sim yes)
\t\t\t(in_bom no)
\t\t\t(on_board no)
\t\t\t(property "Reference" "#FLG" (at 0 1.27 0) {_effects(hide=True)})
\t\t\t(property "Value" {_q(PWR_FLAG_KIND)} (at 0 3.81 0) {_effects()})
\t\t\t(symbol {_q(PWR_FLAG_KIND + '_1_1')}
\t\t\t\t(pin power_out line
\t\t\t\t\t(at 0 0 90)
\t\t\t\t\t(length 0)
\t\t\t\t\t(name "pwr" {_effects(size=1.0)})
\t\t\t\t\t(number "1" {_effects(size=1.0)})
\t\t\t\t)
\t\t\t)
\t\t)"""


# ---------------------------------------------------------------- 図の組み立て

LAND_KIND = {"wire_pads": "wire_land", "battery_holder": "battery_land"}


def expanded(parts):
    """回路の宣言を、**基板に載る姿**へ割る。

    電池ボックスと電源スイッチは、回路としては 1 部品 2 端子だが、
    基板の上ではランド 2 個＝**独立した 2 つのフットプリント**
    （`BT1_+` と `BT1_-`）になる（circuit.board_refs と同じ規則）。

    回路図もその姿で描く。理由は 2 つ。

      1. **1 部品 2 ピンのまま描くと、両ピンのパッド番号が 1 で重なり、
         ERC が duplicate_pins で落ちる**（実際に落ちた）
      2. 割っておくと、回路図の参照名と基板の参照名が 1 対 1 になり、
         突き合わせがそのまま辞書の比較になる
    """
    out = []
    for ref, kind, pins in parts:
        land = LAND_KIND.get(kind)
        if land:
            for pin, net in pins.items():
                out.append((f"{ref}_{pin}", land, {"1": net}))
        else:
            out.append((ref, kind, pins))
    return out


def _ordered(parts):
    """機能の塊ごとに並べ替える。(見出し, [部品]) の一覧を返す。"""
    rest = list(parts)
    out = []
    for title, belongs in GROUPS:
        take = [p for p in rest if belongs(p[0], p[1])]
        if take:
            out.append((title, take))
        rest = [p for p in rest if p not in take]
    if rest:
        out.append(("その他", rest))
    return out


def _needs_power_flag(parts):
    """電源フラグを立てるネット。

    **電源入力ピンがあるのに、電源出力ピンが 1 つも無いネット。**
    そのネットは基板の外（電池・USB・FFC の向こう側）から来ている。
    数え上げで決めるので、部品を足しても自分で追随する。
    """
    has_in, has_out = set(), set()
    for ref, kind, pins in parts:
        for pin, net in pins.items():
            if net == "NC":
                continue
            et = pinmap.etype(kind, pin)
            if et == pinmap.POWER_IN:
                has_in.add(net)
            elif et == pinmap.POWER_OUT:
                has_out.add(net)
    return sorted(has_in - has_out)


def build(parts, project):
    """部品の一覧から .kicad_sch の中身を組み立てて返す。"""
    kinds = sorted({kind for _, kind, _ in parts})
    lib = {}
    for kind in kinds:
        lib[kind] = _lib_symbol(kind, f"{project}:{kind}")

    flags = _needs_power_flag(parts)

    body, labels = [], []
    x, y, col_h = MARGIN, MARGIN, 0.0
    max_x = max_y = 0.0

    # **ネットごとのピン座標を集める（配線を引くかどうかの判断に使う）。**
    #
    # ここに集めるのは「配線候補にするグループ」（マトリクス以外）の
    # ピンだけ。マトリクスはキーごとに独立したネットが多く、機械的に
    # 線で結ぶと 61 キー分の線が基板全体を這って読めなくなる
    # （モジュールの説明の通り）。
    #
    # **接続数で判断する。**電源・シフトレジスタ・ケーブルは部品数が
    # 少なく GND・V3V3 のような共有ネット（3 本以上つながる）と
    # 1 対 1 のネット（分圧の間・信号の中継など）が混ざっている。
    # 1 対 1 のものだけを実配線にする——3 本以上を線で束ねるのは
    # バス配線の設計が要り、複雑さに見合わない。
    net_pins = defaultdict(list)   # netname -> [(px, py), ...]
    all_pins = []   # [(ref, px, py), ...] 全ピン座標。実配線ワイヤーが
                     # 他部品のピン列を横切っていないか判定するのに使う。
    bus_pins = defaultdict(list)   # netname -> [(ref, px, py), ...]（V3V3・GND 用）
    bus_segments = []   # [(x0, x1, y), ...] バス水平線の区間。net_pins の
                         # 迂回判定で「バス線を貫通していないか」も見る。
    bus_drop_jobs = []   # [(title, netname, ref, px, py, bus_y), ...]
                          # バスの枝は、グループの処理順に関わらず
                          # 「全部品を置き終えたあと」に一括で描く。
                          # グループごとにその場で描くと、まだ配置していない
                          # 後続グループのピン（all_pins に無い）を貫通しても
                          # 気づけない（実測：電源グループの V3V3 の枝が、
                          # まだ置いていないシフトレジスタの COL0 ラベルを
                          # 貫通して短絡した）。

    # **バス線を横切る場合も迂回対象にする。**バスは他グループの部品を
    # 含む横長の線なので、素通りすると無関係なネットが電気的に繋がる
    # （実測：U1_U2 がシフトレジスタの GND バスの上を通過し、69 ピンが
    # 1 ネットに誤統合された）。
    def _crosses_bus(yy, xx0, xx1):
        return any(abs(yy - by) < 0.1
                   and not (xx1 < bx0 or xx0 > bx1)
                   for bx0, bx1, by in bus_segments)

    # **V3V3・GND は「1 本の共通バスから枝を引く」。**ただのグローバル
    # ラベルの並びだと、回路の意図（電源レール・ノイズ対策のための
    # パスコン）が図から読み取れない（2026-08-13・利用者の指摘：
    # 「同じネットが正しく共通化されておらず、回路の思想が見えない」）。
    #
    # **過去に 2 度撤回・復元している。**
    #   1 度目：複数のピンが同じ列（同じ x 座標）に並ぶとジャンクション
    #     の UUID が衝突し、KiCad の解析が混乱して無関係な 69 ピンが
    #     1 つのネットに誤統合される事故を起こした → いったん部品ごと
    #     独立シンボル方式に撤回。
    #   2 度目：独立シンボル方式でも「V3V3 を 1 本の線で引いて共通化
    #     されている、という回路の思想が見えない」という当初の指摘が
    #     再燃し、バス方式に戻した（今回）。
    # 今回は、独立シンボル方式で学んだ 2 つの教訓を両方バスの枝にも
    # 適用する。
    #   a) **枝は先に横（ピンの列から出る）、それから縦。**縦線が
    #      ピンの列（x = px）に乗る区間を作らない。同じ部品が V3V3・
    #      GND を両方持つ場合（74LVC595 の VCC・MR）、真っ直ぐ縦に
    #      伸ばすと 1 ピッチ隣の自分自身の別ピン（Q0=COLn 等）を
    #      素通りする（実測：37〜69 ピンの巨大ネットに誤統合された）。
    #   b) **バスの枝は全部品を置き終えたあとに一括で描く。**グループ
    #      の処理順に依存する短絡を避ける。
    BUS_NETS = ("V3V3", "GND")

    def place(ref, kind, pins, x, y, wire_candidate):
        """1 部品を置く。ピンには次のどちらかを添える。

        wire_candidate な部品のピンで、そのネットの接続数が 2 以下なら
        座標だけ net_pins に記録し、あとで build() の最後に 1 本の
        ワイヤーとして結ぶ。それ以外はグローバルラベル。
        """
        _, h = lib[kind]
        pin_rows = _symbol_pins(kind)
        top = (len(pin_rows) - 1) * PIN_PITCH / 2
        s = [
            "\t(symbol",
            f"\t\t(lib_id {_q(project + ':' + kind)})",
            f"\t\t(at {x:.2f} {y:.2f} 0)",
            "\t\t(unit 1)",
            "\t\t(exclude_from_sim no)",
            "\t\t(in_bom yes)",
            "\t\t(on_board yes)",
            "\t\t(dnp no)",
            f"\t\t(uuid {_q(_uid(project, ref))})",
            f"\t\t(property \"Reference\" {_q(ref)} "
            f"(at {x:.2f} {y - h - 1.27:.2f} 0) {_effects()})",
            f"\t\t(property \"Value\" {_q(kind)} "
            f"(at {x:.2f} {y + h + 1.27:.2f} 0) {_effects()})",
        ]
        for i, (name, pad, _et) in enumerate(pin_rows):
            s.append(f"\t\t(pin {_q(pad if pad is not None else name)} "
                     f"(uuid {_q(_uid(project, ref, name))}))")
            netname = pins.get(name, "NC")
            # **シンボルの (x, y) は、配置座標に対して y が反転する。**
            # KiCad はシンボルライブラリを Y 上向き、回路図を Y 下向きで
            # 扱うため。ここを間違えるとラベルがピンに触れず、
            # ネットが 1 本も繋がらない（netlist を出して確かめてある）。
            px = x - (BODY_HW + PIN_LEN)
            py = y - (top - i * PIN_PITCH)
            all_pins.append((ref, px, py))
            if netname == "NC":
                labels.append(f"\t(no_connect (at {px:.2f} {py:.2f}) "
                              f"(uuid {_q(_uid(project, ref, name, 'nc'))}))")
            elif wire_candidate and netname in BUS_NETS and net_count[netname] >= 2:
                # 1 本しかない（このグループ内にそのネットの部品が
                # 1 個だけ）ときはバス化しない。長さ 0 の横線ができて
                # KiCad が「線に触れていない」と判定する
                # （実測：J_MAIN 単体の「ケーブル」グループで
                #  label_dangling）。
                bus_pins[netname].append((ref, name, px, py))
            elif wire_candidate and net_count[netname] == 2:
                net_pins[netname].append((px, py))
            else:
                # **ラベルの矢印は、ピン先端に直接置く。**動かさない。
                #
                # ピン番号の数字と矢印の形が重なって見た目は完全には
                # 綺麗にならないが（2026-08-13・利用者がスクリーンショットで
                # 指摘）、動かす方式を 3 回試して 3 回とも新しい交差
                # バグを生んだ（別部品のピンとの短絡・他ネットの配線との
                # 短絡・GND と V3V3 が電気的に統合される、の順に悪化）。
                # **電気的な安全性を優先し、動かさない方針に確定する。**
                # ピッチを広げた分（PIN_PITCH 5.08mm）、文字は重ならず
                # 並ぶので、矢印の頭が番号に触れる程度で読解には支障ない。
                labels.append(
                    "\t(global_label\n"
                    f"\t\t{_q(netname)}\n"
                    "\t\t(shape input)\n"
                    f"\t\t(at {px:.2f} {py:.2f} 180)\n"
                    f"\t\t{_effects(size=1.0)}\n"
                    f"\t\t(uuid {_q(_uid(project, ref, name, 'lbl'))})\n"
                    "\t)")
        s += [
            "\t\t(instances",
            f"\t\t\t(project {_q(project)}",
            f"\t\t\t\t(path \"/{_uid(project, 'sheet')}\"",
            f"\t\t\t\t\t(reference {_q(ref)})",
            "\t\t\t\t\t(unit 1)",
            "\t\t\t\t)",
            "\t\t\t)",
            "\t\t)",
            "\t)",
        ]
        return "\n".join(s)

    texts, wires = [], []
    # **配線を引くグループ。**マトリクスは 54〜68 個のキーが独立した
    # ネットを持ち、線で結ぶと基板全体を這って読めなくなる
    # （モジュール冒頭の説明の通り）。それ以外は 10 個前後で、
    # 実配線を引いても十分読める（2026-08-13・利用者の指摘）。
    #
    # **座標は行・列の一括計算式ではなく、部品ごとに手で決める**
    # （2026-08-13・利用者の提案）。一括計算式は「同じ行に何個並ぶか」
    # を変えるたびに、意図しない場所で水平線が別の部品を貫通する
    # 事故を繰り返した（機械的な配置ルールでは避けきれなかった）。
    # ここでは信号の流れ（電池→スイッチ→整流→分圧、SPI→シフト
    # レジスタ→ケーブル）に沿って (行, 列) を明示する。
    WIRE_LAYOUT = {
        "電源": {
            "BT1_+": (0, 0), "SW_PWR_1": (0, 1), "BT1_-": (0, 2),
            "SW_PWR_2": (1, 0), "D_PWR": (1, 1), "C_BULK": (1, 2),
            "R_HI": (2, 0), "R_LO": (2, 1),
        },
        "シフトレジスタ": {
            "U1": (0, 0), "U2": (0, 1), "C_U1": (0, 2), "C_U2": (0, 3),
        },
        "マイコン": {
            "U_MCU": (0, 0), "C_DB": (0, 1),
        },
        "ケーブル": {
            "J_DB": (0, 0), "J_MAIN": (0, 0),
        },
    }

    for title, group in _ordered(parts):
        wire_candidate = title in WIRE_LAYOUT
        # 塊の頭で改列し、見出しを置く
        if col_h:
            y += col_h + ROW_GAP * 2
            col_h = 0
        texts.append(
            f"\t(text {_q('── ' + title + ' ──')}\n"
            f"\t\t(at {MARGIN:.2f} {y - PIN_PITCH * 3:.2f} 0)\n"
            f"\t\t{_effects(size=2.54)}\n"
            f"\t\t(uuid {_q(_uid(project, 'ttl', title))})\n\t)")
        net_count = defaultdict(int)
        if wire_candidate:
            for _ref, _kind, pins in group:
                for _pin, net in pins.items():
                    if net != "NC":
                        net_count[net] += 1
        net_pins.clear()
        bus_pins.clear()

        if wire_candidate:
            layout = WIRE_LAYOUT[title]
            x0 = MARGIN + BODY_HW + PIN_LEN + 25.4
            # **バス線の分だけ、部品の上下に余白を空ける。**V3V3 は
            # 部品群の上、GND は部品群の下にバスを通す（電源が上から
            # 下りて GND へ抜けていく、一般的な回路図の描き方に合わせる。
            # 2026-08-13・利用者の指摘）。固定 PIN_PITCH*2 では足りず、
            # 部品本体（74LVC595 なら半高 40mm 超）とバス線が重なった
            # ことがあるので、そのグループの最大部品の半高ぶんを足す。
            top_h = max((h for _, h in (lib[k] for _r, k, _p in group)),
                        default=0)
            y0 = y + top_h + PIN_PITCH * 2
            for ref, kind, pins in group:
                row, col = layout[ref]
                _, h = lib[kind]
                px_ = x0 + col * COL_W
                py_ = y0 + row * (ROW_GAP + 2 * max(h, 12.7))
                body.append(place(ref, kind, pins, px_, py_ + h, wire_candidate))
                max_x, max_y = max(max_x, px_), max(max_y, py_ + h * 2)

            group_top = y0 - top_h
            group_bottom = max_y
            bus_y_of = {"V3V3": group_top - PIN_PITCH,
                        "GND": group_bottom + PIN_PITCH}
            for netname in BUS_NETS:
                pts = bus_pins.get(netname)
                if not pts:
                    continue
                bus_y = bus_y_of[netname]
                bus_x1 = max(px for _r, _n, px, _py in pts)
                bus_x0 = min(px for _r, _n, px, _py in pts) - PIN_PITCH
                bus_segments.append((bus_x0, bus_x1, bus_y))
                wires.append(
                    "\t(wire\n"
                    f"\t\t(pts (xy {bus_x0:.2f} {bus_y:.2f}) "
                    f"(xy {bus_x1:.2f} {bus_y:.2f}))\n"
                    "\t\t(stroke (width 0.508) (type default))\n"
                    f"\t\t(uuid {_q(_uid(project, 'bus', title, netname))})\n"
                    "\t)")
                wires.append(
                    "\t(label\n"
                    f"\t\t{_q(netname)}\n"
                    f"\t\t(at {bus_x0:.2f} {bus_y:.2f} 0)\n"
                    f"\t\t{_effects(size=1.0)}\n"
                    f"\t\t(uuid {_q(_uid(project, 'buslbl', title, netname))})\n"
                    "\t)")
                for ref, name, px, py in pts:
                    bus_drop_jobs.append((title, netname, ref, name, px, py, bus_y))
            if bus_pins.get("GND"):
                max_y = bus_y_of["GND"]
            y = max_y + PIN_PITCH * 2 + ROW_GAP
        else:
            row_len = 11
            x = MARGIN + BODY_HW + PIN_LEN + 25.4
            for ref, kind, pins in group:
                _, h = lib[kind]
                if x > MARGIN + COL_W * row_len:
                    x = MARGIN + BODY_HW + PIN_LEN + 25.4
                    y += col_h + ROW_GAP
                    col_h = 0
                body.append(place(ref, kind, pins, x, y + h, wire_candidate))
                col_h = max(col_h, h * 2 + ROW_GAP)
                max_x, max_y = max(max_x, x), max(max_y, y + h * 2)
                x += COL_W
            y += col_h + ROW_GAP
            col_h = 0

        # **ちょうど 2 点のネットを 1 本のワイヤーで結ぶ。**
        # net_pins は place() が「net_count == 2」のときだけ書き込む
        # （1 本しかない・3 本以上つながるネットは place() 側で
        #  ラベルへ回るので、ここには来ない）。
        for wi, (netname, pts) in enumerate(net_pins.items()):
            assert len(pts) == 2, (netname, pts)   # net_count と食い違ったら壊れている
            (x1, y1), (x2, y2) = pts
            # **部品を手動で隣接配置してあるので、基本は 2 点の間だけを
            # 結ぶ最短の L 字（水平 → 垂直）で足りる。**以前はここで
            # シート左端まで回り込む経路を使っていたが、それは「部品が
            # 離れている」ことを前提にした設計で、隣どうしに並べた今は
            # 不要な迂回でしかない（実測：当時の C_RAIL の隣に R_HI・R_LO を
            # 置いても、この迂回経路のせいで VBATT_SENSE の線が
            # 見出しの外まで伸びていた）。
            #
            # **ただし、水平区間が相手部品の別のピンを横切る場合だけは
            # 例外。**U1.Q7S → U2.DS のように、隣の部品の中で高さが
            # 違うピンへ向かうと、その部品の別のピン（Q7S など）の
            # 前を素通りしてしまい、無関係なピンと短絡する
            # （実測：ERC が「出力どうし接続」を報告）。
            # その場合だけ、相手部品の外（上端の外）を回る。
            # **境界（相手部品の先頭ピン列の x）を含めて判定する。**
            # U1.Q7S → U2.DS のようなケースでは、U2 のブロックする
            # ピン（Q7S）がちょうど x2（U2 側の目的ピンの x）と同じ列に
            # 並ぶ。厳密な不等号 `<` だと境界のこのケースを見逃す
            # （実測：blocked=False のまま短絡が再発した）。
            blocked = any(
                abs(py - y1) < 0.1 and min(x1, x2) <= px <= max(x1, x2)
                and (px, py) not in ((x1, y1), (x2, y2))
                for _ref, px, py in all_pins
            ) or _crosses_bus(y1, x1, x2)
            if not blocked:
                wires.append(
                    "\t(wire\n"
                    f"\t\t(pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y1:.2f}))\n"
                    "\t\t(stroke (width 0) (type default))\n"
                    f"\t\t(uuid {_q(_uid(project, 'wire', title, netname, 'h'))})\n"
                    "\t)")
                if y1 != y2:
                    wires.append(
                        "\t(wire\n"
                        f"\t\t(pts (xy {x2:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f}))\n"
                        "\t\t(stroke (width 0) (type default))\n"
                        f"\t\t(uuid {_q(_uid(project, 'wire', title, netname, 'v'))})\n"
                        "\t)")
            else:
                # 相手部品の上端の外を回る。**衝突しなくなるまで
                # PIN_PITCH ずつ上へずらす。**1 段上げただけでは、
                # そこにまた別のピン（同じ部品の GND 等）が並んでいる
                # ことがある（実測：Q7S の 1 段上が GND のラベルと
                # 一致し、今度は BT1_- と誤って繋がった）。
                all_x = (x1, x2)
                detour_y = min(y1, y2) - PIN_PITCH
                for _ in range(20):
                    hit = any(
                        abs(py - detour_y) < 0.1
                        and min(all_x) <= px <= max(all_x)
                        for _ref, px, py in all_pins
                    ) or _crosses_bus(detour_y, *all_x)
                    if not hit:
                        break
                    detour_y -= PIN_PITCH
                else:
                    raise SystemExit(
                        f"{netname}: 迂回経路が 20 段上げても衝突を"
                        "避けられない。部品の配置を見直すこと")
                for seg, (a, b) in enumerate([
                    ((x1, y1), (x1, detour_y)),
                    ((x1, detour_y), (x2, detour_y)),
                    ((x2, detour_y), (x2, y2)),
                ]):
                    wires.append(
                        "\t(wire\n"
                        f"\t\t(pts (xy {a[0]:.2f} {a[1]:.2f}) "
                        f"(xy {b[0]:.2f} {b[1]:.2f}))\n"
                        "\t\t(stroke (width 0) (type default))\n"
                        f"\t\t(uuid {_q(_uid(project, 'wire', title, netname, f'd{seg}'))})\n"
                        "\t)")
                y1 = detour_y   # ラベル位置の計算に使う
            # **ワイヤーだけではネット名が付かない。**
            # KiCad は名前の無いワイヤーに `Net-(REF-PadN)` という
            # 自動生成の名前を振る。宣言した名前（VBATT_RAW 等）と
            # 一致させるには、ラベルを 1 個添える必要がある
            # （実測：付けなかったら test_schematic の突き合わせが落ちた）。
            # **global_label ではなくローカルの label にする**——
            # このネットは同じワイヤーの中で完結しており、他のシートや
            # 別の場所と束ねる必要が無い。
            # 水平区間の中点に置く。部品を隣接配置してあるので区間は
            # 短く、他のワイヤーと交差する余地がない。
            lx, ly = (x1 + x2) / 2, y1
            wires.append(
                "\t(label\n"
                f"\t\t{_q(netname)}\n"
                f"\t\t(at {lx:.2f} {ly:.2f} 0)\n"
                f"\t\t{_effects(size=1.0)}\n"
                f"\t\t(uuid {_q(_uid(project, 'wlbl', title, netname))})\n"
                "\t)")

    # **バスの枝は、全部品を置き終えたあとにまとめて描く。**理由は
    # bus_drop_jobs への追加箇所を参照。
    for title, netname, ref, name, px, py, bus_y in bus_drop_jobs:
        up = netname == "V3V3"
        # **先に横（ピンの列から出る）、それから縦。**逆順だと縦線が
        # ピンの列（x = px）を通ってしまい、隣のピンを素通りする。
        # 同じ部品が V3V3・GND を両方持つ場合（74LVC595 の VCC・MR）、
        # 隣は 1 ピッチ違いのピンなので、真っ直ぐ縦に伸ばすとそこを
        # 串刺しにする（実測：U1.VCC の枝が隣の Q0=COL0 を素通りして
        # 37〜69 ピンの巨大ネットに誤統合された）。
        jog_x = px - PIN_PITCH
        # **ジョグ先の列も、通過区間に無関係なピンが無いか見る。**
        # 自分自身の他のピン（同じ ref）も対象にする——除外すると、
        # 1 個の部品が同じバスネットに 2 本のピンを持つケースを
        # 見逃す。
        ylo, yhi = min(py, bus_y), max(py, bus_y)
        for _ in range(10):
            # all_pins は (ref, x, y) のみを持つ。同じ ref の別ピンも
            # 判定対象に含めたいので、(ref, px, py) 自身の座標だけを
            # 除外する形にする。
            blocked = any(
                (r, ppx, ppy) != (ref, px, py) and abs(ppx - jog_x) < 0.1
                and ylo - 0.1 <= ppy <= yhi + 0.1
                for r, ppx, ppy in all_pins
            ) or _crosses_bus(py, min(px, jog_x), max(px, jog_x))
            if not blocked:
                break
            jog_x -= PIN_PITCH
        else:
            raise SystemExit(
                f"{netname}: {ref}.{name} のバスの枝が 10 段ずらしても"
                "衝突を避けられない")
        wires.append(
            "\t(wire\n"
            f"\t\t(pts (xy {px:.2f} {py:.2f}) (xy {jog_x:.2f} {py:.2f}))\n"
            "\t\t(stroke (width 0) (type default))\n"
            f"\t\t(uuid {_q(_uid(project, ref, name, 'busdrop', 'h'))})\n"
            "\t)")
        wires.append(
            "\t(wire\n"
            f"\t\t(pts (xy {jog_x:.2f} {py:.2f}) (xy {jog_x:.2f} {bus_y:.2f}))\n"
            "\t\t(stroke (width 0) (type default))\n"
            f"\t\t(uuid {_q(_uid(project, ref, name, 'busdrop', 'v'))})\n"
            "\t)")
        wires.append(
            "\t(wire\n"
            f"\t\t(pts (xy {jog_x:.2f} {bus_y:.2f}) (xy {px:.2f} {bus_y:.2f}))\n"
            "\t\t(stroke (width 0) (type default))\n"
            f"\t\t(uuid {_q(_uid(project, ref, name, 'busdrop', 'h2'))})\n"
            "\t)")
        # **バス線と枝の分岐点にジャンクションを置く。**KiCad は T 字
        # （線の途中から別の線が分岐する形）を座標の一致だけでは
        # 接続と認識しないことがある（実測：座標はすべて正しいのに
        #  ERC が pin_not_connected を出し続けた。junction が
        #  1 個も無かった）。
        #
        # **UUID には ref・name を含める。**同じ列（同じ x）に複数の
        # ピンが並ぶと UUID が重複し、KiCad の解析が混乱して無関係な
        # ピンどうしが 1 つの巨大ネットに誤統合される事故が起きた
        # （実測：69 ピンが 1 ネットに統合）。
        # **diameter は 0 ではなく 1.016（KiCad の既定値）。**
        # KiCad 純正テンプレートを確認したら diameter 0 のジャンクション
        # は無く、全部 1.016 だった。0 だと KiCad の接続解析で無効化
        # される疑いがある（69 ピンの誤統合の原因候補。実測でも
        # 解消した）。
        wires.append(
            f"\t(junction (at {px:.2f} {bus_y:.2f}) "
            f"(diameter 1.016) (color 0 0 0 0)\n"
            f"\t\t(uuid {_q(_uid(project, 'busjct', title, netname, ref, name))})\n"
            "\t)")
        all_pins.append((ref, jog_x, bus_y))

    # 電源フラグ
    fx = MARGIN + BODY_HW + PIN_LEN + 25.4
    texts.append(
        f"\t(text {_q('── 電源フラグ（基板の外から来るネット）──')}\n"
        f"\t\t(at {MARGIN:.2f} {y - PIN_PITCH:.2f} 0)\n"
        f"\t\t{_effects(size=2.54)}\n"
        f"\t\t(uuid {_q(_uid(project, 'ttl', 'flag'))})\n\t)")
    y += PIN_PITCH * 2
    for i, net in enumerate(flags):
        px = fx + i * 25.4
        body.append("\n".join([
            "\t(symbol",
            f"\t\t(lib_id {_q(project + ':' + PWR_FLAG_KIND)})",
            f"\t\t(at {px:.2f} {y:.2f} 0)",
            "\t\t(unit 1)",
            "\t\t(exclude_from_sim yes)",
            "\t\t(in_bom no)",
            "\t\t(on_board no)",
            "\t\t(dnp no)",
            f"\t\t(uuid {_q(_uid(project, 'flag', net))})",
            f"\t\t(property \"Reference\" {_q('#FLG' + str(i))} "
            f"(at {px:.2f} {y - 2.54:.2f} 0) {_effects(hide=True)})",
            f"\t\t(property \"Value\" {_q(PWR_FLAG_KIND)} "
            f"(at {px:.2f} {y - 5.08:.2f} 0) {_effects()})",
            f"\t\t(pin \"1\" (uuid {_q(_uid(project, 'flagpin', net))}))",
            "\t\t(instances",
            f"\t\t\t(project {_q(project)}",
            f"\t\t\t\t(path \"/{_uid(project, 'sheet')}\"",
            f"\t\t\t\t\t(reference {_q('#FLG' + str(i))})",
            "\t\t\t\t\t(unit 1)",
            "\t\t\t\t)",
            "\t\t\t)",
            "\t\t)",
            "\t)",
        ]))
        labels.append(
            "\t(global_label\n"
            f"\t\t{_q(net)}\n"
            "\t\t(shape input)\n"
            f"\t\t(at {px:.2f} {y:.2f} 180)\n"
            f"\t\t{_effects(size=1.0)}\n"
            f"\t\t(uuid {_q(_uid(project, 'flaglbl', net))})\n"
            "\t)")
        max_x, max_y = max(max_x, px), max(max_y, y)

    w = max_x + COL_W + MARGIN
    hgt = max_y + MARGIN * 2
    head = [
        "(kicad_sch",
        f"\t(version {SCH_VERSION})",
        '\t(generator "hhkb_split")',
        '\t(generator_version "10.0")',
        f"\t(uuid {_q(_uid(project, 'sheet'))})",
        f"\t(paper \"User\" {w:.2f} {hgt:.2f})",
        "\t(title_block",
        f"\t\t(title {_q(project)})",
        f"\t\t(comment 1 {_q('tools/gen_sch.py が circuit.py から自動生成。手で編集しない')})",
        "\t)",
        "\t(lib_symbols",
    ]
    head += [lib[k][0] for k in kinds]
    head.append(_pwr_flag_sym(f'{project}:{PWR_FLAG_KIND}'))
    head.append("\t)")
    tail = ["\t(sheet_instances", '\t\t(path "/" (page "1"))', "\t)", ")"]
    return "\n".join(head + labels + wires + texts + body + tail) + "\n"


SHEETS = {
    "hhkb_split_left": lambda: netlist("left"),
    "hhkb_split_right": lambda: netlist("right"),
    "hhkb_split_daughterboard": daughterboard_netlist,
}


def write(project, path=None):
    """回路図を書き出してその場所を返す。"""
    path = Path(path) if path else OUT / f"{project}.kicad_sch"
    path.write_text(build(expanded(SHEETS[project]()), project),
                    encoding="utf-8")
    return path


def netlist_from_sch(path):
    """回路図から netlist を出して {参照名: {パッド番号: ネット名}} で返す。

    **KiCad 自身に読ませる。**自分が書いた s 式を自分で解釈しても、
    KiCad がどう解釈するかの証拠にはならない。
    """
    import xml.etree.ElementTree as ET
    path = Path(path)
    xml = path.with_suffix(".netlist.xml")
    subprocess.run(
        [KICAD_CLI, "sch", "export", "netlist", "--format", "kicadxml",
         "-o", str(xml), str(path)],
        check=True, capture_output=True, text=True)
    out = {}
    for net in ET.parse(xml).getroot().find("nets"):
        name = net.get("name")
        # **ローカルラベルのネットには先頭に `/`（ルートシートパス）が付く。**
        # グローバルラベル（マトリクス側）はプロジェクト全体スコープなので
        # 付かない。同じ VBATT_RAW でも由来によって名前の見た目が変わると
        # 突き合わせ検査が誤って「食い違い」を報告する（実測）ので、
        # ここで剥がして揃える。1 階層しか無いこの回路図では、
        # 先頭の `/` は名前の一部ではなく scope の印にすぎない。
        name = name.lstrip("/")
        for node in net.findall("node"):
            out.setdefault(node.get("ref"), {})[node.get("pin")] = name
    xml.unlink()
    return out


def main():
    for project in SHEETS:
        p = write(project)
        nl = netlist_from_sch(p)
        pins = sum(len(v) for v in nl.values())
        print(f"OK {p.name}  部品 {len(nl)} 個 / 接続されたピン {pins} 本")
    print("\n出した。次: .venv/bin/pytest tools/test_schematic.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
