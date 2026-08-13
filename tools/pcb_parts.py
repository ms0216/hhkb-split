"""基板の実装部品の占有空間を、KiCad の STEP から取り出して記録する。

open-gaps #29。組み立て検査の `pcb` は「板＋キー下のソケット」の粗い箱で、
**実装部品（ダイオード 61・595・FFC コネクタ…）は 1 つも入っていなかった。**
KiCad が実物の 3D を持っているので、そこから取り出して検査に足す。

**KiCad は実体の無い 3D モデルを警告なしに飛ばす**（#29 で確認済み。
宣言 9 種のうち Kailh ソケットとスタビライザの 3 種は実体が無い）。だから
「STEP から持ってきた」だけでは検証にならない。**何が入ったかを数えて
JSON に記録し、検査が外部の事実（キー数・回路）と突き合わせる。**

流れ:
  1. `kicad-cli pcb export step` → build123d で読む（このファイルの --write）
  2. 部品ごとの bbox を tools/pcb_parts.json に記録（コミットする）
  3. gen_assembly が JSON から箱を組み立てて検査に入れる
     （毎回 STEP を読むと KiCad の無い環境で検査が黙って消えるため、
      JSON を経由する。鮮度は test_assembly が kicad-cli のある環境で見張る）

座標系（実測で確認・2026-08-09）:
  KiCad の STEP は X=KiCad x / Y=−KiCad y / 部品面の裏側が z<0。
  本体基板は ORIGIN (150,100) が板の中心なので、plate 座標へは
  (X−150, Y+100)。z は**板の上面を 0** に合わせる（envelopes.pcb_envelope と
  同じ基準）。STEP の板厚は 1.51mm（誘電体のみ。公称 1.6 との差 0.09 は
  外層の銅とレジスト）なので、上面合わせにすると部品の座面が
  envelope の下面 −1.6 とほぼ一致する。
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "pcb_parts.json"
KICAD_CLI = os.environ.get(
    "KICAD_CLI", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")

# **pcbnew を持っている Python。**KiCad 同梱のものにしか入っていない。
# KICAD_CLI と同じく環境変数で差し替えられる。
#
# **固定パスのままだと、KiCad の無い環境で FileNotFoundError になる。**
# CI の checks ジョブ（KiCad を入れない）で実際にそうなっていて、
# skip ではなく赤が 7 件、2026-08-13 まで常駐していた。
# 場所が違う環境では KICAD_PYTHON で指す。
KICAD_PYTHON = os.environ.get(
    "KICAD_PYTHON",
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/"
    "Versions/3.9/bin/python3.9")

BOARDS = {
    "left": "pcb/hhkb_split_left.kicad_pcb",
    "right": "pcb/hhkb_split_right.kicad_pcb",
    "db": "pcb/hhkb_split_daughterboard.kicad_pcb",
}
ORIGIN = (150.0, 100.0)          # gen_pcb.ORIGIN（pcbnew が要るので直接読めない）


# kiswitch ライブラリの部品（ソケット・スタビ）。**基板を貫く**ので、
# 穴の無い板の占有空間と重ねると偽の干渉になる。組み立てでは専用の
# 保守的な箱（envelopes.socket_envelope / stab_reservation）が受け持ち、
# こちらは「数の確認」と「箱が保守側であることの突き合わせ」に使う。
KEYSWITCH_LABELS = {"kailh_socket", "kailh_socket_leg",
                    "stab_housing", "stab_insert", "stab_wire"}


# (長辺, 短辺) の見本。**完全一致で引かない。**回転した部品の bbox は
# ±0.1mm ほど揺れ、実際にソケット 27 個中 15 個が取りこぼされて
# ffc_conn に化けた。許容差 0.25mm で最も近い見本に寄せる。
_SHAPES = [
    ("diode_sod123", 3.8, 1.6),
    ("ic_tssop16", 6.4, 5.0),
    ("cap_1206", 3.2, 1.6),
    ("kailh_socket", 11.0, 6.0),
    ("kailh_socket_leg", 4.6, 2.0),
    ("stab_housing", 19.2, 6.8),
    ("stab_insert", 8.3, 4.4),
]


def _classify(sx, sy, sz):
    """bbox の寸法から部品の種類を推定する。数を数えるための札。"""
    a, b = sorted((round(sx, 2), round(sy, 2)), reverse=True)
    for label, ta, tb in _SHAPES:
        if abs(a - ta) <= 0.25 and abs(b - tb) <= 0.25:
            return label
    if abs(a - 2.0) <= 0.25 and abs(b - 1.2) <= 0.25:
        return "res_0805" if sz < 1.0 else "cap_0805"
    if a >= 20.0:                # スタビのワイヤ組立（2u 25.5 / 3u 39.7）
        return "stab_wire"
    if a >= 8.0:                 # FFC コネクタは 3 つの立体でできている
        return "ffc_conn"
    return f"unknown_{a}x{b}"


def _export_step(name, out):
    """kicad-cli で STEP を出す。**失敗したら kicad-cli の言い分を見せる。**

    以前は capture_output のまま check=True で投げていたので、CalledProcessError
    の一行しか残らなかった。CI が KiCad 9 で基板ファイル（KiCad 10 の書式）を
    読めずに終了コード 3 で落ちていたのに、**赤の理由が読めなかった。**

    --subst-models: .wrl 宣言を同名の .stp に置き換える。kiswitch の
    ソケット・スタビのモデルはこれが無いと STEP に出ない。
    """
    r = subprocess.run([KICAD_CLI, "pcb", "export", "step", "--force",
                        "--subst-models", "--output", str(out),
                        str(ROOT / BOARDS[name])], capture_output=True,
                       text=True)
    if r.returncode:
        raise RuntimeError(
            f"kicad-cli が {name} の STEP 出力に失敗した（終了コード "
            f"{r.returncode}）。**版が合っているか見ること**（基板ファイルは "
            f"KiCad 10 の書式）。\n"
            f"  cli: {KICAD_CLI}\n  stderr: {r.stderr.strip()}\n"
            f"  stdout: {r.stdout.strip()}")


def kicad_available():
    """kicad-cli が使えるか。**実形状を作れる環境かの判定はここに一本化。**"""
    return Path(KICAD_CLI).exists()


def kicad_python_available():
    """pcbnew を持つ Python があるか。**判定はここに一本化。**"""
    return Path(KICAD_PYTHON).exists()


def board_sha256(name):
    """基板ファイルのハッシュ。**KiCad が無くても計算できる。**"""
    import hashlib

    return hashlib.sha256((ROOT / BOARDS[name]).read_bytes()).hexdigest()


def extract(name):
    """kicad-cli で STEP を出し、板と部品の bbox を返す。"""
    from build123d import import_step

    with tempfile.TemporaryDirectory() as td:
        step = Path(td) / f"{name}.step"
        _export_step(name, step)
        solids = import_step(str(step)).solids()

    board = max(solids, key=lambda s: s.volume)
    bb = board.bounding_box()
    # 本体基板は plate 座標（板の中心が原点・上面 z=0）。
    # 子基板は基板ローカル座標（外形中心が原点・**下面** z=0。
    # 組み立てでは下面の高さ FLOOR+DB_BOSS_H が基準になるため）。
    dx, dy = -ORIGIN[0], ORIGIN[1]          # X−150, Y+100
    dz = -bb.max.Z if name != "db" else 0.0

    def box(s):
        b = s.bounding_box()
        return [round(b.min.X + dx, 3), round(b.min.Y + dy, 3),
                round(b.min.Z + dz, 3), round(b.max.X + dx, 3),
                round(b.max.Y + dy, 3), round(b.max.Z + dz, 3)]

    comps = []
    counts = {}
    for s in solids:
        if s is board:
            continue
        x0, y0, z0, x1, y1, z1 = box(s)
        # 子基板の板の上に居る立体は全部 XIAO のモデル（84 個の細かい
        # 部品でできている）。個別に分類すると USB シェルが ffc_conn に
        # 化けるなどラベルが汚れるので、まとめて 1 つの札にする。
        if name == "db" and z0 > 1.4:
            label = "xiao_asm"
        else:
            label = _classify(x1 - x0, y1 - y0, z1 - z0)
        counts[label] = counts.get(label, 0) + 1
        comps.append({"label": label, "bbox": [x0, y0, z0, x1, y1, z1]})

    return {
        "source": BOARDS[name],
        # **盤面のハッシュ。**記録が古いまま基板だけ変わると、検査は昔の
        # 部品を検査し続ける。KiCad の無い環境（CI）でも、ここを突き合わせる
        # だけで「古い記録を検査している」ことに気づける（drc.py と同じ型）。
        "board_sha256": board_sha256(name),
        "solids": len(solids),
        "board_bbox": box(board),
        "board_step_thickness": round(bb.size.Z, 2),
        "counts": counts,
        "components": comps,
    }


def real_compound(name):
    """STEP を出し直し、実形状（板＋全部品モデル）の Compound を返す。

    視覚確認用の STL 出力（export_assembly）と、基板上の実形状どうしの
    干渉検査（test_assembly）が使う。kicad-cli とモデルの入った環境が要る。
    """
    from build123d import import_step

    with tempfile.TemporaryDirectory() as td:
        step = Path(td) / f"{name}.step"
        _export_step(name, step)
        return import_step(str(step))


def load():
    return json.loads(DATA.read_text())


def third_party_model(stem):
    """kiswitch のモデル（.stp）の実在するパスを返す。無ければ None。

    フットプリントは `${KICAD6_3RD_PARTY}` を参照している。CI はその環境変数を
    立てるが、手元は KiCad が既定の場所（~/Documents/KiCad/<版>/3rdparty）に
    置くので、**両方を見る**。片方しか見ないと、どちらかで黙って飛ぶ。
    """
    rel = ("3dmodels/com_github_perigoso_keyswitch-kicad-library"
           f"/3d-library.3dshapes/{stem}.stp")
    roots = [Path(os.environ["KICAD6_3RD_PARTY"])] if os.environ.get(
        "KICAD6_3RD_PARTY") else []
    roots += sorted(Path.home().glob("Documents/KiCad/*/3rdparty"))
    for r in roots:
        if (r / rel).exists():
            return r / rel
    return None


def usb_receptacle():
    """**XIAO の USB-C メスの実寸**（子基板ローカル・z=0 が板の下面）。

    (x0, y0, z0, x1, y1, z1) を返す。板の奥端より外へ出ている唯一の立体で、
    子基板の奥端（y = +DB_D/2）より **さらに 3.05mm 外**まで出ている。

    **これを使わずに `XIAO_OVERHANG`（1.8mm）でメスの位置を導いていた。**
    1.8 は XIAO の**基板**の張り出しで、その先にコネクタがもう 1.25mm ある。
    そのせいで壁の穴（メスより 0.44mm 低い）にコネクタの頭が当たり、
    プラグは 1.25mm 深く挿さったことにされていた。**#28 と同じ形の間違い**を
    もう 1 段深いところで繰り返していた（2026-08-10 に実形状の検査で発覚）。
    """
    rec = load()["db"]
    y_edge = rec["board_bbox"][4]
    out = max(rec["components"], key=lambda c: c["bbox"][4])
    if out["bbox"][4] <= y_edge:
        raise ValueError(
            "子基板の奥端より外へ出ている立体が無い。XIAO の向きか"
            "配置が変わった可能性がある（この値はケースの穴を決める）")
    return tuple(out["bbox"])


def component_boxes(name):
    """部品の bbox を、**物理的に正しい高さに直して**返す。

    **ソケット・スタビ（KEYSWITCH_LABELS）は除く。**基板を貫く部品なので、
    穴の無い板の占有空間と必ず重なる。組み立てでは専用の箱が受け持つ。

    高さの直し方: KiCad の STEP が描く板は**誘電体だけで 1.51mm**、公称の
    1.6mm には外層の銅とレジストが含まれる。裏面の部品は STEP では
    −1.51 の面に載っているが、**実物は公称の下面（−1.6）に載る**ので、
    その差 0.09mm ぶん下げる。直さないと、裏面の部品が板の占有空間へ
    0.09mm 潜り込んで見える（許容値でごまかしていた 1.35mm^3 の正体）。

    **記録（json）そのものは STEP のありのままにしておく。**直すのはここ。
    """
    from envelopes import PCB_T

    rec = load()[name]
    step_t = rec["board_step_thickness"]
    drop = PCB_T - step_t                      # 0.09mm
    out = []
    for c in rec["components"]:
        if c["label"] in KEYSWITCH_LABELS:
            continue
        x0, y0, z0, x1, y1, z1 = c["bbox"]
        if z1 <= -step_t + 1e-6:               # 板の下面より下＝裏面の部品
            z0, z1 = z0 - drop, z1 - drop
        out.append((x0, y0, z0, x1, y1, z1))
    return out


def keyswitch_boxes(name, label):
    """kiswitch 由来の部品（label 指定）の bbox 一覧。突き合わせ検査用。"""
    return [tuple(c["bbox"]) for c in load()[name]["components"]
            if c["label"] == label]


def fuse_touching(boxes):
    """**重なる箱どうしをまとめて 1 つの製品にする。**

    ソケットは「本体＋端子 2 本」、FFC コネクタは 3 立体で 1 個。これらは
    別々の部品ではないので、重なっているのが当たり前。まとめずに検査へ
    渡すと、自分自身と衝突していると報告される。

    **逆に、重ならない箱は絶対にまとめない。**まとめた時点で、その中の
    重なりは融合して見えなくなる（隣り合うキーキャップの隙間が今日まで
    一度も検査されていなかったのは、これが原因）。
    """
    groups = []
    for b in boxes:
        hit = [g for g in groups
               if any(b[0] < o[3] and o[0] < b[3] and b[1] < o[4] and o[1] < b[4]
                      and b[2] < o[5] and o[2] < b[5] for o in g)]
        if hit:
            merged = [b]
            for g in hit:
                merged += g
                groups.remove(g)
            groups.append(merged)
        else:
            groups.append([b])
    return groups


GROUPS_DATA = Path(__file__).resolve().parent / "pcb_product_groups.json"


def _fingerprints(solids):
    """立体の並びを照合するための指紋（体積と重心）。

    記録した組分け（index の組）は、**立体の並び順が同じでないと嘘になる。**
    STEP の書き出しは環境で並びが変わりうるので、盤面のハッシュだけでは
    足りない。使う直前に指紋を突き合わせ、合わなければ記録を捨てて実測する。
    """
    out = []
    for s in solids:
        c = s.center()
        out.append([s.volume, c.X, c.Y, c.Z])
    return out


def _fingerprints_match(a, b, tol=0.05):
    # 完全一致で引かない。体積・重心は書き出しのたびに最下位桁が揺れる
    # （_classify の bbox が ±0.1mm 揺れたのと同じ型）。
    return len(a) == len(b) and all(
        abs(x - y) <= tol for fa, fb in zip(a, b) for x, y in zip(fa, fb))


def compute_product_groups(solids):
    """**実際に食い込んでいる立体どうしを 1 つの製品にまとめる。**

    - XIAO は 84 立体、ソケットは本体＋端子、FFC コネクタは 3 立体で 1 個。
      まとめないと「自分自身と衝突」と報告される。
      **重ならないものは絶対にまとめない**（まとめた瞬間に製品どうしの
      重なりが見えなくなる）。
    - **bbox ではなく、実際に交差しているかでまとめる。**bbox は大きい部品で
      破綻する（板の bbox は全部品を含む）。bbox は絞り込みにだけ使う。
    - **板そのものは対象から外す。**板は全部品と接するので、入れた瞬間に
      基板が丸ごと 1 個の塊になる。

    返り値: (板の index, [[index, ...], ...])。座標に依らない
    （立体を平行移動しても組分けは変わらない）ので、記録して使い回せる。
    """
    from verify import intersection_volume

    board_i = max(range(len(solids)), key=lambda i: solids[i].volume)
    rest = [i for i in range(len(solids)) if i != board_i]
    bbs = {i: solids[i].bounding_box() for i in rest}

    def _near(i, j):
        a, b = bbs[i], bbs[j]
        return (a.min.X < b.max.X and b.min.X < a.max.X
                and a.min.Y < b.max.Y and b.min.Y < a.max.Y
                and a.min.Z < b.max.Z and b.min.Z < a.max.Z)

    parent = {i: i for i in rest}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a_ in range(len(rest)):
        for b_ in range(a_ + 1, len(rest)):
            i, j = rest[a_], rest[b_]
            if find(i) == find(j) or not _near(i, j):
                continue
            if intersection_volume(solids[i], solids[j]) > 1e-6:
                parent[find(j)] = find(i)          # 実際に食い込む＝1 製品

    groups = {}
    for i in rest:
        groups.setdefault(find(i), []).append(i)
    return board_i, sorted(groups.values())


def product_groups(name, solids):
    """組分けを返す。**記録が現物と合えばそれを、合わなければ実測を。**

    組分けの実測は片側 139 秒かかり、**基板が変わらない限り結果は同じ**
    （open-gaps #31）。だから --write-groups で記録し、鮮度は
    盤面のハッシュと立体の指紋で守る。合わないときに黙って記録を使うと
    嘘の組分けになるので、必ず実測に落ちる（遅いが正しい）。
    """
    rec = (json.loads(GROUPS_DATA.read_text()).get(name)
           if GROUPS_DATA.exists() else None)
    if (rec and rec["board_sha256"] == board_sha256(name)
            and _fingerprints_match(rec["fingerprints"], _fingerprints(solids))):
        return rec["board_index"], rec["groups"]
    print(f"pcb_parts: {name} の組分けの記録が無いか現物と合わない。実測する"
          f"（`pcb_parts.py --write-groups` で記録し直せる）", file=sys.stderr)
    return compute_product_groups(solids)


def write_product_groups():
    data = {}
    for name in BOARDS:
        solids = real_compound(name).solids()
        board_i, groups = compute_product_groups(solids)
        data[name] = {
            "board_sha256": board_sha256(name),
            "board_index": board_i,
            "fingerprints": [[round(v, 3) for v in f]
                             for f in _fingerprints(solids)],
            "groups": groups,
        }
        print(f"{name}: 立体 {len(solids)} 個 → 製品 {len(groups)} 個")
    GROUPS_DATA.write_text(
        json.dumps(data, ensure_ascii=False) + "\n")
    print(f"→ {GROUPS_DATA}")


def build_envelope(name):
    """部品の占有空間を 1 つの Part にする（本体基板は plate 座標・上面 z=0）。"""
    from build123d import Align, Box, Compound, Location

    # **融合させない。**まとめると部品どうしの重なりが消える
    # （envelopes.key_stack_envelopes の注記と同じ理由）。
    from build123d import BuildPart, Locations

    parts = []
    for group in fuse_touching(component_boxes(name)):
        with BuildPart() as one:                 # 1 製品の中だけ融合させる
            for x0, y0, z0, x1, y1, z1 in group:
                with Locations(((x0 + x1) / 2, (y0 + y1) / 2, z0)):
                    Box(x1 - x0, y1 - y0, z1 - z0,
                        align=(Align.CENTER, Align.CENTER, Align.MIN))
        parts.append(one.part)
    return Compound(children=parts)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--write-groups"]:
        write_product_groups()
        return 0
    if argv != ["--write"]:
        print(__doc__.split("\n")[0])
        print("使い方: pcb_parts.py --write          （STEP を出し直して JSON を更新）")
        print("        pcb_parts.py --write-groups   （実形状の組分けを記録し直す。数分）")
        d = load() if DATA.exists() else {}
        for name, rec in d.items():
            print(f"  {name}: 立体 {rec['solids']} 個 {rec['counts']}")
        return 0
    data = {name: extract(name) for name in BOARDS}
    DATA.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    for name, rec in data.items():
        print(f"{name}: 立体 {rec['solids']} 個 {rec['counts']}")
    print(f"→ {DATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
