#ifndef TASK_H
#define TASK_H
#include <stddef.h>
#include <stdint.h>

/* State: bits x1..x7 of the shift register stored in bits 0..6 of `state` (bit 0 = x1, most recent).
   For each input bit b (bytes processed least-significant bit first):
       fb  = x7 XOR x4          (state bit 6 XOR state bit 3)
       out = b XOR fb
       state = ((state << 1) | fb) & 0x7F */
typedef struct {
    uint8_t state;
} scrambler_t;

/* seed uses the low 7 bits; a zero seed is replaced by 0x7F (the all-zero state would lock up). */
void scrambler_init(scrambler_t *s, uint8_t seed);

/* Scrambles len bytes from in to out (in and out may alias); updates the state. */
void scrambler_apply(scrambler_t *s, const uint8_t *in, uint8_t *out, size_t len);

#endif
