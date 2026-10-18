/*
 * 打ち止め電圧を割ったら、自分から止まる（open-gaps #25b）。
 *
 * 何が起きるか:
 *   レールが 1.7V を割ると nRF52840 はブラウンアウトでリセットする。
 *   電池は負荷が消えると電圧が戻るので、リセット → 起動 → 広告 →
 *   電圧降下 → リセット を繰り返す。
 *     - 残り少ない電池を早く使い切る
 *     - 使う側からは故障に見える
 *     - **低電圧での flash 書き込みでペアリング情報が壊れうる**
 *       （nRF52840 の NVMC は VDD ≧ 1.7V が条件）
 *
 * どう止めるか:
 *   ZMK が電池を測る周期（ZMK_BATTERY_REPORT_INTERVAL・既定 60 秒）と
 *   同じ周期の自前タイマーで、**driver がキャッシュしている電圧**を読む
 *   （ADC を余分に回さない）。打ち止め（devicetree の empty-millivolts）を
 *   下回った状態が規定回数続いたら zmk_pm_soft_off() に入る。
 *
 *   ⚠️ 2026-09-03 まで zmk_battery_state_changed を待ち受けていたが、
 *   ZMK 本体（app/src/battery.c）はその事象を **% が変わったときしか
 *   出さない**（last_state_of_charge != val1）。% が 0 に張り付くと
 *   2 回目が来ず、止まらなかった。周期で読む形に直した。
 *
 *   USB 給電中は判定しない。電源スイッチ OFF＋USB のとき分圧は 0mV を
 *   返すので、そのまま数えると USB でつないだ瞬間に soft off する。
 *
 * 復帰:
 *   電池を替えれば、背面の電源スイッチが電池を機械的に切り離しているので
 *   入れ直しで起動する。soft off の wake ピンには依存しない。
 *
 * ⚠️ **これはビルドが通っているだけで、実機では一度も動かしていない。**
 *    確かめるのは Task C4/C5（電池を実際に使い切る試験）。
 *
 * SPDX-License-Identifier: MIT
 */

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <zephyr/init.h>

#include <zmk/pm.h>
#include <zmk/activity.h>
#include <zmk/event_manager.h>
#include <zmk/events/activity_state_changed.h>

#if IS_ENABLED(CONFIG_HHKB_STATUS_LED)
#include "status_led.h"
#endif
#include <zmk/workqueue.h>
/* **門は CONFIG_USB_DEVICE_STACK で切る（CONFIG_ZMK_USB ではない）。**
 * 分割の右（ペリフェラル）は ZMK の Kconfig の依存で ZMK_USB が n になる（HID を出さないため）。
 * ZMK_USB で切っていた間、右は USB 給電中でもここを素通りし、電池なし・スイッチ OFF で USB だけ
 * つなぐと約 2 分で soft off した（2026-10-06 に CI の .config で発覚・10-08 に修正）。
 * zmk_usb_is_powered() の実体（usb.c）は USB_DEVICE_STACK でビルドされ、ZMK 自身の activity.c も
 * 同じ条件で切っている。 */
#if IS_ENABLED(CONFIG_USB_DEVICE_STACK)
#include <zmk/usb.h>
#endif

LOG_MODULE_DECLARE(hhkb_battery, CONFIG_SENSOR_LOG_LEVEL);

#define BATTERY_NODE DT_CHOSEN(zmk_battery)

BUILD_ASSERT(DT_NODE_HAS_PROP(BATTERY_NODE, empty_millivolts),
             "chosen zmk,battery に empty-millivolts が無い。"
             "hhkb,battery-alkaline を使うこと");

#define EMPTY_MV DT_PROP(BATTERY_NODE, empty_millivolts)

static const struct device *const battery = DEVICE_DT_GET(BATTERY_NODE);

