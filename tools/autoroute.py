"""未配線の基板を Freerouting に通して配線する。

**手書きのルータをやめた理由**は
docs/superpowers/specs/2026-08-08-pcb-autoroute-design.md にある。
要点は、衝突判定を持たないルータは任意のネット対を短絡させ、
それは経路の調整では 0 にならないということ。

    "$KPY" tools/gen_pcb.py --no-route   # 未配線の基板を出す
    "$KPY" tools/autoroute.py            # 配線する
    .venv/bin/python3 tools/drc.py       # 確かめる

DSN が 4 層・クリアランス規則・NPTH の keepout・GND ベタ（面として）を
運ぶことは実測で確認済み。
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pcbnew

import boardhash
import gnd_fanout

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "pcb"
UNROUTED = PCB / "unrouted"
HALVES = ("left", "right")
PASSES = 100

JAR = Path(os.environ.get(
    "FREEROUTING_JAR",
    Path.home() / ".local/share/freerouting/freerouting-2.3.0.jar"))


def _java():
    """java の実行ファイル。Homebrew の openjdk は PATH に無いことがある。"""
    for cand in (shutil.which("java"),
                 "/opt/homebrew/opt/openjdk/bin/java",
                 "/usr/local/opt/openjdk/bin/java"):
        if cand and Path(cand).exists():
            return cand
    raise SystemExit(
        "java が見つからない。brew install openjdk を実行すること")


def _check_jar():
    if not JAR.exists():
        raise SystemExit(
            f"Freerouting が見つからない: {JAR}\n"
            "入手:\n"
            "  mkdir -p ~/.local/share/freerouting\n"
            "  curl -L -o ~/.local/share/freerouting/freerouting-2.3.0.jar \\\n"
            "    https://github.com/freerouting/freerouting/releases/download/"
            "v2.3.0/freerouting-2.3.0.jar\n"
            "別の場所に置くなら FREEROUTING_JAR で指定する")


def _protect_the_ground_plane(dsn):
    """In1.Cu を「電源層」として宣言し直す。

    **KiCad の DSN は 4 層すべてを (type signal) として書き出す。**
    In1.Cu は GND のベタなのに、そのまま渡すと自動配線器が基準面の上に
    信号を通し、面を切り刻む。

    分割キーボードは左右で 2.4GHz を至近距離で動かすので、基準電位が
    連続していることの価値が大きい（4 層にしたのはそのため）。
    DRC は面が切れていても何も言わないので、ここで守る。

    効いたかどうかは、配線後に In1.Cu の配線本数を数えて確かめる
    （test_the_ground_plane_is_not_cut_by_routing）。
    """
    txt = dsn.read_text()
    old = "(layer In1.Cu\n      (type signal)"
    new = "(layer In1.Cu\n      (type power)"
    if old not in txt:
        raise SystemExit(
            "DSN の In1.Cu の宣言が想定と違う。KiCad の書式が変わった"
            "可能性がある。手で確かめること")
    dsn.write_text(txt.replace(old, new, 1))


def _strip_gnd(dsn):
    """GND を DSN から完全に消す。

    **GND は配線対象ではない。**ベタ（In1.Cu）と、配置段階で立てた
    ファンアウトのビア（tools/gnd_fanout.py）で既に配り終えている。

    「ピンだけ消してネットは残す」ような中途半端なやり方をすると、
    **Freerouting が NullPointerException で落ちる**（実測。GUI が
    立ち上がって例外ダイアログが出る）。ネット定義・クラスの一覧・
    plane 宣言をまとめて消すこと。

    ファンアウトのビアとスタブは `(type protect)` に変える。ネットを
    持たない固定の障害物として渡すと、Freerouting はそこを避けて
    配線する。**消してしまうと避けてくれない。**
    """
    t = dsn.read_text()
    t = re.sub(r"\s*\(plane GND \(polygon [\s\S]*?\)\)", "", t)
    t = re.sub(r"\s*\(net GND\s*\n\s*\(pins [^)]*\)\s*\n\s*\)", "", t)
    t = re.sub(r"(\(class \S+ [^)]*?)\bGND\b", r"\1", t)
    t = t.replace("(net GND)(type route)", "(type protect)")
    if "GND" in t:
        raise SystemExit(
            f"{dsn.name}: GND が消しきれていない。DSN の書式が変わった"
            "可能性がある。残すと Freerouting が NPE で落ちる")
    dsn.write_text(t)


def run(half):
    """未配線の基板を配線し、記録を残して返す。"""
    _check_jar()
    src = UNROUTED / f"hhkb_split_{half}.kicad_pcb"
    if not src.exists():
        raise SystemExit(
            f"未配線の基板が無い: {src}\n"
            'KiCad の Python で "tools/gen_pcb.py --no-route" を実行すること')

    board = pcbnew.LoadBoard(str(src))
    dsn = PCB / f"_{half}.dsn"
    ses = PCB / f"_{half}.ses"
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise SystemExit(f"{half}: DSN の書き出しに失敗した")
    _protect_the_ground_plane(dsn)
    _strip_gnd(dsn)

    # Freerouting のログは終わりに「N violations」と出すが、これは
    # protect にしたファンアウトどうしの接触を数えているだけ。
    # **本当の判定は KiCad の DRC**（tools/drc.py）。ここの数字で
    # 良否を決めないこと。
    subprocess.run(
        [_java(), "-jar", str(JAR), "-de", str(dsn), "-do", str(ses),
         "-mp", str(PASSES)],
        check=True)
    if not ses.exists():
        raise SystemExit(f"{half}: Freerouting が SES を出さなかった")

    if not pcbnew.ImportSpecctraSES(board, str(ses)):
        raise SystemExit(f"{half}: SES の取り込みに失敗した")

    # **ファンアウトを立て直す。**
    #
    # ImportSpecctraSES は既存の配線を全部作り直すので、配置段階で
    # 立てたビアが消える（実測: 7 個 → 0 個）。GND は DSN から外して
    # あるため SES にも入っておらず、ここで復活させないとベタに
    # 届かないまま残る。
    #
    # 位置は gnd_fanout が決定的に決めるので配線前と同じところに戻り、
    # Freerouting はそこを避けて配線済みなので衝突しない。
    gnd_fanout.place(board)

    # **ゾーンを塗り直す。**
    #
    # 「ゾーンを足した」と「塗られた」は別。この案件では 4 層化のときと
    # V3V3 の島のときの 2 回、ここで嵌まっている。SES の取り込みで
    # ビアが増えているので、塗り直さないと GND ベタが古いままになる。
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    out = PCB / f"hhkb_split_{half}.kicad_pcb"
    board.Save(str(out))
    dsn.unlink()
    ses.unlink()

    # **どの未配線基板から作られたかを残す。**
    # これが無いと「配置を変えたのに配線し直していない」が検出できない。
    #
    # バイト列ではなく指紋を使う。KiCad は保存のたびに UUID と
    # フットプリントの並び順を変えるので、バイトのハッシュは
    # 「再生成しただけ」でも変わってしまう（boardhash.py の説明を見る）。
    rec = {
        "board": out.name,
        "unrouted": src.name,
        "unrouted_fingerprint": boardhash.fingerprint(src),
        "freerouting": JAR.name,
        "passes": PASSES,
    }
    (PCB / f"route_{half}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    return rec


def main():
    for half in HALVES:
        rec = run(half)
        print(f"OK {half:5s} {rec['unrouted']} → {rec['board']}"
              f"  ({rec['freerouting']}, {rec['passes']} パス)")
    print("\n配線した。次: .venv/bin/python3 tools/drc.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
