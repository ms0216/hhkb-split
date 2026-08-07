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
SHIELDS = ROOT / "config" / "boards" / "shields"
WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"

# ZMK が受け付けるボード名。Zephyr 4.1 以降は zmk バリアントが必須。
ZMK_VARIANT = "//zmk"

REQUIRED = ["Kconfig.shield", "{name}.overlay", "{name}.keymap"]


def load_yaml(path, problems):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        problems.append(f"{path.relative_to(ROOT)}: YAML が読めない ({e})")
        return None


def find_shield_dir(name):
    """<name>.overlay を持つディレクトリを探す。"""
    for d in SHIELDS.iterdir():
        if d.is_dir() and (d / f"{name}.overlay").exists():
            return d
    return None


def count_map_entries(overlay):
    """overlay の matrix-transform の map に並んだ RC(...) の数。"""
    text = overlay.read_text(encoding="utf-8")
    m = re.search(r"map\s*=\s*<(.*?)>\s*;", text, re.S)
    return len(re.findall(r"RC\s*\(", m.group(1))) if m else 0


def count_bindings(keymap):
    """キーマップの各レイヤーのバインディング数を [(名前, 個数), ...] で返す。"""
    text = keymap.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)      # コメントを除く
    out = []
    for m in re.finditer(r"(\w+)\s*\{[^{}]*?bindings\s*=\s*<(.*?)>\s*;", text, re.S):
        out.append((m.group(1), len(re.findall(r"&\w+", m.group(2)))))
    return out


def main():
    problems, notes = [], []

    build = load_yaml(ROOT / "build.yaml", problems)
    west = load_yaml(ROOT / "config" / "west.yml", problems)
    wf = load_yaml(WORKFLOW, problems)

    # west.yml
    if west:
        self_path = (west.get("manifest", {}).get("self") or {}).get("path")
        if self_path != "config":
            problems.append(f"west.yml の self.path が 'config' でない: {self_path!r}")
        rev = [p.get("revision") for p in west["manifest"]["projects"]
               if p.get("name") == "zmk"]
        notes.append(f"ZMK の revision: {rev[0] if rev else '未指定'}")

    # 配置は ZMK 標準（リポジトリ直下の config/ と build.yaml）であること。
    # 入れ子にすると west のワークスペース位置がずれて
    # "no west workspace found" で失敗する。
    if wf:
        with_ = (wf.get("jobs", {}).get("build", {}) or {}).get("with", {}) or {}
        for key in ("build_matrix_path", "config_path"):
            if key in with_:
                problems.append(
                    f"ワークフローが {key} を指定している（{with_[key]!r}）。"
                    "config は必ずリポジトリ直下に置くこと")
    if not (ROOT / "config" / "west.yml").exists():
        problems.append("config/west.yml がリポジトリ直下にない")
    if not (ROOT / "build.yaml").exists():
        problems.append("build.yaml がリポジトリ直下にない")

    # build.yaml のシールドが実在するか
    if build:
        entries = build.get("include", [])
        notes.append(f"ビルド対象 {len(entries)} 件")
        for e in entries:
            name, board = e.get("shield"), e.get("board")
            if board and not board.endswith(ZMK_VARIANT):
                problems.append(
                    f"ボード名 {board!r} に {ZMK_VARIANT} が付いていない。"
                    "Zephyr 4.1 以降の ZMK は zmk バリアント必須")
            # 分割シールドは 1 つのディレクトリに左右 2 つのシールド名を置く慣例。
            # ディレクトリ名 = シールド名とは限らないので、<name>.overlay が
            # あるディレクトリを探す。
            d = find_shield_dir(name)
            if d is None:
                problems.append(f"シールド '{name}': {name}.overlay が見つからない")
                continue
            if not (d / "Kconfig.shield").exists():
                problems.append(f"{name}: Kconfig.shield が無い（{d.name}/）")
            if not list(d.glob("*.keymap")):
                problems.append(f"{name}: キーマップが無い（{d.name}/）")
            # Kconfig.shield が **このシールド名** を宣言しているか。
            # 綴りがずれるとビルド時に無言で無視される。
            kc = d / "Kconfig.shield"
            if kc.exists():
                declared = set(re.findall(r"shields_list_contains,\s*([A-Za-z0-9_]+)\s*\)",
                                          kc.read_text(encoding="utf-8")))
                if not declared:
                    problems.append(f"{name}: Kconfig.shield に shields_list_contains が無い")
                elif name not in declared:
                    problems.append(
                        f"{name}: Kconfig.shield が宣言しているのは {sorted(declared)} で、"
                        f"'{name}' が無い（ビルド時に無言で無視される）")
            notes.append(f"  {board} / {name}  ({d.name}/)")

    # キーマップのバインディング個数
    #
    # ZMK で最も多い失敗。個数が matrix-transform の map と合わないと
    # ビルドが落ちるか、キーが 1 つずつずれる。手元で数えれば往復が減る。
    for d in sorted(p for p in SHIELDS.iterdir() if p.is_dir()):
        km = list(d.glob("*.keymap"))
        if not km:
            continue
        n_map = sum(count_map_entries(f) for f in sorted(d.glob("*.overlay")))
        if n_map == 0:
            continue
        for layer, n in count_bindings(km[0]):
            if n != n_map:
                problems.append(
                    f"{d.name}: レイヤー '{layer}' のバインディングが {n} 個。"
                    f"transform の map は合計 {n_map} 箇所（{n - n_map:+d}）")
        notes.append(f"  {d.name}: map {n_map} 箇所 / "
                     f"レイヤー {len(count_bindings(km[0]))} 枚すべて一致")

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
