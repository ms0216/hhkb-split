/*
 * スティックポッド（K 案）のフレーム検査とクリック計数。**Zephyr に依存しない。**
 *
 * ここを別ファイルに分けてあるのは、**参照モデル（proto_model_v6.py の
 * class Host）と 1 手ずつ突き合わせるため。**手元に Zephyr SDK は無いが、
 * このファイルだけは普通の C コンパイラで通るので、モデルと同じ乱数列を
 * 流して「返り値・押下・マスク・同期・連続失敗・経過時間」が毎回一致する
 * ことを確かめられる（test/test_proto_equivalence.py）。
 *
 * **数字を足すときは、モデルと両方を直すこと。**片方だけ直すと、
 * 突き合わせが赤になる（そのために置いてある）。
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SP_FRAME_LEN 11
#define SP_MAGIC 0xC3
/* byte1 bit7-6。**違う版のフレームは捨てて失敗に数える**（K_SPEC v7 §2 の表）。 */
#define SP_VERSION 1

/* 規則 3: 前の正常フレームからこれより長くあいたら、回数を再生しない。
 * **静止周期 250ms の 3 倍＋50ms。**静止周期を変えるならここも変える
 * （stick_pod.c の BUILD_ASSERT が 3 × rest-period-ms + 50 <= SP_GAP_MS を見ている）。 */
#define SP_GAP_MS 800
/* 不在: 連続失敗がこの回数以上、かつ最後の正常フレームからこの時間以上。 */
#define SP_ABSENT_AFTER 3
#define SP_ABSENT_MS 150
/* 規則 1: T がこれ未満のフレームは捨てる。X・Y は T+SP_XY_SLACK まで。 */
#define SP_T_MIN 64
#define SP_XY_SLACK 8

struct sp_frame {
    uint8_t version;     /* byte1 bit7-6 */
    uint8_t reset_cause; /* byte1 bit5-4。0=電源投入 1=BOD 2=WDT 3=その他 */
    bool pressed;        /* byte1 bit0 */
    uint8_t boot_id;
    uint8_t pc, rc; /* 押した回数・離した回数（mod 16） */
    uint8_t seq;
    uint16_t t, x, y; /* 各 10bit */
};

enum sp_verdict {
    SP_ACCEPT = 0,
    SP_REJ_IO,    /* 読めなかった（NACK・タイムアウト） */
    SP_REJ_LEN,   /* 長さ */
    SP_REJ_MAGIC, /* マジック */
    SP_REJ_CRC,   /* CRC */
    SP_REJ_VERSION, /* 版が SP_VERSION でない */
    SP_REJ_RANGE, /* T<64, X>T+8, Y>T+8 */
    SP_REJ_STALE, /* (ブート ID, 通し番号) が前回の正常フレームと同じ */
    SP_VERDICT_COUNT,
};

/*
 * 押下状態が変わるたびに呼ばれる。
 *   urgent = false … 回数の再生／状態合わせ。**間をあけて出す**（規則 5）
 *   urgent = true  … 不在・固着・停止。**待たせずに離す**（規則 6・8）。
 *                    このとき pressed は必ず false。
 */
typedef void (*sp_edge_cb)(void *ctx, bool pressed, bool urgent);

struct sp_host {
    sp_edge_cb edge;
    void *ctx;

    bool synced;        /* false = 「不在」（初回も同じ扱い） */
    bool pressed;       /* ホストが信じている押下状態（出力待ちを含む） */
    bool mask;          /* 固着: 押下を無視する（規則 8） */
    bool have_last;     /* boot_id/seq/pc/rc が有効か（**不在を挟んでも消さない**・規則 7） */
    bool last_was_sync; /* 直前の受理が「状態だけ合わせる」だったか */
    uint8_t boot_id, seq, pc, rc;

    uint32_t fails;   /* 連続失敗 */
    uint32_t polls;   /* 前の正常フレームからのポーリング回数（今回を含む） */
    uint32_t ms;      /* 前の正常フレームからの経過時間 */
    uint32_t held_ms; /* 押下が続いている時間（正常フレームの上で数える） */

    uint32_t count[SP_VERDICT_COUNT]; /* 判定ごとの累計。[SP_ACCEPT] は受理数 */
    uint32_t resyncs;                 /* 同期したまま「状態だけ合わせる」に落ちた回数 */
};

uint16_t sp_crc16(const uint8_t *data, size_t len);

/* 規則 1 だけを見る。buf が NULL なら SP_REJ_IO。 */
enum sp_verdict sp_parse(const uint8_t *buf, size_t len, struct sp_frame *out);

void sp_host_init(struct sp_host *h, sp_edge_cb edge, void *ctx);

/*
 * 1 回のポーリングの結果を渡す。**読めなかったときも必ず呼ぶ**（buf = NULL）。
 * dt_ms は前回のポーリングからの経過時間。
 * SP_ACCEPT のときだけ *out が有効。呼んだあと h->synced が false なら「不在」。
 */
enum sp_verdict sp_host_feed(struct sp_host *h, const uint8_t *buf, size_t len, uint32_t dt_ms,
                             struct sp_frame *out);

/* 固着: 離しを出し、押下 0 を見るか離しの回数が進むまで押下を無視する。 */
void sp_host_stuck(struct sp_host *h);

/* 止める（SLEEP・分割リンクの変化）: 押下を解き、次の正常フレームは
 * 「状態だけ合わせる」から始める。**モデルには無い**（不在に入るのと同じ後始末）。 */
void sp_host_drop(struct sp_host *h);

/* ------------------------------------------------------------------ */
/* 傾き → 相対移動（不感帯 → 曲線 → 速度 → 端数持ち越し）               */

/* 傾きは X/T・Y/T を 16bit 固定小数（65536 = 1.0）にしたもの。 */
#define SP_Q16_ONE 65536

struct sp_motion_cfg {
    uint16_t dead_q16;  /* 不感帯の半径 */
    uint16_t full_q16;  /* これ以上倒しても速くならない半径（> dead_q16） */
    uint16_t max_speed; /* いっぱいに倒したときの速さ [カウント/秒] */
    uint8_t curve;      /* 曲線の指数 1..3 */
};

struct sp_motion {
    int64_t acc_x, acc_y; /* 端数（カウント × 32768 × 1000） */
};

uint16_t sp_ratio_q16(uint16_t v, uint16_t t);
bool sp_in_dead_zone(const struct sp_motion_cfg *cfg, int32_t dx, int32_t dy);
void sp_motion_reset(struct sp_motion *m);
/* dx, dy は中心からの差（Q16）。*ox, *oy に今回出すカウント（0 のことがある）。 */
void sp_motion_step(const struct sp_motion_cfg *cfg, struct sp_motion *m, int32_t dx, int32_t dy,
                    uint32_t dt_ms, int32_t *ox, int32_t *oy);