static void low_battery_check(struct k_work *work) {
    static uint8_t consecutive;

#if IS_ENABLED(CONFIG_USB_DEVICE_STACK)
    if (zmk_usb_is_powered()) {
        consecutive = 0;
        return;
    }
#endif

    /* **測り直さない。**ZMK が同じ周期で fetch 済みなので、driver の
     * キャッシュを読むだけでよい。ADC をもう一度回すと電池を余分に使う。
     *
     * ⚠️⚠️ **この前提は idle では崩れる**（2026-10-15 の監査で判明・未修正）。
     * ZMK の app/src/battery.c:171-173 は `ZMK_ACTIVITY_IDLE`（既定 30 秒の
     * 無操作）で `k_timer_stop(&battery_timer)` を呼び、**測定を止める。**
     * だがこちらのタイマーは回り続けるので、**止まったあとの古いキャッシュを
     * 読んで数え続ける**（alk_channel_get は data->millivolts をそのまま返す）。
     *
     * 実害の向き: 電池が減って idle に入ると、その時点の電圧が凍る。
     *   - 凍った値が打ち止めより上 … **いつまでも soft off しない**（撃ち漏らし）
     *   - 凍った値が打ち止め以下 … 数回で soft off する（早すぎはしない）
     * **どちらも「古い値で決めている」点が問題。**
     * 直すなら activity の事象を受けて自分のタイマーも止める／起こすか、
     * ここで `sensor_sample_fetch()` を自分で呼ぶ（ADC を余分に回す代償）。
     * open-gaps #25b に追記すること。 */
    struct sensor_value voltage;
    int rc = sensor_channel_get(battery, SENSOR_CHAN_GAUGE_VOLTAGE, &voltage);
    if (rc != 0) {
        LOG_WRN("電池電圧が読めない (%d)。判定を飛ばす", rc);
        return;
    }

    uint32_t mv = voltage.val1 * 1000U + voltage.val2 / 1000U;
    if (mv > EMPTY_MV) {
        consecutive = 0;
        return;
    }

    consecutive++;
    LOG_WRN("電池が打ち止め %u mV を下回った（%u mV・%u 回目）", (unsigned)EMPTY_MV,
            (unsigned)mv, (unsigned)consecutive);

    /* 1 回では止めない。BLE 送信中は電池の内部抵抗ぶん一時的に下がる。 */
    if (consecutive < CONFIG_HHKB_LOW_BATTERY_SOFT_OFF_SAMPLES) {
        return;
    }

    LOG_ERR("電池が尽きた。soft off に入る（電池を替えて電源を入れ直すこと）");

    /* **LED を先に消す。**点いたまま System OFF に入ると、nRF52840 の GPIO は
     * 状態を保持するので 1〜2mA を舐め続ける（待機 20µA の 50〜100 倍）。
     * 「電池が尽きたので消費を止める」というこの機能自体が台無しになる。
     * 2026-10-15 の監査で見つかった。
     * ⚠️ **ここが唯一の消灯経路。**PM デバイス化（soft off の SUSPEND で
     * 自動的に消える形）はビルドが落ちて見送った（status_led.c の注記）。
     * **soft off を他の場所からも呼ぶようになったら、そこでも消すこと。** */
#if IS_ENABLED(CONFIG_HHKB_STATUS_LED)
    hhkb_status_led_off();
#endif

    zmk_pm_soft_off();
}

K_WORK_DEFINE(low_battery_work, low_battery_check);

static void low_battery_tick(struct k_timer *timer) {
    k_work_submit_to_queue(zmk_workqueue_lowprio_work_q(), &low_battery_work);
}

K_TIMER_DEFINE(low_battery_timer, low_battery_tick, NULL);

/* 周期は 1 か所だけに書く（init と再開の両方から使う）。 */
#define TICK_PERIOD K_SECONDS(CONFIG_ZMK_BATTERY_REPORT_INTERVAL)

/*
 * **ZMK が電池を測るのをやめたら、こちらの判定もやめる**（案 A・2026-10-15）。
 *
 * ZMK の app/src/battery.c:171-173 は `ZMK_ACTIVITY_IDLE`（既定 30 秒の
 * 無操作）で `k_timer_stop(&battery_timer)` を呼び、**測定を止める。**
 * こちらのタイマーだけ回し続けると、**止まったあとの古いキャッシュを
 * 読んで数え続ける**ことになる（alk_channel_get は measured 値をそのまま
 * 返すだけで、測り直さない）。それは「古い値で電源を落とすか決める」
 * ということで、判定として成立しない。
 *
 * → ZMK と歩調を合わせる。ACTIVE で動かし、IDLE/SLEEP で止める。
 *   **止めている間は判定しない。**キーに触れば ACTIVE に戻り、
 *   ZMK が測り直し、こちらも数え直す。
 *
 * ⚠️ **この窓では打ち止めを見逃す**（30 秒〜30 分の無操作中に電池が尽きる場合）。
 * 30 分を超えると ZMK 自身が deep sleep に入るので、どちらにせよ判定は止まる。
 * **見逃しが問題になるなら案 B**（自分で `sensor_sample_fetch()` を呼ぶ）に
 * 変えること。消費は見積もりで **+0.002µA**＝分圧抵抗 1.5µA の 0.13% で、
 * 実質ゼロ（ZMK も起きている間は同じ ADC 読み取りを 60 秒ごとにしている）。
 * **切り替えるのはこの関数 1 つ。**
 */
static int low_battery_activity_listener(const zmk_event_t *eh) {
    if (as_zmk_activity_state_changed(eh) == NULL) {
        return ZMK_EV_EVENT_BUBBLE;
    }

    switch (zmk_activity_get_state()) {
    case ZMK_ACTIVITY_ACTIVE:
        /* ZMK は K_NO_WAIT で測り直すが、こちらは**1 周期待つ**。
         * 起こした直後はまだ ZMK の新しい値が入っていないため
         * （init と同じ理由。下の low_battery_init の注記）。 */
        k_timer_start(&low_battery_timer, TICK_PERIOD, TICK_PERIOD);
        break;
    case ZMK_ACTIVITY_IDLE:
    case ZMK_ACTIVITY_SLEEP:
        k_timer_stop(&low_battery_timer);
        break;
    default:
        break;
    }
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(low_battery_off, low_battery_activity_listener);
ZMK_SUBSCRIPTION(low_battery_off, zmk_activity_state_changed);

static int low_battery_init(void) {
    /* 最初の 1 周は待つ。ZMK がまだ一度も測っていないと、キャッシュは 0mV。 */
    k_timer_start(&low_battery_timer, K_SECONDS(CONFIG_ZMK_BATTERY_REPORT_INTERVAL + 5),
                  TICK_PERIOD);
    return 0;
}

SYS_INIT(low_battery_init, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);
