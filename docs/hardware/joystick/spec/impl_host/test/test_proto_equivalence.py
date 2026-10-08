"""stick_pod_proto.c を、参照モデル（proto_model_v6.py の class Host）と 1 手ずつ突き合わせる。

モデルの run() が作る Host を「モデルと C を同時に動かす二重の Host」に差し替え、
feed()/stuck() のたびに **返り値と内部状態が一致すること**を assert する。
モデルの 16 条件（各 40 万フレーム）＋決め打ちの場面をそのまま流す。

実行:  cc -shared -fPIC -o libsp.dylib ../firmware/drivers/stick_pod_proto.c
       python3 -B test_proto_equivalence.py
"""
import ctypes as C
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import proto_model_v6_copy as pm  # noqa: E402  （仕様側のファイルの写し。中身は変えていない）

lib = C.CDLL(str(HERE / "libsp.dylib"))
EDGE = C.CFUNCTYPE(None, C.c_void_p, C.c_bool, C.c_bool)
NV = 8


class Frame(C.Structure):
    _fields_ = [("version", C.c_uint8), ("reset_cause", C.c_uint8), ("pressed", C.c_bool),
                ("boot_id", C.c_uint8), ("pc", C.c_uint8), ("rc", C.c_uint8), ("seq", C.c_uint8),
                ("t", C.c_uint16), ("x", C.c_uint16), ("y", C.c_uint16)]


class CHostS(C.Structure):
    _fields_ = [("edge", EDGE), ("ctx", C.c_void_p),
                ("synced", C.c_bool), ("pressed", C.c_bool), ("mask", C.c_bool),
                ("have_last", C.c_bool), ("last_was_sync", C.c_bool),
                ("boot_id", C.c_uint8), ("seq", C.c_uint8), ("pc", C.c_uint8), ("rc", C.c_uint8),
                ("fails", C.c_uint32), ("polls", C.c_uint32), ("ms", C.c_uint32),
                ("held_ms", C.c_uint32), ("count", C.c_uint32 * NV), ("resyncs", C.c_uint32)]


lib.sp_host_feed.restype = C.c_int
lib.sp_host_feed.argtypes = [C.POINTER(CHostS), C.c_char_p, C.c_size_t, C.c_uint32, C.POINTER(Frame)]
lib.sp_crc16.restype = C.c_uint16
lib.sp_crc16.argtypes = [C.c_char_p, C.c_size_t]

checked = 0
urgent_seen = 0


class Dual(pm.Host):
    """モデルの Host を継承し、同じ入力を C にも流して毎回比べる。"""

    def __init__(self):
        super().__init__()
        self.c = CHostS()
        self.c_events = []
        self._seen = 0
        self._cb = EDGE(self._edge)          # 参照を持ち続けないと GC される
        lib.sp_host_init(C.byref(self.c), self._cb, None)

    def _edge(self, _ctx, pressed, urgent):
        global urgent_seen
        assert not (urgent and pressed), "urgent で押しが来た"
        urgent_seen += urgent
        self.c_events.append('P' if pressed else 'R')

    def _same(self, where):
        global checked
        c = self.c
        m = (self.synced, self.pressed, self.mask, self.fails, self.polls, self.ms, self.held_ms,
             self.last_was_sync, self.rejected, self.stale, self.resyncs)
        rej = sum(c.count[1:7])     # IO・長さ・マジック・CRC・版・範囲
        k = (c.synced, c.pressed, c.mask, c.fails, c.polls, c.ms, c.held_ms,
             c.last_was_sync, rej, c.count[7], c.resyncs)
        assert m == k, (where, m, k)
        # 全体を毎回比べると O(n²)。長さと、前回からの増分だけを見る（列は消さない:
        # モデルの run() が events[before:] で数えているので、縮めると検査が狂う）
        assert len(self.events) == len(self.c_events), where
        assert self.events[self._seen:] == self.c_events[self._seen:], \
            (where, self.events[-5:], self.c_events[-5:])
        self._seen = len(self.events)
        if self.boot_id is not None:
            assert c.have_last and (self.boot_id, self.seq, self.pc, self.rc) == \
                (c.boot_id, c.seq, c.pc, c.rc), where
        checked += 1

    def feed(self, f, dt=250):
        out = super().feed(f, dt)
        fr = Frame()
        v = lib.sp_host_feed(C.byref(self.c), f, 0 if f is None else len(f), dt, C.byref(fr))
        assert (out is None) == (v != 0), ("verdict", out, v)
        if out is not None:
            assert out == (fr.t, fr.x, fr.y), (out, fr.t, fr.x, fr.y)
        self._same("feed")
        return out

    def stuck(self):
        super().stuck()
        lib.sp_host_stuck(C.byref(self.c))
        self._same("stuck")


def main():
    # CRC がモデルと同じこと
    import random
    rng = random.Random(3)
    for _ in range(2000):
        b = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 12)))
        assert lib.sp_crc16(b, len(b)) == pm.crc16(b)
    assert lib.sp_crc16(b"123456789", 9) == 0x29B1          # CRC-16/CCITT-FALSE の検査値

    pm.Host = Dual
    r = pm.run(200_000, 1, 0.0, 0.0, dts=(12, 16, 250))
    assert r["true"] == r["host"] and r["strict_viol"] == 0 and r["stuck_viol"] == 0, r
    cases = [
        dict(p_bad=0.30), dict(p_bad=0.30, p_reboot=0.001), dict(p_loop=0.0005),
        dict(p_bad=0.30, p_loop=0.0005), dict(p_bad=0.95, p_reboot=0.001), dict(p_stale=0.2),
        dict(p_bad=0.30, clicks=(0, 1, 2, 5, 9)), dict(p_cold=0.002), dict(p_bad=0.30, p_cold=0.002),
        dict(p_cold=0.002, cold_rnd=True), dict(p_bad=0.30, p_cold=0.002, cold_rnd=True),
        dict(p_unplug=0.002), dict(p_hold=0.01), dict(p_bad=0.30, p_hold=0.01, p_unplug=0.001),
        dict(p_hold=0.003, p_bad=0.30, p_reboot=0.001, p_loop=0.0003, p_cold=0.001, p_unplug=0.001,
             p_stale=0.05, cold_rnd=True),
    ]
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400_000
    for kw in cases:
        r = pm.run(n, 7, **{"p_bad": 0, "p_reboot": 0, **kw})
        print(kw, {k: r[k] for k in ("true", "host", "strict_viol", "stuck_viol", "resyncs")})
    # 動作中の周期だけ（不在が 150ms で決まる側）も流す
    r = pm.run(n, 11, 0.5, 0.001, p_unplug=0.002, p_hold=0.003, dts=(10, 12, 16))
    print("active only", {k: r[k] for k in ("true", "host", "strict_viol", "stuck_viol")})

    # 決め打ち: 空・短い・全 00・全 FF・マジックだけ
    # 決め打ち: 版が違うフレームは CRC が合っていても捨てる（v7）
    for ver in (0, 2, 3):
        p = pm.Pod(); p.sample(800, 400, 400)
        f = bytearray(p.frame()); f[1] = (f[1] & 0x3F) | (ver << 6)
        c = pm.crc16(f[:9]); f[9], f[10] = c >> 8, c & 0xFF
        assert Dual().feed(bytes(f)) is None, ver
    for bad in (None, b"", bytes(11), bytes([0xFF] * 11), bytes([pm.MAGIC] * 11), bytes(10), bytes(12)):
        assert Dual().feed(bad) is None
    print("checked", checked, "calls; urgent edges", urgent_seen)
    assert urgent_seen > 0


if __name__ == "__main__":
    main()
