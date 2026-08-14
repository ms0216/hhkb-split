"""未配線の基板を Freerouting に通して配線する。

**手書きのルータをやめた理由**は
docs/superpowers/specs/2026-08-08-pcb-autoroute-design.md にある。
要点は、衝突判定を持たないルータは任意のネット対を短絡させ、
それは経路の調整では 0 にならないということ。

    "$KPY" tools/gen_pcb.py --no-route   # 未配線の基板を出す
    "$KPY" tools/autoroute.py            # 配線する
    .venv/bin/python3 tools/drc.py       # 確かめる

DSN が層構成・クリアランス規則・NPTH の keepout・GND ベタ（面として）を
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
from gen_pcb import prewire_row_bus, prewire_switch_diode

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "pcb"
UNROUTED = PCB / "unrouted"
HALVES = ("left", "right")
PASSES = 300      # 800 に増やしても未配線は減らなかった（2026-08-13）

# ⚠️ **DSN に `(autoroute_settings ...)` を足さないこと**（2026-08-14 に実測）。
#
# 利用者の指摘「ROW0 がなぜ表裏を行き来するのか。同じ面で横一直線の方が
# 自然では」を受けて `(via_costs N)` + `(start_ripup_costs 100)` を
# structure の末尾に入れてみた。**左が未配線 1 → 66 本に激増した。**
# via_costs を 200 でも 80 でも同じ 66 本だったので、**効いているのは
# 値ではなくブロックの存在そのもの**（右は 0 のままだった）。
#
# 行バスを一直線にしたいなら、この道ではなく **自分で引く**
# （prewire_switch_diode と同じやり方）。ROW4 は 0 ビア・片面で
# 通っているので経路は存在する。DIODE_OFFSET の注記にある
# 「行のバスを y=+3.65 に通せる」が本来の設計意図。

JAR = Path(os.environ.get(
    "FREEROUTING_JAR",
    Path.home() / ".local/share/freerouting/freerouting-2.3.0.jar"))


def _java():
    """java の実行ファイル。Homebrew の openjdk は PATH に無いことがある。

    **あることを確かめるだけでは足りない。**macOS には `/usr/bin/java` と
    いうスタブが必ず存在し、実行すると「Java をインストールせよ」と出して
    失敗する。存在検査だけだとこれを選び、配線が黙って失敗する（実際に
    そうなった。PATH に openjdk が無い環境で起きる）。
    **`-version` が通ることまで確かめる。**
    """
    tried = []
    for cand in (shutil.which("java"),
                 "/opt/homebrew/opt/openjdk/bin/java",
                 "/usr/local/opt/openjdk/bin/java"):
        if not cand or not Path(cand).exists():
            continue
        tried.append(cand)
        try:
            r = subprocess.run([cand, "-version"], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            return cand
    raise SystemExit(
        "動く java が見つからない。brew install openjdk を実行すること。\n"
        f"  試したもの: {tried or 'なし'}\n"
        "  （/usr/bin/java は macOS のスタブで、存在しても動かない）")


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


# **2 層になったので、GND 専用層の予約は無くなった**（2026-08-12・指摘 2）。
#
# 4 層のときは In1.Cu を `(type power)` と宣言し直して、自動配線器に
# 「ここに信号を通すな」と全面予約していた。2 層では信号層と GND ベタ層が
# 同じ 2 枚を兼ねるので、**両方を予約したら配線する場所が無くなる。**
#
# したがって GND ベタは最初から配線を避けた歯抜けになる。分断された島を
# 繋ぎ直すのは gnd_fanout.stitch のスティッチングビアの仕事で、
# 繋がったかどうかは test_pcb が「GND の島が 1 つか」で見る。


# gen_pcb.py が自分で引いてしまうネット。**DSN から丸ごと外す。**
#
#   GND      両面のベタと gnd_fanout のビアで配り終えている
#   SW\d+_D  スイッチ → ダイオード。裏面の L 字 2 本で届く
#             （gen_pcb.prewire_switch_diode）
#   ROW\d+   行のバス。裏面の一直線で引く（gen_pcb.prewire_row_bus）。
#             **ダイオードの K 側は行ごとに y が完全に一致していて、
#             ライン上にスルーホールが無い**ので経路に迷いが無い。
#             自動配線器に任せると表裏を 5〜7 回行き来していた
#             （2026-08-14・利用者の指摘）。
#             ⚠️ 全部は外せない。**J_DB へ戻る 1 本だけは残す**——
#             コネクタは行のラインから外れた y にあり、直線では届かない。
PREWIRED = re.compile(r"GND|SW\d+_D")


# Freerouting に上乗せして要求するクリアランス（µm）。
#
# **Freerouting は要求ぎりぎりを狙い、丸めで下回ることがある。**
# 実測（2026-08-13）: 0.200mm を要求したのに 0.187〜0.198mm で引き、
# KiCad の DRC がクリアランス違反にすることがある。
#
# KiCad 側の判定は 0.2mm のまま動かさない（そちらを緩めたら意味が無い）。
# **自動配線器にだけ多めに言う。**
#
# 値は左右**共通**（利用者の要望。基板ごとに違う値を使う非対称は
# 避ける）で、両方の未配線が最小になる値を総当たりで探した
# （10〜30µm を刻んで、左右それぞれの未配線本数と DRC 違反を記録）。
# **15µm が両方を満たす。**マージンを上げすぎると、配線が入れる
# 隙間そのものが狭くなり未配線が増えるトレードオフがある
# （40µm で右の未配線が 2→3 に悪化した）。
#
# それでも Freerouting 自身が打つビア（層間移動用。こちらの
# クリアランス判定を通らない）が規則ぎりぎりに来ることがあり、
# その 1 本は残る（下の DSN_CLEARANCE_MARGIN_UM の説明を見る）。
DSN_CLEARANCE_MARGIN_UM = 15


def _ask_freerouting_for_a_little_more_clearance(dsn):
    """DSN のクリアランスだけ少し増やす。KiCad の設計規則は変えない。

    `(clearance N)` の N は µm（DSN の冒頭が `(unit um)`）。
    **`(type smd_smd)` の行は触らない**——あれは同じ部品の中の
    パッドどうしの許容で、増やすとファンアウトが通らなくなる。
    """
    t = dsn.read_text()
    n = [0]

    def bump(m):
        n[0] += 1
        return f"(clearance {int(m.group(1)) + DSN_CLEARANCE_MARGIN_UM})"

    t = re.sub(r"\(clearance (\d+)\)(?!\s*\(type)", bump, t)
    if not n[0]:
        raise SystemExit(
            "DSN にクリアランスの指定が見つからない。KiCad の書式が"
            "変わった可能性がある。**黙って進めない**"
            "（Freerouting が丸めで規則を下回る）")
    dsn.write_text(t)


def _strip_prewired(dsn):
    """自分で引いたネットを DSN から完全に消す。

    残すと Freerouting が「未配線だ」と思って引き直し、二重になる。

    **「ピンだけ消してネットは残す」ような中途半端なやり方はしない。**
    Freerouting が NullPointerException で落ちる（実測。ヘッドレスの
    つもりでも GUI が立ち上がって例外ダイアログが出る）。ネット定義・
    クラスの一覧・plane 宣言をまとめて消すこと。

    配線材は `(type protect)` に変える。ネットを持たない固定の障害物
    として渡すと Freerouting はそこを避けて配線する。
    **消してしまうと避けてくれず、上から配線されて短絡する。**
    """
    t = dsn.read_text()
    names = sorted({n for n in re.findall(r"\(net (\S+)", t) if PREWIRED.fullmatch(n)})
    for n in names:
        e = re.escape(n)
        t = re.sub(rf"\s*\(plane {e} \(polygon [\s\S]*?\)\)", "", t)
        t = re.sub(rf"\s*\(net {e}\s*\n\s*\(pins [^)]*\)\s*\n\s*\)", "", t)
        t = re.sub(rf"(\(class \S+ [^)]*?)\b{e}\b", r"\1", t)
        t = t.replace(f"(net {n})(type route)", "(type protect)")
    left = [n for n in re.findall(r"\(net (\S+)", t) if PREWIRED.fullmatch(n)]
    if left:
        raise SystemExit(
            f"{dsn.name}: 消しきれていないネットがある: {sorted(set(left))}\n"
            "DSN の書式が変わった可能性がある。残すと Freerouting が"
            "二重配線するか NPE で落ちる")
    dsn.write_text(t)


def _route_once(half, seed):
    """未配線の基板を 1 回配線して、その結果を返す。"""
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
    _strip_prewired(dsn)
    _ask_freerouting_for_a_little_more_clearance(dsn)

    # Freerouting のログは終わりに「N violations」と出すが、これは
    # protect にしたファンアウトどうしの接触を数えているだけ。
    # **本当の判定は KiCad の DRC**（tools/drc.py）。ここの数字で
    # 良否を決めないこと。
    subprocess.run(
        [_java(), "-jar", str(JAR), "-de", str(dsn), "-do", str(ses),
         "-mp", str(PASSES), "--gui.enabled=false"],
        check=True)
    if not ses.exists():
        raise SystemExit(f"{half}: Freerouting が SES を出さなかった")

    if not pcbnew.ImportSpecctraSES(board, str(ses)):
        raise SystemExit(f"{half}: SES の取り込みに失敗した")

    # **トラック幅を揃える。**
    #
    # Freerouting は同じ入力でも**たまに 0.12mm / 0.15mm の線を引く**
    # （2026-08-12 に左で 4 本出た。前回の配線では 1 本も無かった）。
    # 0.12mm は JLCPCB の最小 0.127mm を割るので DRC が赤になる。
    # **配線し直すたびに当たるかどうかが変わる**ので、ここで潰す。
    # 太くする向きなので、クリアランスは DRC で確認する。
    # **ネットごとに、そのクラスの幅まで引き上げる。**
    # 以前は既定幅（0.2mm）を下回るものだけ直していたが、
    # 電源をクラス分けしたので、V3V3 が 0.225mm で出てくることがある
    # （クラスは 0.3mm）。**細い方向のばらつきは全部ここで潰す。**
    from pcb_rules import TRACK_W
    _w = pcbnew.FromMM(TRACK_W)
    _fixed = 0
    for t in board.GetTracks():
        if t.GetClass() == "PCB_TRACK" and t.GetWidth() < _w:
            t.SetWidth(_w)
            _fixed += 1
    if _fixed:
        print(f"   {half}: 細いトラック {_fixed} 本を {TRACK_W}mm へ揃えた")

    # **電源をクラスの幅まで引き上げることはしない。**
    #
    # 一度やったら DRC のクリアランス違反が増えた（左 0→1・右 1→2）。
    # 調べると、Freerouting は**狭いところで自分から幅を絞っている**。
    # つまり利用者が求めた「太くできるところは太く、できないところは
    # しない」を、自動配線器が既にやっている。**後から一律に太らせるのは、
    # その正しい判断を壊す行為だった。**
    # 幅の分布は test_pcb が見る（大半がクラスの幅であること）。

    # **自分で引いた配線を立て直す。**
    #
    # ImportSpecctraSES は既存の配線を全部作り直すので、配置段階で
    # 引いたものが消える（実測: GND のビア 7 個 → 0 個）。どちらも
    # DSN から外してあり SES にも入っていないので、ここで復活させないと
    # 繋がらないまま残る。
    #
    # 位置はどちらも決定的に決まるので配線前と同じところに戻り、
    # Freerouting はそこを避けて配線済みなので衝突しない。
    prewire_switch_diode(board)
    # **行のバスも引き直す。**SES 取り込みで消えているので、
    # gen_pcb で引いたのと同じ直線をここで復活させる。
    # DSN では `(type protect)` の障害物として渡してあるので、
    # Freerouting はこれを避けて J_DB への 1 本だけを引いている。
    n_row = prewire_row_bus(board)
    print(f"   {half}: 行のバスを裏面の直線で {n_row} 区間")
    n_fan = gnd_fanout.place(board)

    # **順序が効く。狙って打つものを先に、埋め草を後に。**
    #
    # 最初は格子（stitch）を先に打っていたが、**配線の脇という一番
    # 効く場所が格子に先取りされ、フェンスが並ばなかった**
    # （2026-08-13。利用者が絵を見て「斜め線のところにビアが無い」と
    # 気づいた）。長い配線の脇は戻り電流の横断口なので、そちらが先。
    #
    # どちらも配線が終わってから打つ。配線を障害物として避けたいので、
    # 配線前に打つと置き場所を見誤る。
    n_fe, n_long = gnd_fanout.fence(board)
    n_st, n_skip = gnd_fanout.stitch(board)
    print(f"   {half}: GND ビア ファンアウト {n_fan} 個 / "
          f"長い経路 {n_long} 本の脇に {n_fe} 個 / "
          f"格子で埋めた {n_st} 個（置けなかった格子点 {n_skip}）")

    # **配線後に 1 本ずつ太らせる後処理は入れていない**（2026-08-12）。
    #
    # 指摘 8 は gen_pcb.POWER_CLASSES のクラス分けで達成している
    # （V3V3 = 0.3mm＝FFC の 0.30mm パッドに載る上限、他 = 0.6mm）。
    # そのうえで「開けたところだけさらに太く」する後処理も書いたが、
    # **自前の当たり判定が取りこぼし、DRC のクリアランス違反を
    # 3 回続けて出した。**得られるのは V3V3 が 15mA しか流さない区間で
    # 太くなることだけなので、割に合わないと判断して外した。
    # 実装も消した（使わないものを残さない）。

    # **離島になった GND を、ビアで本土へ繋ぎ戻す**（指摘 4・5）。
    #
    # 2 層では配線がベタを割るので、GND のどこにも触れない区画ができる。
    # そういう銅は電位が決まっておらず GND ではない。**消すのではなく
    # 繋ぐ**——反対面のベタを経由すれば戻せる。
    #
    # この中でゾーンの塗り直しまで済ませる（ビアを打つとベタの形が
    # 変わるので、繰り返して収束させる必要がある）。
    n_is, left = gnd_fanout.stitch_islands(board)
    print(f"   {half}: 離島に打ったビア {n_is} 個 / 繋げ切れなかった区画 {left}")

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
    board.BuildConnectivity()
    left_over = board.GetConnectivity().GetUnconnectedCount(False)
    rec = {
        "board": out.name,
        "unrouted": src.name,
        "unrouted_fingerprint": boardhash.fingerprint(src),
        "freerouting": JAR.name,
        "passes": PASSES,
        "attempt": seed,
        "unconnected": left_over,
    }
    (PCB / f"route_{half}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    return rec


# **引き直しても無駄。Freerouting は決定的。**
#
# 「実行のたびに結果が揺れるので、0 が出るまで引き直す」という仕組みを
# 書きかけたが、**仮定を検証したら間違いだった**（2026-08-13）。
# 同じ入力で 3 回引いて未配線は 3 回とも同じ本数。揺れて見えていたのは
# こちらがコードを変えていたからで、Freerouting のせいではない。
#
# パス数を増やしても解けない（100 → 300 → 800 で未配線は減らなかった）。
# **残るのは配置の問題**なので、そちらで解く。


def run(half):
    """未配線の基板を配線し、記録を残して返す。"""
    return _route_once(half, 1)


def main():
    for half in HALVES:
        rec = run(half)
        print(f"OK {half:5s} {rec['unrouted']} → {rec['board']}"
              f"  ({rec['freerouting']}, {rec['passes']} パス)")
    print("\n配線した。次: .venv/bin/python3 tools/drc.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
