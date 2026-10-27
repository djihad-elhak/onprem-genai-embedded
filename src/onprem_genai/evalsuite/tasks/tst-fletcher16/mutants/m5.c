#include "task.h"

uint16_t fletcher16(const uint8_t *data, size_t len)
{
    uint16_t sum1 = 0u;
    uint16_t sum2 = 0u;
    for (size_t i = 0u; i < len; ++i) {
        sum1 = (uint16_t)((sum1 + data[i]) % 255u);
        sum2 = (uint16_t)((sum2 + data[i]) % 255u);
    }
    return (uint16_t)((sum2 << 8) | sum1);
}

int fletcher16_frame_ok(const uint8_t *frame, size_t len)
{
    if (len < 2u) {
        return 0;
    }
    return fletcher16(frame, len) == 0u;
}
