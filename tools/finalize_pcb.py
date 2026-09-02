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

# --src unrouted: gen_pcb が記録（matrix_routing.json）から再現した板を
# 入力にする。**外形を変えたとき用**（#51 候補 3・2026-08-24）——
# matrix_only は利用者が直接編集する板なので、こちらからは上書きしない。
# 配線座標は同じ記録から来るので中身は等価（DRC が答え合わせ）。
if "--src" in sys.argv:
    i = sys.argv.index("--src")
    SRC = ROOT / "pcb" / sys.argv[i + 1]
    del sys.argv[i:i + 2]



# --------------------------------------------------------------------------
# オシロ／リード線用に銅を露出させる（open-gaps #49・2026-08-25）
#
# **部品も配線も足さない。**利用者の提案「適当な既存のビアにリード線を
# 半田付けできるようにすればいい」に沿って、既存の銅のレジストだけを
# 剥がす。テストパッド（実装なしのランド）を足す案は、パッドから既存
# ネットへのスタブが引けず取り消した（利用者「試行錯誤したが諦める」）。
#
# ネットごとに **他ネットの銅から最も離れた** 1 点を機械的に選ぶ:
#   - ビアがあれば、そのビアの**部品面（裏・B）のテンティングを外す**
#   - ビアが無ければ（左は SPI 系が全部 B.Cu だけ）、最も孤立した直線
#     区間の中央に **B.Mask の窓**（DEBUG_WINDOW_L × DEBUG_WINDOW_W）を開ける
# GND は群の重心に最も近い孤立した GND ビアを同様に露出する。
#
# 選定は本番の板から毎回決定的に計算する（写した配線が変われば追随）。
# ⚠️ **半田付けの現実**: 配線幅 0.2mm・隣の銅まで 0.65mm 前後の箇所も
# ある。細いリード線（AWG30 級）と先の細いこて前提。番号は下の表で
# 印字せず、finalize の出力と drc 記録で追う。
# --------------------------------------------------------------------------
from pcb_rules import (DEBUG_ACCESS_MM, DEBUG_MIN_CLEAR_MM,       # noqa: E402
                       DEBUG_NETS, DEBUG_WINDOW_L, DEBUG_WINDOW_W)


