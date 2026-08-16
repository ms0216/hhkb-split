/*
 * XIAO 基板上の LED で、実機 HHKB の LED インジケーターを再現する。
 *
 * **これは新機能ではなく、欠落していた実機再現。**
 * 実機 HHKB Professional HYBRID には前面に LED インジケーターがあるのに、
 * この案件はその事実を記録していなかった（2026-08-16 に利用者の指摘で判明）。
 * 経緯と決定は docs/hardware/decisions/2026-08-16-status-led.md。
 *
 * --------------------------------------------------------------------------
 * 実機の状態表（出典: PFU 取扱説明書 P3PC-6641-05・2023 年 6 月）
 * --------------------------------------------------------------------------
 *   消灯                              接続モード / OFF モード
 *   青色点滅（1 秒に 2 回）            ペアリング待機モード
 *   青色点滅（1 秒に 4 回）            ペアリングモード
 *   青色点灯                          接続待機モード
 *   橙色 1 回点滅を 30 秒間隔          電池残量が少ない
 *   橙色 2 回点滅を 15 秒間隔          電池を交換
 *   電源オン時                        青色に点灯したあと、消灯
 *
 * **接続中は「消灯」が実機の正しい挙動。**常時点灯ではないので、
 * 乾電池 2 本でも電流の心配がほぼ無い（実機も同じ理由と思われる）。
 *
 * --------------------------------------------------------------------------
 * ⚠️ 実機に無い状態がある（**完全分割型ゆえ**）
 * --------------------------------------------------------------------------
 * 実機は一体型なので、状態表に「**右手と繋がっているか**」が無い。
 * だが左手は独立した 2 つの接続を持つ:
 *   - ホストへの広告・接続   … 実機の青がそのまま当たる
 *   - **右手のスキャン・接続** … **実機に対応が無い**
 *
 * 右手が落ちると利用者から見て「**キーの右半分が反応しない**」という
 * 最も切実な故障になる。ここに表示が無いのは実用上まずいので、
 * **実機に無い緑**を当て、**ホスト未接続より優先**する。
 *
 * --------------------------------------------------------------------------
 * ⚠️ ZMK に「広告中」「スキャン中」の事象は無い
 * --------------------------------------------------------------------------
 * 広告もスキャンも app/src/split/bluetooth/central.c と ble.c の内部に
 * 閉じていて、イベントマネージャに出てこない。よって
 * **「繋がっていない」を広告／ペアリング待機の代理として使う。**
 * 実機の状態表とは意味が厳密には一致しない。割り切りである。
 *
 * --------------------------------------------------------------------------
 * ⚠️ LED は 3 個ではなく **RGB 1 個**（Seeed Wiki: "3-in-one LED"）
 * --------------------------------------------------------------------------
 * 赤 P0.26 / 緑 P0.30 / 青 P0.06 が 1 パッケージの共通アノード。
 * **1 個なので赤+緑を同時に点けると、同じ一点が橙色に光る**
 * （3 個離れていたら 2 箇所が光るだけで橙には見えない）。
 * 極性は devicetree の GPIO_ACTIVE_LOW が持つので、**ここに反転を書かない**。
 *
 * SPDX-License-Identifier: MIT
 */

#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <zmk/activity.h>
#include <zmk/event_manager.h>
#include <zmk/events/activity_state_changed.h>
#include <zmk/events/battery_state_changed.h>

#if IS_ENABLED(CONFIG_ZMK_SPLIT)
#include <zmk/events/split_peripheral_status_changed.h>
#endif

#if IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
#include <zmk/ble.h>
#include <zmk/events/ble_active_profile_changed.h>
#include <zmk/split/transport/central.h>
#include <zmk/split/transport/types.h>
#endif

LOG_MODULE_REGISTER(hhkb_status_led, CONFIG_ZMK_LOG_LEVEL);

/* **エイリアスが無い基板では黙って無効化せず、ここで落とす。**
 * xiao_ble//zmk は Zephyr の xiao_ble.dts を #include するだけで
 * leds も aliases も削っていないことを上流で確認済み。 */
