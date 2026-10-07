/*
 * スティックポッド（K 案・純ポーリング I2C）の Zephyr input ドライバ。
 *
 * ポッド上の ATtiny1616 は、**読まれた瞬間だけ起きて**スティックを測って返す。
 * こちらは System OFF 以外のあいだ、静止中は毎秒 4 回、動いている間は
 * 毎秒 60〜100 回読み、傾きを相対移動（INPUT_REL_X/Y）に、クリックを
 * INPUT_BTN_0 に変えて出す。
 *
 * ファイルの分担:
 *   stick_pod_proto.c … フレームの検査とクリック計数（規則 1〜4・7・8）。
 *                       Zephyr に依らず、参照モデルと 1 手ずつ突き合わせてある
 *   このファイル       … I2C の電源管理・ポーリングの状態機械・中心・変換・
 *                       出力の間隔（規則 5）・止め方（規則 6）
 *
 * 2026-10-06 レビュー後の修正版（review/fixed/CHANGES.md の F2〜F16）。
 *
 * **I2C（TWIM）を自分で suspend/resume している。**
 *   CONFIG_PM_DEVICE_RUNTIME は使えない（入れると PM_DEVICE_SYSTEM_MANAGED が
 *   切れ、ZMK の pm.c が zmk_pm_suspend_devices を持たなくなってリンクできない）。
 *   TWIM を有効のままにすると電流が乗るので、**読む間だけ**起こす
 *   （いくら乗るかは測っていない。K_SPEC の試験 9）。
 *   Zephyr の i2c_nrfx_twim_common.c の PM ハンドラは、RESUME で
 *   「default のピン状態 → nrfx_twim_enable」、SUSPEND で
 *   「nrfx_twim_disable → sleep のピン状態」を行う。
 *
 * ⚠️ **これはビルドも実機も通していない。**手元に Zephyr SDK が無いので、
 *    使っている API は上流のソース（ZMK main / zephyr v4.1.0+zmk-fixes）と
 *    1 つずつ照らしたが、**コンパイルが通るかは CI の ZMK ビルドが唯一の確認。**
 *    通ったあとに見るものは NOTES.md の (d)。
 *
 * SPDX-License-Identifier: MIT
 */

#define DT_DRV_COMPAT hhkb_stick_pod

#include <stdint.h>
#include <stdlib.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/input/input.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/pm/device.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/util.h>

#if IS_ENABLED(CONFIG_SETTINGS)
#include <zephyr/settings/settings.h>
#endif

#include <zmk/activity.h>
#include <zmk/event_manager.h>
#include <zmk/events/activity_state_changed.h>

/* 右手（ペリフェラル）だけが「左手と繋がっているか」を持つ。 */
#define SP_HAS_SPLIT_LINK (IS_ENABLED(CONFIG_ZMK_SPLIT) && !IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL))

#if SP_HAS_SPLIT_LINK
#include <zmk/events/split_peripheral_status_changed.h>
#endif

#include "stick_pod.h"
#include "stick_pod_proto.h"

LOG_MODULE_REGISTER(hhkb_stick_pod, CONFIG_INPUT_LOG_LEVEL);

/* 中心を settings に持つので、1 台に 1 個だけ。左右に付けるときは
 * **左右それぞれのファーム**に 1 個ずつ入る（左右で別の XIAO）。 */
BUILD_ASSERT(!IS_ENABLED(CONFIG_PM_DEVICE_RUNTIME),
	     "stick-pod: PM_DEVICE_RUNTIME とは併用しない（Kconfig では依存が輪になるのでここで止める）");
BUILD_ASSERT(DT_NUM_INST_STATUS_OKAY(DT_DRV_COMPAT) == 1, "hhkb,stick-pod は 1 個だけ置くこと");

/* タイムアウトが既定（500ms）のままだと、SCL が Low に固定されたときに
 * このスレッドが 0.5 秒ずつ止まり、不在の判定（3 回・150ms）が 1.5 秒かかる。
 * Kconfig で 10 にしているが、**設定しただけで効いていない**を防ぐためここで見る。 */
BUILD_ASSERT(CONFIG_I2C_NRFX_TRANSFER_TIMEOUT > 0 && CONFIG_I2C_NRFX_TRANSFER_TIMEOUT <= 20,
             "CONFIG_I2C_NRFX_TRANSFER_TIMEOUT を 10 前後にすること（既定の 500 のままになっている）");

/* ---- 仕様で決まっている数字（devicetree に出さない） ---- */
#define SP_STABLE_LSB 3         /* 「そろっている」「不変」の幅（±3LSB） */
#define SP_ADOPT_FRAMES 8       /* 中心の採用に要る連続フレーム数 */
#define SP_ADOPT_LO 19661       /* 0.5 − 0.2 */
#define SP_ADOPT_HI 45875       /* 0.5 + 0.2 */
#define SP_TRACK_WINDOW 6554    /* ±0.1 */
#define SP_NO_CENTRE_WARN_MS 60000
/* ---- 仕様が決めていない数字（NOTES.md (b)。実機で詰める） ---- */
#define SP_TRACK_SHIFT 6             /* 静止中の追従: 1 フレームで差の 1/64（4Hz で時定数 16 秒） */
#define SP_SAVE_DELTA 655            /* RAM の中心が保存値から 0.01 動いたら保存を予約する */
#define SP_SAVE_DELAY K_MINUTES(10)  /* 保存の間引き（flash を減らさない） */
#define SP_RECAL_TIMEOUT_MS 5000     /* キー操作の取り直しを諦めるまで */
#define SP_MAX_PENDING 32            /* 出力待ちの押し/離し（規則 5: 32 個まで） */
#define SP_STATS_PERIOD_MS (10 * 60 * 1000)

#define SP_SETTINGS_TREE "hhkb/stick"
#define SP_SETTINGS_KEY "centre"

enum sp_state { SP_ST_ABSENT, SP_ST_REST, SP_ST_ACTIVE, SP_ST_STUCK };

