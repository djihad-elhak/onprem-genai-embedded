#include "task.h"

void scrambler_init(scrambler_t *s, uint8_t seed)
{
    s->state = (uint8_t)(seed & 0x7Fu);
    if (s->state == 0u) {
        s->state = 0x7Fu;
    }
}

void scrambler_apply(scrambler_t *s, const uint8_t *in, uint8_t *out, size_t len)
{
    for (size_t i = 0u; i < len; ++i) {
        uint8_t byte = in[i];
        uint8_t res = 0u;
        for (unsigned b = 0u; b < 8u; ++b) {
            uint8_t fb = (uint8_t)(((s->state >> 6) ^ (s->state >> 3)) & 1u);
            res |= (uint8_t)((((byte >> b) & 1u) ^ fb) << b);
            s->state = (uint8_t)(((s->state << 1) | fb) & 0x7Fu);
        }
        out[i] = res;
    }
}
