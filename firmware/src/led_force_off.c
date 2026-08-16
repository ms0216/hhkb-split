/*
 * RGB LED を起動直後に明示的に消し、二度と触らない。**電流測定のため。**
 *
 * --------------------------------------------------------------------------
 * なぜ要るか
 * --------------------------------------------------------------------------
 * Task C4 で `BLE_TX_CURRENT`（BLE 送信バーストの高さ）を測る。
 * シャント 10Ω を XIAO の 3V3 パッドに直列に入れて、その両端を見る。
 *
 * **XIAO の RGB LED は共通アノードで、アノードは 3V3 に直結**
 * （回路図 Seeed Studio XIAO nRF52840 v1.1・RGB1）。つまり
 * **注入した電流は LED を通る経路を持っている。**
 *
 *     3V3 ─ RGB1（共通アノード）┬─ R3 ─ P0.06 (青)
 *                                ├─ R4 ─ P0.30 (緑)
 *                                └─ R6 ─ P0.26 (赤)
 *
 * 1 色あたり 1〜2mA（provisional-values.md）。**測りたい TX バーストが
 * 15mA 級なので、同じ桁で乗る。**未接続だと青と緑が 1 秒に 2 回点滅する
 * 条件に入るので（status_led.c の状態表）、**必ず邪魔になる。**
 *
 * --------------------------------------------------------------------------
 * ⚠️ `CONFIG_HHKB_STATUS_LED=n` にするだけでは足りない
 * --------------------------------------------------------------------------
 * それは status_led.c を**コンパイルしない**だけで、**ピンを消灯側へ
 * 駆動するわけではない。**未初期化の GPIO は入力ハイインピーダンスなので
 * 消えている「はず」だが、**それは確かめていない推測。**
 *
 * CLAUDE.md 5: **設定しただけでは効いていない。実際に消えたかまで見る。**
 *
 * ここで明示的に「消灯」を書き込むことで、推測を 1 つ減らす。
 * **そのうえで、オシロでベースラインを読んで実際に消えたことを確認する**
 * （それが本来の検証。このファイルは「確認しやすくする」ためのもの）。
 *
 * --------------------------------------------------------------------------
 * なぜ status_led.c の #else ではないのか
 * --------------------------------------------------------------------------
 * CMakeLists.txt が `zephyr_library_sources_ifdef(CONFIG_HHKB_STATUS_LED
 * src/status_led.c)` なので、**無効時はそのファイル自体がビルドされない。**
 * #else を書いても到達しない。**別ファイルにするしかない。**
 *
 * SPDX-License-Identifier: MIT
 */

#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(hhkb_led_force_off, CONFIG_ZMK_LOG_LEVEL);

/* **エイリアスが無い基板では黙って無効化せず、ここで落とす。**
 * status_led.c と同じ扱い（黙って効かないのがいちばん危ない）。 */
BUILD_ASSERT(DT_HAS_ALIAS(led0), "この基板に led0 のエイリアスが無い");
BUILD_ASSERT(DT_HAS_ALIAS(led1), "この基板に led1 のエイリアスが無い");
BUILD_ASSERT(DT_HAS_ALIAS(led2), "この基板に led2 のエイリアスが無い");

/* **極性は devicetree の GPIO_ACTIVE_LOW が持つ。**ここに反転を書かない
 * （status_led.c と同じ約束。書くと二重に反転して点きっぱなしになる）。 */
static const struct gpio_dt_spec leds[] = {
    GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios),   /* 赤 P0.26 */
    GPIO_DT_SPEC_GET(DT_ALIAS(led1), gpios),   /* 緑 P0.30 */
    GPIO_DT_SPEC_GET(DT_ALIAS(led2), gpios),   /* 青 P0.06 */
};

static int hhkb_led_force_off(void)
{
    for (size_t i = 0; i < ARRAY_SIZE(leds); i++) {
        if (!gpio_is_ready_dt(&leds[i])) {
            /* **黙って続けない。**消えていない可能性を残したまま
             * 測定に入ると、その電流を TX と読み違える。 */
            LOG_ERR("LED %u の GPIO が使えない。**消灯を保証できない。**"
                    "この状態で電流を測らないこと", (unsigned)i);
            return -ENODEV;
        }
        /* GPIO_OUTPUT_INACTIVE = 論理 0（＝消灯）で出力にする。
         * ACTIVE_LOW が効くので、実際のピンは High になる。 */
        int err = gpio_pin_configure_dt(&leds[i], GPIO_OUTPUT_INACTIVE);
        if (err) {
            LOG_ERR("LED %u を消せなかった (err %d)。"
                    "**この状態で電流を測らないこと**", (unsigned)i, err);
            return err;
        }
    }

    LOG_INF("RGB LED を消灯に固定した（電流測定用・CONFIG_HHKB_LED_FORCE_OFF）");
    return 0;
}

/* **status_led.c より後に走っても意味がない**が、そもそも両方同時には
 * 積めない（Kconfig で depends on !HHKB_STATUS_LED）。
 * APPLICATION 段で、BLE が動き出す前に消しておく。 */
SYS_INIT(hhkb_led_force_off, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);