static const char *const sp_state_name[] = {"不在", "静止", "動作", "固着"};

enum sp_flag {
    SP_F_STOP_SLEEP,    /* ZMK の活動状態が SLEEP */
    SP_F_STOP_PM,       /* ZMK がこのデバイスを suspend した（soft off を含む） */
    SP_F_LINK_DOWN,     /* 分割リンクが切れている（右だけ） */
    SP_F_LINK_CHANGED,  /* 上が変わった。スレッド側で後始末する */
    SP_F_RECAL,         /* キー操作で中心を取り直す */
    SP_F_LOADED,        /* settings を読み終えた（保存値の有無が確定した） */
    SP_F_COUNT,
};

struct sp_centre {
    uint16_t x, y; /* X/T・Y/T（Q16） */
};

struct sp_config {
    struct i2c_dt_spec i2c;
    uint16_t rest_ms, active_ms, absent_ms, stuck_ms;
    uint16_t hold_ms;       /* 中心かつ非押下がこれだけ続いたら「静止」へ */
    uint16_t replay_gap_ms; /* 押し/離しを出す間隔（規則 5） */
    uint32_t stuck_after_ms;
    struct sp_motion_cfg motion;
};

struct sp_data {
    const struct device *dev;
    struct k_thread thread;
    struct k_sem wake;
    /* **ポーリングと「止める処理」が取り合う錠。**転送の途中で ZMK に
     * TWIM を suspend させない。状態（下の全部）もこれで守る。 */
    struct k_mutex lock;
    ATOMIC_DEFINE(flags, SP_F_COUNT);

    struct sp_host host;
    enum sp_state state;
    int64_t last_poll;  /* 前回読んだ時刻 */
    int64_t last_frame; /* 前回の正常フレーム */

    /* 押し/離しの出力（規則 5）。host.pressed は「出し終えたら」こうなる状態で、
     * out_pressed は実際に出した状態。差は pending 回の反転。 */
    bool out_pressed;
    uint8_t pending;
    int64_t last_edge;

    /* 状態機械の時計 */
    int64_t active_since;  /* 「動作」に入った時刻 */
    int64_t centred_since; /* 中心かつ非押下が始まった時刻（0 = 続いていない） */
    int64_t press_since;   /* 押下が始まった時刻（0 = 押されていない） */
    int64_t anchor_since;  /* 傾きが anchor から ±3LSB を出ていない間の起点 */
    uint16_t anchor_x, anchor_y;
    bool stuck_by_button;
    uint16_t stuck_x, stuck_y;

    /* 中心 */
    bool have_centre;
    struct sp_centre saved; /* settings にある値 */
    struct sp_centre ram;   /* いま使っている値（静止中に ±0.1 の窓で追従） */
    uint8_t run_n;          /* 採用の途中: そろった連続フレーム数 */
    uint16_t run_x0, run_y0;
    uint32_t run_sx, run_sy, run_st;
    int64_t no_centre_since;
    bool no_centre_warned;
    bool recal;
    int64_t recal_deadline;

    struct sp_motion motion;

    /* 見えるようにするもの */
    uint32_t n_nack, n_timeout, n_edge_drop, n_boot_change;
    bool seen_frame;
    uint8_t seen_boot_id;
    int64_t last_stats;
};

static struct k_work_delayable sp_save_work;

static const struct device *const sp_dev0 = DEVICE_DT_GET(DT_DRV_INST(0));

static bool sp_stopped(const struct sp_data *data) {
    return atomic_test_bit(data->flags, SP_F_STOP_SLEEP) ||
           atomic_test_bit(data->flags, SP_F_STOP_PM);
}

/* ------------------------------------------------------------------ */
/* I2C の電源管理                                                      */

/* **-EALREADY は成功。**ZMK が先に同じ状態へ動かしていることがある
 * （SLEEP・soft off の suspend）。-ENOSYS は PM 無しのビルドで、TWIM は
 * 起きっぱなしになる（Kconfig の depends on PM_DEVICE で弾いている）。 */
static int sp_bus_pm(const struct device *bus, enum pm_device_action action) {
    int rc = pm_device_action_run(bus, action);

    return (rc == -EALREADY) ? 0 : rc;
}

/* ------------------------------------------------------------------ */
/* 出力                                                                */

/* 押し/離しは落とさない。**離しが落ちると、ホストで押しっぱなしになる。**
 * input_report は、システムワークキューから呼ぶと待ち時間を 0 に落とす
 * （subsys/input/input.c）。止める処理はそこから来るので、戻り値を数える。 */
/* **出せなかったら「出したつもり」にしない**（F5）。out_pressed は成功したとき
 * だけ動かす。last_edge は失敗でも進める（すぐ回し直して空回りしないため。
 * 次の試行は replay_gap_ms 後）。 */
static bool sp_report_button(struct sp_data *data, bool pressed) {
    int rc = input_report_key(data->dev, INPUT_BTN_0, pressed ? 1 : 0, true, K_MSEC(20));

    data->last_edge = k_uptime_get();
    if (rc < 0) {
        data->n_edge_drop++;
        LOG_ERR("クリックの%sを出せなかった (%d)。出し直す", pressed ? "押し" : "離し", rc);
        return false;
    }
    data->out_pressed = pressed;
    return true;
}

/* **待ち行列を捨て、押下を出したままなら離しを出す**（F4。K_SPEC §4:
 * 不在・固着・停止・分割リンク断。ホスト側の押下状態が変わったかどうかに
 * 関係なく、こちらが「実際に出した状態」で決める）。
 * 呼ぶ時点で host.pressed は必ず false（不在 = fail()、固着 = sp_host_stuck か
 * もともと false、停止・リンク = sp_host_drop）。
 * 離しが出せなかったら（システムワークキューからは待てない）、**離し 1 個を
 * 待ち行列に残す**。スレッドが回っていれば replay_gap_ms 後に出し直す。 */
