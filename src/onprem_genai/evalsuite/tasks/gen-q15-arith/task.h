#ifndef TASK_H
#define TASK_H
#include <stdint.h>

typedef int16_t q15_t; /* value = raw / 32768, range [-1, 1 - 2^-15] */

/* a + b clamped to [-32768, 32767]. */
q15_t q15_add_sat(q15_t a, q15_t b);

/* floor((a * b + 2^14) / 2^15) computed exactly in integer arithmetic, then clamped to
   [-32768, 32767] (so -1.0 * -1.0 saturates to 32767). */
q15_t q15_mul(q15_t a, q15_t b);

#endif
