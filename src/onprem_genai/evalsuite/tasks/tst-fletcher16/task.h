#ifndef TASK_H
#define TASK_H
#include <stddef.h>
#include <stdint.h>

/* Fletcher-16 checksum: sum1 = sum1 + byte (mod 255), sum2 = sum2 + sum1 (mod 255), both start at 0.
   Result = (sum2 << 8) | sum1. */
uint16_t fletcher16(const uint8_t *data, size_t len);

/* Verifies a frame whose last two bytes hold check bytes c0, c1 computed so that the Fletcher-16 of the whole
   frame is 0: returns 1 if valid, 0 otherwise (also 0 when len < 2). */
int fletcher16_frame_ok(const uint8_t *frame, size_t len);

#endif
