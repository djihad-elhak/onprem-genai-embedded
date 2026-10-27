#ifndef TASK_H
#define TASK_H
#include <stdint.h>

/* Saturating 16-bit signed arithmetic: results are clamped to [INT16_MIN, INT16_MAX]. */
int16_t sat_add16(int16_t a, int16_t b);
int16_t sat_sub16(int16_t a, int16_t b);
int16_t sat_abs16(int16_t a);   /* sat_abs16(INT16_MIN) == INT16_MAX */

#endif