BUILD_ASSERT(DT_HAS_ALIAS(led0), "この基板に led0 のエイリアスが無い");
BUILD_ASSERT(DT_HAS_ALIAS(led1), "この基板に led1 のエイリアスが無い");
BUILD_ASSERT(DT_HAS_ALIAS(led2), "この基板に led2 のエイリアスが無い");

static const struct gpio_dt_spec led_r = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static const struct gpio_dt_spec led_g = GPIO_DT_SPEC_GET(DT_ALIAS(led1), gpios);
static const struct gpio_dt_spec led_b = GPIO_DT_SPEC_GET(DT_ALIAS(led2), gpios);

/* 実機の状態表に対応する色。橙は赤+緑（RGB 1 個なので混色になる）。 */
enum led_color {
    COLOR_OFF,
    COLOR_BLUE,   /* ホスト系。実機どおり */
    COLOR_AMBER,  /* 電池系。実機どおり */
    COLOR_GREEN,  /* **右手と繋がっていない。実機に無い・分割型固有** */
};

/*
 * 表示すべき状態。**上ほど優先。**
 * 同時に複数成立しうるので、必ず 1 つに畳んでから点ける
 * （状態ごとに別の work を走らせると競合して色が混ざる）。
 */
enum led_state {
    STATE_BOOT,             /* 起動直後: 青点灯 → 消灯 */
    STATE_BATT_REPLACE,     /* 橙 2 回点滅 / 15 秒 */
    STATE_BATT_LOW,         /* 橙 1 回点滅 / 30 秒 */
    STATE_PERIPHERAL_LOST,  /* **緑 1 秒に 2 回。分割型固有** */
    STATE_HOST_LOST,        /* 青 1 秒に 2 回（実機のペアリング待機相当） */
    STATE_IDLE,             /* 消灯 */
};

/* --- 実機の表から来る時定数 ------------------------------------------- */
#define BOOT_ON_MS       3000  /* 「青色に点灯したあと、消灯」 */
#define FAST_BLINK_MS     250  /* 1 秒に 2 回 = 250ms on / 250ms off */
#define PULSE_MS          120  /* 橙の 1 回ぶんの点灯 */
#define PULSE_GAP_MS      280  /* 橙 2 回点滅の間隔 */
#define BATT_LOW_MS     30000  /* 橙 1 回点滅を 30 秒間隔 */
#define BATT_REPLACE_MS 15000  /* 橙 2 回点滅を 15 秒間隔 */

/* 電池の 2 段階。ZMK の % は zmk_battery_state_changed で降ってくる。
 * **打ち止め電圧の判定は low_battery_off.c の担当**で、こちらは表示だけ。
 * 同じ数字を 2 か所に書かないため、ここは % の閾値のみを持つ。 */
#define BATT_LOW_PCT     15
#define BATT_REPLACE_PCT  5

static bool host_connected;
static bool peripheral_connected = true; /* 分割でなければ「繋がっている」扱い */
static uint8_t battery_pct = 100;
static bool booting = true;
static enum zmk_activity_state activity = ZMK_ACTIVITY_ACTIVE;

static void set_color(enum led_color c) {
    gpio_pin_set_dt(&led_r, c == COLOR_AMBER);
    gpio_pin_set_dt(&led_g, c == COLOR_AMBER || c == COLOR_GREEN);
    gpio_pin_set_dt(&led_b, c == COLOR_BLUE);
}

#if IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
/*
 * **左手が「右手と繋がっているか」を知る唯一の公開 API。**
 *
 * central.c の peripherals[] は static で外から見えず、
 * zmk/split/central.h にも接続状態を返す関数は無い。
 * だが transport 層は ZMK_SPLIT_TRANSPORT_CENTRAL_REGISTER =
 * STRUCT_SECTION_ITERABLE_NAMED で登録されているので、
 * **列挙して api->get_status() を呼べる。内部 static には触らない。**
 */
