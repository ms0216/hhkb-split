"""基板を絵にする。**変わっていなければ何もしない。**

「視覚的に確認したか」に「していません」と答え続けたのが発端（2026-08-16）。
道具（kicad-cli・pdftoppm）は前からあったが、**呼ぶかどうかが裁量だった**ので
呼ばれなかった。ここを裁量から外し、フックから毎回叩く。

**同じ設計を上書きしただけなら描かない。**判定は `boardhash.fingerprint`
（UUID と並び順を落とした設計の指紋）。保存のたびに変わるバイト列の sha256
では、毎回描き直してしまって用をなさない。

**全体図だけでは細部が読めない。**子基板は 499x774 px しかなく、
別セッションが D_PWR を動かしたとき「配線が読めないので測り直す」と
なった（2026-08-16）。そこで**動いた部品の周りを拡大した図も出す**。
どれが動いたかは指紋の材料（部品ごとの位置・向き・結線）を突き合わせて出す。

出力は build/pcb_view/<板の名前>.png と、拡大図 <板>__<部品>.png。
指紋は同じ場所の .fingerprint に置く（中身は部品ごとの表。前回との差を取る）。

  .venv/bin/python3 tools/render_pcb.py pcb/hhkb_split_left.kicad_pcb
  .venv/bin/python3 tools/render_pcb.py --all
  .venv/bin/python3 tools/render_pcb.py --zoom D_PWR pcb/...  # 指定して拡大
  .venv/bin/python3 tools/render_pcb.py --force pcb/...       # 指紋を無視する
"""

import argparse
import ast
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

import boardhash
from pcb_parts import KICAD_CLI

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "pcb_view"

# 全体図は表裏を 1 枚に重ねる。配線の取り回しと、部品の載り方が同時に見える。
LAYERS = "F.Cu,B.Cu,Edge.Cuts,F.Silkscreen"

# 拡大図は**その部品が載っている面だけ**を描く。
# 重ねると手前の面が塗り潰し、**見たい部品が消える**。実際にそうなった:
# この子基板は discrete が全部 B.Cu にいるのに F.Cu を上に描いていたので、
# BT1_- の拡大図が「緑の枠の中に何も無い」絵になった。
#
# **鏡像にはしない。**--mirror を付けると x が反転し（実測: bbox が
# 139.5-160.5 から 136.4-157.6 へ動く）、mm から画素への対応が壊れて
# 窓の位置がずれる。裏返さずに裏面を描けば座標はそのまま使える（実測で確認）。
# 「裏から見た向き」で確かめたいときは KiCad で開くこと。
SIDE_LAYERS = {"F": "F.Cu,Edge.Cuts,F.Silkscreen",
               "B": "B.Cu,Edge.Cuts,B.Silkscreen"}

# 600dpi。150 では基板が A4 の中に小さく載り、クロップ後 126px で読めなかった（実測）。
DPI = 600

# 拡大図の窓は**部品の実寸から**決める（中心から一律ではない）。
# 部品の縁からこれだけ余白を取る。繋がり先の配線が見える程度。
ZOOM_MARGIN_MM = 3.5
# 小さい部品でも最低これだけの窓にする。0402 が画面いっぱいに映っても
# 「どこへ繋がっているか」が分からず、拡大した意味が無い。
ZOOM_MIN_MM = 12.0

# 拡大図だけ解像度を上げる。600dpi のままだと 12mm 角が 283px にしかならず、
# 「D_PWR の周りが読めない」が解消しない（実測。283px は計算とも一致）。
# **紙は 1 回しか描かない。**全体図はここから縮めて作る（2 回描くと 2 倍遅い）。
ZOOM_DPI = 1800


def side_of(pcb: Path, ref: str) -> str:
    """`ref` のパッドが載っている面。"F" か "B"。

    両面にまたがる（スルーホール）ときは "F"。どちらから見ても写る。
    """
    txt = pcb.read_text()
    for _, blk in boardhash._blocks(txt):
        m = boardhash.REF.search(blk)
        if not m or m.group(1) != ref:
            continue
        layers = re.findall(r"\(layers ([^)]*)\)", blk)
        if any("*.Cu" in s for s in layers):
            return "F"
        if any("B.Cu" in s for s in layers) and \
           not any("F.Cu" in s for s in layers):
            return "B"
        return "F"
    return "F"


