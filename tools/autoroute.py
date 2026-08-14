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
HALVES = ("left", "right")             # マトリクスを持つ基板
# **配線する基板は 3 枚。**子基板は 2026-08-14 に手配線をやめて
# ここへ来た（open-gaps #41）。部品が 9 個に増えて、衝突判定を持たない
# 手書きルータでは DRC が収束しなくなったため。
BOARDS = HALVES + ("daughterboard",)
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
#   V3V3     子基板で自分で引く（gen_daughterboard._prewire_power）。
#             4 つのパッドがほぼ一直線なのに Freerouting が 8.37mm・
#             6 セグメントで蛇行し、GND のスタブと交差した（2026-08-14）。
#             ⚠️ **主基板の V3V3 も対象になる。**あちらは FFC から各所へ
#             配るだけで prewire していないが、DSN から消えると未配線に
#             なるので、**子基板だけ**に効かせる（下の PREWIRED_DB）。
PREWIRED = re.compile(r"GND|SW\d+_D")
# 子基板だけ、これも自分で引いてある。
#
# ⚠️ **レーンを通る ROW を入れるのが対**（2026-08-14・利用者「D3〜D5 を XIAO
# パッドの外側を通るようにできませんか」）。`gen_daughterboard._prewire_rows`
# が列の外の帯に 3 本引くので、**ここに足さないと DSN に「未配線」として
# 残り、Freerouting が同じネットをもう一度引いて自分自身と交差する。**
# 2026-08-14 に手配線をやめた原因がまさにこれで、当時 ROW は
# protect にならないまま引かれていた（交差 5 件のうち 3 件が自己交差）。
# ⚠️ **SPARE も入れる**（2026-08-14・利用者）。D1 は用途未定だが
# FFC 12 番まで**列の外の帯を自分で引いてある**ので、ROW と同じ扱い。
# ⚠️ **右列を自分で引いたら、その 5 本も入れる**（2026-08-14）。
# SPI_MOSI / SPI_SCK / CS / SPARE2。入れないと Freerouting が二重に引く。
PREWIRED_DB = re.compile(
    r"GND|SW\d+_D|V3V3|ROW[01234]|SPARE2?|SPI_MOSI|SPI_SCK|CS")


# Freerouting に上乗せして要求するクリアランス（µm）。
#
# **Freerouting は要求ぎりぎりを狙い、丸めで下回ることがある。**
# 実測（2026-08-13）: 0.200mm を要求したのに 0.187〜0.198mm で引き、
# KiCad の DRC がクリアランス違反にすることがある。
#
# KiCad 側の判定は 0.2mm のまま動かさない（そちらを緩めたら意味が無い）。
# **自動配線器にだけ多めに言う。**
#
# 値は左右**共通**（利用者の要望。基板ごとに違う値を使う非対称は避ける）。
# マージンを上げすぎると、配線が入れる隙間そのものが狭くなり未配線が
# 増えるトレードオフがある（40µm で右の未配線が 2→3 に悪化した）。
#
# **2026-08-14 に 15 → 20 へ上げた。**この日の変更（電源鎖の移動・
# 行バスの直線化・VBATT_RAW 廃止・V3V3 の 0.3→0.2mm）のあと、
# 15 では丸め不足が顕在化して DRC のクリアランス違反が出た
# （左 1 件・右 3 件。実測 0.1917〜0.1919mm ＜ 規則 0.2000mm）。
#
#     15µm … 違反 左1/右3、未配線 左0/右1
#     20µm … **違反 0/0/0、未配線 左2/右0**  ← いまここ
#     25µm … 違反 0/0/0、未配線 左2/右1
#
# 左に残る 2 本は ROW3/ROW4 が J_DB へ降りる枝（マージンとは別の話。
# J_DB の ROW パッドの並びが行バスの y 順と食い違っていて交差する）。
DSN_CLEARANCE_MARGIN_UM = 20


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


