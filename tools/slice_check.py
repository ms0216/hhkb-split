"""OrcaSlicer の CLI で実際にスライスし、印刷可能性を機械的に確認する。

自作の検査（inspect_mesh.py）は近似でしかない。最終的に形状を解釈するのは
スライサーなので、スライサー自身に通させるのが一番確実な物理検証になる。

確認するもの:
  - スライスがエラー無く完了するか（形状がスライサーに受理されるか）
  - 警告の有無（サポートが要る、薄すぎる、ベッドからはみ出す等）
  - 生成された G-code から推定所要時間と材料使用量

プロファイル（プリンタ／フィラメント／プロセス）はアプリのバンドル内から
実行時に探す。K1 Max / PLA / 0.2mm を優先して選ぶ。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
BUILD = ROOT / "build"
OUT = BUILD / "slice"

APP = Path("/Applications/OrcaSlicer.app")
BIN_CANDIDATES = [
    APP / "Contents/MacOS/OrcaSlicer",
    APP / "Contents/MacOS/orca-slicer",
]
PROFILES = APP / "Contents/Resources/profiles"

# プロファイル名の表記はバンドル内で揺れている（machine は "K1 Max"、
# process は "K1Max" と空白の有無が違う）。ヒントは実際の綴りに合わせる。
PRINTER_HINTS = ["K1 Max (0.4 nozzle)", "K1 Max", "K1"]
FILAMENT_HINTS = ["Creality Generic PLA @K1-all", "Generic PLA @K1", "Generic PLA"]
PROCESS_HINTS = ["0.20mm Standard @Creality K1Max (0.4 nozzle)",
                 "0.20mm Standard @Creality K1", "0.20mm Standard"]


def find_binary():
    for b in BIN_CANDIDATES:
        if b.exists():
            return b
    raise SystemExit(f"OrcaSlicer が見つからない。探した場所: {BIN_CANDIDATES}")


def pick(paths, hints, label):
    """ヒントに合うプロファイルを 1 つ選ぶ。優先順位はヒントの並び順。"""
    for hint in hints:
        for p in paths:
            if hint.lower() in p.stem.lower():
                return p
    if paths:
        print(f"   ! {label}: ヒントに合うものが無いので {paths[0].stem} を使う")
        return paths[0]
    raise SystemExit(f"{label} のプロファイルが見つからない")


def find_profiles(vendor="Creality"):
    base = PROFILES / vendor
    if not base.exists():
        raise SystemExit(f"{base} が無い。導入されている vendor: "
                         f"{[p.name for p in PROFILES.iterdir()][:10]}")
    machines = sorted((base / "machine").glob("*.json"))
    filaments = sorted((base / "filament").glob("*.json"))
    processes = sorted((base / "process").glob("*.json"))
    m = pick([p for p in machines if "K1" in p.stem], PRINTER_HINTS, "プリンタ") \
        if any("K1" in p.stem for p in machines) else pick(machines, PRINTER_HINTS, "プリンタ")
    f = pick(filaments, FILAMENT_HINTS, "フィラメント")
    pr = pick([p for p in processes if "K1" in p.stem] or processes,
              PROCESS_HINTS, "プロセス")
    return m, f, pr


def slice_one(binary, stl, machine, filament, process):
    # 出力名は入力名によらず plate_N.gcode になるので、部品ごとに別の
    # ディレクトリへ出す（同じ場所に出すと上書きされて区別できない）。
    outdir = OUT / stl.stem
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(binary),
        "--load-settings", f"{machine};{process}",
        "--load-filaments", str(filament),
        "--slice", "0",
        "--outputdir", str(outdir),
        str(stl),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    return r, outdir


def summarize_gcode(gcode):
    """G-code から所要時間と材料使用量を拾う。

    OrcaSlicer はサマリを**末尾**に書く。先頭だけ読んでいたため、
    大きい部品（3.9MB、14万行）で時間と材料が取れていなかった。
    先頭と末尾の両方を見る。
    """
    info = {}
    try:
        raw = gcode.read_bytes()
        head = raw[:200_000].decode(errors="replace")
        tail = raw[-300_000:].decode(errors="replace")
    except Exception:
        return info
    head = head + "\n" + tail
    for key, pat in [
        ("時間", r";\s*(?:model printing time|estimated printing time[^:=]*)\s*[:=]\s*([^\n;]+)"),
        ("材料", r";\s*filament used \[cm3\]\s*[:=]\s*([\d.]+)"),
        ("層数", r";\s*total layer number\s*[:=]\s*(\d+)"),
    ]:
        m = re.search(pat, head, re.IGNORECASE)
        if m:
            info[key] = m.group(1).strip()
    return info


def main(names=None):
    binary = find_binary()
    machine, filament, process = find_profiles()
    print(f"プリンタ     {machine.stem}")
    print(f"フィラメント {filament.stem}")
    print(f"プロセス     {process.stem}\n")

    stls = sorted(p for p in BUILD.glob("*.stl")
                  if not p.stem.startswith(("smoke", "dbg", "mut", "_")))

    # **古い STL を黙って「刷れます」と言わない。**
    #
    # ⚠️ 2026-08-12。底面の電池蓋を廃止したのに build/battery_lid_*.stl が
    # 残り、ここが拾って合格を出していた。**存在しない部品を刷らせる。**
    # 調査中に出した残骸（lid.stl / c.stl）も同じように拾っていた。
    # 生成器側でも片付けるようにしたが、ここでも**目に見える形で**出す。
    newest = max((q.stat().st_mtime for q in TOOLS.glob("*.py")
                  if not q.name.startswith("test_")), default=0.0)
    stale = [p for p in stls if p.stat().st_mtime < newest]
    if stale:
        print("⚠️ tools/*.py より古い STL がある（作り直すか、消すこと）:")
        for q in stale:
            print(f"     {q.name}")
        print()
    if names:
        stls = [p for p in stls if p.stem in names]

    failed = []
    for stl in stls:
        r, outdir = slice_one(binary, stl, machine, filament, process)
        out = (r.stdout or "") + (r.stderr or "")
        warns = sorted(set(
            line.strip() for line in out.splitlines()
            if re.search(r"warn|error|fail|cannot|invalid", line, re.I)
        ))
        gcodes = sorted(outdir.glob("*.gcode"))
        ok = r.returncode == 0 and gcodes
        mark = "OK " if ok else "NG "
        print(f"{mark}{stl.stem}")
        if gcodes:
            info = summarize_gcode(gcodes[-1])
            if info:
                unit = {"材料": "cm3"}
                print("      " + "  ".join(
                    f"{k} {v}{unit.get(k, '')}" for k, v in info.items()))
        for w in warns[:6]:
            print(f"      ! {w[:150]}")
        if not ok:
            failed.append(stl.stem)
            if not warns:
                print(f"      終了コード {r.returncode}")
                print(f"      {out.strip()[-400:]}")

    print(f"\n{len(stls) - len(failed)}/{len(stls)} 件がスライス成功")
    if failed:
        print("失敗: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
