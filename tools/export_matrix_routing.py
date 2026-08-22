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

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "pcb" / "matrix_only"
OUT = ROOT / "pcb" / "matrix_routing.json"


def dump(half):
    f = SRC / f"hhkb_split_{half}.kicad_pcb"
    if not f.exists():
        return None
    b = pcbnew.LoadBoard(str(f))
    tracks, vias = [], []
    for t in b.GetTracks():
        n = t.GetNetname()
        if n == "GND" or not n:
            continue
        if t.GetClass() == "PCB_VIA":
            vias.append({
                "net": n,
                "x": round(t.GetPosition().x / 1e6, 4),
                "y": round(t.GetPosition().y / 1e6, 4),
                "d": round(pcbnew.ToMM(t.GetWidth()), 4),
                "drill": round(pcbnew.ToMM(t.GetDrill()), 4),
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
    return {"tracks": tracks, "vias": vias}


def main():
    out = {}
    for half in ("left", "right"):
        d = dump(half)
        if d is None:
            print(f"   {half}: pcb/matrix_only/ に板が無い — 飛ばす")
            continue
        out[half] = d
        print(f"   {half}: 配線 {len(d['tracks'])} / ビア {len(d['vias'])}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(f"書き出した: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