def _strip_prewired(dsn, pattern=PREWIRED):
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
    names = sorted({n for n in re.findall(r"\(net (\S+)", t) if pattern.fullmatch(n)})
    for n in names:
        e = re.escape(n)
        t = re.sub(rf"\s*\(plane {e} \(polygon [\s\S]*?\)\)", "", t)
        t = re.sub(rf"\s*\(net {e}\s*\n\s*\(pins [^)]*\)\s*\n\s*\)", "", t)
        t = re.sub(rf"(\(class \S+ [^)]*?)\b{e}\b", r"\1", t)
        t = t.replace(f"(net {n})(type route)", "(type protect)")
    left = [n for n in re.findall(r"\(net (\S+)", t) if pattern.fullmatch(n)]
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
    _strip_prewired(dsn, PREWIRED_DB if half not in HALVES else PREWIRED)
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
    # **マトリクスがある基板だけ。**子基板にはスイッチも行も無い。
    if half in HALVES:
        prewire_switch_diode(board)
        # **行のバスも引き直す。**SES 取り込みで消えているので、
        # gen_pcb で引いたのと同じ直線をここで復活させる。
        # DSN では `(type protect)` の障害物として渡してあるので、
        # Freerouting はこれを避けて J_DB への 1 本だけを引いている。
        n_row = prewire_row_bus(board)
        print(f"   {half}: 行のバスを裏面の直線で {n_row} 区間")
    else:
        # **電源も引き直す。**上の行バスと同じ理由——**SES 取り込みは
        # 既存の配線を全部置き換える**ので、gen_daughterboard で引いた
        # V3V3 と GND の引き出しは消えている（実測: unrouted に V3V3 6・
        # GND 7 本あったものが、取り込み後は V3V3 0・GND 4 になっていた。
        # 2026-08-14）。DSN では protect の障害物として渡してあるので、
        # Freerouting はここを避けて残りを引いている。
        from gen_daughterboard import _prewire_power, _prewire_rows
        _prewire_power(board)
        # **列の外のレーン 3 本も立て直す**（2026-08-14）。
        # 上と同じ理由——SES 取り込みが既存の配線を全部作り直すので、
        # gen_daughterboard で引いた 12 区間が消える（実測: 立て直しを
        # 入れる前は 3 本とも「Missing connection」になった）。
        _prewire_rows(board)
        # **右列も同じ**（2026-08-14）。SES 取り込みで消えるので立て直す。
        from gen_daughterboard import RIGHT_OUTER_LANE_PADS
        _prewire_rows(board, RIGHT_OUTER_LANE_PADS, side=+1)
        # **子基板は配線後にベタを敷く**（2026-08-14・open-gaps #41）。
        # 主基板は gen_pcb が配置段階で敷いてから配線するが、子基板は
        # 手配線をやめて Freerouting に移したので、主基板と同じ
        # 「配線 → ベタ → ビア」の順に揃える。
        _restore_rule_area_layers(board)
        _pour_daughterboard_ground(board)
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
    # **子基板も同じ仕組みで配線する**（2026-08-14・open-gaps #41）。
    # 手書きのルータをやめたので、3 枚とも Freerouting を通る。
    #
    # **直した基板だけを指定できる**（2026-08-14・利用者「DB だけの修正に
    # 左右も再配線する意味ある？」）。無い。Freerouting は毎回わずかに
    # 違う経路を出すので、**触っていない基板まで sha256 が変わり**、
    # drc_*.json の差分が汚れて「何を直したか」が読めなくなる。
    #
    #     "$KPY" tools/autoroute.py daughterboard
    targets = sys.argv[1:] or list(BOARDS)
    unknown = [t for t in targets if t not in BOARDS]
    if unknown:
        raise SystemExit(f"知らない基板: {unknown}／選べるもの: {list(BOARDS)}")
    for half in targets:
        rec = run(half)
        print(f"OK {half:5s} {rec['unrouted']} → {rec['board']}"
              f"  ({rec['freerouting']}, {rec['passes']} パス)")
    print("\n配線した。次: .venv/bin/python3 tools/drc.py")
    return 0


def _pour_daughterboard_ground(board):
    """**子基板の GND ベタを両面に敷く**（2026-08-14・open-gaps #41）。

    2026-08-14 まで裏面だけだった。主基板は最初から両面
    （`gen_pcb.GND_POUR_LAYERS`）なのに、**2.4GHz のアンテナが載って
    いるこの基板だけ片面**という非対称だった（利用者の指摘
    「MAIN PCB に施していて DB に施していないものがある」）。
    基準電位の安定はここでこそ効く。

    アンテナの真下は `gen_daughterboard._antenna_keepout` が両面とも
    抜いてある（禁止域は配置の段階で入っていて、DSN にも乗る）。
    """
    from gen_daughterboard import DB_D, DB_W
    from gen_pcb import ORIGIN
    gnd = board.FindNet("GND")
    if gnd is None:
        raise SystemExit("子基板に GND が無い")
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        zone = pcbnew.ZONE(board)
        zone.SetNet(gnd)
        zone.SetLayer(layer)
        zone.SetLocalClearance(pcbnew.FromMM(0.25))
        # **サーマルリリーフを使わずベタ付けにする。**GND は放熱より
        # 接続の確実さと低インピーダンスを優先する。リリーフのままだと
        # FFC の GND パッドでスポークが 1 本しか取れず、DRC が
        # 「接続が不完全」と出た。
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        pts = pcbnew.VECTOR_VECTOR2I()
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pts.append(pcbnew.VECTOR2I_MM(ORIGIN[0] + dx * DB_W / 2,
                                          ORIGIN[1] + dy * DB_D / 2))
        zone.AddPolygon(pts)
        board.Add(zone)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


def _restore_rule_area_layers(board):
    """**SES 取り込みで消えたルール領域の層を戻す**（2026-08-14・#41）。

    アンテナの禁止域は `gen_daughterboard` が F.Cu と B.Cu を指定して
    作るが、**DSN → Freerouting → SES を往復すると層が空になる**
    （`GetLayer()` が -1 になる。実測）。層を持たないゾーンは何も禁止
    しないので、**そのあとに敷いたベタがアンテナの真下に入り込む**
    （実測 3297 頂点。test_daughterboard が気づいた）。

    ⚠️ **「宣言したから効いている」と思わないこと。**この案件で
    3 回目の同じ型（#23 の禁止域・主基板の的外れな禁止域・これ）。
    """
    n = 0
    for zone in board.Zones():
        if not zone.GetIsRuleArea():
            continue
        ls = pcbnew.LSET()
        for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
            ls.addLayer(lay)
        zone.SetLayerSet(ls)
        n += 1
    if n:
        print(f"   ルール領域 {n} 個の層を戻した（SES 往復で消える）")


if __name__ == "__main__":
    sys.exit(main())