static void sp_flush_edges(struct sp_data *data) {
    data->pending = 0;
    data->press_since = 0;
    if (data->out_pressed && !sp_report_button(data, false)) {
        data->pending = 1;
    }
}

/* sp_host から。urgent は「待たせずに離す」（不在・固着・停止）。 */
static void sp_edge(void *ctx, bool pressed, bool urgent) {
    struct sp_data *data = ctx;

    if (urgent) {
        /* 出力待ちは捨てる（クリックを取りこぼすだけで、幻にはならない）。
         * **これだけに頼らない**: host.pressed がすでに false だとここへは来ない。
         * 不在・固着・停止・リンク断の各入口が sp_flush_edges を直接呼ぶ（F4）。 */
        sp_flush_edges(data);
        return;
    }

    /* 1 回呼ばれるごとに押下状態が 1 回反転している。偶奇さえ保てば、
     * 出し終えたときに host.pressed と一致する。 */
    if (data->pending >= SP_MAX_PENDING) {
        data->pending -= 2; /* あふれたら偶奇を保って 2 個（＝クリック 1 回）捨てる */
    }
    data->pending++;
    data->press_since = pressed ? k_uptime_get() : 0;
}

/* 出力待ちを 1 つ出す。出したら true。 */
static bool sp_drain_edge(struct sp_data *data, const struct sp_config *cfg, int64_t now) {
    if (data->pending == 0 || now - data->last_edge < cfg->replay_gap_ms) {
        return false;
    }
    /* 出せたときだけ行列を進める（F5）。失敗なら行列はそのまま、次の間隔で出し直す。 */
    if (!sp_report_button(data, !data->out_pressed)) {
        return false;
    }
    data->pending--;
    return true;
}

/* **差分ゼロのイベントは出さない。**入力イベントは ZMK の活動扱いになり
 * （app/src/activity.c の INPUT_CALLBACK_DEFINE(NULL, …)）、出し続けると
 * 30 分たっても眠れない。右では 1 イベントが BLE の通知 1 個にもなる。 */
static void sp_report_motion(struct sp_data *data, int32_t dx, int32_t dy) {
    if (dx != 0) {
        input_report_rel(data->dev, INPUT_REL_X, dx, dy == 0, K_NO_WAIT);
    }
    if (dy != 0) {
        input_report_rel(data->dev, INPUT_REL_Y, dy, true, K_NO_WAIT);
    }
}

/* ------------------------------------------------------------------ */
/* 中心                                                                */

static bool sp_within(uint16_t a, uint16_t b, uint16_t tol) { return abs((int)a - (int)b) <= tol; }

static void sp_run_reset(struct sp_data *data) { data->run_n = 0; }

/* 保存は、このスレッドではやらない（settings → NVS → flash はスタックを食う。
 * ZMK 本体と同じくシステムワークキューから書く）。 */
static void sp_save_work_cb(struct k_work *work) {
#if IS_ENABLED(CONFIG_SETTINGS)
    struct sp_data *data = sp_dev0->data;
    struct sp_centre c;

    k_mutex_lock(&data->lock, K_FOREVER);
    c = data->ram;
    k_mutex_unlock(&data->lock);

    int rc = settings_save_one(SP_SETTINGS_TREE "/" SP_SETTINGS_KEY, &c, sizeof(c));

    if (rc < 0) {
        /* saved は動かさない（F14）。次に 0.01 ずれたとき、また予約される。 */
        LOG_ERR("中心を保存できなかった (%d)", rc);
        return;
    }
    k_mutex_lock(&data->lock, K_FOREVER);
    data->saved = c; /* **書けてから**「保存値」にする */
    k_mutex_unlock(&data->lock);
    LOG_INF("中心を保存した: %u, %u", c.x, c.y);
#else
    /* 保存先が無い。追従と固着の窓の基準（saved）だけ合わせる（F14）。 */
    struct sp_data *data = sp_dev0->data;

    k_mutex_lock(&data->lock, K_FOREVER);
    data->saved = data->ram;
    k_mutex_unlock(&data->lock);
#endif
}

/* 中心の採用（保存値が無い初回・キー操作での取り直し）。
 * 連続 8 フレームが最初の 1 枚から ±3LSB にそろい、その平均の X/T・Y/T が
 * 0.5±0.2 に入ったら採用する。**倒したまま起動しても、倒した位置を
 * 中心にしないため**の窓（X/T は R2 やポットの値に依らず約 0.5）。 */
static void sp_adopt_step(struct sp_data *data, const struct sp_frame *fr) {
    if (data->run_n > 0 &&
        (!sp_within(fr->x, data->run_x0, SP_STABLE_LSB) || !sp_within(fr->y, data->run_y0, SP_STABLE_LSB))) {
        data->run_n = 0;
    }
    if (data->run_n == 0) {
        data->run_x0 = fr->x;
        data->run_y0 = fr->y;
        data->run_sx = data->run_sy = data->run_st = 0;
    }
    data->run_sx += fr->x;
    data->run_sy += fr->y;
    data->run_st += fr->t;
    if (++data->run_n < SP_ADOPT_FRAMES) {
        return;
    }
    data->run_n = 0;

    /* 合計どうしの比（= 平均の X ÷ 平均の T）。T の合計は 8×64 以上。 */
    uint32_t cx = (uint32_t)(((uint64_t)data->run_sx << 16) / data->run_st);
    uint32_t cy = (uint32_t)(((uint64_t)data->run_sy << 16) / data->run_st);

    if (cx < SP_ADOPT_LO || cx > SP_ADOPT_HI || cy < SP_ADOPT_LO || cy > SP_ADOPT_HI) {
        return; /* そろってはいるが中心らしくない（倒したまま）。待つ */
    }

    data->ram = (struct sp_centre){.x = (uint16_t)cx, .y = (uint16_t)cy};
    data->have_centre = true;
    data->recal = false;
    sp_motion_reset(&data->motion);
    LOG_INF("中心を採用した: %u, %u（Q16・0.5 = 32768）", cx, cy);
    k_work_reschedule(&sp_save_work, K_NO_WAIT);
}

