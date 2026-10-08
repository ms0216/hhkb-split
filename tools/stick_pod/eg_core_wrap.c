/* tools/test_encoder_gated.py から ctypes で呼ぶための薄い皮。 */
#include "../../firmware/drivers/encoder_gated_core.h"
void eg_start(struct eg_core *c, int a, int b) { eg_core_start(c, a != 0, b != 0); }
int eg_edge(struct eg_core *c, int a, int b, int inv) { return eg_core_edge(c, a != 0, b != 0, inv != 0); }
int eg_pulses(struct eg_core *c) { return c->pulses; }
