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
#include <zmk/split/transport/types.h>
#endif

#if IS_ENABLED(CONFIG_ZMK_SPLIT) && !IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
#include <zmk/split/bluetooth/peripheral.h>
#include <zmk/split/transport/peripheral.h>
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
    STATE_RECOVERED,        /* **復帰の合図**: 1 秒点灯 → 消灯。色は復帰した系統 */
    STATE_BATT_REPLACE,     /* 橙 2 回点滅 / 15 秒 */
    STATE_BATT_LOW,         /* 橙 1 回点滅 / 30 秒 */
    STATE_LINK_LOST,        /* 分割・ホストの未接続。**交互に出す**（下記） */
    STATE_IDLE,             /* 消灯 */
};

/*
 * **1 つのリンクの状態。**分割（左右間）とホストで独立に持つ。
 *
 * 決定表: docs/hardware/decisions/2026-08-16-led-state-table.md
 *   未ボンド        … 相手を知らない＝ペアリング待ち。**速い点滅（1 秒に 4 回）**
 *   ボンド済み未接続 … 相手は知っていて探している。**遅い点滅（1 秒に 2 回）**
 *   接続済み        … 消灯
 */
enum link_state {
    LINK_UNBONDED,
    LINK_DISCONNECTED,
    LINK_CONNECTED,
};

/* --- 実機の表から来る時定数 ------------------------------------------- */
#define BOOT_ON_MS       3000  /* 「青色に点灯したあと、消灯」 */
#define RECOVERED_ON_MS  1000  /* 復帰の合図。実機も機器切替で「点灯 → 消灯」 */
#define SLOW_BLINK_MS     250  /* **1 秒に 2 回** = 250ms on/off。ボンド済み・未接続 */
#define FAST_BLINK_MS     125  /* **1 秒に 4 回** = 125ms on/off。未ボンド */
#define PULSE_MS          120  /* 橙の 1 回ぶんの点灯 */
#define PULSE_GAP_MS      280  /* 橙 2 回点滅の間隔 */
#define BATT_LOW_MS     30000  /* 橙 1 回点滅を 30 秒間隔 */
#define BATT_REPLACE_MS 15000  /* 橙 2 回点滅を 15 秒間隔 */

/* 電池の 2 段階。ZMK の % は zmk_battery_state_changed で降ってくる。
 * **打ち止め電圧の判定は low_battery_off.c の担当**で、こちらは表示だけ。
 * 同じ数字を 2 か所に書かないため、ここは % の閾値のみを持つ。 */
#define BATT_LOW_PCT     15
#define BATT_REPLACE_PCT  5

/* **左（セントラル）と、分割でない構成だけが持つ。**
 * 右にホストとの接続は無いので、変数ごと存在させない
 * （存在させると「更新されないまま既定値」で青が点滅し続ける）。 */
#if IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL) || !IS_ENABLED(CONFIG_ZMK_SPLIT)
#define HAS_HOST_LINK 1
static enum link_state host_link = LINK_DISCONNECTED;
#else
#define HAS_HOST_LINK 0
#endif

/* 分割リンク。分割でなければ「繋がっている」扱いで、表示に出さない。 */
#if IS_ENABLED(CONFIG_ZMK_SPLIT)
#define HAS_SPLIT_LINK 1
static enum link_state split_link = LINK_DISCONNECTED;
#else
#define HAS_SPLIT_LINK 0
#endif

/*
 * 「相手と繋がっているか」。左では右手、右では左（セントラル）を指す。
 *
 * ⚠️ **初期値は左右で違う。**
 *   左（セントラル）… 毎 tick に transport の get_status() で読み直すので
 *                      初期値は事実上使われない。true でよい。
 */
static uint8_t battery_pct = 100;
static bool booting = true;

/*
 * **復帰の合図を出すためのもの。**
 *
 * 接続中は消灯（実機どおり）なので、**繋がった瞬間に消えるだけ**だと
 * 見ていない限り気づけない（2026-08-16 に利用者の指摘）。
 * 直前まで未接続だったなら、消える前に 1 秒点灯して知らせる。
 *
 * ⚠️ **色は「復帰した系統」の色。**分割が繋がったなら緑、ホストなら青。
 * 青で一律にしていたのを利用者に指摘されて直した:
 * 「左右間の接続に関するものが緑なのであれば、左右接続の瞬間は緑点灯
 * であるべきでは？」——**色に意味を持たせると決めた以上、合図も同じ色。**
 */
static enum led_color announce_color; /* COLOR_OFF なら合図なし */
static enum zmk_activity_state activity = ZMK_ACTIVITY_ACTIVE;

static void set_color(enum led_color c) {
    gpio_pin_set_dt(&led_r, c == COLOR_AMBER);
    gpio_pin_set_dt(&led_g, c == COLOR_AMBER || c == COLOR_GREEN);
    gpio_pin_set_dt(&led_b, c == COLOR_BLUE);
}

