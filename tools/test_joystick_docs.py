"""ジョイスティック／エンコーダの設計記録（docs/hardware/joystick/）が、記録どおりに成り立っていること。

- 帯の穴ごとの配置が期待する回路と一致し、壊した配置を検出できる（pod_layout.py --break）
- 刷る受け皿に 0.9mm 未満の細い所が無い（thin_check.py）
形の生成（joystick_rkjxv.py）は main の筐体コードに依存し重いので、ここでは生成物の STL を検査する。
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "docs/hardware/joystick"


def run(*args):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=D)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    return r.stdout


def test_right_strip_layout_matches_circuit_and_detects_breakage():
    assert "問題なし" in run(D / "pod_layout/pod_layout.py")
    out = run(D / "pod_layout/pod_layout.py", "--break")
    assert "12/12" in out and "16/16" in out and "検出" in out, out


def test_left_strip_layout_matches_circuit():
    assert "問題なし" in run(D / "pod_layout/left_layout.py")


@pytest.mark.parametrize("stl", ["left_tray.stl", "right_tray.stl"])
def test_trays_have_no_unprintable_thin_walls(stl):
    pytest.importorskip("scipy")
    out = run(D / "print/thin_check.py", D / "print" / stl, "0.9")
    assert "未満の所 0 か所" in out and out.count("0 か所") == 2, out