/* 静止中のゆっくりした追従。**保存値の ±0.1 から外へは出ない。** */
static void sp_track_centre(struct sp_data *data, uint16_t rx, uint16_t ry) {
    if (!sp_within(rx, data->saved.x, SP_TRACK_WINDOW) || !sp_within(ry, data->saved.y, SP_TRACK_WINDOW)) {
        return;
    }
    data->ram.x += ((int32_t)rx - data->ram.x) / (1 << SP_TRACK_SHIFT);
    data->ram.y += ((int32_t)ry - data->ram.y) / (1 << SP_TRACK_SHIFT);

    if (!sp_within(data->ram.x, data->saved.x, SP_SAVE_DELTA) ||
        !sp_within(data->ram.y, data->saved.y, SP_SAVE_DELTA)) {
        /* schedule は「まだ予約が無いときだけ」動く。最初の予約から 10 分後に 1 回書く。 */
        k_work_schedule(&sp_save_work, SP_SAVE_DELAY);
    }
}

/* ------------------------------------------------------------------ */
/* 状態機械                                                            */

static void sp_log_counters(const struct sp_data *data, const char *why) {
    const struct sp_host *h = &data->host;

    /* 2 行に分けてある（1 行に引数 13 個は、スタックとログの上限の両方に近い）。 */
    LOG_INF("%s: 受理 %u / NACK %u / タイムアウト %u / マジック %u / 長さ %u / CRC %u / 版 %u", why,
            h->count[SP_ACCEPT], data->n_nack, data->n_timeout, h->count[SP_REJ_MAGIC],
            h->count[SP_REJ_LEN], h->count[SP_REJ_CRC], h->count[SP_REJ_VERSION]);
    LOG_INF("%s: 範囲 %u / 使い回し %u / 再同期 %u / 再起動 %u / 出力落ち %u", why,
            h->count[SP_REJ_RANGE], h->count[SP_REJ_STALE], h->resyncs, data->n_boot_change,
            data->n_edge_drop);
}

static void sp_set_state(struct sp_data *data, enum sp_state next) {
    if (data->state != next) {
        LOG_DBG("%s → %s", sp_state_name[data->state], sp_state_name[next]);
        data->state = next;
    }
}

static void sp_enter_active(struct sp_data *data, const struct sp_frame *fr, int64_t now) {
    sp_set_state(data, SP_ST_ACTIVE);
    data->active_since = now;
    data->centred_since = 0;
    data->anchor_x = fr->x;
    data->anchor_y = fr->y;
    data->anchor_since = now;
    if (data->host.pressed && data->press_since == 0) {
        data->press_since = now;
    }
}

/* 「不在」へ。離しは sp_host が urgent で出すが、それに頼らずここでも片付ける（規則 5・6）。
 * **ゼロ移動のイベントは出さない**（相対移動に「止まった」という状態は無く、
 * 出すと活動扱いになるだけ）。持ち越した端数だけ捨てる。 */
static void sp_enter_absent(struct sp_data *data, const char *why) {
    if (data->state != SP_ST_ABSENT) {
        LOG_WRN("ポッドを見失った（%s）", why);
        sp_log_counters(data, "不在");
    }
    sp_set_state(data, SP_ST_ABSENT);
    sp_flush_edges(data); /* F4: host.pressed がすでに false でも、行列と出した押下を片付ける */
    sp_motion_reset(&data->motion);
    sp_run_reset(data);
}

static void sp_enter_stuck(struct sp_data *data, const struct sp_frame *fr, bool tilt_stuck,
                           uint16_t rx, uint16_t ry) {
    data->stuck_by_button = data->host.pressed;
    data->stuck_x = fr->x;
    data->stuck_y = fr->y;
    LOG_WRN("固着: %s%s", tilt_stuck ? "傾きが動かない " : "", data->stuck_by_button ? "ボタンが押されたまま" : "");

    if (data->host.pressed) {
        sp_host_stuck(&data->host); /* 離しを出し、押下 0 を見るまで無視（規則 8） */
    }
    sp_flush_edges(data); /* F4: 規則 5「固着に入ったら行列を捨てる」 */
    sp_motion_reset(&data->motion);

    /* 傾きで入ったなら、保存済みの中心の ±0.1 以内のときだけ新しい中心にする
     * （RAM 上。保存は間引く）。外なら何もせず、変化を待つ。 */
    if (tilt_stuck && data->have_centre && sp_within(rx, data->saved.x, SP_TRACK_WINDOW) &&
        sp_within(ry, data->saved.y, SP_TRACK_WINDOW)) {
        data->ram = (struct sp_centre){.x = rx, .y = ry};
        LOG_INF("固着した位置を中心にした: %u, %u", rx, ry);
        k_work_schedule(&sp_save_work, SP_SAVE_DELAY);
    }
    sp_set_state(data, SP_ST_STUCK);
}