def _dist_pt_seg(px, py, x0, y0, x1, y1):
    import math
    dx, dy = x1 - x0, y1 - y0
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / l2))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def expose_debug_copper(board, half):
    """デバッグ用ネットの銅を 1 点ずつ露出する。露出した点の一覧を返す。"""
    import math
    mm = lambda v: v / 1e6
    vias = [(t, mm(t.GetPosition().x), mm(t.GetPosition().y), t.GetNetname())
            for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    segs = [(t, mm(t.GetStart().x), mm(t.GetStart().y), mm(t.GetEnd().x),
             mm(t.GetEnd().y), t.GetNetname())
            for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
    pads = [(mm(p.GetPosition().x), mm(p.GetPosition().y), p.GetNetname())
            for fp in board.GetFootprints() for p in fp.Pads()]

    # **部品の本体の下は候補にしない**（2026-08-25・利用者の指摘）。
    # 右の露出ビア 3 点が J_DB コネクタの真下にあり、実質半田付けできなかった。
    # コートヤードの矩形に DEBUG_ACCESS_MM の余裕を足した箱の中は除外。
    # 本体とみなす範囲:
    #   - 電子部品（ELEC_REF: J_DB / U* / C_U* / D_PWR …）… Fab 外形
    #   - キースイッチ（SW*）… **ソケット実物の外形だけ**（B.Fab 図形）。
    #     フットプリント全体（19mm 角）にすると板が丸ごと除外される（踏んだ）
    #   - ダイオード（D*）… Fab 外形
    import re
    from circuit import ELEC_REF
    bodies = []
    a = DEBUG_ACCESS_MM
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if not (re.fullmatch(r"SW\d+", ref) or ELEC_REF.fullmatch(ref) or re.fullmatch(r"D\d+", ref)):
            continue
        # 本体 = フットプリントの Fab 図形（実物の外形）。コートヤードや bands.SOCK_*
        # （ケース側の帯）は実物より大きく、届くビアを弾いた（2026-08-26 に 2 回）。
        # 端子パッドは本体に含めない——他ネットのパッドは clearance() が別に見る
        # スイッチは B.Fab（裏のソケット）だけ。F.Fab は表のスイッチ本体で裏の作業に無関係
        layers = ("B.Fab",) if re.fullmatch(r"SW\d+", ref) else ("B.Fab", "F.Fab")
        items = [d for d in fp.GraphicalItems() if d.GetLayerName() in layers]
        if not items:
            raise SystemExit(f"{ref}: Fab 層に外形が無い")
        bb = items[0].GetBoundingBox()
        for d in items[1:]:
            bb.Merge(d.GetBoundingBox())
        bodies.append((mm(bb.GetLeft()) - a, mm(bb.GetTop()) - a, mm(bb.GetRight()) + a, mm(bb.GetBottom()) + a))

    def under_a_part(x, y):
        return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in bodies)

    def body_gap(x, y):
        """最寄りの部品本体（余裕を含まない外形）までの距離。報告用。"""
        best = 99.0
        for x0, y0, x1, y1 in bodies:
            dx = max(x0 + a - x, 0.0, x - (x1 - a))
            dy = max(y0 + a - y, 0.0, y - (y1 - a))
            best = min(best, math.hypot(dx, dy))
        return best

    def clearance(x, y, net):
        if under_a_part(x, y):
            return -1.0          # 除外（負の孤立度）
        others = [math.hypot(x - a, y - b) for _, a, b, n in vias if n != net]
        others += [math.hypot(x - a, y - b) for a, b, n in pads if n != net]
        others += [_dist_pt_seg(x, y, a, b, c, d) for _, a, b, c, d, n in segs if n != net]
        return min(others) if others else 99.0

    exposed = []
    for net in DEBUG_NETS[half]:
        best = None
        for v, x, y, n in vias:
            if n != net:
                continue
            d = clearance(x, y, net)
            if best is None or d > best[0]:
                best = (d, "via", v, x, y)
        if best is not None and best[0] < 0:
            best = None          # ビアはあるが全部部品の下 → 配線の窓へ
        if best is None:
            for s, x0, y0, x1, y1, n in segs:
                if n != net or math.hypot(x1 - x0, y1 - y0) < DEBUG_WINDOW_L + 0.5:
                    continue
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                d = clearance(cx, cy, net)
                if best is None or d > best[0]:
                    best = (d, "window", s, cx, cy)
        if best is None or best[0] < DEBUG_MIN_CLEAR_MM:
            why = "部品の下しか無い" if (best is None or best[0] < 0) else \
                  f"隣の銅まで {best[0]:.2f}mm しか無い"
            print(f"   {half}: {net} を露出できる銅が無い（{why}）"
                  "——利用者がその配線の上に、部品から離れた所へビアを置けば選ばれる")
            continue
        exposed.append((net,) + best)

    # GND: 露出点群の重心に近く、かつ孤立した GND ビア
    if exposed:
        gx = sum(e[4] for e in exposed) / len(exposed)   # e = (net, d, kind, item, x, y)
        gy = sum(e[5] for e in exposed) / len(exposed)
        best = None
        for v, x, y, n in vias:
            if n != "GND" or math.hypot(x - gx, y - gy) > 15.0:
                continue
            d = clearance(x, y, "GND")
            if d < 0:
                continue
            score = d - 0.05 * math.hypot(x - gx, y - gy)
            if best is None or score > best[0]:
                best = (score, "via", v, x, y, d)
        if best is not None:
            exposed.append(("GND", best[5], "via", best[2], best[3], best[4]))

    for net, d, kind, item, x, y in exposed:
        if kind == "via":
            item.SetBackTentingMode(pcbnew.TENTING_MODE_NOT_TENTED)
        else:
            x0, y0 = mm(item.GetStart().x), mm(item.GetStart().y)
            x1, y1 = mm(item.GetEnd().x), mm(item.GetEnd().y)
            ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
            # **配線に沿って回した多角形**にする。rect は軸平行にしか
            # 保存されず（Rotate が効かない）、斜めの配線では窓が配線を
            # 横切るだけになる。
            ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            hl, hw = DEBUG_WINDOW_L / 2, DEBUG_WINDOW_W / 2
            corners = [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)]
            pts = pcbnew.VECTOR_VECTOR2I()
            for u, v in corners:
                pts.append(pcbnew.VECTOR2I_MM(x + u * ca - v * sa, y + u * sa + v * ca))
            win = pcbnew.PCB_SHAPE(board)
            win.SetShape(pcbnew.SHAPE_T_POLY)
            win.SetLayer(pcbnew.B_Mask)
            win.SetFilled(True)
            win.SetPolyPoints(pts)
            board.Add(win)
        print(f"   {half}: {net:9s} {'ビア' if kind == 'via' else '窓'} "
              f"({x:.2f},{y:.2f}) 他ネットまで {d:.2f}mm / 部品本体まで {body_gap(x, y):.2f}mm")
    return exposed

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

    expose_debug_copper(board, half)

    # **発注の道具（Fabrication Toolkit）が読むフィールドを焼き込む**
    # （2026-09-02・fab_fields.py）。無いと BOM の LCSC が空で、
    # ソケット 61 個が top で出る。
    import fab_fields
    fab_fields.stamp(board, half)

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
    # ⚠️ **板を出したら、板から作られる記録も古くなる。**
    #
    # `pcb_parts.json` と `pcb_product_groups.json` は本番の板から
    # STEP を出して作る。**ここを忘れると `test_the_recorded_*` が
    # 赤になる**（2026-08-23 に実際に踏んだ）。
    #
    # **この場で呼べない。**`pcb_parts.py` は build123d を使うので
    # `.venv` の Python が要り、この道具は KiCad の Python 3.9 で動く。
    # → **出力に書いて、人に起こさせる。**
    print()
    print("  ⚠️ **板から作られる記録も古くなった。**続けて次を実行すること:")
    print("       .venv/bin/python3 tools/pcb_parts.py --write")
    print("       .venv/bin/python3 tools/pcb_parts.py --write-groups   （数分）")
    print("       .venv/bin/python3 tools/drc.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
