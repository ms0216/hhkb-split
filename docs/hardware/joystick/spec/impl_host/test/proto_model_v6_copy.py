"""K 案 v6 のフレームとクリック計数の参照モデル＋ファズ。

v4 からの変更（R6 の指摘 R4-1）: 不在は「3 回連続の失敗 かつ 最後の正常フレームから 150ms 以上」。失敗のたびに判定する。
離しカウンタが進んだら固着のマスクを解く（2 秒ポーリングの間の「離して押し直し」を拾う）。


v3 からの変更（R5 の指摘 R3-1/R3-2）:
  - 「固着」: 押下が長く続いたら離しを出し、押下 0 のフレームを受け入れるまでボタンを無視する
  - 不在はどの状態からでも入る（連続 3 回失敗）。古いフレームの使い回しも失敗に数える
  - 化け無し・周期 250ms 以下なら、押し回数が実物と完全に一致することを assert する


v2 からの変更（R4 の指摘 R2-1/R2-2/R2-3）:
  - 不在に入ったら「離し」を出して押下を解く（押しっぱなしの残留を無くす）
  - ブート ID が同じでも、通し番号の進みが「前回からのポーリング回数」の範囲外なら状態だけ合わせる
    （電源の入れ直しで ID が偶然同じになった場合の幻クリックを防ぐ）
  - 「あきすぎ」は回数ではなく時間（500ms 超）で判定する


v1 からの変更（R3-S の指摘 M2/M3/M4/m17）:
  - 「再起動旗 8 フレーム」をやめ、ブート ID（起動ごとに +1 の 8bit）を毎フレーム比べる
  - (ブート ID, seq) が前回と同じフレームは捨てる（古いフレームの使い回し）
  - 前の正常フレームから時間があきすぎたら、回数を再生せず状態だけ合わせる
  - 検査を強くした: ホストが出した「押し」の累計が、実物の「押し」の累計を決して超えない
"""
import random

MAGIC = 0xC3
GAP_MS = 800             # 前の正常フレームからこれより長くあいたら再生しない
ABSENT_AFTER = 3         # 連続失敗がこの回数以上
ABSENT_MS = 150          # かつ最後の正常フレームからこの時間以上で不在


def crc16(data, init=0xFFFF, poly=0x1021):
    c = init
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ poly) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