static void sp_on_frame(struct sp_data *data, const struct sp_config *cfg, const struct sp_frame *fr,
                        int64_t now) {
    /* ---- 見えるようにする: 起動・再起動 ---- */
    if (!data->seen_frame || data->seen_boot_id != fr->boot_id) {
        static const char *const cause[] = {"電源投入", "BOD", "WDT", "その他"};

        if (data->seen_frame) {
            data->n_boot_change++;
            LOG_WRN("ポッドが再起動した: ブート ID %u → %u・要因 %s（累計 %u 回）", data->seen_boot_id,
                    fr->boot_id, cause[fr->reset_cause], data->n_boot_change);
        } else {
            LOG_INF("ポッドを見つけた: 版 %u・ブート ID %u・リセット要因 %s", fr->version, fr->boot_id,
                    cause[fr->reset_cause]);
        }
        data->seen_frame = true;
        data->seen_boot_id = fr->boot_id;
    }
    if (data->state == SP_ST_ABSENT) {
        sp_set_state(data, SP_ST_REST);
        sp_log_counters(data, "復帰");
    }

    /* ---- 傾き ---- */
    uint16_t rx = sp_ratio_q16(fr->x, fr->t);
    uint16_t ry = sp_ratio_q16(fr->y, fr->t);
    int32_t dx = 0, dy = 0;
    bool centred = true; /* 中心が無い間は「中心にある」とみなす */
    bool usable = data->have_centre && !data->recal;

    if (usable) {
        dx = (int32_t)rx - data->ram.x;
        dy = (int32_t)ry - data->ram.y;
        centred = sp_in_dead_zone(&cfg->motion, dx, dy);
    } else if (atomic_test_bit(data->flags, SP_F_LOADED)) {
        /* 保存値の有無が確定するまで採用を始めない（読み込み前に採用すると、
         * 起動のたびに保存値を上書きする）。 */
        sp_adopt_step(data, fr);
        if (!data->have_centre && !data->no_centre_warned &&
            now - data->no_centre_since >= SP_NO_CENTRE_WARN_MS) {
            data->no_centre_warned = true;
            LOG_WRN("中心を 1 分採用できていない（倒したまま？ X/T=%u Y/T=%u・0.5=32768）", rx, ry);
        }
    }

    /* 状態を動かす「押下」は、固着のマスクを通したあとの状態（出力待ちを含む）。 */
    bool pressed = data->host.pressed || data->pending > 0;

    /* ---- 遷移 ---- */
    if (data->state == SP_ST_STUCK) {
        bool moved = !sp_within(fr->x, data->stuck_x, SP_STABLE_LSB) ||
                     !sp_within(fr->y, data->stuck_y, SP_STABLE_LSB);
        bool unmasked = data->stuck_by_button && !data->host.mask;

        /* 抜ける条件（K_SPEC §4）: 傾きが変わった／ボタンの無視が解けた／
         * **（マスク後の）押下が立った**（F6: 傾きで固着している間に押されたら、
         * 固着を抜けて普通に扱う。抜けないと 2 秒周期のままで、クリックは規則 3 の
         * 800ms に掛かって消え、押しっぱなしは 5 分で切れない）。
         * 押下で固着しているボタンはマスクされているので pressed は立たない。 */
        if (!moved && !unmasked && !pressed) {
            return;
        }
        /* **「静止」へ戻る**（F7。仕様どおり）。傾いたまま／押されているなら、
         * すぐ下の「静止」の判定がこの同じフレームで「動作」へ進める。 */
        sp_set_state(data, SP_ST_REST);
        sp_motion_reset(&data->motion);
    }

    if (data->state == SP_ST_REST) {
        if (!centred || pressed) {
            sp_enter_active(data, fr, now);
        } else if (usable) {
            sp_track_centre(data, rx, ry);
        }
    }

    if (data->state != SP_ST_ACTIVE) {
        return;
    }

    /* 中心かつ非押下が hold_ms 続いたら「静止」へ。 */
    if (centred && !pressed) {
        if (data->centred_since == 0) {
            data->centred_since = now;
        } else if (now - data->centred_since >= cfg->hold_ms) {
            sp_set_state(data, SP_ST_REST);
            sp_motion_reset(&data->motion);
            return;
        }
    } else {
        data->centred_since = 0;
    }

    /* 傾きが不変かどうか（最初の 1 枚から ±3LSB を出たら数え直し）。
     *
     * ⚠️ **仮の規則（F9・provisional-values.md に載せること）。**
     * 倒れたままの傾きが 3LSB を超えて揺れると（例: 7 秒ごとに 5LSB）、ここが
     * 毎回数え直しになり、**固着に永久に入らない**（机上の模擬で 35 分間 83Hz の
     * まま・移動を出し続け、ZMK は眠れない）。±3 は仕様の数字だが、
     * **実物の ADC の雑音を測っていない。**
     * TODO(F9): 試験 3・7 で静止時と倒したままの揺れ幅を測り、(a) 幅を広げる、
     * (b) 「直近 N 秒の最大−最小」で見る、のどちらかに決める。仕様も直す。 */
    if (!sp_within(fr->x, data->anchor_x, SP_STABLE_LSB) || !sp_within(fr->y, data->anchor_y, SP_STABLE_LSB)) {
        data->anchor_x = fr->x;
        data->anchor_y = fr->y;
        data->anchor_since = now;
    }

    /* 固着: 「動作」のまま連続 stuck_after、傾きが不変か、ボタンが押されたまま。 */
    if (now - data->active_since >= cfg->stuck_after_ms) {
        bool tilt_stuck = now - data->anchor_since >= cfg->stuck_after_ms;
        bool btn_stuck = data->host.pressed && data->press_since != 0 &&
                         now - data->press_since >= cfg->stuck_after_ms;

        if (tilt_stuck || btn_stuck) {
            sp_enter_stuck(data, fr, tilt_stuck, rx, ry);
            return;
        }
    }

    /* ---- 変換 ---- */
    if (usable && !centred) {
        /* 経過時間ぶん進める。静止から入った 1 枚目（250ms 空いている）で飛ばないよう、
         * 動作の周期 2 回ぶんで頭を打つ。 */
        uint32_t dt = (uint32_t)CLAMP(now - data->last_frame, 1, 2 * (int64_t)cfg->active_ms);
        int32_t ox, oy;

        sp_motion_step(&cfg->motion, &data->motion, dx, dy, dt, &ox, &oy);
        sp_report_motion(data, ox, oy);
    } else {
        sp_motion_reset(&data->motion);
    }
}

