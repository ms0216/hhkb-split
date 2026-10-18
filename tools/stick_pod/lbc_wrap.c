/* tools/test_low_battery_core.py から ctypes で呼ぶための薄い皮。 */
#include "../../firmware/src/low_battery_core.h"

int lbc_step_of(struct lbc_state *s, int usb, int readable, unsigned mv,
                unsigned empty_mv, int samples) {
    return (int)lbc_step(s, usb != 0, readable != 0, mv, empty_mv, (uint8_t)samples);
}
int lbc_count(struct lbc_state *s) { return s->consecutive; }
