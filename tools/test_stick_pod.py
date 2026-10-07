"""スティックポッド（右手のジョイスティック・K 案）の検査。

1. キーボード側の受け入れ規則（firmware/drivers/stick_pod_proto.c）が、参照モデル
   （tools/stick_pod/proto_model_v6_copy.py）と 1 手ずつ一致すること
2. ポッドのマイコン（ATtiny1616）のファーム firmware/pod/pod.c が警告 0 でコンパイルできること
   （avr-gcc が無ければ飛ばす。CI の pod-firmware ジョブは REQUIRE_AVR=1 で必須にする）

**どちらも実機の代わりにはならない。**1 は規則の論理、2 は名前と型が合っていることしか見ない。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_host_rules_match_the_reference_model(tmp_path):
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("C コンパイラが無い")
    lib = tmp_path / "libsp.so"
    subprocess.run([cc, "-shared", "-fPIC", "-o", str(lib), str(ROOT / "firmware/drivers/stick_pod_proto.c")], check=True)
    r = subprocess.run([sys.executable, "-B", str(ROOT / "tools/stick_pod/proto_equivalence.py"), "40000"],
                       env={**os.environ, "SP_LIB": str(lib)}, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "checked" in r.stdout          # 最後の行まで走った（途中で黙って終わっていない）


def test_pod_firmware_compiles_without_warnings(tmp_path):
    gcc = shutil.which("avr-gcc")
    if gcc is None:
        if os.environ.get("REQUIRE_AVR"):
            pytest.fail("avr-gcc が無い（REQUIRE_AVR=1）")
        pytest.skip("avr-gcc が無い")
    elf = tmp_path / "pod.elf"
    # Ubuntu の avr-libc は ATtiny1616 を知らない（CI で RSTCTRL などが未定義になった・2026-10-07）。
    # Microchip の ATtiny_DFP を AVR_DFP で渡す。手元の Arduino 版 avr-gcc は同梱のヘッダで通る。
    dfp = os.environ.get("AVR_DFP")
    extra = ["-B", f"{dfp}/gcc/dev/attiny1616/", "-I", f"{dfp}/include"] if dfp else []
    cmd = [gcc, "-mmcu=attiny1616", *extra, "-Os", "-std=gnu11", "-Wall", "-Wextra", "-Werror"]
    r = subprocess.run([*cmd, "-o", str(elf), str(ROOT / "firmware/pod/pod.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-3000:]
    # 逃げ道の版（上端の電圧を PA4 で測る）も通ること。PB5 自身で読めなかったときに使う
    r2 = subprocess.run([*cmd, "-DPOD_T_MUXPOS=ADC_MUXPOS_AIN4_gc", "-o", str(tmp_path / "pod_pa4.elf"),
                         str(ROOT / "firmware/pod/pod.c")], capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr[-3000:]
    size = subprocess.run([shutil.which("avr-size"), str(elf)], capture_output=True, text=True).stdout
    text = int(size.splitlines()[1].split()[0])
    assert 1000 < text < 16384, size      # 空でない・16KB に収まる
