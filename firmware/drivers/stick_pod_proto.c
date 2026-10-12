/*
 * スティックポッド（K 案）のフレーム検査とクリック計数。
 * 何をしているか・なぜ分けてあるかは stick_pod_proto.h の冒頭。
 *
 * **判定の順番まで proto_model_v6.py の Host.feed と揃えてある。**
 * 順番を入れ替えると結果が変わる所が 2 つある:
 *   - 版の判定は CRC のあと・範囲の前（モデルと同じ位置）
 *   - 「使い回し」の判定は、長さ・マジック・CRC・版・範囲のあと（化けたフレームを
 *     使い回しと数えない）
 *   - 固着のマスクを解くのは、押し/離しを出す**前**（同じフレームで押し直せる）
 *
 * SPDX-License-Identifier: MIT
 */

#include "stick_pod_proto.h"

/* CRC-16/CCITT-FALSE（多項式 0x1021・初期値 0xFFFF・反転なし・最後の XOR なし）。
 * Zephyr の crc16_itu_t(0xFFFF, …) と同じだが、**CONFIG_CRC に頼らない**ように
 * 持っている（9 バイトしか掛けないので表も要らない）。 */
uint16_t sp_crc16(const uint8_t *data, size_t len) {
    uint16_t c = 0xFFFF;

    for (size_t i = 0; i < len; i++) {
        c ^= (uint16_t)data[i] << 8;
        for (int b = 0; b < 8; b++) {
            c = (c & 0x8000) ? (uint16_t)((c << 1) ^ 0x1021) : (uint16_t)(c << 1);
        }
    }
    return c;
}

enum sp_verdict sp_parse(const uint8_t *f, size_t len, struct sp_frame *out) {
    if (f == NULL) {
        return SP_REJ_IO;
    }
    if (len != SP_FRAME_LEN) {
        return SP_REJ_LEN;
    }
    if (f[0] != SP_MAGIC) {
        return SP_REJ_MAGIC;
    }
    /* CRC は上位バイトが先（byte9 = 上位）。 */
    if (sp_crc16(f, 9) != (uint16_t)(((uint16_t)f[9] << 8) | f[10])) {
        return SP_REJ_CRC;
    }
    if ((f[1] >> 6) != SP_VERSION) {
        return SP_REJ_VERSION;
    }

    /* byte5-8 は上位から T・X・Y を 10bit ずつ詰めた 32bit（先頭 2bit は空き）。
     * ⚠️ この詰め方は仕様の表には無く、モデル（Pod.frame）だけが決めている。 */
    uint32_t packed = ((uint32_t)f[5] << 24) | ((uint32_t)f[6] << 16) | ((uint32_t)f[7] << 8) | f[8];

    out->version = f[1] >> 6;
    out->reset_cause = (f[1] >> 4) & 3;
    out->pressed = (f[1] & 1) != 0;
    out->boot_id = f[2];
    out->pc = f[3] >> 4;
    out->rc = f[3] & 15;
    out->seq = f[4];
    out->t = (packed >> 20) & 0x3FF;
    out->x = (packed >> 10) & 0x3FF;
    out->y = packed & 0x3FF;

    if (out->t < SP_T_MIN || out->x > out->t + SP_XY_SLACK || out->y > out->t + SP_XY_SLACK) {
        return SP_REJ_RANGE;
    }
    return SP_ACCEPT;
}

static uint32_t sat_add(uint32_t a, uint32_t b) { return (a > UINT32_MAX - b) ? UINT32_MAX : a + b; }

static void emit(struct sp_host *h, bool pressed, bool urgent) {
    if (h->mask && pressed) {
        return;
    }
    if (pressed != h->pressed) {
        h->pressed = pressed;
        if (h->edge != NULL) {
            h->edge(h->ctx, pressed, urgent);
        }
    }
}

void sp_host_init(struct sp_host *h, sp_edge_cb edge, void *ctx) {
    *h = (struct sp_host){.edge = edge, .ctx = ctx, .last_was_sync = true};
}

/* 失敗 1 回。**不在の判定は失敗のたびに行う**（3 回目だけではない）。 */
static void fail(struct sp_host *h) {
    h->fails = sat_add(h->fails, 1);
    if (h->synced && h->fails >= SP_ABSENT_AFTER && h->ms >= SP_ABSENT_MS) {
        emit(h, false, true); /* 規則 6 */
        h->synced = false;
    }
}

