#ifndef TASK_H
#define TASK_H
#include <stdint.h>

/* Codeword layout, bit 6 .. bit 0 = positions 1..7 = p1 p2 d1 p3 d2 d3 d4.
   The data nibble is d1 d2 d3 d4 with d1 its most significant bit.
   Parity (even): p1 covers positions 1,3,5,7; p2 covers 2,3,6,7; p3 covers 4,5,6,7. */
uint8_t hamming74_encode(uint8_t nibble);                 /* uses the low 4 bits of nibble */

/* Decodes the low 7 bits of codeword into *nibble (0..15).
   Returns 0 if the codeword was valid, 1 if a single-bit error was corrected. */
int hamming74_decode(uint8_t codeword, uint8_t *nibble);

#endif