#if IS_ENABLED(CONFIG_ZMK_SPLIT) && !IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
/*
 * **右手が「セントラルと繋がっているか」を読む。**
 *
 * 2026-08-16 に実機で露見した: 事象
 * （zmk_split_peripheral_status_changed）だけに頼っていたため、
 * **繋がっているのに点滅したままになった。**事象は connected()/
 * disconnected() でしか飛ばず、起動直後の 3 秒（青の点灯中）に
 * 繋がるとその 1 回を取り逃す。
 *
 * peripheral.c も get_status を公開していて、中身は
 * zmk_split_bt_peripheral_is_connected() そのもの。**左と同じように
 * 毎 tick 読み直す。**事象は「すぐ反応させる」ためだけに使う。
 */
static enum link_state read_split_link(void) {
    bool connected = true;

    STRUCT_SECTION_FOREACH(zmk_split_transport_peripheral, t) {
        if (t->api == NULL || t->api->get_status == NULL) {
            continue;
        }
        struct zmk_split_transport_status st = t->api->get_status();

        /* 左と同じ理由で、available / enabled が偽なら「未接続」に倒す。
         * 黙って continue して true を返さない。 */
        if (!st.available || !st.enabled ||
            st.connections != ZMK_SPLIT_TRANSPORT_CONNECTIONS_STATUS_ALL_CONNECTED) {
            connected = false;
            break;
        }
    }

    if (connected) {
        return LINK_CONNECTED;
    }
    /* **右はボンドの有無が分かる**（peripheral.h の公開 API）。
     * 未ボンド＝相手を知らない＝ペアリング待ち → 速い点滅。 */
    return zmk_split_bt_peripheral_is_bonded() ? LINK_DISCONNECTED : LINK_UNBONDED;
}
#endif

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
static enum link_state read_split_link(void) {
    STRUCT_SECTION_FOREACH(zmk_split_transport_central, t) {
        if (t->api == NULL || t->api->get_status == NULL) {
            continue;
        }
        struct zmk_split_transport_status st = t->api->get_status();

        /* ⚠️ **available / enabled で continue しないこと。**
         *
         * 2026-08-16 に実機で露見したバグ。ここを continue にしていたため、
         * 「見るべき transport が 1 つも無い」→ 最後の return true に落ち、
         * **繋がっていないのに『繋がっている』と報告していた。**
         * だから右の電源を切っても左の緑が出なかった。
         *
         * available は `!CLEAR_BONDS_ON_START && settings_loaded`、
         * enabled は set_enabled() の結果（central.c）。
         * **どちらも「まだ使えない／止めている」という意味であって、
         * 「繋がっている」ではない。**警告灯の既定は安全側＝未接続にする。 */
        if (!st.available || !st.enabled) {
            return LINK_DISCONNECTED;
        }
        if (st.connections != ZMK_SPLIT_TRANSPORT_CONNECTIONS_STATUS_ALL_CONNECTED) {
            /* ⚠️ **左は「分割相手とボンド済みか」を知る公開 API が無い。**
             * 右には zmk_split_bt_peripheral_is_bonded() があるが、
             * central.c に対応物は無く peripherals[] は static。
             * bt_foreach_bond() で数える手はあるが、ホストのボンドと
             * 混ざるので peer の照合が要る。**今回はそこまでやらない。**
             * 左は一律「ボンド済み・未接続」＝遅い点滅に寄せる。
             * → decisions/2026-08-16-led-state-table.md の非対称の項 */
            return LINK_DISCONNECTED;
        }
    }

    return LINK_CONNECTED;
}
#endif

