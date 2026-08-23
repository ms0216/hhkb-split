"""**確定した板を本番 `pcb/` へ出し、GND のビアを打つ。**

（2026-08-23・利用者「B で」）

`pcb/matrix_only/` は**配線が確定した板**（左右ともエラー 0・未配線 0）。
そこには GND のビアが**ファンアウトぶんしか無い**——縫いも格子も
打っていない（利用者「GND_STITCH は、シルクよりもさらに後」）。

**発注に使う `pcb/` は、それに GND のビアを足したもの。**打つ順序と
理由は `autoroute.py` の後半と同じ:

    1. fence          長い配線の脇（戻り電流の横断口。**いちばん効く場所**）
    2. ring           禁止域のふち（格子 6.5mm では落ちない幅 1mm の帯）
    3. stitch         格子で埋める
    4. stitch_islands 離島を本土へ繋ぎ戻す（ベタの塗り直しまで含む）

⚠️ **順序が効く。**格子を先に打つと、配線の脇という一番効く場所を
格子に先取りされてフェンスが並ばない（2026-08-13 に実際に起きた）。

⚠️ **Freerouting は通さない。**配線は全部確定済みで、自動配線に
渡すものが無い（利用者「matrix_only をそのまま持っていく」で OK）。

    "$KPY" tools/finalize_pcb.py            # 左右とも
    "$KPY" tools/finalize_pcb.py left       # 片側だけ
"""
import shutil
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import gnd_fanout                                            # noqa: E402
from gen_pcb import _sync_project_rules                      # noqa: E402

SRC = ROOT / "pcb" / "matrix_only"
OUT = ROOT / "pcb"


def finalize(half):
    src = SRC / f"hhkb_split_{half}.kicad_pcb"
    if not src.exists():
        print(f"   {half}: {src} が無い")
        return None
    dst = OUT / f"hhkb_split_{half}.kicad_pcb"

    # **プロジェクトも一緒に運ぶ。**DRC は隣の .kicad_pro から規則を
    # 読むので、板だけ置くと古い規則で判定される（2026-08-23 に踏んだ）。
    for ext in (".kicad_pro", ".kicad_prl"):
        s = src.with_suffix(ext)
        if s.exists():
            shutil.copy(s, dst.with_suffix(ext))

    board = pcbnew.LoadBoard(str(src))

    n_fe, n_long = gnd_fanout.fence(board)
    n_ring = gnd_fanout.ring(board)
    n_st, n_skip = gnd_fanout.stitch(board)
    print(f"   {half}: 長い経路 {n_long} 本の脇に {n_fe} 個 / "
          f"禁止域のふちに {n_ring} 個 / "
          f"格子で埋めた {n_st} 個（置けなかった格子点 {n_skip}）")

    n_is, left = gnd_fanout.stitch_islands(board)
    print(f"   {half}: 離島に打ったビア {n_is} 個 / 繋げ切れなかった区画 {left}")

    board.Save(str(dst))
    _sync_project_rules(dst)

    # **どの未配線基板から作ったかを残す**（`autoroute.py` と同じ形）。
    # `test_the_routing_was_made_from_the_current_placement` が
    # 「配置を変えたのに配線し直していない」を見るための記録。
    # ⚠️ **バイト列でなく指紋。**KiCad は保存のたびに UUID と並び順を
    # 変えるので、sha256 だと再生成しただけで落ちる（boardhash.py）。
    import json

    import boardhash
    board.BuildConnectivity()
    rec = {
        "board": dst.name,
        "unrouted": (ROOT / "pcb" / "unrouted" / f"hhkb_split_{half}.kicad_pcb").name,
        "unrouted_fingerprint": boardhash.fingerprint(
            ROOT / "pcb" / "unrouted" / f"hhkb_split_{half}.kicad_pcb"),
        "freerouting": None,          # **通していない**（配線は確定済み）
        "made_by": "finalize_pcb.py",
        "unconnected": board.GetConnectivity().GetUnconnectedCount(False),
    }
    (OUT / f"route_{half}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n")

    n_via = sum(1 for t in board.GetTracks() if t.GetClass() == "PCB_VIA")
    print(f"   {half}: → {dst}（ビア {n_via} 個 / 未配線 {rec['unconnected']}）")
    return dst


def main():
    halves = [a for a in sys.argv[1:] if a in ("left", "right")] or ["left", "right"]
    for half in halves:
        finalize(half)
    return 0


if __name__ == "__main__":
    sys.exit(main())