/* 1 回読む。錠を取ったまま呼ぶ。 */
static void sp_poll(const struct device *dev, int64_t now) {
    struct sp_data *data = dev->data;
    const struct sp_config *cfg = dev->config;
    uint8_t buf[SP_FRAME_LEN];
    struct sp_frame fr;
    uint32_t dt = (uint32_t)MIN(now - data->last_poll, UINT32_MAX);
    bool was_synced = data->host.synced;
    int rc;

    data->last_poll = now;

    rc = sp_bus_pm(cfg->i2c.bus, PM_DEVICE_ACTION_RESUME);
    if (rc == 0) {
        int64_t t0 = k_uptime_get();

        rc = i2c_read_dt(&cfg->i2c, buf, sizeof(buf));
        if (rc < 0) {
            /* TWIM ドライバは NACK もタイムアウトも -EIO で返す。かかった時間で分ける。 */
            if (k_uptime_get() - t0 >= CONFIG_I2C_NRFX_TRANSFER_TIMEOUT) {
                data->n_timeout++;
            } else {
                data->n_nack++;
            }
        }
    } else {
        LOG_ERR("I2C を起こせなかった (%d)", rc);
    }
    /* **読めても読めなくても必ず寝かせる。**起こしたままだと TWIM の電流が乗り続ける。 */
    (void)sp_bus_pm(cfg->i2c.bus, PM_DEVICE_ACTION_SUSPEND);

    enum sp_verdict v = sp_host_feed(&data->host, (rc == 0) ? buf : NULL, sizeof(buf), dt, &fr);

    if (v == SP_ACCEPT) {
        sp_on_frame(data, cfg, &fr, now);
        data->last_frame = now;
    } else {
        sp_run_reset(data); /* 「連続 8 フレーム」は失敗で途切れる */
        if (was_synced && !data->host.synced) {
            sp_enter_absent(data, "3 回以上続けて読めず 150ms 以上たった");
        }
    }

    if (now - data->last_stats >= SP_STATS_PERIOD_MS) {
        data->last_stats = now;
        sp_log_counters(data, "定期");
    }
}

static uint32_t sp_period_ms(const struct sp_data *data, const struct sp_config *cfg) {
    uint32_t p;

    switch (data->state) {
    case SP_ST_ACTIVE:
        p = cfg->active_ms;
        break;
    case SP_ST_REST:
        p = cfg->rest_ms;
        break;
    case SP_ST_STUCK:
        p = cfg->stuck_ms;
        break;
    default:
        p = cfg->absent_ms;
        break;
    }
    if (data->recal && data->state != SP_ST_ABSENT) {
        p = cfg->active_ms; /* 取り直しは 8 フレームを待たせない */
    }
    if (atomic_test_bit(data->flags, SP_F_LINK_DOWN)) {
        p = MAX(p, cfg->absent_ms); /* 届け先が無い間は 2 秒 */
    }
    return p;
}

/* 止める（SLEEP・ZMK からの suspend）。**呼ぶ側のスレッドで最後までやる。**
 * ZMK は SLEEP の事象を出した直後に全デバイスを suspend して sys_poweroff() に
 * 入るので、こちらのスレッドに任せると間に合わない。 */
static void sp_stop(const struct device *dev, enum sp_flag why) {
    struct sp_data *data = dev->data;
    const struct sp_config *cfg = dev->config;

    /* zmk_pm_soft_off() は **初期化に失敗したデバイスにも** SUSPEND を掛ける
     * （device_is_ready を見ない）。錠が未初期化のまま触らない。 */
    if (!device_is_ready(dev)) {
        return;
    }

    k_mutex_lock(&data->lock, K_FOREVER); /* 転送の途中なら終わるまで待つ */
    atomic_set_bit(data->flags, why);
    sp_host_drop(&data->host);
    sp_enter_absent(data, "止める"); /* 行列を捨て、出した押下があれば離す（規則 6・F4） */

    /* **resume → suspend をやり直して、ピンを確実に sleep 状態へ戻す**（F8）。
     * zmk_pm_soft_off() は全デバイスを**前から順に** suspend するので、i2c は
     * このデバイスより先に止められる（転送の途中でも）。そのとき読み出しは
     * タイムアウトし、TWIM ドライバのバス復旧が SCL を GPIO で叩いたあと、
     * PM 上は SUSPENDED なのでピンを戻さない（i2c_nrfx_twim_common.c の
     * i2c_nrfx_twim_recover_bus）。こちらの SUSPEND は -EALREADY で何もしない。
     * 一度 RESUME（default ピン＋有効化）してから SUSPEND（無効化＋sleep ピン）
     * すれば、どの経路で来ても同じ終わり方になる。 */
    (void)sp_bus_pm(cfg->i2c.bus, PM_DEVICE_ACTION_RESUME);
    (void)sp_bus_pm(cfg->i2c.bus, PM_DEVICE_ACTION_SUSPEND);
    k_mutex_unlock(&data->lock);
}

static void sp_start(const struct device *dev, enum sp_flag why) {
    struct sp_data *data = dev->data;

    if (!device_is_ready(dev)) {
        return;
    }
    atomic_clear_bit(data->flags, why);
    k_sem_give(&data->wake);
}