static bool peripherals_all_connected(void) {
    STRUCT_SECTION_FOREACH(zmk_split_transport_central, t) {
        if (t->api == NULL || t->api->get_status == NULL) {
            continue;
        }
        struct zmk_split_transport_status st = t->api->get_status();
        if (!st.available || !st.enabled) {
            continue;
        }
        if (st.connections != ZMK_SPLIT_TRANSPORT_CONNECTIONS_STATUS_ALL_CONNECTED) {
            return false;
        }
    }

    /* 使える transport が 1 つも無いときは、判定材料が無いということ。
     * **誤って緑を出さない**（起動直後はまだ登録前でここに来る）。 */
    return true;
}
#endif

static enum led_state current_state(void) {
    if (activity != ZMK_ACTIVITY_ACTIVE) {
        return STATE_IDLE;
    }
    if (booting) {
        return STATE_BOOT;
    }
    if (battery_pct <= BATT_REPLACE_PCT) {
        return STATE_BATT_REPLACE;
    }
    if (battery_pct <= BATT_LOW_PCT) {
        return STATE_BATT_LOW;
    }
    /* **右手を先に見る。**キーの半分が死ぬ方が切実。 */
    if (!peripheral_connected) {
        return STATE_PERIPHERAL_LOST;
    }
    if (!host_connected) {
        return STATE_HOST_LOST;
    }
    return STATE_IDLE; /* 接続中は消灯。実機どおり */
}

