#include "task.h"

static int16_t clamp16(int32_t v)
{
    if (v > INT16_MAX) {
        return INT16_MAX;
    }
    if (v < INT16_MIN) {
        return INT16_MIN + 1;
    }
    return (int16_t)v;
}

int16_t sat_add16(int16_t a, int16_t b) { return clamp16((int32_t)a + (int32_t)b); }

int16_t sat_sub16(int16_t a, int16_t b) { return clamp16((int32_t)a - (int32_t)b); }

int16_t sat_abs16(int16_t a) { return clamp16(a < 0 ? -(int32_t)a : (int32_t)a); }