static enum led_state current_state(void) {
    /* **sleep のときだけ消す。idle では消さない。**
     * idle は 30 秒無操作で入るので、ここで消すと未接続の警告が
     * 30 秒で勝手に消える（2026-08-16 に利用者の指摘で直した）。 */
    if (activity == ZMK_ACTIVITY_SLEEP) {
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
    /* 分割・ホストのどちらかが繋がっていなければ知らせる。
     * **どちらを出すかは blink_work_cb 側で交互に決める**
     * （両方未接続のとき、片方だけ出すともう片方の異常が見えない）。
     *
     * ⚠️ ホストの判定はセントラル（左）だけ。右にホストとの接続は無い。
     * 2026-08-16 に、この囲いを忘れて**右で青が点滅し続けた。** */
#if HAS_SPLIT_LINK
    if (split_link != LINK_CONNECTED) {
        return STATE_LINK_LOST;
    }
#endif
#if HAS_HOST_LINK
    if (host_link != LINK_CONNECTED) {
        return STATE_LINK_LOST;
    }
#endif

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

    /* **状態を決める前に読む。**後で読むと表示が 1 tick 遅れる。
     * イベントが飛ばない経路があるので毎回確かめる
     * （専用のタイマーは増やさない）。 */
#if HAS_SPLIT_LINK
    enum link_state prev_split = split_link;
    split_link = read_split_link();
    if (prev_split != LINK_CONNECTED && split_link == LINK_CONNECTED && !booting) {
        announce_color = COLOR_GREEN; /* **分割が繋がった → 緑で知らせる** */
    }
#endif

#if HAS_HOST_LINK
    /* ⚠️ **ホストも毎回読み直す。**
     * zmk_ble_active_profile_changed が「プロファイルの切り替え」でしか
     * 飛ばない可能性があり、事象だけに頼ると
     * **繋がっているのに青が点滅し続ける**。実際の状態を見るのが確実。 */
    enum link_state prev_host = host_link;
    host_link = zmk_ble_active_profile_is_connected() ? LINK_CONNECTED
                : zmk_ble_active_profile_is_open()    ? LINK_UNBONDED
                                                      : LINK_DISCONNECTED;
    if (prev_host != LINK_CONNECTED && host_link == LINK_CONNECTED && !booting) {
        announce_color = COLOR_BLUE; /* **ホストが繋がった → 青で知らせる** */
    }
#endif

    enum led_state st = current_state();

    /* 合図は「全部繋がって消灯に落ちる」ときだけ出す。
     * まだ他が未接続なら、そちらの点滅を優先する。 */
    if (announce_color != COLOR_OFF && st == STATE_IDLE) {
        st = STATE_RECOVERED;
    } else if (st != STATE_IDLE && st != STATE_RECOVERED) {
        announce_color = COLOR_OFF; /* 出しそびれたら捨てる */
    }

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

    case STATE_RECOVERED:
        /* **復帰の合図。**1 秒点けてから消灯に落ちる。
         * **色は復帰した系統**（分割＝緑・ホスト＝青）。
         * 実機も機器切替で「点灯したあと、消灯」とする。 */
        set_color(announce_color);
        announce_color = COLOR_OFF;
        next_ms = RECOVERED_ON_MS;
        break;

    case STATE_IDLE:
        set_color(COLOR_OFF);
        /* 消えている間も接続状態は見張る（分割は落ちうる）。 */
        next_ms = FAST_BLINK_MS * 4;
        break;

    case STATE_LINK_LOST: {
        /*
         * 未接続のリンクを知らせる。**両方未接続なら交互に出す**
         * （利用者の判断。片方だけ出すと、もう片方の異常が見えない）。
         *
         *   色     … 緑＝左右間 / 青＝ホスト
         *   速さ   … 4 回/秒＝未ボンド（ペアリング待ち）
         *            2 回/秒＝ボンド済み・未接続（探している）
         *
         * step の下位ビットで点灯／消灯、上位で「いまどちらの系統か」。
         */
        enum led_color c = COLOR_OFF;
        enum link_state ls = LINK_CONNECTED;

#if HAS_SPLIT_LINK && HAS_HOST_LINK
        bool split_bad = (split_link != LINK_CONNECTED);
        bool host_bad = (host_link != LINK_CONNECTED);
        /* 1 周（点灯＋消灯）ごとに系統を入れ替える。 */
        bool show_split = split_bad && (!host_bad || ((step >> 1) & 1) == 0);
        c = show_split ? COLOR_GREEN : COLOR_BLUE;
        ls = show_split ? split_link : host_link;
#elif HAS_SPLIT_LINK
        c = COLOR_GREEN;
        ls = split_link;
#elif HAS_HOST_LINK
        c = COLOR_BLUE;
        ls = host_link;
#endif

        bool on = (step & 1) == 0;
        set_color(on ? c : COLOR_OFF);
        next_ms = (ls == LINK_UNBONDED) ? FAST_BLINK_MS : SLOW_BLINK_MS;

        step = (step + 1) & 3; /* 0..3 で 2 周ぶん。上位ビットが系統の切替 */
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
    /* **起動時の点灯中は割り込まない**（3 秒を切ってしまう）。
     * 取りこぼしにはならない: 状態は毎 tick に読み直しているので、
     * 点灯が終わった次の tick で正しい表示に落ち着く。 */
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

        /* ⚠️ **idle では消さない。sleep でだけ消す。**
         *
         * 2026-08-16 に利用者の指摘で直した。当初は
         * `!= ZMK_ACTIVITY_ACTIVE` で一律に消していたが、
         * ZMK の idle は **30 秒無操作**（CONFIG_ZMK_IDLE_TIMEOUT の既定）。
         * **未接続の警告が 30 秒で勝手に消えていた。**
         * 放っておくと消えるのでは、いちばん見せたいものが見られない。
         *
         * sleep で消すのは正当（GPIO は状態を保持するので、点けたまま
         * 寝ると 30 分ぶん垂れ流す）。**idle で消す理由は無い。** */
        if (activity == ZMK_ACTIVITY_SLEEP) {
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

    /* 以下の事象は「すぐ描き直す」ためだけに使う。
     * **状態そのものは毎 tick に読み直している**ので、ここで値を
     * 持ち回らない（事象の取りこぼしで表示が固まるのを防ぐ）。 */
#if IS_ENABLED(CONFIG_ZMK_SPLIT) && !IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
    if (as_zmk_split_peripheral_status_changed(eh) != NULL) {
        refresh();
        return ZMK_EV_EVENT_BUBBLE;
    }
#endif

#if IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
    if (as_zmk_ble_active_profile_changed(eh) != NULL) {
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
