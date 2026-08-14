"""検査ぜんぶで共有する足回り。

いまのところ入っているのは **「KiCad の Python（pcbnew）が要る検査」の
入口**だけ。

なぜ要るか
----------
**2026-08-13 まで、CI の `checks` ジョブは 7 件ずっと赤だった。**

`test_schematic` / `test_pinmap` / `test_pcb` は pcbnew を使うのに、
`/Applications/KiCad/...` という **macOS の固定パス**を
`subprocess.run` へ直接渡していた。`checks` ジョブは KiCad を
入れない（実形状は別ジョブの仕事）ので Linux には当然その道が無く、
**skip ではなく `FileNotFoundError` で落ちていた。**

赤が 7 件も常駐すると、**新しい赤がその中に紛れて見えなくなる**。
実際このバックログの作業中、「自分より前から赤か」を毎回確かめる
必要があった。

**ただし黙って飛ばすのも駄目。**「飛んだ検査は無いのと同じ」で
緑になる事故がこの案件で 4 回起きている（test_assembly.py の
`_require_kicad` の docstring）。だから同じ約束にする:

  - pcbnew が無い環境 …… skip
  - **`REQUIRE_KICAD=1` なら fail**（入れたはずが入っていない、を通さない）
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pcb_parts  # noqa: E402


def require_kicad_python(what):
    """pcbnew を持つ Python が無ければ skip。REQUIRE_KICAD=1 なら fail。

    `test_assembly._require_kicad`（kicad-cli 版）と同じ約束。
    """
    import os

    if pcb_parts.kicad_python_available():
        return
    if os.environ.get("REQUIRE_KICAD") == "1":
        pytest.fail(
            f"{what}: pcbnew を持つ Python が無い（{pcb_parts.KICAD_PYTHON}）。"
            "このジョブは飛ばしてはいけない。KICAD_PYTHON で場所を指せる")
    pytest.skip(f"{what}: KiCad の Python が無い環境（KICAD_PYTHON で指せる）")


def require_kicad_cli(what):
    """kicad-cli が無ければ skip。REQUIRE_KICAD=1 なら fail。

    ⚠️ **fixture の中で使うこと。**kicad-cli を呼ぶ道は
    `gen_sch.write`（netlist の書き出し）のように**間接的**なことが
    あり、テスト本体に guard を置いても fixture の側で先に落ちる。
    落ちると skip ではなく **error** になる（2026-08-14・6 件）。
    """
    import os

    if pcb_parts.kicad_available():
        return
    if os.environ.get("REQUIRE_KICAD") == "1":
        pytest.fail(f"{what}: kicad-cli が無い（{pcb_parts.KICAD_CLI}）。"
                    "このジョブは飛ばしてはいけない。KICAD_CLI で場所を指せる")
    pytest.skip(f"{what}: kicad-cli が無い環境（KICAD_CLI で指せる）")