static void sp_thread(void *p1, void *p2, void *p3) {
    const struct device *dev = p1;
    struct sp_data *data = dev->data;
    const struct sp_config *cfg = dev->config;
    int64_t next_poll = k_uptime_get();

    ARG_UNUSED(p2);
    ARG_UNUSED(p3);

    while (true) {
        if (sp_stopped(data)) {
            k_sem_take(&data->wake, K_FOREVER);
            next_poll = k_uptime_get();
            continue;
        }

        k_mutex_lock(&data->lock, K_FOREVER);
        int64_t now = k_uptime_get();

        if (!sp_stopped(data)) { /* 錠を待つ間に止められたかもしれない */
            if (atomic_test_and_clear_bit(data->flags, SP_F_LINK_CHANGED)) {
                /* 左手は切断時に自分で離しを作る（input_split.c）。こちらの
                 * 「出した状態」を捨て、次の正常フレームで状態を合わせ直す。 */
                sp_host_drop(&data->host);
                sp_enter_absent(data, "分割リンクが変わった"); /* 行列も捨てる（F4） */
                if (!atomic_test_bit(data->flags, SP_F_LINK_DOWN)) {
                    /* **上がった直後は不在周期ぶん待ってから状態を合わせる**（F10）。
                     * この事象は BT の接続時点で来る。左の購読（GATT の発見）は
                     * まだ済んでいないので、すぐ読むと「押下を合わせる押し」が
                     * 届かず、あとの離しだけが左に届く。 */
                    next_poll = now + cfg->absent_ms;
                }
            }
            if (atomic_test_and_clear_bit(data->flags, SP_F_RECAL)) {
                data->recal = true;
                data->recal_deadline = now + SP_RECAL_TIMEOUT_MS;
                sp_run_reset(data);
                sp_motion_reset(&data->motion);
                next_poll = now;
                LOG_INF("中心を取り直す（スティックから手を離すこと）");
            }
            if (data->recal && now >= data->recal_deadline) {
                data->recal = false;
                LOG_WRN("中心を取り直せなかった（%s）。前の中心のまま",
                        data->state == SP_ST_ABSENT ? "ポッドが居ない" : "そろわない／中心らしくない");
            }

            sp_drain_edge(data, cfg, now);

            if (now >= next_poll) {
                sp_poll(dev, now);
                next_poll = now + sp_period_ms(data, cfg);
            }
        }

        int64_t until = next_poll;

        if (data->pending > 0) {
            until = MIN(until, data->last_edge + cfg->replay_gap_ms);
        }
        k_mutex_unlock(&data->lock);

        int64_t wait = until - k_uptime_get();

        k_sem_take(&data->wake, K_MSEC(MAX(wait, 0)));
    }
}

/* ------------------------------------------------------------------ */
/* 外から                                                              */

int hhkb_stick_pod_recalibrate(void) {
    struct sp_data *data = sp_dev0->data;

    if (!device_is_ready(sp_dev0)) {
        return -ENODEV;
    }
    atomic_set_bit(data->flags, SP_F_RECAL);
    k_sem_give(&data->wake);
    return 0;
}

/* ZMK の活動状態。**SLEEP になったら止める。**ACTIVE/IDLE に戻るのは
 * 「眠ろうとして失敗した」ときだけ（成功すれば System OFF で、次は起動から）。 */
