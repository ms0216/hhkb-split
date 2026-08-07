"""ZMK の設定を、ビルドに出す前にローカルで検査する。

実際のビルドは GitHub Actions 上で走るので手元では確認できないが、
**よくある失敗はファイルを読むだけで分かる**。往復 1 回あたり数分かかるので、
出す前に潰す。

検査する内容:
  - YAML が壊れていないか
  - build.yaml が参照するシールドが実在するか
  - Kconfig.shield の shields_list_contains 引数がディレクトリ名と一致するか
    （一致していないとビルド時に無言で無視される）
  - シールドに必要なファイルが揃っているか
  - ファイル名がシールド名と一致するか
  - west.yml の self.path が config になっているか
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FW = ROOT / "firmware"
SHIELDS = FW / "config" / "boards" / "shields"
WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"

REQUIRED = ["Kconfig.shield", "{name}.overlay", "{name}.keymap"]


def load_yaml(path, problems):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        problems.append(f"{path.relative_to(ROOT)}: YAML が読めない ({e})")
        return None


def main():
    problems, notes = [], []

    build = load_yaml(FW / "build.yaml", problems)
    west = load_yaml(FW / "config" / "west.yml", problems)
    wf = load_yaml(WORKFLOW, problems)

    # west.yml
    if west:
        self_path = (west.get("manifest", {}).get("self") or {}).get("path")
        if self_path != "config":
            problems.append(f"west.yml の self.path が 'config' でない: {self_path!r}")
        rev = [p.get("revision") for p in west["manifest"]["projects"]
               if p.get("name") == "zmk"]
        notes.append(f"ZMK の revision: {rev[0] if rev else '未指定'}")

    # ワークフローが firmware/ を指しているか
    if wf:
        with_ = (wf.get("jobs", {}).get("build", {}) or {}).get("with", {})
        for key, want in [("build_matrix_path", "firmware/build.yaml"),
                          ("config_path", "firmware/config")]:
            if with_.get(key) != want:
                problems.append(f"ワークフローの {key} が {want!r} でない: {with_.get(key)!r}")

    # build.yaml のシールドが実在するか
    if build:
        entries = build.get("include", [])
        notes.append(f"ビルド対象 {len(entries)} 件")
        for e in entries:
            name, board = e.get("shield"), e.get("board")
            d = SHIELDS / name
            if not d.is_dir():
                problems.append(f"シールド '{name}' のディレクトリが無い: {d.relative_to(ROOT)}")
                continue
            for pat in REQUIRED:
                f = d / pat.format(name=name)
                if not f.exists():
                    problems.append(f"{name}: {f.name} が無い")
            # Kconfig.shield の引数
            kc = (d / "Kconfig.shield")
            if kc.exists():
                m = re.search(r"shields_list_contains,\s*([A-Za-z0-9_]+)\s*\)",
                              kc.read_text(encoding="utf-8"))
                if not m:
                    problems.append(f"{name}: Kconfig.shield に shields_list_contains が無い")
                elif m.group(1) != name:
                    problems.append(
                        f"{name}: Kconfig.shield の引数 '{m.group(1)}' が"
                        f"ディレクトリ名 '{name}' と違う（ビルド時に無言で無視される）")
            notes.append(f"  {board} / {name}")

    # シールドの keymap と overlay の対応
    for d in sorted(p for p in SHIELDS.iterdir() if p.is_dir()):
        stems = {f.stem for f in d.glob("*.*")}
        odd = {s for s in stems if s not in {d.name, "Kconfig"} and not s.startswith(d.name)}
        if odd:
            problems.append(f"{d.name}: 名前がシールド名と一致しないファイル {sorted(odd)}")

    for n in notes:
        print(f"  {n}")
    if problems:
        print()
        for p in problems:
            print(f"!! {p}")
        print(f"\n{len(problems)} 件の問題")
        return 1
    print("\n問題なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
