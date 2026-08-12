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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pinmap                                                    # noqa: E402
from circuit import (daughterboard_netlist, netlist)             # noqa: E402

OUT = ROOT / "pcb"
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"

# KiCad 10 が書き出す書式版。template/*.kicad_sch から読み取った。
SCH_VERSION = "20250114"

# --- 図面の寸法（mm）---
BODY_HW = 6.35          # シンボル本体の半幅
PIN_LEN = 5.08          # ピンの長さ
PIN_PITCH = 2.54        # ピンの縦の間隔
COL_W = 60.96           # 部品の列の間隔
ROW_GAP = 7.62          # 部品の縦の余白
MARGIN = 25.4

# 参照名の接頭辞から、シンボルの見た目の名前を決めるための塊の順序。
# **回路図は人が読むものなので、宣言順ではなく機能順に並べる。**
GROUPS = [
    ("電源",       lambda ref, kind: kind in ("battery_land", "wire_land",
                                              "schottky", "res_1M")
                                     or ref in ("C_BULK", "C_MCU")),
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

    def place(ref, kind, pins, x, y):
        """1 部品を置き、各ピンにグローバルラベルを添える。"""
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
            if netname == "NC":
                labels.append(f"\t(no_connect (at {px:.2f} {py:.2f}) "
                              f"(uuid {_q(_uid(project, ref, name, 'nc'))}))")
            else:
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

    texts = []
    for title, group in _ordered(parts):
        # 塊の頭で改列し、見出しを置く
        if col_h:
            y += col_h + ROW_GAP * 2
            col_h = 0
        texts.append(
            f"\t(text {_q('── ' + title + ' ──')}\n"
            f"\t\t(at {MARGIN:.2f} {y - PIN_PITCH * 3:.2f} 0)\n"
            f"\t\t{_effects(size=2.54)}\n"
            f"\t\t(uuid {_q(_uid(project, 'ttl', title))})\n\t)")
        x = MARGIN + BODY_HW + PIN_LEN + 25.4
        for ref, kind, pins in group:
            _, h = lib[kind]
            if x > MARGIN + COL_W * 11:
                x = MARGIN + BODY_HW + PIN_LEN + 25.4
                y += col_h + ROW_GAP
                col_h = 0
            body.append(place(ref, kind, pins, x, y + h))
            col_h = max(col_h, h * 2 + ROW_GAP)
            max_x, max_y = max(max_x, x), max(max_y, y + h * 2)
            x += COL_W
        y += col_h + ROW_GAP
        col_h = 0

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
        '\t(generator_version "9.0")',
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
    return "\n".join(head + labels + texts + body + tail) + "\n"


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
