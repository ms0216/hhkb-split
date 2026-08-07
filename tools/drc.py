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
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
HALVES = ("left", "right")


def board_path(half):
    return PCB / f"hhkb_split_{half}.kicad_pcb"


def report_path(half):
    return PCB / f"drc_{half}.json"


def board_hash(half):
    return hashlib.sha256(board_path(half).read_bytes()).hexdigest()


def run(half):
    """DRC を走らせ、違反数・未配線数と基板のハッシュを記録して返す。"""
    out = PCB / f"_drc_raw_{half}.json"
    subprocess.run(
        [KICAD_CLI, "pcb", "drc", "--severity-error", "--format", "json",
         "-o", str(out), str(board_path(half))],
        check=True, capture_output=True)
    raw = json.loads(out.read_text())
    out.unlink()
    record = {
        "board": board_path(half).name,
        "sha256": board_hash(half),
        "violations": len(raw.get("violations", [])),
        "unconnected": len(raw.get("unconnected_items", [])),
        "details": [v.get("description", "") for v in raw.get("violations", [])][:20],
    }
    report_path(half).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


def main():
    bad = 0
    for half in HALVES:
        r = run(half)
        mark = "OK" if r["violations"] == 0 and r["unconnected"] == 0 else "NG"
        bad += r["violations"] + r["unconnected"]
        print(f"{mark} {half:5s} 違反 {r['violations']} / 未配線 {r['unconnected']}"
              f"  sha256 {r['sha256'][:12]}")
        for d in r["details"]:
            print(f"      {d}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