def _pdf(pcb: Path, td: Path, layers: str = None, tag: str = "board") -> Path:
    """基板を A4 の PDF に描く。

    **紙のまま扱うのが要点。** A4 は 297x210mm と決まっていて、KiCad は
    基板の mm 座標をそのまま紙に置く。だから「画素 = mm * dpi / 25.4」で
    場所が確定する（実測で確かめた: 外形 x 139.5-160.5 に対し
    ラスタの bbox が 139.45-160.57）。

    先に基板の形で切り詰めると、この対応が壊れる。**シルクの文字が外形より
    外にはみ出す**ので、切り詰めた絵の縁は外形と一致しない
    （実測: 上辺が 84.0mm ではなく 83.31mm。縦横比も 0.6447 vs 0.6562 と
    食い違う）。拡大図の位置がずれる原因になる。
    """
    pdf = td / f"{tag}.pdf"
    r = subprocess.run(
        [KICAD_CLI, "pcb", "export", "pdf", "--layers", layers or LAYERS,
         "-o", str(pdf), str(pcb)],
        capture_output=True, text=True)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"kicad-cli が PDF を出せなかった: {r.stderr.strip()}")
    return pdf


def _raster(pdf: Path, td: Path, dpi: int, tag: str, box_mm=None) -> Image.Image:
    """PDF を PNG にする。box_mm=(x0,y0,x1,y1) を渡すとその範囲だけ。

    **範囲を渡すときは pdftoppm 側で切る。**紙全体を高い解像度で起こしてから
    切り出すと、A4 1800dpi = 3 億画素になって PIL が
    DecompressionBombError で止まる（実際に踏んだ）。必要な窓だけ起こせば
    12mm 角で 850px、一瞬で終わる。
    """
    cmd = ["pdftoppm", "-png", "-r", str(dpi)]
    if box_mm is not None:
        k = dpi / 25.4
        x0, y0, x1, y1 = box_mm
        cmd += ["-x", str(max(0, int(x0 * k))), "-y", str(max(0, int(y0 * k))),
                "-W", str(max(1, int((x1 - x0) * k))),
                "-H", str(max(1, int((y1 - y0) * k)))]
    r = subprocess.run(cmd + [str(pdf), str(td / tag)], capture_output=True, text=True)
    pages = sorted(td.glob(f"{tag}-*.png"))
    if r.returncode != 0 or not pages:
        raise RuntimeError(f"pdftoppm が PNG を出せなかった: {r.stderr.strip()}")
    return Image.open(pages[0]).convert("RGB")


def _mark(im: Image.Image, box_mm, part_mm, ref: str, dpi: int) -> Image.Image:
    """拡大図の中で、どれがその部品かを枠と名前で示す。

    **囲まないと使えない。**シルクには全部の名前が載っているわけではなく
    （子基板で見えるのは USB と U_MCU だけ）、拡大しても「どれが BT1_- か」
    が分からない。絵が出ていることと、読めることは別
    （実際に「あんまり使えるものじゃない」と言われた）。
    """
    k = dpi / 25.4
    x0, y0 = box_mm[0], box_mm[1]
    px0 = (part_mm[0] - x0) * k
    py0 = (part_mm[1] - y0) * k
    px1 = (part_mm[2] - x0) * k
    py1 = (part_mm[3] - y0) * k

    d = ImageDraw.Draw(im)
    pad = max(2, int(0.25 * k))                   # 部品に被せず、少し外を囲む
    d.rectangle([px0 - pad, py0 - pad, px1 + pad, py1 + pad],
                outline=(0, 200, 0), width=max(3, int(0.12 * k)))

    # 名前は**絵の隅**に置く。枠のすぐ上に置くと、その下の配線を隠す
    # （BT1_- で実際に隠れた）。隅なら、囲みの意味は保ったまま何も潰さない。
    size = max(20, int(1.4 * k))
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", size)
    except OSError:
        font = ImageFont.load_default()
    tw = d.textlength(ref, font=font)
    m = max(4, int(0.3 * k))
    # 枠が上半分にいるなら下の隅、下半分にいるなら上の隅（枠と重ねない）
    ty = im.height - size - m if (py0 + py1) / 2 < im.height / 2 else m
    d.rectangle([m - 4, ty - 4, m + tw + 4, ty + size + 4], fill=(0, 160, 0))
    d.text((m, ty), ref, fill=(255, 255, 255), font=font)
    return im