enum sp_verdict sp_host_feed(struct sp_host *h, const uint8_t *buf, size_t len, uint32_t dt_ms,
                             struct sp_frame *out) {
    struct sp_frame fr;

    h->polls = sat_add(h->polls, 1);
    h->ms = sat_add(h->ms, dt_ms);

    enum sp_verdict v = sp_parse(buf, len, &fr);

    if (v == SP_ACCEPT && h->have_last && fr.boot_id == h->boot_id && fr.seq == h->seq) {
        v = SP_REJ_STALE; /* 規則 2・7: 不在を挟んでも覚えている */
    }
    h->count[v]++;
    if (v != SP_ACCEPT) {
        fail(h);
        return v;
    }

    uint8_t adv = (uint8_t)(fr.seq - h->seq);
    bool seq_ok = h->have_last && adv >= 1 && adv <= h->polls;
    bool same_boot = h->have_last && fr.boot_id == h->boot_id;

    /* 規則 8: 離されたのを見た（押下 0、または同じブート ID で離しの回数が進んだ）。 */
    if (!fr.pressed || (h->mask && same_boot && fr.rc != h->rc)) {
        h->mask = false;
    }

    if (!h->synced || !same_boot || h->ms > SP_GAP_MS || !seq_ok) {
        /* 規則 3: 回数は数えず、押下状態だけ合わせる。 */
        if (h->synced) {
            h->resyncs++;
        }
        h->synced = true;
        h->last_was_sync = true;
        emit(h, fr.pressed, false);
    } else {
        /* 規則 4: 回数の差分から順に再生する。 */
        uint8_t dp = (fr.pc - h->pc) & 15;
        uint8_t dr = (fr.rc - h->rc) & 15;
        bool start = h->pressed;
        bool ok = (!start && dp >= dr && (dp - dr) == (fr.pressed ? 1 : 0)) ||
                  (start && dr >= dp && (dr - dp) == (fr.pressed ? 0 : 1));

        if (ok) {
            bool s = start;

            h->last_was_sync = false;
            for (uint8_t i = 0; i < dp + dr; i++) {
                s = !s;
                emit(h, s, false);
            }
        } else {
            h->resyncs++; /* 矛盾 → 規則 3 と同じ扱い */
            h->last_was_sync = true;
            emit(h, fr.pressed, false);
        }
    }

    h->held_ms = h->pressed ? sat_add(h->held_ms, h->ms) : 0;
    h->boot_id = fr.boot_id;
    h->seq = fr.seq;
    h->pc = fr.pc;
    h->rc = fr.rc;
    h->have_last = true;
    h->fails = 0;
    h->polls = 0;
    h->ms = 0;

    if (out != NULL) {
        *out = fr;
    }
    return SP_ACCEPT;
}

void sp_host_stuck(struct sp_host *h) {
    emit(h, false, true);
    h->mask = true;
}

void sp_host_drop(struct sp_host *h) {
    emit(h, false, true);
    h->synced = false;
}

/* ------------------------------------------------------------------ */

uint16_t sp_ratio_q16(uint16_t v, uint16_t t) {
    if (t == 0) {
        return 0;
    }

    uint32_t r = ((uint32_t)v << 16) / t;

    return (r > 65535U) ? 65535U : (uint16_t)r; /* X は T+8 まで通すので 1.0 を少し超えうる */
}

static uint32_t isqrt64(uint64_t n) {
    uint64_t r = 0, bit = (uint64_t)1 << 62;

    while (bit > n) {
        bit >>= 2;
    }
    while (bit != 0) {
        if (n >= r + bit) {
            n -= r + bit;
            r = (r >> 1) + bit;
        } else {
            r >>= 1;
        }
        bit >>= 2;
    }
    return (uint32_t)r;
}

bool sp_in_dead_zone(const struct sp_motion_cfg *cfg, int32_t dx, int32_t dy) {
    uint64_t m2 = (uint64_t)((int64_t)dx * dx) + (uint64_t)((int64_t)dy * dy);

    return m2 <= (uint64_t)cfg->dead_q16 * cfg->dead_q16;
}

void sp_motion_reset(struct sp_motion *m) { m->acc_x = m->acc_y = 0; }

#define SP_ACC_ONE ((int64_t)32768 * 1000)

void sp_motion_step(const struct sp_motion_cfg *cfg, struct sp_motion *m, int32_t dx, int32_t dy,
                    uint32_t dt_ms, int32_t *ox, int32_t *oy) {
    *ox = *oy = 0;
    if (sp_in_dead_zone(cfg, dx, dy) || cfg->full_q16 <= cfg->dead_q16) {
        return;
    }

    /* 円形の不感帯（軸ごとの四角にすると、斜めだけ不感帯が広くなる）。 */
    uint32_t mag = isqrt64((uint64_t)((int64_t)dx * dx) + (uint64_t)((int64_t)dy * dy));
    uint32_t span = (uint32_t)cfg->full_q16 - cfg->dead_q16;
    uint32_t n = mag - cfg->dead_q16;

    if (mag == 0) {
        return;
    }
    if (n > span) {
        n = span;
    }

    uint32_t g = (n << 15) / span; /* 0..32768 */
    uint32_t c = g;

    for (uint8_t i = 1; i < cfg->curve; i++) {
        c = (c * g) >> 15;
    }

    /* 速さ × 時間を、向き（dx/mag, dy/mag）に分ける。割り切れないぶんは持ち越す。 */
    int64_t v = (int64_t)c * cfg->max_speed * dt_ms;

    m->acc_x += v * dx / (int64_t)mag;
    m->acc_y += v * dy / (int64_t)mag;

    *ox = (int32_t)(m->acc_x / SP_ACC_ONE); /* 0 方向へ丸める（左右で対称） */
    *oy = (int32_t)(m->acc_y / SP_ACC_ONE);
    m->acc_x -= (int64_t)*ox * SP_ACC_ONE;
    m->acc_y -= (int64_t)*oy * SP_ACC_ONE;
}