static int sp_zmk_listener(const zmk_event_t *eh) {
    const struct zmk_activity_state_changed *act = as_zmk_activity_state_changed(eh);

    if (act != NULL) {
        if (act->state == ZMK_ACTIVITY_SLEEP) {
            sp_stop(sp_dev0, SP_F_STOP_SLEEP);
        } else {
            sp_start(sp_dev0, SP_F_STOP_SLEEP);
        }
        return ZMK_EV_EVENT_BUBBLE;
    }

#if SP_HAS_SPLIT_LINK
    const struct zmk_split_peripheral_status_changed *link =
        as_zmk_split_peripheral_status_changed(eh);

    if (link != NULL) {
        /* BT のスレッドから来る。旗を立てるだけにして、後始末はスレッドで。 */
        struct sp_data *data = sp_dev0->data;

        if (!device_is_ready(sp_dev0)) {
            return ZMK_EV_EVENT_BUBBLE;
        }

        atomic_set_bit_to(data->flags, SP_F_LINK_DOWN, !link->connected);
        atomic_set_bit(data->flags, SP_F_LINK_CHANGED);
        k_sem_give(&data->wake);
    }
#endif
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(hhkb_stick_pod, sp_zmk_listener);
ZMK_SUBSCRIPTION(hhkb_stick_pod, zmk_activity_state_changed);
#if SP_HAS_SPLIT_LINK
ZMK_SUBSCRIPTION(hhkb_stick_pod, zmk_split_peripheral_status_changed);
#endif

/* ZMK の pm.c は、SLEEP でも soft off でも全デバイスに SUSPEND を掛ける。
 * **soft off（電池切れ・&soft_off）は活動状態の事象を出さない**ので、
 * 上の listener だけでは止まらない。こちらで受ける。 */
static int sp_pm_action(const struct device *dev, enum pm_device_action action) {
    switch (action) {
    case PM_DEVICE_ACTION_SUSPEND:
        sp_stop(dev, SP_F_STOP_PM);
        return 0;
    case PM_DEVICE_ACTION_RESUME:
        sp_start(dev, SP_F_STOP_PM);
        return 0;
    default:
        return -ENOTSUP;
    }
}

#if IS_ENABLED(CONFIG_SETTINGS)
static int sp_settings_set(const char *key, size_t len, settings_read_cb read_cb, void *cb_arg) {
    struct sp_data *data = sp_dev0->data;
    const char *next;

    if (!device_is_ready(sp_dev0)) {
        return 0;
    }

    if (settings_name_steq(key, SP_SETTINGS_KEY, &next) && next == NULL) {
        struct sp_centre c;

        if (len != sizeof(c)) {
            return -EINVAL;
        }

        ssize_t rc = read_cb(cb_arg, &c, sizeof(c));

        if (rc < 0) {
            return (int)rc;
        }

        k_mutex_lock(&data->lock, K_FOREVER);
        data->saved = data->ram = c;
        data->have_centre = true;
        sp_run_reset(data);
        k_mutex_unlock(&data->lock);
        LOG_INF("保存してあった中心: %u, %u", c.x, c.y);
        return 0;
    }
    return -ENOENT;
}

/* settings_load() が全部読み終えたあとに呼ばれる。ここで初めて
 * 「保存値が無い」と言える。 */
static int sp_settings_commit(void) {
    struct sp_data *data = sp_dev0->data;

    data->no_centre_since = k_uptime_get();
    atomic_set_bit(data->flags, SP_F_LOADED);
    return 0;
}

SETTINGS_STATIC_HANDLER_DEFINE(hhkb_stick_pod, SP_SETTINGS_TREE, NULL, sp_settings_set,
                               sp_settings_commit, NULL);
#endif /* CONFIG_SETTINGS */

static K_THREAD_STACK_DEFINE(sp_stack, CONFIG_HHKB_STICK_POD_STACK_SIZE);

static int sp_init(const struct device *dev) {
    struct sp_data *data = dev->data;
    const struct sp_config *cfg = dev->config;
    int rc;

    if (!i2c_is_ready_dt(&cfg->i2c)) {
        LOG_ERR("I2C が使えない");
        return -ENODEV;
    }

    /* TWIM は起動時に有効の状態で始まる（pm_device_driver_init が RESUME を
     * 呼ぶ）。**ここで一度寝かせる。**以後は読む間だけ起こす。 */
    rc = sp_bus_pm(cfg->i2c.bus, PM_DEVICE_ACTION_SUSPEND);
    if (rc < 0) {
        LOG_ERR("I2C を寝かせられない (%d)。PM_DEVICE が無い？", rc);
        return rc;
    }

    data->dev = dev;
    data->state = SP_ST_ABSENT; /* 「不在」から始める */
    k_mutex_init(&data->lock);
    k_sem_init(&data->wake, 0, 1);
    k_work_init_delayable(&sp_save_work, sp_save_work_cb);
    sp_host_init(&data->host, sp_edge, data);
    sp_motion_reset(&data->motion);
    data->last_poll = data->last_frame = data->last_stats = k_uptime_get();

#if !IS_ENABLED(CONFIG_SETTINGS)
    atomic_set_bit(data->flags, SP_F_LOADED); /* 保存先が無い。毎回採用し直す */
#endif
#if SP_HAS_SPLIT_LINK
    atomic_set_bit(data->flags, SP_F_LINK_DOWN); /* 繋がったら事象が来る */
#endif

    k_thread_create(&data->thread, sp_stack, K_THREAD_STACK_SIZEOF(sp_stack), sp_thread,
                    (void *)dev, NULL, NULL, K_PRIO_PREEMPT(CONFIG_HHKB_STICK_POD_THREAD_PRIORITY),
                    0, K_NO_WAIT);
    k_thread_name_set(&data->thread, "stick_pod");
    return 0;
}

/* 規則 6: 固着までの時間 < ZMK のスリープまでの時間（F12）。SLEEP 直前の離しは
 * ホストに届かないので、押しっぱなしは固着で先に解いておく必要がある。 */
#if IS_ENABLED(CONFIG_ZMK_SLEEP)
#define SP_ASSERT_STUCK_BEFORE_SLEEP(n)                                                            \
    BUILD_ASSERT(DT_INST_PROP(n, stuck_after_seconds) * 1000 < CONFIG_ZMK_IDLE_SLEEP_TIMEOUT,      \
                 "stuck-after-seconds は CONFIG_ZMK_IDLE_SLEEP_TIMEOUT より短いこと（規則 6）")
#else
#define SP_ASSERT_STUCK_BEFORE_SLEEP(n) BUILD_ASSERT(1, "")
#endif

#define SP_INST(n)                                                                                 \
    BUILD_ASSERT(DT_INST_PROP(n, full_scale_permille) > DT_INST_PROP(n, dead_zone_permille),       \
                 "full-scale-permille は dead-zone-permille より大きいこと");                      \
    BUILD_ASSERT(DT_INST_PROP(n, full_scale_permille) <= 999,                                      \
                 "full-scale-permille は 999 まで（Q16 の 16bit に収まらない）");                  \
    BUILD_ASSERT(DT_INST_PROP(n, full_scale_permille) > 200,                                       \
                 "full-scale-permille は中心採用の窓（0.5±0.2 = 200）より大きいこと");            \
    BUILD_ASSERT(3 * DT_INST_PROP(n, rest_period_ms) + 50 <= SP_GAP_MS,                            \
                 "rest-period-ms を延ばすなら SP_GAP_MS（規則 3）も 3 倍＋50ms に直すこと");       \
    BUILD_ASSERT(DT_INST_PROP(n, replay_gap_ms) >= 16, "replay-gap-ms は 16 以上（規則 5）");      \
    SP_ASSERT_STUCK_BEFORE_SLEEP(n);                                                               \
    BUILD_ASSERT(DT_INST_PROP(n, curve_exponent) >= 1 && DT_INST_PROP(n, curve_exponent) <= 3,     \
                 "curve-exponent は 1〜3");                                                        \
    static struct sp_data sp_data_##n;                                                             \
    static const struct sp_config sp_cfg_##n = {                                                   \
        .i2c = I2C_DT_SPEC_INST_GET(n),                                                            \
        .rest_ms = DT_INST_PROP(n, rest_period_ms),                                                \
        .active_ms = DT_INST_PROP(n, active_period_ms),                                            \
        .absent_ms = DT_INST_PROP(n, absent_period_ms),                                            \
        .stuck_ms = DT_INST_PROP(n, stuck_period_ms),                                              \
        .hold_ms = DT_INST_PROP(n, active_hold_ms),                                                \
        .replay_gap_ms = DT_INST_PROP(n, replay_gap_ms),                                           \
        .stuck_after_ms = DT_INST_PROP(n, stuck_after_seconds) * 1000U,                            \
        .motion =                                                                                  \
            {                                                                                      \
                .dead_q16 = DT_INST_PROP(n, dead_zone_permille) * SP_Q16_ONE / 1000,               \
                .full_q16 = DT_INST_PROP(n, full_scale_permille) * SP_Q16_ONE / 1000,              \
                .max_speed = DT_INST_PROP(n, max_speed),                                           \
                .curve = DT_INST_PROP(n, curve_exponent),                                          \
            },                                                                                     \
    };                                                                                             \
    PM_DEVICE_DT_INST_DEFINE(n, sp_pm_action);                                                     \
    DEVICE_DT_INST_DEFINE(n, sp_init, PM_DEVICE_DT_INST_GET(n), &sp_data_##n, &sp_cfg_##n,         \
                          POST_KERNEL, CONFIG_INPUT_INIT_PRIORITY, NULL);

DT_INST_FOREACH_STATUS_OKAY(SP_INST)
