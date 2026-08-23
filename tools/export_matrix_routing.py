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
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pcb_rules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "pcb" / "matrix_only"
OUT = ROOT / "pcb" / "matrix_routing.json"


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
    if fixed:
        print(f"   {half}: アニュラーが足りないビアを {len(fixed)} 個 広げた"
              f"（穴はそのまま）")
        for n, x, y, was, now in fixed:
            print(f"       {n:8s} ({x:8.3f},{y:7.3f})  φ{was} → φ{now}")
    return {"tracks": tracks, "vias": vias,
            "gnd_vias": gnd_vias, "gnd_stubs": gnd_stubs}


def main():
    out = {}
    for half in ("left", "right"):
        d = dump(half)
        if d is None:
            print(f"   {half}: pcb/matrix_only/ に板が無い — 飛ばす")
            continue
        out[half] = d
        print(f"   {half}: 配線 {len(d['tracks'])} / ビア {len(d['vias'])}"
              f" / GND ビア {len(d['gnd_vias'])} + スタブ {len(d['gnd_stubs'])}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(f"書き出した: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