static void blink_work_cb(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(blink_work, blink_work_cb);

/*
 * 1 つの work だけで全パターンを出す。step は状態ごとの進行位置。
 * **状態が変わったら step を 0 に戻す**（前の色が残らないように）。
 */
static void blink_work_cb(struct k_work *work) {
    static enum led_state shown = STATE_IDLE;
    static uint8_t step;

#if IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
    /* **状態を決める前に読む。**後で読むと表示が 1 tick 遅れる。
     *
     * イベントが飛ばない経路があるので、ついでに毎回確かめる
     * （専用のタイマーは増やさない）。
     *
     * ⚠️ **host_connected も毎回読み直す。**
     * zmk_ble_active_profile_changed が「プロファイルの切り替え」でしか
     * 飛ばない可能性があり（上流で未確認）、事象だけに頼ると
     * **繋がっているのに青が点滅し続ける**。実際の状態を見るのが確実。 */
    peripheral_connected = peripherals_all_connected();
    host_connected = zmk_ble_active_profile_is_connected();
#endif

    enum led_state st = current_state();
    if (st != shown) {
        shown = st;
        step = 0;
    }

    uint32_t next_ms;

    switch (st) {
    case STATE_BOOT:
        /* 実機の「青色に点灯したあと、消灯」。
         * **点灯しきるまで booting を降ろさない。**降ろしてしまうと、
         * この 3 秒の間に来た事象の refresh() が青を途中で切る。 */
        set_color(COLOR_BLUE);
        if (step == 0) {
            step = 1;
            next_ms = BOOT_ON_MS;
        } else {
            booting = false;
            next_ms = 0; /* 次の tick で本来の状態を描く */
        }
        break;

    case STATE_IDLE:
        set_color(COLOR_OFF);
        /* 消えている間も接続状態は見張る（分割は落ちうる）。 */
        next_ms = FAST_BLINK_MS * 4;
        break;

    case STATE_PERIPHERAL_LOST:
    case STATE_HOST_LOST: {
        enum led_color c = (st == STATE_PERIPHERAL_LOST) ? COLOR_GREEN : COLOR_BLUE;
        step ^= 1;
        set_color(step ? c : COLOR_OFF);
        next_ms = FAST_BLINK_MS;
        break;
    }

    case STATE_BATT_LOW:
    case STATE_BATT_REPLACE: {
        /* 橙 1 回（低下）または 2 回（要交換）点滅して、長く休む。 */
        const uint8_t pulses = (st == STATE_BATT_REPLACE) ? 2 : 1;
        const uint32_t rest = (st == STATE_BATT_REPLACE) ? BATT_REPLACE_MS : BATT_LOW_MS;

        if (step >= pulses * 2) {
            step = 0;
        }
        bool on = (step % 2) == 0;
        set_color(on ? COLOR_AMBER : COLOR_OFF);
        step++;

        if (step >= pulses * 2) {
            next_ms = rest;   /* 最後の消灯ぶんを、そのまま休みに充てる */
            step = 0;
        } else {
            next_ms = on ? PULSE_MS : PULSE_GAP_MS;
        }
        break;
    }

    default:
        set_color(COLOR_OFF);
        next_ms = FAST_BLINK_MS * 4;
        break;
    }

    k_work_reschedule(&blink_work, K_MSEC(next_ms));
}

/* 状態が変わったので、待たずに描き直す。
 * **起動時の点灯中は割り込まない**（3 秒を切ってしまう）。 */
static void refresh(void) {
    if (booting) {
        return;
    }
    k_work_reschedule(&blink_work, K_NO_WAIT);
}

static int status_led_init(void) {
    if (!gpio_is_ready_dt(&led_r) || !gpio_is_ready_dt(&led_g) || !gpio_is_ready_dt(&led_b)) {
        LOG_ERR("LED の GPIO が使えない");
        return -ENODEV;
    }

    /* GPIO_ACTIVE_LOW は devicetree 側。ここでは論理値だけ扱う。 */
    gpio_pin_configure_dt(&led_r, GPIO_OUTPUT_INACTIVE);
    gpio_pin_configure_dt(&led_g, GPIO_OUTPUT_INACTIVE);
    gpio_pin_configure_dt(&led_b, GPIO_OUTPUT_INACTIVE);

    /* refresh() は booting 中に弾かれるので、ここは直接起こす。 */
    k_work_reschedule(&blink_work, K_NO_WAIT);
    return 0;
}

SYS_INIT(status_led_init, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);

static int status_led_listener(const zmk_event_t *eh) {
    if (as_zmk_activity_state_changed(eh) != NULL) {
        activity = zmk_activity_get_state();
        if (activity != ZMK_ACTIVITY_ACTIVE) {
            /* **点いたまま寝ると GPIO はその状態を保つ。**
             * 30 分ぶん垂れ流すので、寝る前に必ず消す。 */
            k_work_cancel_delayable(&blink_work);
            set_color(COLOR_OFF);
        } else {
            refresh();
        }
        return ZMK_EV_EVENT_BUBBLE;
    }

    const struct zmk_battery_state_changed *batt = as_zmk_battery_state_changed(eh);
    if (batt != NULL) {
        battery_pct = batt->state_of_charge;
        refresh();
        return ZMK_EV_EVENT_BUBBLE;
    }

#if IS_ENABLED(CONFIG_ZMK_SPLIT) && !IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
    /* **右手（周辺機）側。**この事象は peripheral.c が出すので、
     * 自分がセントラルと繋がっているかがそのまま分かる。 */
    const struct zmk_split_peripheral_status_changed *sp =
        as_zmk_split_peripheral_status_changed(eh);
    if (sp != NULL) {
        peripheral_connected = sp->connected;
        refresh();
        return ZMK_EV_EVENT_BUBBLE;
    }
#endif

#if IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
    if (as_zmk_ble_active_profile_changed(eh) != NULL) {
        host_connected = zmk_ble_active_profile_is_connected();
        refresh();
        return ZMK_EV_EVENT_BUBBLE;
    }
#endif

    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(hhkb_status_led, status_led_listener);
ZMK_SUBSCRIPTION(hhkb_status_led, zmk_activity_state_changed);
ZMK_SUBSCRIPTION(hhkb_status_led, zmk_battery_state_changed);

#if IS_ENABLED(CONFIG_ZMK_SPLIT) && !IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
ZMK_SUBSCRIPTION(hhkb_status_led, zmk_split_peripheral_status_changed);
#endif

#if IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
ZMK_SUBSCRIPTION(hhkb_status_led, zmk_ble_active_profile_changed);
#endif
