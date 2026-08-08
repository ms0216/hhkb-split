"""定数を機械的に書き換えて、検査が気づくかを測る。

    .venv/bin/python3 tools/mutate.py [モジュール名]

「検査が 276 件ある」は何も語らない。**壊して落ちるかどうか**だけが語る。
生き残った変異＝その数字を間違えても誰も気づかない箇所。

CLAUDE.md の検証の作法 2「通ったことは調べた証拠にならない」を、1 件ずつ
手でやる代わりに機械でやる。**手でやっていたので漏れが残っていた。**

初回（2026-08-08）の結果は 検出 34 / 生存 9。そこから見つかったもの:

  - `BATT_CELLS` を 2→3 にしても 276 件が全部通った。3 本なら新品で 4.95V、
    ショットキーを引いて 4.55V が nRF52840 の VDD へ入る（絶対最大 3.9V）。
    **電圧の上限を見る検査が 1 つも無かった**
  - `DIVIDER_R_HIGH` を 1MΩ→1.1MΩ にしても通った。ファームの
    `full-ohms` と一致を見ていなかった（残量表示が静かに狂う）
  - `BAND_H` を 9.25→10.175 にしても通った。帯を広げると検査は緩むだけ
  - `XIAO_H_WITH_USB` はどこからも使われていなかった。USB 切り欠きの
    余裕が 0.10mm しか無いことに気づいていなかった

**注意: 走らせている間、tools/*.py は書き換わっている。**同時に編集したり
pytest を回したりしないこと（実際に編集を 1 つ失った）。
"""
import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = ROOT / ".venv/bin/pytest"
MODULES = ["interface.py", "circuit.py", "bands.py", "matrix.py", "envelopes.py"]


def _number(node):
    """数値リテラルなら値を返す。そうでなければ None。

    **負の数を忘れないこと。**`-2.6` は AST では単項マイナスなので、
    `ast.Constant` だけを見ていると素通りする。実際 `SOCK_LO = -2.6` が
    一度も変異されていなかった。
    """
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _number(node.operand)
        return None if v is None else -v
    if (isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)):
        return node.value
    return None


def constants(path):
    """モジュール直下の数値定数。**タプル代入も拾う。**

    最初はタプルを飛ばしていて、`XIAO_L, XIAO_W, XIAO_H = 21.0, 18.0, 3.0`
    のような行が一度も変異されていなかった。**測っていない箇所は
    「守られている」ではなく「測っていない」。**
    """
    tree = ast.parse(path.read_text())
    out = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tg in node.targets:
            v = _number(node.value)
            if isinstance(tg, ast.Name) and v is not None:
                out.append((tg.id, v, node.lineno, None))
            elif (isinstance(tg, ast.Tuple)
                  and isinstance(node.value, ast.Tuple)
                  and len(tg.elts) == len(node.value.elts)):
                for i, (name, val) in enumerate(zip(tg.elts, node.value.elts)):
                    v = _number(val)
                    if isinstance(name, ast.Name) and v is not None:
                        out.append((name.id, v, node.lineno, i))
    return out


def mutate(value):
    """**気づかれにくい方向へずらす。**桁を変えると型検査で落ちてしまう。"""
    if isinstance(value, int) and not isinstance(value, float):
        # **大きい整数を +1 しても意味がない。**1MΩ を 1000001Ω にしても
        # 誰も気づかないのは当たり前で、検査の穴ではない。
        return value + 1 if abs(value) < 10 else int(round(value * 1.10))
    return round(value * 1.10, 4) if value else 1.0


def main():
    print("**実行中は tools/*.py が書き換わる。同時に編集しないこと。**\n",
          flush=True)
    only = sys.argv[1] if len(sys.argv) > 1 else None
    survived, killed = [], []
    for name in MODULES:
        if only and name != only:
            continue
        path = ROOT / "tools" / name
        original = path.read_text()
        lines = original.split("\n")
        for const, value, lineno, slot in constants(path):
            new = mutate(value)
            line = lines[lineno - 1]
            # 代入の右辺だけを置き換える（コメントは触らない）
            head, _, rest = line.partition("=")
            code, sep, comment = rest.partition("#")
            if slot is None:
                body = str(new)
            else:
                # タプル代入は、その位置の要素だけを差し替える
                parts = [t.strip() for t in code.split(",")]
                parts[slot] = str(new)
                body = ", ".join(parts)
            patched = f"{head}= {body}  {sep}{comment}" if sep else f"{head}= {body}"
            mutated = "\n".join(lines[:lineno - 1] + [patched] + lines[lineno:])
            path.write_text(mutated)
            try:
                r = subprocess.run(
                    [str(PY), "tools", "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
                    cwd=ROOT, capture_output=True, text=True, timeout=600)
                ok = r.returncode == 0
            except subprocess.TimeoutExpired:
                ok = False
            finally:
                path.write_text(original)
            tag = f"{name}:{const} {value} -> {new}"
            (survived if ok else killed).append(tag)
            print(("生存 " if ok else "検出 ") + tag, flush=True)

    print(f"\n検出 {len(killed)} / 生存 {len(survived)}")
    if survived:
        print("\n**この数字は間違えても誰も気づかない:**")
        for s in survived:
            print("  " + s)


if __name__ == "__main__":
    main()
