#include "task.h"

/**
 * @brief clamp16.
 * @param v Input `v`.
 * @return Result, see task.h for ranges and error codes.
 */
static int16_t clamp16(int32_t v)
{
    if (v > INT16_MAX) {
        return INT16_MAX;
    }
    if (v < INT16_MIN) {
        return INT16_MIN;
    }
    return (int16_t)v;
}

/**
 * @brief sat add16.
 * @param a Input `a`.
 * @param b Input `b`.
 * @return Result, see task.h for ranges and error codes.
 */
int16_t sat_add16(int16_t a, int16_t b) { return clamp16((int32_t)a + (int32_t)b); }

/**
 * @brief sat sub16.
 * @param a Input `a`.
 * @param b Input `b`.
 * @return Result, see task.h for ranges and error codes.
 */
int16_t sat_sub16(int16_t a, int16_t b) { return clamp16((int32_t)a - (int32_t)b); }

/**
 * @brief sat abs16.
 * @param a Input `a`.
 * @return Result, see task.h for ranges and error codes.
 */
int16_t sat_abs16(int16_t a) { return clamp16(a < 0 ? -(int32_t)a : (int32_t)a); }
