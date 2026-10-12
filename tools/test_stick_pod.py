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


SIM = ROOT / "tools/stick_pod/sim"


def _run_sim(tmp_path, driver_src, scenes=range(1, 27), defs=()):
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("C コンパイラが無い")
    exe = tmp_path / "sim"
    subprocess.run([cc, "-std=gnu11", "-O1", "-w", "-DCONFIG_PM_DEVICE_RUNTIME=0", *defs, "-I", str(SIM / "stubs"),
                    "-I", str(ROOT / "firmware/drivers"), "-o", str(exe), str(SIM / "sim.c"), str(driver_src),
                    str(ROOT / "firmware/drivers/stick_pod_proto.c")], check=True)
    return "".join(subprocess.run([str(exe), str(i)], capture_output=True, text=True, timeout=120).stdout
                   for i in scenes)


def test_host_state_machine_reproduces_the_recorded_scenes(tmp_path):
    """キーボード側ドライバ（stick_pod.c）の状態機械を、代役のヘッダと仮想の時計の上で 26 場面走らせ、
    記録した結果（tools/stick_pod/sim/expected.txt）と 1 文字も違わないこと。

    場面: 初回起動・倒す・ダブルクリック・押しっぱなし 11 分・押したまま抜く・固着・スリープ・リンク断 など。
    **論理だけの確認**（Zephyr の API は代役）。記録そのものが正しいかは別（S9 は既知の未解決。S21 は 2026-10-08 に直した: 36 万カウント → 0。S23 はその裏返し＝本当に動かせば移動が戻る。S24 は不在を挟んで中心へ戻れば止めたままにならないこと、S25 は倒れたまま戻ったら流さないこと。S26 は既知: 読みが 5LSB 揺れると既定の幅では中心を採用できない）。
    意図して挙動を変えたら、結果を読んでから expected.txt を更新する。"""
    got = _run_sim(tmp_path, ROOT / "firmware/drivers/stick_pod.c")
    assert got == (SIM / "expected.txt").read_text()


def test_the_scene_check_notices_a_changed_driver(tmp_path):
    """上の検査が、ドライバを変えると本当に落ちること（故意に壊す）。"""
    src = (ROOT / "firmware/drivers/stick_pod.c").read_text()
    assert "#define SP_MAX_PENDING" in src
    import re
    broken = tmp_path / "stick_pod.c"
    broken.write_text(re.sub(r"#define SP_MAX_PENDING\s+\d+", "#define SP_MAX_PENDING 2", src))
    assert _run_sim(tmp_path, broken) != (SIM / "expected.txt").read_text()


def test_wider_stable_band_lets_a_wobbling_stuck_stick_settle(tmp_path):
    """倒れたまま 7 秒ごとに 5LSB 揺れるスティック（S9）は、既定の ±3LSB では固着に入れず 30 分流れ続ける。
    devicetree の stuck-stable-lsb を 8 にすれば、5 分で固着に入って止まること。"""
    src = ROOT / "firmware/drivers/stick_pod.c"
    assert "next 30 min=2160000" in _run_sim(tmp_path, src, scenes=[9])                      # 既定: 流れ続ける（既知）
    assert "next 30 min=0 " in _run_sim(tmp_path, src, scenes=[9], defs=["-DSTUB_stuck_stable_lsb=8"])


def test_wider_centre_band_lets_a_wobbling_stick_adopt_its_centre(tmp_path):
    """初回起動で読みが 300ms ごとに 5LSB 揺れる（S26 の波形）と、既定の ±3LSB では中心を採用できず、ポインタが動かない
    （揺れの周期が 2 秒以上なら既定でも採用できる。「どんな揺れでも」ではない）。
    devicetree の centre-stable-lsb を 8 にすれば採用できること。**固着の幅（stuck-stable-lsb）を広げても効かない**
    ことも見る（2 つの設定の取り違えを検出する）。"""
    src = ROOT / "firmware/drivers/stick_pod.c"
    assert "saves=0 " in _run_sim(tmp_path, src, scenes=[26])
    assert "saves=1 " in _run_sim(tmp_path, src, scenes=[26], defs=["-DSTUB_centre_stable_lsb=8"])
    assert "saves=0 " in _run_sim(tmp_path, src, scenes=[26], defs=["-DSTUB_stuck_stable_lsb=8"])
