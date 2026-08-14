"""基板の DRC を走らせ、結果を**基板のハッシュつきで**記録する。

DRC は kicad-cli が要るので CI（Ubuntu ランナー）では走らせられない。
そこで「手元で走らせた結果」を記録に残し、**その記録が現在の基板から
作られたものかどうか**を CI で検査する。

こうしないと「基板を直したが DRC をかけ直していない」状態のまま
発注してしまう。実際、DRC は私が手で叩いたときしか走っていなかった。

    python3 tools/drc.py        # 走らせて pcb/drc_*.json を更新する
    pytest tools/test_pcb.py    # 記録が最新かどうかを検査する
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "pcb"
# **場所の定義は pcb_parts に一本化**（KICAD_CLI で差し替え可能）。
sys.path.insert(0, str(ROOT / "tools"))
from pcb_parts import KICAD_CLI                                  # noqa: E402
HALVES = ("left", "right", "daughterboard")


def board_path(half):
    return PCB / f"hhkb_split_{half}.kicad_pcb"


def report_path(half):
    return PCB / f"drc_{half}.json"


def board_hash(half):
    return hashlib.sha256(board_path(half).read_bytes()).hexdigest()


def run(half):
    """DRC を走らせ、違反数・未配線数と基板のハッシュを記録して返す。

    ⚠️ **`--severity-error` を渡さない**（2026-08-14・利用者の指示
    「今後警告を隠さないようにしてほしい。警告は『危ない』ということなので」）。

    渡していた間、この道具は「違反 0」と報告し続けながら、実際には
    **右 48 件・子基板 24 件の警告を構造的に見えなくしていた。**
    嘘ではないが、読む人は「問題 0」と受け取る。中には
    `gnd_fanout` が打った GND ビアがスイッチの穴に 0.479mm まで
    寄っている実害（`hole_to_hole`）も混ざっていた。
    **`hole_to_hole` は KiCad の既定が `warning` なので、
    エラーだけ見ている限り永久に表に出てこない。**

    **それでも警告を `violations` に足さない。**足すと、スイッチ内部の
    NPTH どうし（MX フットプリントが持つ固定の穴間隔・34 件）で
    **永久に赤になる。**部品の寸法そのものなので直しようがなく、
    直せない赤は新しい赤を隠す。だから**別の数として数え、必ず出す。**
    合否はエラーだけで決め、警告は種類ごとに全部見せる。
    """
    out = PCB / f"_drc_raw_{half}.json"
    subprocess.run(
        [KICAD_CLI, "pcb", "drc", "--format", "json",
         "-o", str(out), str(board_path(half))],
        check=True, capture_output=True)
    raw = json.loads(out.read_text())
    out.unlink()

    def split(items):
        """(エラー, 警告) に分ける。**重大度が無いものはエラー扱い。**
        分からないものを軽い方へ倒すと、見えなくなる。"""
        err = [v for v in items if v.get("severity") != "warning"]
        warn = [v for v in items if v.get("severity") == "warning"]
        return err, warn

    v_err, v_warn = split(raw.get("violations", []))
    u_err, u_warn = split(raw.get("unconnected_items", []))
    warns = v_warn + u_warn
    kinds = {}
    for w in warns:
        kinds[w.get("type", "?")] = kinds.get(w.get("type", "?"), 0) + 1
    record = {
        "board": board_path(half).name,
        "sha256": board_hash(half),
        "violations": len(v_err),
        "unconnected": len(u_err),
        # **警告も残す。**合否には使わないが、記録から消さない。
        "warnings": len(warns),
        "warning_kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        "details": [v.get("description", "") for v in v_err][:20],
    }
    report_path(half).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


def main():
    bad = 0
    for half in HALVES:
        r = run(half)
        mark = "OK" if r["violations"] == 0 and r["unconnected"] == 0 else "NG"
        bad += r["violations"] + r["unconnected"]
        # **警告の数を必ず出す。**0 のときも「警告 0」と書く。
        # 書かないと、読む人は「警告を見た上で 0 だった」のか
        # 「そもそも見ていない」のかを区別できない。
        print(f"{mark} {half:5s} 違反 {r['violations']} / 未配線 {r['unconnected']}"
              f" / 警告 {r['warnings']}  sha256 {r['sha256'][:12]}")
        for d in r["details"]:
            print(f"      {d}")
        for kind, n in r["warning_kinds"].items():
            print(f"      ⚠ {kind} {n} 件")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