def _crop_to_content(im: Image.Image) -> Image.Image:
    """紙の余白を落とす。左上の画素を紙の色とみなす。"""
    bg = Image.new("RGB", im.size, im.getpixel((0, 0)))
    box = ImageChops.difference(im, bg).getbbox()
    if box is None:
        raise RuntimeError("描いた絵が真っ白だった（基板が空か、レイヤー指定が外れている）")
    return im.crop(box)


def parts(pcb: Path) -> dict:
    """部品ごとの (位置・向き・結線)。指紋の材料そのものを表にして返す。"""
    rows, _ = ast.literal_eval(boardhash.canonical(pcb.read_text()))
    return {r[0]: {"at": [float(r[2]), float(r[3])], "rot": r[4],
                   "nets": sorted(n for _, n in r[5])}
            for r in rows}


def outline(pcb: Path) -> tuple:
    """基板の外形 (x0, y0, x1, y1) mm。"""
    _, edges = ast.literal_eval(boardhash.canonical(pcb.read_text()))
    xs, ys = [], []
    for e in edges:
        for pt in e[1:]:
            x, y = pt.split(",")
            xs.append(float(x))
            ys.append(float(y))
    if not xs:
        raise RuntimeError("外形（Edge.Cuts）が読めない")
    return min(xs), min(ys), max(xs), max(ys)


def extent(pcb: Path, ref: str) -> tuple:
    """`ref` のパッドが占める範囲 (x0, y0, x1, y1) mm。

    **中心の点だけでは窓を決められない。**中心から一律 6mm で切ると、
    基板の縁にいる部品では窓が外形をはみ出し、**絵の 3 分の 1 が紙の白**に
    なる（実際にそうなった: BT1_- は y 84.28-87.33 にいて、外形の上辺は
    y=84.0。中心 85.8 から 6mm 取ると y=79.8 まで行き、4mm 以上が板の外）。

    pcbnew の GetBoundingBox が使えれば早いが、**あれは KiCad の Python
    でしか動かない**。フックは venv から走るので、S 式から直に読む。
    """
    txt = pcb.read_text()
    for name, blk in boardhash._blocks(txt):
        m = boardhash.REF.search(blk)
        if not m or m.group(1) != ref:
            continue
        a = boardhash.AT.search(blk)
        if not a:
            break
        ox, oy = float(a.group(1)), float(a.group(2))
        rot = math.radians(float(a.group(3) or 0))
        xs, ys = [], []
        # パッドの位置は footprint 内の相対座標。footprint の回転で回す。
        for pm in re.finditer(r"\(pad \"[^\"]*\"[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)"
                              r"(?:\s+[-\d.]+)?\)\n\s*\(size ([-\d.]+) ([-\d.]+)\)",
                              blk):
            px, py = float(pm.group(1)), float(pm.group(2))
            sx, sy = float(pm.group(3)) / 2, float(pm.group(4)) / 2
            rx = px * math.cos(rot) - py * math.sin(rot)
            ry = px * math.sin(rot) + py * math.cos(rot)
            # size はパッド自身の向きに沿うが、ここは窓の目安なので
            # 大きい方を両側に取って安全側に倒す。
            s = max(sx, sy)
            xs += [ox + rx - s, ox + rx + s]
            ys += [oy + ry - s, oy + ry + s]
        if xs:
            return min(xs), min(ys), max(xs), max(ys)
        break
    raise RuntimeError(f"{ref} のパッドが読めない")


