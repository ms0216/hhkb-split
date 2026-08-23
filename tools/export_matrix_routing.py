"""**利用者が KiCad で引いた配線を、再現できる形で書き出す。**

（2026-08-22・利用者「**今の** matrix_only からスクリプト化すれば？」）

`pcb/matrix_only/` は利用者が直接編集する板。そこに引かれた配線を
そのままデータとして落とし、`gen_pcb` が生成した板へ載せ直せるように
する。**規則として書き下すのではなく、現物を写す。**

⚠️ **規則を推測して書き直そうとして 3 回失敗している**（着地で U1 の
他のパッドを横切る／レーンを縦に伸ばして交差する／跨がない行に橋を
架ける）。**利用者が引いた座標そのものが仕様。**

    "$KPY" tools/export_matrix_routing.py          # 書き出す
    "$KPY" tools/gen_pcb.py                        # 生成側へ載る

**GND は書き出さない。**ベタとファンアウトで別に配り直すため
（ここに入れると古い塗りが固定されてしまう）。
"""
import json
import re
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pcb_rules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "pcb" / "matrix_only"
OUT = ROOT / "pcb" / "matrix_routing.json"


# 手で引いたときに出る「ごく短い残骸」。KiCad のスナップと引き直しで
# 生まれる 5〜50µm の区間で、**両端が同じものに触れている**（実測で
# 左 12 本・右 11 本を確認）。電気的な意味は無く、絵を汚し、
# `hole_to_hole` や `dangling` の誤検出の元になる。
TINY_MM = 0.05

# 名札を**生成側の規則が決める**部品。ここは写さない。
AUTO_LABEL = re.compile(r"(SW|D|ST|H)\d+$")

def _drop_tiny(tracks):
    """**ごく短い残骸を落とす。**両端が繋がっているものだけ。"""
    import math
    keep, dropped = [], []
    ends = []
    for t in tracks:
        ends.append((t["net"], t["x1"], t["y1"]))
        ends.append((t["net"], t["x2"], t["y2"]))
    for t in tracks:
        L = math.dist((t["x1"], t["y1"]), (t["x2"], t["y2"]))
        if 0 < L < TINY_MM:
            # 両端に、この区間以外の端点があるか
            def n_at(px, py):
                return sum(1 for (n, x, y) in ends
                           if n == t["net"] and math.dist((x, y), (px, py)) < 0.06)
            # 自分の端点 2 つを差し引く
            if n_at(t["x1"], t["y1"]) >= 3 and n_at(t["x2"], t["y2"]) >= 3:
                dropped.append(t)
                continue
        keep.append(t)
    return keep, dropped


def _drop_useless_vias(tracks, vias):
    """**層をまたがないビアを落とす。**

    （2026-08-23・利用者の指示で `via_dangling` を調べた結果）

    ビアの意味は「表と裏をつなぐ」こと。**片面にしか線が無いビアは、
    立てても何も繋いでいない。**手で引くと必ず残る——レーンの左端で
    7 個（右・利用者が削除済み）、J_DB まわりで 8 個が実際に出た。

    害は 3 つ: **穴が 1 つ増える**（費用と `hole_to_hole` の元）、
    **ベタに穴を開けて離島を増やす**、**絵が汚れて読み違える**。

    ⚠️ **パッドに触れているビアは残す。**パッドは片面にしか無いので
    「線が片面だけ」になるが、そのビアは**パッドを反対面のベタや配線へ
    引き出している**（GND のファンアウトがまさにこれ）。
    """
    import math
    keep, dropped = [], []
    for v in vias:
        lays = set()
        for t in tracks:
            if t["net"] != v["net"]:
                continue
            # ⚠️ **端点だけ見てはいけない。**列の縦バスは着地ビアの
            # **途中を通過する**（実測 COL3 のバスは u=0.128 の位置で
            # 交わる）。端点だけで数えて、着地ビア 11 個を「層をまたが
            # ない」と誤判定した（2026-08-23）。**線分への距離で見る。**
            x1, y1, x2, y2 = t["x1"], t["y1"], t["x2"], t["y2"]
            dx, dy = x2 - x1, y2 - y1
            ll = dx * dx + dy * dy
            u = 0 if ll == 0 else max(0, min(1, ((v["x"] - x1) * dx
                                                 + (v["y"] - y1) * dy) / ll))
            if math.dist((x1 + u * dx, y1 + u * dy), (v["x"], v["y"])) < 0.06:
                lays.add(t["layer"])
        if len(lays) >= 2:
            keep.append(v)
        else:
            dropped.append(v)
    return keep, dropped


