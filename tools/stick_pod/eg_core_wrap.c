/* tools/test_encoder_gated.py から ctypes で呼ぶための薄い皮。 */
#include "../../firmware/drivers/encoder_gated_core.h"
void eg_start(struct eg_core *c, int a, int b) { eg_core_start(c, a != 0, b != 0); }
int eg_edge(struct eg_core *c, int a, int b, int inv) { return eg_core_edge(c, a != 0, b != 0, inv != 0); }
int eg_pulses(struct eg_core *c) { return c->pulses; }

/* --- button_latch の切り出し分（tools/test_button_latch.py から） --- */
#include "../../firmware/src/button_latch_core.h"
int bl_applies_of(int ev_type, int key_type, int code, int from) {
    return bl_applies((uint16_t)ev_type, (uint16_t)key_type, (uint16_t)code, (uint16_t)from) ? 1 : 0;
}
int bl_any_of(const int *active, int len) {
    bool buf[16];
    for (int i = 0; i < len && i < 16; i++) buf[i] = active[i] != 0;
    return bl_any_layer_active(buf, (size_t)(len < 16 ? len : 16)) ? 1 : 0;
}