def window(pcb: Path, ref: str) -> tuple:
    """`ref` を必ず含み、基板の外にはみ出さない窓 (x0, y0, x1, y1) mm。"""
    bx0, by0, bx1, by1 = outline(pcb)
    px0, py0, px1, py1 = extent(pcb, ref)

    # 部品の実寸に余白を足す。小さい部品でも最低 ZOOM_MIN_MM は見せる
    # （SOT-23 だけ映っても、どこへ繋がっているか分からない）。
    w = max(px1 - px0 + 2 * ZOOM_MARGIN_MM, ZOOM_MIN_MM)
    h = max(py1 - py0 + 2 * ZOOM_MARGIN_MM, ZOOM_MIN_MM)
    w = h = max(w, h)                             # 正方形にして歪ませない
    cx, cy = (px0 + px1) / 2, (py0 + py1) / 2

    # 板からはみ出す分を押し戻す。板より窓が大きいときは板全体。
    if w >= bx1 - bx0:
        x0, x1 = bx0, bx1
    else:
        x0 = min(max(cx - w / 2, bx0), bx1 - w)
        x1 = x0 + w
    if h >= by1 - by0:
        y0, y1 = by0, by1
    else:
        y0 = min(max(cy - h / 2, by0), by1 - h)
        y1 = y0 + h
    return x0, y0, x1, y1


def moved(before: dict, after: dict) -> list:
    """動いた・向きが変わった・繋ぎ替わった・増えた／消えた部品の名前。"""
    return sorted(set(before) ^ set(after)
                  | {k for k in set(before) & set(after) if before[k] != after[k]})


def update(pcb: Path, force: bool = False, zoom: list = ()) -> tuple:
    """変わっていれば描き直す。(描いたか, 全体図, 拡大図の一覧) を返す。"""
    png = OUT / f"{pcb.stem}.png"
    stamp = OUT / f"{pcb.stem}.fingerprint"

    now = parts(pcb)
    fp = boardhash.fingerprint(pcb)
    was = None
    if stamp.exists():
        try:
            rec = json.loads(stamp.read_text())
            was = rec.get("parts")
            if not force and rec.get("fingerprint") == fp and png.exists():
                return False, png, []
        except (ValueError, AttributeError):
            pass                                  # 昔の書式。作り直す

    # 何を拡大するか。指定が無ければ「動いた部品」。
    # **前回の記録が無いときは拡大しない。**全部が「新しい」ことになり、
    # 部品の数だけ絵を出してしまう（子基板で 9 枚、本体で 30 枚以上）。
    targets = list(zoom) if zoom else (moved(was, now) if was is not None else [])

    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _crop_to_content(_raster(_pdf(pcb, td), td, DPI, "full")).save(png)

        # 面ごとの PDF は、要るものだけ 1 回ずつ作って使い回す。
        side_pdf = {}
        shots = []
        for i, ref in enumerate(targets):
            if ref not in now:
                continue                          # 消えた部品は拡大しようがない
            try:
                box = window(pcb, ref)
                part = extent(pcb, ref)
            except RuntimeError as e:
                print(f"  拡大できない {ref}: {e}")
                continue
            s = side_of(pcb, ref)
            if s not in side_pdf:
                side_pdf[s] = _pdf(pcb, td, SIDE_LAYERS[s], f"side{s}")
            dest = OUT / f"{pcb.stem}__{ref}.png"
            shot = _raster(side_pdf[s], td, ZOOM_DPI, f"z{i}", box)
            _mark(shot, box, part, ref, ZOOM_DPI).save(dest)
            shots.append(dest)

    stamp.write_text(json.dumps({"fingerprint": fp, "parts": now},
                                ensure_ascii=False, indent=1))
    return True, png, shots


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcb", nargs="*", type=Path)
    ap.add_argument("--all", action="store_true", help="pcb/*.kicad_pcb を全部")
    ap.add_argument("--force", action="store_true", help="指紋が同じでも描き直す")
    ap.add_argument("--zoom", action="append", default=[], metavar="REF",
                    help="この部品の周りを拡大する（既定は動いた部品）")
    a = ap.parse_args()

    targets = sorted((ROOT / "pcb").glob("*.kicad_pcb")) if a.all else a.pcb
    if not targets:
        ap.error("基板を指すか --all を付ける")

    rc = 0
    for pcb in targets:
        if not pcb.exists():
            print(f"NG {pcb} が無い")
            rc = 1
            continue
        try:
            drew, png, shots = update(pcb, a.force, a.zoom)
        except RuntimeError as e:
            print(f"NG {pcb.name}: {e}")
            rc = 1
            continue
        print(f"{'描いた  ' if drew else '変化なし'} {png.relative_to(ROOT)}")
        for s in shots:
            print(f"  拡大   {s.relative_to(ROOT)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
