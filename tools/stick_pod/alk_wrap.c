/* tools/test_battery_alkaline.py から ctypes で呼ぶための薄い皮。
 *
 * ⚠️ **battery_alkaline.c をそのまま include できない**（Zephyr の
 * device.h / adc.h / sensor.h に依存する）。写すのではなく、
 * **換算の式だけを同じ形で持つ**のは「自分の生成物どうしの一致」に
 * なってしまうので、ここでは **.c から該当関数を切り出して取り込む**。
 * 取り込み方は test 側で検証する（式がずれたら落ちる）。 */
#include <stdint.h>

struct alk_config {
    uint8_t io_channel;
    uint32_t output_ohm;
    uint32_t full_ohm;
    uint16_t empty_mv;
    uint16_t full_mv;
};

/* ここに battery_alkaline.c の alkaline_mv_to_pct を貼る代わりに、
 * ビルド時に #include する（tools/test_battery_alkaline.py が
 * .c から関数本体を抜き出して一時ファイルに書く）。 */
#include "alk_fn.inc"

int alk_pct(unsigned empty_mv, unsigned full_mv, unsigned mv) {
    struct alk_config cfg = {.empty_mv = (uint16_t)empty_mv, .full_mv = (uint16_t)full_mv};
    return (int)alkaline_mv_to_pct(&cfg, (uint16_t)mv);
}
