#include "task.h"

static q15_t clamp(int32_t v)
{
    if (v > INT16_MAX) {
        return INT16_MAX;
    }
    if (v < INT16_MIN) {
        return INT16_MIN;
    }
    return (q15_t)v;
}

q15_t q15_add_sat(q15_t a, q15_t b) { return clamp((int32_t)a + (int32_t)b); }

q15_t q15_mul(q15_t a, q15_t b)
{
    int32_t p = (int32_t)a * (int32_t)b + (1 << 14);
    /* floor division by 2^15 without relying on implementation-defined right shifts */
    int32_t q = p / 32768;
    if ((p % 32768) != 0 && p < 0) {
        q -= 1;
    }
    return clamp(q);
}
