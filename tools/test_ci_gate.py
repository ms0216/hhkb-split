"""CI の changed ゲートが、形の入力を全部覆っていることを守る。

open-gaps #31 の案 A で、干渉検査は real-shape ジョブ**ただ 1 つ**になった。
real-shape は `changed` ゲート付きで、**ゲートの filter に入っていない場所から
形が変わると、干渉検査は黙って走らなくなる**（「飛んだ検査は無いのと同じ」。
この案件で 4 回起きた型）。

filter の複製をここに書いて突き合わせるのでは、両方を同時に書き忘れたら
終わり。だから**実際に組み立てを走らせ、open されたファイルを監査フックで
全部採る**。新しい入力（例: config/ を読む形のコード）が増えれば、
ここに自動で現れて、filter を直すまで落ちる。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent

# 監査対象から外すもの。**形の入力ではないもの**だけを列挙する。
#   - build/ は生成物（読むのはキャッシュ）。.venv/.git は環境
#   - ezdxf.ini は ezdxf が cwd に作る自分の設定ファイル
#   - __pycache__ は**外さない**。コード（tools/*.py）の読み込みは
#     pyc の場所として映り、コードもゲートが覆うべき形の入力だから
_IGNORE = ("build/", ".venv/", ".git/", "ezdxf.ini")


def _gate_pattern():
    """checks.yml から changed ゲートの正規表現をそのまま取り出す。"""
    text = (ROOT / ".github/workflows/checks.yml").read_text()
    m = re.search(r"grep -qE '([^']+)'", text)
    assert m, "checks.yml に changed ゲートの grep -qE が見つからない"
    return m.group(1)


def _shape_inputs():
    """組み立てを**新しいプロセスで**走らせ、open された repo 内の
    ファイルを全部返す。

    別プロセスなのは、import 済みのモジュール（tools/*.py）の読み込みも
    含めて採るため。このプロセスで測ると、コードのファイルは既に読まれて
    いて監査に出ない。
    """
    code = r"""
import json, sys
from pathlib import Path
ROOT = Path(%r)
opened = set()
def hook(event, args):
    if event != "open" or not args:
        return
    p = args[0]
    if not isinstance(p, (str, bytes)):
        return
    p = p.decode() if isinstance(p, bytes) else p
    try:
        rel = Path(p).resolve().relative_to(ROOT)
    except ValueError:
        return
    opened.add(str(rel))
sys.addaudithook(hook)
sys.path.insert(0, str(ROOT / "tools"))
from gen_plate import halves
from gen_assembly import build_assembly
build_assembly(halves()["left"], "left", real=False)
print(json.dumps(sorted(opened)))
""" % str(ROOT)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=1200)
    assert r.returncode == 0, f"組み立てが失敗した:\n{r.stderr[-2000:]}"
    files = json.loads(r.stdout.splitlines()[-1])
    assert files, "open が 1 件も採れていない（監査フックが効いていない）"
    return files


def test_the_changed_gate_covers_every_shape_input():
    """**ゲートの filter が、形の入力を 1 つ残らず含むこと。**

    ここが破れると、filter 外のファイルで形が変わっても real-shape が
    走らず、**唯一の干渉検査が黙って消える**（案 A の前提条件）。
    """
    pat = re.compile(_gate_pattern())
    files = _shape_inputs()

    # real モードだけが読む入力も足す。kicad-cli が**子プロセスで**読む
    # 基板ファイルは監査フックに映らないので、宣言（pcb_parts.BOARDS）から
    # 取る。宣言と実際の読み込みは board_sha256/_export_step が同じ定数を
    # 使うので一致する。
    import pcb_parts
    files = list(files) + list(pcb_parts.BOARDS.values())

    checked, escaped = 0, []
    for f in files:
        if any(part in f for part in _IGNORE):
            continue
        checked += 1
        if not pat.search(f):
            escaped.append(f)
    # 母数（2026-08-11 に数えた）: コード 8（tools/ の pyc）＋
    # layout/hhkb_split.json ＋ tools/pcb_parts.json ＋ 基板 3 ＝ 13
    assert checked >= 12, f"母数が少なすぎる（{checked} 件）。採り方が壊れている"
    assert not escaped, (
        "changed ゲートの filter に入っていない形の入力がある。\n"
        "この状態で該当ファイルだけを push すると、唯一の干渉検査"
        "（real-shape）が走らない。checks.yml の filter に足すこと:\n  "
        + "\n  ".join(sorted(set(escaped))))


def test_the_gate_guard_itself_detects_a_hole():
    """**この見張り自体が効いていることを、狭めた filter で確かめる。**

    layout/ を外した filter なら、layout の JSON が「漏れ」として
    検出されなければならない。検出できないなら、上の検査は
    何も見ていない。
    """
    pat = re.compile(r"^(tools/|pcb/)")          # layout/ をわざと外す
    files = _shape_inputs()
    escaped = [f for f in files
               if not any(p in f for p in _IGNORE) and not pat.search(f)]
    assert any(f.startswith("layout/") for f in escaped), (
        "layout/ を外した filter でも漏れが出ない。監査が形の入力を"
        "採れていない（見張りが機能していない）")