def _is_stub(t):
    """GND の短い引き出し線か。**ベタを縫う長い線と区別する。**"""
    import math
    return math.dist((t.GetStart().x / 1e6, t.GetStart().y / 1e6),
                     (t.GetEnd().x / 1e6, t.GetEnd().y / 1e6)) < 8.0


def dump(half):
    f = SRC / f"hhkb_split_{half}.kicad_pcb"
    if not f.exists():
        return None
    b = pcbnew.LoadBoard(str(f))
    tracks, vias, gnd_vias, gnd_stubs, fixed = [], [], [], [], []
    labels = []
    for t in b.GetTracks():
        n = t.GetNetname()
        if not n:
            continue
        if n == "GND":
            # **GND のベタとスタブは写さない**が、**ビアの位置は写す**
            # （2026-08-23）。利用者「GND ビアの位置を変えています。
            # 3V3 の近くにあるのは危ないのかなと」。
            #
            # `gnd_fanout.place` はパッドの形から機械的に決めるので、
            # **利用者が手で寄せた位置は次の生成で消える。**実測すると
            # U1/U2 の GND ビアが V3V3 まで 0.302 / 0.312mm しかなく、
            # 利用者はそれを 1.26〜1.86mm へ離していた。
            #
            # ⚠️ **規則（「電源から N mm 離す」）にしようとして失敗した。**
            # 候補を弾くと、逆に V3V3 の**配線**側へ押し出され、
            # `_drop_gnd_vias_hitting` が 7 個中 4 個を落とした。
            # **パッドしか見ない探索に、配線の都合は表現できない。**
            # 現物の座標を写すのが正しい。
            #
            # **スタブの線も一緒に写す。**引き直そうとして層を取り違え、
            # F.Cu に引いて ROW_D / ROW_E と交差した（同日）。
            # 利用者の板では B.Cu で引かれている。**現物を写せば迷わない。**
            #
            # **ベタ（ZONE）は写さない。**塗りは生成側で塗り直す。
            if t.GetClass() == "PCB_VIA":
                gnd_vias.append({
                    "x": round(t.GetPosition().x / 1e6, 4),
                    "y": round(t.GetPosition().y / 1e6, 4),
                })
            elif _is_stub(t):
                gnd_stubs.append({
                    "layer": b.GetLayerName(t.GetLayer()),
                    "x1": round(t.GetStart().x / 1e6, 4),
                    "y1": round(t.GetStart().y / 1e6, 4),
                    "x2": round(t.GetEnd().x / 1e6, 4),
                    "y2": round(t.GetEnd().y / 1e6, 4),
                    "w": round(pcbnew.ToMM(t.GetWidth()), 4),
                })
            continue
        if t.GetClass() == "PCB_VIA":
            drill = round(pcbnew.ToMM(t.GetDrill()), 4)
            d = round(pcbnew.ToMM(t.GetWidth()), 4)
            # **アニュラーが規格に満たないビアは、外径を広げて写す**
            # （2026-08-23）。KiCad の既定ビアは φ0.5/穴 0.3 で
            # アニュラーが **0.100mm**。JLCPCB の下限は **0.130mm**
            # （pcb_rules.JLC["annular_ring"]）なので DRC が
            # `annular_width` を出す。**手で引くと必ずこれを踏む**
            # ——実測で左 10 個・右 1 個。
            #
            # **穴は変えない。**広げるのは外径だけなので、経路にも
            # 位置にも影響しない。**黙って直さず、何個直したか出す。**
            # ⚠️ **規格を満たす最小に留める。**一度 pcb_rules.VIA_D (0.6)
            # へ揃えたら、**広げたぶん隣の線に近づいて `clearance` が
            # 2 件出た**（左 ROW_B 0.194mm / ROW_D 0.150mm・要 0.200）。
            # 手で引いた場所は詰まっているので、太らせる余地が無い。
            need = round(drill + 2 * pcb_rules.JLC["annular_ring"], 4)
            if d < need:
                fixed.append((n, t.GetPosition().x / 1e6, t.GetPosition().y / 1e6, d, need))
                d = need
            vias.append({
                "net": n,
                "x": round(t.GetPosition().x / 1e6, 4),
                "y": round(t.GetPosition().y / 1e6, 4),
                "d": d,
                "drill": drill,
            })
        else:
            tracks.append({
                "net": n,
                "layer": b.GetLayerName(t.GetLayer()),
                "x1": round(t.GetStart().x / 1e6, 4),
                "y1": round(t.GetStart().y / 1e6, 4),
                "x2": round(t.GetEnd().x / 1e6, 4),
                "y2": round(t.GetEnd().y / 1e6, 4),
                "w": round(pcbnew.ToMM(t.GetWidth()), 4),
            })
    tracks, tiny = _drop_tiny(tracks)
    vias, useless = _drop_useless_vias(tracks, vias)
    if useless:
        print(f"   {half}: 層をまたがないビアを {len(useless)} 個 落とした")
        for v in useless:
            print(f"       {v['net']:9s} ({v['x']:8.3f},{v['y']:7.3f})")
    if tiny:
        print(f"   {half}: ごく短い残骸を {len(tiny)} 本 落とした"
              f"（両端が繋がっているものだけ）")
    # **名札（シルク）の位置も写す**（2026-08-23）。
    #
    # 利用者「左右ともにシルクの位置を修正しました」。IC とコネクタの
    # 名札を、部品の輪郭や配線から外へ逃がしてある（右で silk の警告が
    # 20 → 4 件に減った）。**フットプリントの既定位置は生成のたびに
    # 戻る**ので、写さないと次の生成で消える。
    #
    # ⚠️ **既定と違うものだけ写す。**全部書くと、フットプリントを
    # 差し替えたときに古い位置で上書きしてしまう。
    # **電子部品の名札の位置を写す**（2026-08-23・利用者「左右ともに
    # シルクの位置を修正しました」）。IC とコネクタの名札を、部品の
    # 輪郭や配線から外へ逃がしてある（右で silk の警告が 20 → 4 件）。
    # **フットプリントの既定位置は生成のたびに戻る**ので、写さないと消える。
    #
    # ⚠️ **「生成物と違うものだけ」にして壊した**（同日）。基準が
    # `pcb/unrouted/` だと、**一度反映した瞬間に差が消えて記録が空になる。**
    # 次の書き出しで利用者の修正が失われる。**基準を動くものに置かない。**
    #
    # → **電子部品（キー・ダイオード・スタビ・取付穴を除く全部）は
    # 無条件に記録する。**数は左 5・右 6 程度で、揺れない。
    # キーの名札は `_place_hole_label` など生成側の規則が決めるので触らない。
    for f in b.GetFootprints():
        if AUTO_LABEL.match(f.GetReference()):
            continue
        t = f.Reference()
        labels.append({
            "ref": f.GetReference(),
            "dx": round(t.GetPosition().x / 1e6 - f.GetPosition().x / 1e6, 4),
            "dy": round(t.GetPosition().y / 1e6 - f.GetPosition().y / 1e6, 4),
        })
    if fixed:
        print(f"   {half}: アニュラーが足りないビアを {len(fixed)} 個 広げた"
              f"（穴はそのまま）")
        for n, x, y, was, now in fixed:
            print(f"       {n:8s} ({x:8.3f},{y:7.3f})  φ{was} → φ{now}")
    return {"tracks": tracks, "vias": vias,
            "gnd_vias": gnd_vias, "gnd_stubs": gnd_stubs, "labels": labels}


def main():
    out = {}
    for half in ("left", "right"):
        d = dump(half)
        if d is None:
            print(f"   {half}: pcb/matrix_only/ に板が無い — 飛ばす")
            continue
        out[half] = d
        print(f"   {half}: 配線 {len(d['tracks'])} / ビア {len(d['vias'])}"
              f" / GND ビア {len(d['gnd_vias'])} + スタブ {len(d['gnd_stubs'])}"
              f" / 名札 {len(d['labels'])}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(f"書き出した: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