class Pod:
    def __init__(self):
        self.phys = False
        self.boot_id = 0          # .noinit RAM。電源断では乱数になるが、ここでは連番で十分
        self.boot()

    def boot(self, same_id=False, rnd=None):
        if rnd is not None:       # 電源投入リセットでは ID を乱数でかき混ぜる（R2-2 の対策）
            self.boot_id = rnd
        elif not same_id:         # same_id=True は「電源断で RAM が同じ値に戻った」最悪の場合
            self.boot_id = (self.boot_id + 1) & 0xFF
        self.pc = self.rc = 0
        self.pressed = self.phys
        self.seq = 0

    def press(self):
        if not self.phys:
            self.phys = self.pressed = True
            self.pc = (self.pc + 1) & 15

    def release(self):
        if self.phys:
            self.phys = self.pressed = False
            self.rc = (self.rc + 1) & 15

    total = 0                     # 検査用: この個体で実際に起きた押しの累計（フレームには載らない）

    def sample(self, t, x, y):
        """アドレス一致で測り直す。seq はここで進む。"""
        self.seq = (self.seq + 1) & 0xFF
        self.last = (t, x, y)

    def frame(self):
        t, x, y = self.last
        packed = (t << 20) | (x << 10) | y
        body = [MAGIC, (1 << 6) | (1 if self.pressed else 0), self.boot_id,
                (self.pc << 4) | self.rc, self.seq,
                (packed >> 24) & 0xFF, (packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF]
        c = crc16(body)
        return bytes(body + [c >> 8, c & 0xFF])


class Host:
    N = 11

    def __init__(self):
        self.synced = False
        self.pressed = False
        self.boot_id = self.seq = None
        self.pc = self.rc = 0
        self.events = []
        self.resyncs = self.rejected = self.stale = 0
        self.last_was_sync = True # 直前の受理が「状態だけ合わせる」だったか
        self.mask = False         # 固着中: 押下 0 を見るまでボタンを無視
        self.held_ms = 0
        self.fails = 0            # 連続失敗
        self.polls = 0            # 前の正常フレームからのポーリング回数
        self.ms = 0               # 前の正常フレームからの経過時間

    def stuck(self):
        """押下が長く続いた: 離しを出して、押下 0 を見るまで無視する。"""
        self._emit(False)
        self.mask = True

    def _emit(self, pressed):
        if self.mask and pressed:
            return
        if pressed != self.pressed:
            self.pressed = pressed
            self.events.append('P' if pressed else 'R')

    def _fail(self):
        self.fails += 1
        if self.synced and self.fails >= ABSENT_AFTER and self.ms >= ABSENT_MS:
            self._emit(False)                    # 不在に入る: 押下を解く（失敗のたびに判定）
            self.synced = False
        return None

    def feed(self, f, dt=250):
        self.polls += 1
        self.ms += dt
        if f is None or len(f) != self.N or f[0] != MAGIC or crc16(f[:9]) != ((f[9] << 8) | f[10]):
            self.rejected += 1
            return self._fail()
        if (f[1] >> 6) != 1:                      # 版が違うフレームは捨てて失敗に数える
            self.rejected += 1
            return self._fail()
        pressed, boot_id, pc, rc, seq = bool(f[1] & 1), f[2], f[3] >> 4, f[3] & 15, f[4]
        packed = (f[5] << 24) | (f[6] << 16) | (f[7] << 8) | f[8]
        t, x, y = (packed >> 20) & 0x3FF, (packed >> 10) & 0x3FF, packed & 0x3FF
        if t < 64 or x > t + 8 or y > t + 8:
            self.rejected += 1
            return self._fail()
        if boot_id == self.boot_id and seq == self.seq:   # 不在を挟んでも覚えておく
            self.stale += 1                      # 同じフレームの使い回し
            return self._fail()
        seq_ok = self.seq is not None and 1 <= ((seq - self.seq) & 0xFF) <= self.polls
        if not pressed or (self.mask and rc != self.rc and boot_id == self.boot_id):
            self.mask = False                    # 離されたのを見た（離しカウンタが進んだ場合も）: 固着を解く（押し/離しを出す前に判定）
        if not self.synced or boot_id != self.boot_id or self.ms > GAP_MS or not seq_ok:
            if self.synced:
                self.resyncs += 1
            self.synced = True
            self.last_was_sync = True
            self._emit(pressed)                  # 状態だけ合わせる
        else:
            dp, dr = (pc - self.pc) & 15, (rc - self.rc) & 15
            start = self.pressed
            ok = (not start and dp >= dr and dp - dr == (1 if pressed else 0)) or \
                 (start and dr >= dp and dr - dp == (0 if pressed else 1))
            if ok:
                self.last_was_sync = False
                s = start
                for _ in range(dp + dr):
                    s = not s
                    self._emit(s)
            else:
                self.resyncs += 1
                self.last_was_sync = True
                self._emit(pressed)
        self.held_ms = self.held_ms + self.ms if self.pressed else 0
        self.boot_id, self.seq, self.pc, self.rc = boot_id, seq, pc, rc
        self.fails = self.polls = self.ms = 0
        return t, x, y


def corrupt(f, rng):
    k = rng.random()
    b = bytearray(f)
    if k < 0.15:
        return bytes(len(f))
    if k < 0.30:
        return bytes([0xFF] * len(f))
    if k < 0.40:
        return bytes(b[:rng.randrange(0, len(f))])
    if k < 0.70:
        for _ in range(rng.choice([1, 1, 2, 3])):
            i = rng.randrange(len(b) * 8)
            b[i // 8] ^= 1 << (i % 8)
        return bytes(b)
    for i in range(rng.randrange(len(b)), len(b)):
        b[i] = rng.randrange(256)
    return bytes(b)


def run(steps, seed, p_bad, p_reboot, p_loop=0.0, p_stale=0.0, clicks=(0, 0, 0, 0, 1, 1, 2, 3), p_cold=0.0, p_unplug=0.0, cold_rnd=False, p_hold=0.0, dts=(12, 16, 250, 250, 250, 2000)):
    rng = random.Random(seed)
    pod, host = Pod(), Host()
    true_presses = host_presses = 0
    worst_excess = 0
    accepted_bad = 0
    looping = 0
    prev = None
    unplugged = 0
    last_ok = None
    built = {}
    last_built = None
    iv_true = iv_host = 0          # 直近の正常フレーム以降の押し回数（実物 / ホスト）
    strict_viol = stuck_viol = 0
    hold = 0
    repress_viol = 0
    for _ in range(steps):
        if hold:
            hold -= 1                                # 押しっぱなし（ジャム）の最中は何も起きない
        elif rng.random() < p_hold and pod.phys:
            hold = rng.randrange(50, 400)
        for _ in range(0 if hold else rng.choice(clicks)):
            if pod.phys:
                pod.release()
            else:
                pod.press()
                true_presses += 1
                pod.total += 1
        if looping:
            pod.boot(); looping -= 1
        elif rng.random() < p_loop:
            looping = rng.randrange(2, 40)          # リセットの連続（BOD/WDT ループ）
        elif rng.random() < p_reboot:
            pod.boot()
        elif rng.random() < p_cold:
            pod.boot(same_id=True, rnd=(rng.randrange(256) if cold_rnd else None))
        if unplugged:
            unplugged -= 1
        elif rng.random() < p_unplug:
            unplugged = rng.randrange(1, 30)         # しばらく抜けている
        t = rng.randrange(300, 1024)
        fresh = True
        if prev is not None and rng.random() < p_stale:
            f = prev                                 # 測り直さずに同じフレームを返す故障
            fresh = False
        else:
            pod.sample(t, rng.randrange(0, t + 1), rng.randrange(0, t + 1))
            f = pod.frame()
            built[f] = pod.total                     # このフレームが作られた時点の累計
        prev = f
        bad = rng.random() < p_bad
        g = corrupt(f, rng) if bad else f
        if unplugged:
            g = bytes([0xFF] * len(f))               # 抜けている間は線が High のまま
        dt = rng.choice(dts)
        before = len(host.events)
        was_synced_frame = host.synced
        out = host.feed(g, dt)
        newp = host.events[before:].count('P')
        host_presses += newp
        iv_host += newp
        if out is not None and g == last_ok:
            strict_viol += 1                         # 一度受け入れたフレームを二度受け入れてはならない
        if out is not None:
            last_ok = g
        if out is not None:
            # 厳しい検査: 回数の再生で出した押しは、前の受理フレームからこのフレームまでの間に
            # 実物で起きた押しの数を超えない。状態合わせで出す押しは 1 回まで。
            now_built = built.get(g)
            if now_built is None:
                pass                                 # 化けたのに通ったフレーム（accepted_bad で数える）
            elif host.last_was_sync:
                if newp > 1:
                    strict_viol += 1
            elif last_built is not None and newp > now_built - last_built:
                strict_viol += 1
            last_built = now_built if now_built is not None else last_built
            if len(built) > 4096:
                built = {g: now_built} if now_built is not None else {}
        if host.fails >= ABSENT_AFTER and host.ms >= ABSENT_MS and host.pressed:
            stuck_viol += 1                          # 不在の条件を満たしたのに押下が残っている
        if host.pressed and host.held_ms > 30_000:
            host.stuck()                             # 30 秒（モデル上の「5 分」）押されっぱなし → 固着
        if host.mask and host.pressed:
            repress_viol += 1                        # 固着中に押下へ戻ってはならない
        if bad and g != f and out is not None:
            accepted_bad += 1
        if out is not None and g == f and fresh:
            assert host.pressed == pod.phys or host.mask, "正常フレームの後は実物と一致する（固着中を除く）"
        # ホストが「まだ見ていない押し」を先取りして数えることは決してない
        excess = host_presses - true_presses - (1 if False else 0)
        worst_excess = max(worst_excess, excess)
    return dict(true=true_presses, host=host_presses, strict_viol=strict_viol, stuck_viol=stuck_viol + repress_viol,
                worst_excess=worst_excess, rejected=host.rejected, stale=host.stale, resyncs=host.resyncs,
                accepted_bad=accepted_bad)


if __name__ == "__main__":
    r = run(200_000, 1, 0.0, 0.0, dts=(12, 16, 250))
    assert r["true"] == r["host"] and r["resyncs"] == 0 and r["strict_viol"] == 0 and r["stuck_viol"] == 0, r
    print("A  化けなし・周期≤250ms（押し回数が完全一致）", r)
    for name, kw in [
        ("B  3割が破損               ", dict(p_bad=0.30, p_reboot=0.0)),
        ("C  破損＋単発の再起動      ", dict(p_bad=0.30, p_reboot=0.001)),
        ("D  リセットの連続（破損なし）", dict(p_bad=0.0, p_reboot=0.0, p_loop=0.0005)),
        ("E  リセットの連続＋3割破損 ", dict(p_bad=0.30, p_reboot=0.0, p_loop=0.0005)),
        ("F  95%が破損＋再起動       ", dict(p_bad=0.95, p_reboot=0.001)),
        ("G  古いフレームの使い回し  ", dict(p_bad=0.0, p_reboot=0.0, p_stale=0.2)),
        ("H  連打（1 回の読みに最大 9）", dict(p_bad=0.30, p_reboot=0.0, clicks=(0, 1, 2, 5, 9))),
        ("L  同じ ID のまま電源入れ直し", dict(p_bad=0.0, p_reboot=0.0, p_cold=0.002)),
        ("M  同上＋3割破損           ", dict(p_bad=0.30, p_reboot=0.0, p_cold=0.002)),
        ("L2 入れ直しで ID を乱数化  ", dict(p_bad=0.0, p_reboot=0.0, p_cold=0.002, cold_rnd=True)),
        ("M2 同上＋3割破損           ", dict(p_bad=0.30, p_reboot=0.0, p_cold=0.002, cold_rnd=True)),
        ("N  抜き差し（押したままも）", dict(p_bad=0.0, p_reboot=0.0, p_unplug=0.002)),
        ("P  押しっぱなし（固着）    ", dict(p_bad=0.0, p_reboot=0.0, p_hold=0.01)),
        ("Q  押しっぱなし＋3割破損＋抜き差し", dict(p_bad=0.30, p_reboot=0.0, p_hold=0.01, p_unplug=0.001)),
        ("O  全部入り                ", dict(p_hold=0.003, p_bad=0.30, p_reboot=0.001, p_loop=0.0003, p_cold=0.001, p_unplug=0.001, p_stale=0.05, cold_rnd=True)),
    ]:
        r = run(400_000, 7, **{"p_bad": 0, "p_reboot": 0, **kw})
        flag = "OK " if (r["strict_viol"] == 0 and r["stuck_viol"] == 0) else "NG "
        print(name, flag, r)
    # 決め打ちの場面
    pod, host = Pod(), Host()
    pod.sample(500, 250, 250); assert host.feed(pod.frame()) is not None
    f = pod.frame()
    assert host.feed(f) is None and host.stale == 1          # 同じフレーム 2 回目は捨てる
    for _ in range(16):                                      # 16 回押して離す（4bit が一周）
        pod.press(); pod.release()
    pod.sample(500, 250, 250); host.feed(pod.frame())
    print("I  4bit が一周（16 クリック）→ ホストが出したイベント:", len(host.events), "（取りこぼし。幻ではない）")
    pod2, host2 = Pod(), Host()
    pod2.sample(500, 1, 1); host2.feed(pod2.frame())
    for _ in range(3):
        pod2.press(); pod2.release()
    pod2.boot(); pod2.boot()                                 # 2 連続の再起動
    pod2.sample(500, 1, 1); host2.feed(pod2.frame())
    print("J  2 連続の再起動 → ホストが出したイベント:", host2.events, "（幻のクリック無し）")
    for bad in (bytes(11), bytes([0xFF] * 11), b"", bytes([MAGIC] * 11)):
        assert Host().feed(bad) is None
    print("K  全00・全FF・空・マジックだけ → すべて拒否")
